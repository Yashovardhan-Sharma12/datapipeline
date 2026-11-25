# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import io
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from functions import functions_output_files as outputs
from functions import functions_sql_execution as sql
from routes import routes_downloads

# ----------------------------------------------------------------------------------------------------------------------
#%% Tests


class OutputFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name) / "03-output"
        self.folder.mkdir()
        (self.folder / "Sales.CSV").write_bytes(b'\xef\xbb\xbfvalue\r\n"line 1\nline 2"\r\nother\r\n')
        (self.folder / "other.csv").write_bytes(b"value\r\n")
        (self.folder / "missing_data_report.csv").write_bytes(b"query.sql,202647,MISSING\n")
        (self.folder / "query.sql").write_text("SELECT 1", encoding="utf-8")
        (self.folder / "scratch.tmp").write_bytes(b"tmp")
        patcher = patch.object(outputs, "OUTPUT_FOLDER", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

        app = Flask(__name__)
        app.add_url_rule("/output-files", view_func=routes_downloads.route_downloads_output_files)
        app.add_url_rule("/download-output/<filename>", view_func=routes_downloads.route_downloads_single_file)
        app.add_url_rule("/download-output", view_func=routes_downloads.route_downloads_archive, methods=["GET", "POST"])
        self.client = app.test_client()

    def test_downloads_reject_unsafe_filenames(self):
        names = [
            "../Sales.CSV", r"..\Sales.CSV", r"C:\Sales.CSV", "C:Sales.CSV", "Sales.CSV:stream",
            "another/file.csv", "query.sql", "NUL.csv", "Sales.CSV ", None, [],
        ]
        for name in names:
            with self.subTest(name=name):
                response = self.client.post("/download-output", json={"files": [name]})
                self.assertEqual(response.status_code, 400)
        for path in ("/download-output/query.sql", "/download-output/NUL.csv", "/download-output/absent.csv"):
            status = self.client.get(path).status_code
            self.assertEqual(status, 404 if "absent" in path else 400)
        for name in ("../a.sql", r"..\a.sql", "NUL.sql", "a.sql:stream"):
            with self.subTest(query=name), self.assertRaises(ValueError):
                sql.func_sql_prepare_job(name, None)

    def test_external_symlink_is_excluded_from_downloads(self):
        outside = self.folder.parent / "private.csv"
        outside.write_bytes(b"private")
        try:
            (self.folder / "linked.csv").symlink_to(outside)
        except OSError:
            self.skipTest("Creating symlinks requires permissions on this host")
        self.assertEqual(self.client.get("/download-output/linked.csv").status_code, 404)
        response = self.client.get("/download-output")
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertNotIn("03-output/linked.csv", archive.namelist())

    def test_metadata_counts_records_and_selected_archive_only_contains_requested_files(self):
        files = {item["name"]: item for item in self.client.get("/output-files").get_json()["files"]}
        sales = files["Sales.CSV"]
        self.assertEqual(sales["size"], (self.folder / "Sales.CSV").stat().st_size)
        self.assertEqual(sales["rows"], 2)
        self.assertIsNotNone(datetime.fromisoformat(sales["written_at"]).tzinfo)
        self.assertEqual(files["other.csv"]["rows"], 0)
        self.assertEqual(files["missing_data_report.csv"]["rows"], 1)
        self.assertNotIn("query.sql", files)
        single = self.client.get("/download-output/Sales.CSV")
        self.addCleanup(single.close)
        self.assertEqual(single.data, (self.folder / "Sales.CSV").read_bytes())

        response = self.client.post("/download-output", json={"files": ["Sales.CSV", "Sales.CSV"]})
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["03-output/Sales.CSV"])
        self.assertEqual(self.client.post("/download-output", json={"files": ["Sales.CSV", "missing.csv"]}).status_code, 404)
        with zipfile.ZipFile(io.BytesIO(self.client.get("/download-output").data)) as archive:
            self.assertIn("03-output/query.sql", archive.namelist())
            self.assertNotIn("03-output/scratch.tmp", archive.namelist())

    def test_download_all_excludes_refresh_internals(self):
        runs = self.folder / "_RUNS"
        runs.mkdir()
        (runs / "example.json").write_text("{}", encoding="utf-8")
        for name in ("_refresh_status.json", "_refresh_history.json", "_refresh_complete.JSON"):
            (self.folder / name).write_text("{}", encoding="utf-8")
        with zipfile.ZipFile(io.BytesIO(self.client.get("/download-output").data)) as archive:
            self.assertCountEqual(archive.namelist(), [
                "03-output/Sales.CSV", "03-output/other.csv",
                "03-output/missing_data_report.csv", "03-output/query.sql",
            ])
