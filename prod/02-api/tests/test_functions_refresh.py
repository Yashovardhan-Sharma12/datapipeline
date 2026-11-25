# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from functions.functions_api_client import ApiClientError
from functions import functions_file_io as file_io
from functions import functions_refresh as refresh
from functions import functions_sql_execution as sql
from functions import functions_validation as validation

# ----------------------------------------------------------------------------------------------------------------------
#%% Tests


class RefreshHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.history_file = self.folder / "_refresh_history.json"
        self.status_file = self.folder / "_refresh_status.json"
        self.runs_folder = self.folder / "_runs"
        self.report_file = self.folder / "missing_data_report.csv"
        patches = [
            patch.multiple(
                refresh,
                REFRESH_HISTORY_FILE=self.history_file,
                REFRESH_STATUS_FILE=self.status_file,
                REFRESH_RUNS_FOLDER=self.runs_folder,
                REFRESH_COMPLETE_FILE=self.folder / "_refresh_complete.json",
            ),
            patch.object(validation, "MISSING_DATA_REPORT_FILE", self.report_file),
            patch.dict(sql.jobs, clear=True),
            patch.dict(sql.finished_jobs, clear=True),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_legacy_history_migration_preserves_detail_and_failed_list(self):
        when = "2026-11-24T14:30:00+05:30"
        detail = {
            "job_id": "old-run",
            "status": "completed_with_failures",
            "scheduled_for": when,
            "started_at": when,
            "completed_at": when,
            "failed_queries": 1,
            "total_queries": 2,
            "quality": {"latest_year_week": "202647", "latest_week_present": 1, "failed_query_files": ["failed.sql"]},
            "results": [
                {"status": "complete", "filename": "validation_uk.sql", "comparison_data": [{"value": 1}]},
                {"status": "failed", "filename": "failed.sql", "source_label": "Colleague", "error": "long " * 100},
            ],
        }
        self.history_file.write_text(json.dumps([detail]), encoding="utf-8")
        refresh.func_refresh_migrate_history()

        [summary] = json.loads(self.history_file.read_text(encoding="utf-8"))
        for key in ("job_id", "scheduled_for", "started_at", "completed_at", "status", "total_queries"):
            self.assertEqual(summary[key], detail[key])
        self.assertEqual(summary["quality"]["latest_week_present"], 1)
        self.assertNotIn("failed_query_files", summary["quality"])
        self.assertIsNone(summary["contentgen"])
        [failed] = summary["failed_queries"]
        self.assertEqual(failed["filename"], "failed.sql")
        self.assertLessEqual(len(failed["reason"]), refresh.REFRESH_HISTORY_REASON_LIMIT)
        self.assertEqual(summary["results"], [failed])
        self.assertNotIn("comparison_data", self.history_file.read_text(encoding="utf-8"))
        self.assertEqual(refresh.func_refresh_get_detail("old-run"), detail)
        self.assertIsNone(refresh.func_refresh_get_detail("../old-run"))

        with patch.object(refresh, "func_refresh_write_json") as writer:
            refresh.func_refresh_migrate_history()
            writer.assert_not_called()

    def test_finalisation_keeps_200_summaries_and_uses_exclusive_cursor(self):
        # ----------------------------------------------------------------
        # 1. Seed History
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        existing = [
            refresh.func_refresh_build_summary({
                "job_id": f"run-{index}",
                "started_at": (start + timedelta(hours=index)).isoformat(),
                "status": "success",
            })
            for index in range(200)
        ]
        self.history_file.write_text(json.dumps(existing), encoding="utf-8")
        sql.jobs["new-run"] = {
            "scheduled_refresh": True,
            "status": "running",
            "started_at": (start + timedelta(hours=200)).isoformat(),
            "results": [{"filename": "query.sql", "status": "complete", "comparison_data": [{"value": 10}]}],
        }

        # ----------------------------------------------------------------
        # 2. Publish Progress And Finalise
        refresh.func_refresh_persist_snapshot("new-run")
        self.assertEqual(json.loads(self.history_file.read_text(encoding="utf-8")), existing)
        self.assertNotIn("comparison_data", self.status_file.read_text(encoding="utf-8"))
        self.assertEqual(refresh.func_refresh_get_active()[0]["job_id"], "new-run")
        self.assertFalse(self.runs_folder.exists())
        expired = self.runs_folder / "run-0.json"
        retained = self.runs_folder / "run-1.json"
        for path in (expired, retained):
            refresh.func_refresh_write_json(path, {"job_id": path.stem})
        sql.jobs["new-run"].update(status="success", completed_at=(start + timedelta(hours=201)).isoformat())
        with patch.object(refresh, "func_refresh_write_json", wraps=refresh.func_refresh_write_json) as writer:
            refresh.func_refresh_finalize("new-run")
            refresh.func_refresh_finalize("new-run")
            detail_path = self.runs_folder / "new-run.json"
            self.assertEqual(sum(call.args[0] == detail_path for call in writer.call_args_list), 1)

        # ----------------------------------------------------------------
        # 3. Verify Pages
        first, before = refresh.func_refresh_load_history()
        second, _ = refresh.func_refresh_load_history(before=before)
        self.assertEqual(len(first), 20)
        self.assertEqual(len(second), 20)
        self.assertEqual(first[0]["job_id"], "new-run")
        self.assertEqual(second[0]["job_id"], "run-180")
        self.assertEqual(len(json.loads(self.history_file.read_text(encoding="utf-8"))), 200)
        self.assertFalse(expired.exists())
        self.assertTrue(retained.exists())
        self.assertEqual(json.loads(self.status_file.read_text(encoding="utf-8"))["status"], "success")
        self.assertEqual(refresh.func_refresh_get_detail("new-run")["results"][0]["comparison_data"], [{"value": 10}])
        for kwargs in ({"before": "not-an-iso"}, {"limit": 0}, {"limit": 201}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                refresh.func_refresh_load_history(**kwargs)

    def test_startup_prunes_old_unindexed_details_and_keeps_recent_unindexed_details(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        records = [
            refresh.func_refresh_build_summary({
                "job_id": f"run-{index}", "started_at": (start + timedelta(hours=index)).isoformat(), "status": "success",
            })
            for index in range(200)
        ]
        refresh.func_refresh_write_json(self.history_file, records)
        previous = start - timedelta(days=1)
        expired = self.runs_folder / "expired.json"
        retained = self.runs_folder / "run-0.json"
        unindexed = self.runs_folder / "unindexed.json"
        for path, written in ((expired, previous), (retained, previous), (unindexed, start + timedelta(days=1))):
            refresh.func_refresh_write_json(path, {"job_id": path.stem})
            os.utime(path, (written.timestamp(), written.timestamp()))
        refresh.func_refresh_migrate_history()
        self.assertEqual(set(self.runs_folder.iterdir()), {retained, unindexed})

    def test_does_not_remove_evicted_details_until_history_is_saved(self):
        started = "2026-11-01T10:00:00+05:30"
        previous = [{"job_id": "old", "started_at": started}]
        path = self.runs_folder / "old.json"
        refresh.func_refresh_write_json(self.history_file, previous)
        refresh.func_refresh_write_json(path, {"job_id": "old"})
        with (
            patch.object(refresh, "REFRESH_HISTORY_LIMIT", 1),
            patch.object(refresh, "func_refresh_write_json", side_effect=PermissionError("locked")),
        ):
            with self.assertRaises(PermissionError):
                refresh.func_refresh_save_history([{"job_id": "new", "started_at": "2026-11-02T10:00:00+05:30"}, *previous], previous)
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(self.history_file.read_text()), previous)

    def test_scheduled_refresh_clears_report_and_looks_up_week_once(self):
        self.report_file.write_text("stale.sql,202646,MISSING\n", encoding="utf-8")
        tasks = [{"path": str(self.folder / "empty.sql"), "source": "customer", "source_label": "Customer"}]

        def func_test_lookup_week(_):
            self.assertFalse(self.report_file.exists())
            return "202647"

        with (
            patch.object(refresh, "func_sql_get_tasks", return_value=tasks),
            patch.object(refresh, "func_validation_get_current_week", side_effect=func_test_lookup_week) as lookup,
            patch.object(sql, "func_validation_get_current_week") as unexpected_lookup,
            patch.object(sql, "func_sql_run_file", return_value={"status": "no_data", "message": "No rows returned"}) as run,
        ):
            refresh.func_refresh_run_scheduled(14, 30)

        lookup.assert_called_once()
        unexpected_lookup.assert_not_called()
        run.assert_called_once_with(tasks[0]["path"], "customer", "202647")
        summary = refresh.func_refresh_load_history()[0][0]
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["quality"]["latest_year_week"], "202647")
        self.assertEqual(summary["empty_queries"], 1)
        self.assertEqual(summary["failed_queries"], [])

    def test_marker_retries_after_a_windows_sharing_violation(self):
        replace = file_io.os.replace
        attempts = []

        def func_test_replace(source, destination):
            attempts.append(destination)
            if len(attempts) == 1:
                raise PermissionError("Reader still has marker open")
            replace(source, destination)

        with patch.object(file_io.os, "replace", side_effect=func_test_replace), patch.object(file_io.time, "sleep") as sleep:
            refresh.func_refresh_write_json(self.status_file, {"status": "running"})

        sleep.assert_called_once_with(0.1)
        self.assertEqual(attempts, [self.status_file, self.status_file])
        self.assertEqual(json.loads(self.status_file.read_text(encoding="utf-8")), {"status": "running"})
        self.assertFalse(list(self.folder.glob("*.tmp")))

    def test_runner_outage_is_recorded_when_refresh_finishes(self):
        tasks = [{"path": str(self.folder / "extract.sql"), "source": "customer", "source_label": "Customer"}]
        with (
            patch.object(refresh, "CONTENTGEN_RUNNER_ENABLED", True),
            patch.object(refresh, "ENV_NAME", "dev"),
            patch.object(refresh, "func_sql_get_tasks", return_value=tasks),
            patch.object(refresh, "func_validation_get_current_week", return_value="202647"),
            patch.object(sql, "func_sql_run_file", return_value={"status": "success", "validation": {"status": "ok"}}),
            patch("functions.functions_schedules.func_schedules_get_projects", return_value=["ccec-o"]),
            patch.object(refresh, "func_api_client_submit_runs", side_effect=ApiClientError("Runner unavailable")) as submit,
            patch.object(refresh, "log_message") as logs,
        ):
            refresh.func_refresh_run_scheduled(14, 30, {"run_contentgen": True, "include_diagnostics": True})

        summary = refresh.func_refresh_load_history()[0][0]
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["contentgen"], {"status": "not_started", "reason": "Runner unavailable"})
        request = submit.call_args.args[0]
        self.assertEqual(request["refresh_job_id"], summary["job_id"])
        self.assertEqual(request["items"], [{
            "env": "dev", "project": "ccec-o", "steps": ["diagnostics", "content_gen", "upload"],
        }])
        self.assertTrue(any(summary["job_id"] in call.args[0] and call.args[1] == "WARNING" for call in logs.call_args_list))
