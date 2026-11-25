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
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from apscheduler.schedulers.background import BackgroundScheduler

from functions import functions_schedules as schedules

# ----------------------------------------------------------------------------------------------------------------------
#%% Tests


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "schedules.json"
        patcher = patch.multiple(schedules, SCHEDULES_FILE=self.path, ENV_NAME="dev", DEFAULT_SCHEDULED_PROJECTS=())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scheduler = BackgroundScheduler(timezone=schedules.TIMEZONE)
        self.addCleanup(self.func_test_shutdown)

    def func_test_shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    def func_test_slot(self, key="first", days="mon-fri", at="14:30", paused=False):
        return {"id": key, "days": days, "time": at, "paused": paused,
                "run_contentgen": True, "include_diagnostics": False}

    def test_seed_registration_uses_existing_prod_slots_and_empty_dev(self):
        schedules.func_schedules_start(self.scheduler)
        self.assertEqual({job.id for job in self.scheduler.get_jobs()}, {"hourly_git_pull"})
        self.assertEqual(json.loads(self.path.read_text())["schedules"], [])
        with patch.object(schedules, "ENV_NAME", "prod"):
            prod = schedules.func_schedules_slots()
            self.assertEqual(len(prod), 9)
            self.assertIn(("mon", "19:00"), {(slot["days"], slot["time"]) for slot in prod})
            self.assertIn(("tue-sun", "14:30"), {(slot["days"], slot["time"]) for slot in prod})

    def test_update_replace_pause_resume_delete_and_audit(self):
        # ----------------------------------------------------------------
        # 1. Add And Replace
        self.scheduler.start(paused=True)
        first = self.func_test_slot()
        added = schedules.func_schedules_update(self.scheduler, {
            "schedules": [first], "projects": ["ccec-o"], "run_by": "Operator", "revision": 0,
        })
        self.assertIn("14", str(self.scheduler.get_job("first").trigger))
        self.assertEqual(added["revision"], 1)
        changed = {**first, "time": "18:15", "include_diagnostics": True}
        schedules.func_schedules_update(self.scheduler, {"schedules": [changed], "run_by": "Operator", "revision": 1})
        self.assertEqual(self.scheduler.get_job("first").kwargs["refresh_minute"], 15)

        # ----------------------------------------------------------------
        # 2. Pause And Resume
        schedules.func_schedules_update(self.scheduler, {"schedules": [{**changed, "paused": True}], "run_by": "Operator"})
        self.assertIsNone(self.scheduler.get_job("first").next_run_time)
        schedules.func_schedules_update(self.scheduler, {"schedules": [changed], "run_by": "Operator"})
        self.assertIsNotNone(self.scheduler.get_job("first").next_run_time)

        # ----------------------------------------------------------------
        # 3. Remove And Check Audit
        removed = schedules.func_schedules_update(self.scheduler, {
            "schedules": [], "run_by": "Second operator", "revision": 4,
        })
        self.assertIsNone(self.scheduler.get_job("first"))
        self.assertEqual(removed["projects"], ["ccec-o"])
        self.assertEqual(removed["revision"], 5)
        audit = json.loads(self.path.read_text())["changes"]
        self.assertEqual([row["revision"] for row in audit], [1, 2, 3, 4, 5])
        self.assertEqual(audit[-1]["run_by"], "Second operator")
        self.assertEqual(audit[-1]["schedules"]["removed"], [changed])
        self.assertIsNotNone(datetime.fromisoformat(audit[-1]["at"]).tzinfo)

    def test_next_run_respects_weekdays_and_paused_slots(self):
        zone = schedules.TIMEZONE
        friday = datetime(2026, 11, 27, 14, 30, tzinfo=zone)
        weekdays = self.func_test_slot()
        paused = self.func_test_slot("paused", "daily", "14:31", paused=True)
        result = schedules.func_schedules_next_runs([weekdays, paused], friday, 2)
        self.assertEqual([value["scheduled_for"] for value in result], [
            "2026-11-30T14:30:00+05:30", "2026-12-01T14:30:00+05:30",
        ])

    def test_update_rejects_overlapping_days_without_changing_jobs_or_disk(self):
        self.scheduler.start(paused=True)
        first = self.func_test_slot(days="tue-sun")
        monday = self.func_test_slot("monday", "mon")
        saved = schedules.func_schedules_update(self.scheduler, {"schedules": [first, monday], "run_by": "Operator"})
        before = self.path.read_bytes()
        for days in ("daily", "mon-fri", "tue-sun"):
            with self.subTest(days=days), self.assertRaises(ValueError):
                schedules.func_schedules_update(self.scheduler, {
                    "schedules": [first, monday, self.func_test_slot("overlap", days)],
                    "run_by": "Operator",
                })
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(schedules.func_schedules_describe()["revision"], saved["revision"])
        self.assertEqual({job.id for job in self.scheduler.get_jobs()}, {"first", "monday"})

    def test_startup_pauses_and_audits_existing_overlapping_slot(self):
        first = self.func_test_slot(days="tue-sun")
        overlap = self.func_test_slot("overlap", "daily")
        self.path.write_text(json.dumps({"schedules": [first, overlap], "projects": []}))
        schedules.func_schedules_start(self.scheduler)
        self.assertIsNotNone(self.scheduler.get_job("first").next_run_time)
        self.assertIsNone(self.scheduler.get_job("overlap").next_run_time)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["schedules"], [first, {**overlap, "paused": True}])
        [change] = saved["changes"]
        self.assertEqual(change["run_by"], "Refresh Desk")
        self.assertEqual(change["schedules"]["changed"][0]["before"], overlap)

    def test_failed_disk_write_restores_jobs_and_revision(self):
        self.scheduler.start()
        original = self.func_test_slot()
        schedules.func_schedules_update(self.scheduler, {"schedules": [original], "run_by": "Operator"})
        with patch.object(schedules, "func_file_io_write_json", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                schedules.func_schedules_update(self.scheduler, {
                    "schedules": [self.func_test_slot("replacement")], "revision": 1, "run_by": "Operator",
                })
        self.assertIsNone(self.scheduler.get_job("replacement"))
        self.assertIsNotNone(self.scheduler.get_job("first"))
        self.assertEqual(schedules.func_schedules_describe()["revision"], 1)
        with self.assertRaises(schedules.ScheduleConflictError):
            schedules.func_schedules_update(self.scheduler, {"projects": ["changed"], "revision": 0, "run_by": "Operator"})
