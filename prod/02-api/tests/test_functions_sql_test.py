# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from functions import functions_sql_test as preview

# ----------------------------------------------------------------------------------------------------------------------
#%% Tests


class SqlPreviewTests(unittest.TestCase):
    def test_success_only_reads_first_50_rows_and_rolls_back(self):
        # ----------------------------------------------------------------
        # 1. Establish The Connection Fixture
        connector = SimpleNamespace(engine=SimpleNamespace(url=SimpleNamespace(query={"odbc_connect": "test-source"})))
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.description = [("year_week_number",), ("label",)]
        cursor.fetchmany.return_value = [(202647, f"row-{n}") for n in range(51)]

        # ----------------------------------------------------------------
        # 2. Run The Preview
        sql = "DROP TABLE #rows;\nSELECT 202647 AS year_week_number, N'COMMIT' AS label"
        with (
            patch.dict(preview.QUERY_SOURCES, {"customer": {"conn": connector}}, clear=True),
            patch.object(preview.mssql.pyodbc, "connect", return_value=connection) as connect,
        ):
            result = preview.func_sql_test_execute("customer", "query.sql", sql)

        # ----------------------------------------------------------------
        # 3. Verify Transaction And Result
        connect.assert_called_once_with("test-source", autocommit=False, timeout=preview.QUERY_TEST_LOGIN_TIMEOUT_SECONDS)
        self.assertEqual(connection.timeout, preview.QUERY_TEST_TIMEOUT_SECONDS)
        cursor.fetchmany.assert_called_once_with(51)
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()
        connection.commit.assert_not_called()
        self.assertLess(connection.mock_calls.index(unittest.mock.call.cursor().close()),
                        connection.mock_calls.index(unittest.mock.call.rollback()))
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["rows"]), 50)
        self.assertIn("OBJECT_ID('tempdb..#rows')", cursor.execute.call_args.args[0])

    def test_errors_and_timeouts_are_classified_and_rolled_back(self):
        connector = SimpleNamespace(engine=SimpleNamespace(url=SimpleNamespace(query={"odbc_connect": "test-source"})))
        cases = [
            (Exception("42S22", "[SQL Server]Invalid column name 'wrong'. (207) (SQLExecDirectW)"), "sql_error"),
            (Exception("HYT00", "Query timeout expired (SQLExecDirectW)"), "timeout"),
        ]
        for error, kind in cases:
            with self.subTest(kind=kind):
                connection = Mock()
                connection.cursor.return_value.execute.side_effect = error
                with (
                    patch.dict(preview.QUERY_SOURCES, {"customer": {"conn": connector}}, clear=True),
                    patch.object(preview.mssql.pyodbc, "connect", return_value=connection),
                ):
                    result = preview.func_sql_test_execute("customer", "query.sql", "-- comment\nSELECT wrong")
                connection.rollback.assert_called_once()
                connection.close.assert_called_once()
                connection.commit.assert_not_called()
                self.assertEqual(result["error"]["kind"], kind)
                if kind == "sql_error":
                    self.assertEqual(result["error"]["line_number"], 2)
                    self.assertEqual(result["error"]["sql_error_number"], 207)

    def test_statements_that_escape_rollback_are_rejected_before_connecting(self):
        cases = [
            "SELECT 1; COMMIT TRANSACTION;", "EXEC dbo.preview", "dbo.preview",
            "SELECT * FROM OPENQUERY(link, 'SELECT 1')", "SELECT 1 INTO dbo.table_name",
            "DROP TABLE IF EXISTS #local, dbo.persisted", "INSERT INTO ##global VALUES (1)",
            "SELECT NEXT VALUE FOR dbo.sequence",
        ]
        with patch.object(preview.mssql.pyodbc, "connect") as connect:
            for sql in cases:
                with self.subTest(sql=sql):
                    result = preview.func_sql_test_execute("customer", "query.sql", sql)
                    self.assertEqual(result["status"], "error")
            connect.assert_not_called()
        self.assertIsNone(preview.func_sql_test_safety_error(
            "/* outer /* nested */ comment */\nDROP TABLE IF EXISTS #local;\nSELECT [COMMIT] FROM #local"
        ))
        literal = "SELECT 'Text\nDROP TABLE #local\nText'"
        self.assertEqual(preview.func_sql_test_preview_sql(literal), literal)
