# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from functions import functions_output_files as outputs
from functions import functions_sql_execution as sql

# ----------------------------------------------------------------------------------------------------------------------
#%% Tests


class SqlExecutionTests(unittest.TestCase):
    def test_retention_evicts_oldest_finished_jobs_and_keeps_active_jobs(self):
        entries = {
            "active": {"status": "running"},
            "old": {"status": "completed"},
            "new": {"status": "success", "scheduled_refresh": True},
        }
        with (
            patch.dict(sql.jobs, entries, clear=True),
            patch.dict(sql.finished_jobs, clear=True),
            patch.object(sql, "SQL_JOB_RETENTION_LIMIT", 1),
        ):
            sql.func_sql_retain_finished_job("old")
            sql.func_sql_retain_finished_job("new")
            self.assertIsNone(sql.func_sql_get_job("old"))
            self.assertIsNotNone(sql.func_sql_get_job("active"))
            self.assertIsNotNone(sql.func_sql_get_job("new"))

    def test_named_sql_errors_include_number_and_original_line(self):
        cases = [
            ("42S22", "Invalid column name 'reason_l3'.", 207, "-- reason_l3\nSELECT [reason_l3]"),
            ("42S02", "Invalid object name 'dbo.bad_table'.", 208, "SELECT *\nFROM [dbo].[bad_table]"),
        ]
        for state, message, number, query in cases:
            with self.subTest(state=state):
                error = Exception(state, f"[{state}] [Microsoft][SQL Server]{message} ({number}) (SQLExecDirectW)")
                result = sql.func_sql_classify_error(error, query)
                self.assertEqual(result["kind"], "sql_error")
                self.assertEqual(result["message"], message)
                self.assertEqual(result["sql_error_number"], number)
                self.assertEqual(result["line_number"], 2)

    def test_connection_and_execution_timeouts_are_distinct(self):
        cases = [
            (Exception("08S01", "Communication link failure"), False, "connection"),
            (Exception("08001", "Unable to establish connection"), False, "connection"),
            (Exception("08003", "Connection does not exist"), False, "connection"),
            (Exception("08007", "Connection failure during transaction"), False, "connection"),
            (Exception("HYT01", "Connection timeout expired"), False, "connection"),
            (Exception("HYT00", "Login timeout expired (SQLDriverConnect)"), False, "connection"),
            (Exception("HYT00", "Timeout expired"), True, "connection"),
            (Exception("HYT00", "Query timeout expired (SQLExecDirectW)"), False, "timeout"),
            (TimeoutError("deadline exceeded"), False, "timeout"),
            (None, False, "empty"),
        ]
        for error, connecting, expected in cases:
            with self.subTest(error=error, connecting=connecting):
                result = sql.func_sql_classify_error(error, connecting=connecting)
                self.assertEqual(result["kind"], expected)

    def test_only_connection_failure_retries_with_fresh_connection(self):
        # ----------------------------------------------------------------
        # 1. Set Up
        first_conn, fresh_conn = Mock(), Mock()
        first_conn.cursor.return_value.execute.side_effect = Exception("08S01", "Communication link failure")
        fresh_conn.cursor.return_value.fetchone.return_value = None
        fresh_conn.cursor.return_value.description = [("year_week_number",)]
        fresh_conn.cursor.return_value.fetchall.return_value = [("202647",)]
        connector = Mock()
        connector.engine.raw_connection.side_effect = [first_conn, fresh_conn]
        sources = {"customer": {"label": "Customer", "conn": connector}}

        # ----------------------------------------------------------------
        # 2. Execute
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            query = folder / "extract.sql"
            query.write_text("SELECT year_week_number FROM source", encoding="utf-8")
            tasks = [{"path": str(query), "source": "customer", "source_label": "Customer"}]
            with patch.multiple(sql, OUTPUT_FOLDER=folder, QUERY_SOURCES=sources, QUERY_RETRY_DELAYS_SECONDS=(0,)):
                with patch.dict(sql.jobs, {"job-1": {"status": "running", "results": None}}):
                    sql.func_sql_execute_job("job-1", tasks, latest_week="202647")
                    row = sql.func_sql_get_job("job-1")["results"][0]
            self.assertTrue((folder / "extract.csv").is_file())

        # ----------------------------------------------------------------
        # 3. Verify
        first_conn.invalidate.assert_called_once()
        connector.engine.dispose.assert_called_once()
        self.assertEqual(connector.engine.raw_connection.call_count, 2)
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["attempt_details"][0]["error"]["kind"], "connection")
        self.assertIsNone(row["attempt_details"][1]["error"])
        self.assertTrue(all(attempt["duration_seconds"] >= 0 for attempt in row["attempt_details"]))

    def test_failures_and_empty_results_keep_existing_csv(self):
        # ----------------------------------------------------------------
        # 1. Set Up
        failures = {
            "empty": {"status": "no_data", "message": "No rows returned"},
            "invalid": {
                "status": "error",
                "error_detail": sql.func_sql_classify_error(
                    Exception("42S22", "Invalid column name 'value'. (207) (SQLExecDirectW)"),
                    "SELECT value",
                ),
            },
            "slow": {"status": "error", "error_detail": sql.func_sql_classify_error(TimeoutError())},
        }

        # ----------------------------------------------------------------
        # 2. Execute
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            old_csv = b"value\r\nolder\r\n"
            tasks = []
            for name in failures:
                (folder / f"{name}.csv").write_bytes(old_csv)
                tasks.append({"path": str(folder / f"{name}.sql"), "source": "customer", "source_label": "Customer"})
            with (
                patch.object(outputs, "OUTPUT_FOLDER", folder),
                patch.dict(sql.jobs, {"job-2": {"status": "running", "results": None}}),
                patch.object(sql, "func_sql_run_file", side_effect=lambda path, *_: failures[Path(path).stem]) as run,
            ):
                sql.func_sql_execute_job("job-2", tasks, latest_week=None)
                rows = {Path(row["filename"]).stem: row for row in sql.func_sql_get_job("job-2")["results"]}

            # ----------------------------------------------------------------
            # 3. Verify
            self.assertEqual(run.call_count, len(failures))
            for name, kind in [("empty", "empty"), ("invalid", "sql_error"), ("slow", "timeout")]:
                with self.subTest(name=name):
                    row = rows[name]
                    self.assertEqual(row["status"], "empty" if kind == "empty" else "failed")
                    self.assertEqual(row["attempts"], 1)
                    self.assertEqual(row["attempt_details"][0]["error"]["kind"], kind)
                    self.assertEqual(row["fallback_output"]["name"], f"{name}.csv")
                    self.assertEqual(row["fallback_output"]["rows"], 1)
                    self.assertEqual((folder / f"{name}.csv").read_bytes(), old_csv)

    def test_partial_csv_write_leaves_previous_file_intact(self):
        def func_test_partial_write(path, **kwargs):
            path.write_text("partial", encoding="utf-8")
            raise OSError("Write failed")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "extract.csv"
            target.write_text("previous", encoding="utf-8")
            data = pd.DataFrame({"value": ["current"]})
            with patch.object(data, "to_csv", side_effect=func_test_partial_write):
                with self.assertRaises(OSError):
                    outputs.func_output_files_write_csv(target, data)
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(target.parent.iterdir()), [target])
