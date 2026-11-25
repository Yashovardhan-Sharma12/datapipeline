# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from pathlib import Path
from zoneinfo import ZoneInfo

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure

# Resolve paths relative to this file in a deployed src/<env>/02-api checkout.
API_FOLDER = Path(os.path.abspath(__file__)).parent
ENV_FOLDER = Path(os.path.abspath(os.getenv("DATAPIPELINE_ENV_FOLDER", API_FOLDER.parent)))
ENV_NAME = os.getenv("ENV_NAME", ENV_FOLDER.name)

DATAPIPELINE_HOST = os.getenv("DATAPIPELINE_HOST", "0.0.0.0")
DATAPIPELINE_PORT = int(os.getenv("DATAPIPELINE_PORT", "8001" if ENV_NAME == "dev" else "8000"))
PROD_API_URL = os.getenv("PROD_API_URL", "http://127.0.0.1:8000").rstrip("/")
DEV_API_URL = os.getenv("DEV_API_URL", "http://127.0.0.1:8001").rstrip("/")
RUNNER_URL = os.getenv("RUNNER_URL", "http://127.0.0.1:9100").rstrip("/")
CONTENTGEN_API_URL = os.getenv("CONTENTGEN_API_URL", "http://127.0.0.1:9100").rstrip("/")
CONTENTGEN_TIMEOUT_SECONDS = int(os.getenv("CONTENTGEN_TIMEOUT_SECONDS", "10"))
GITHUB_TOKEN_ENV_NAME = os.getenv("GITHUB_TOKEN_ENV_NAME", "GITHUB_TOKEN")
GITHUB_WEB_URL = os.getenv("DATAPIPELINE_GITHUB_URL", "https://github.com").rstrip("/")
GITHUB_API_URL = os.getenv(
    "DATAPIPELINE_GITHUB_API_URL",
    "https://api.github.com" if GITHUB_WEB_URL == "https://github.com" else GITHUB_WEB_URL + "/api/v3",
).rstrip("/")
GITHUB_TIMEOUT_SECONDS = float(os.getenv("DATAPIPELINE_GITHUB_TIMEOUT_SECONDS", "10"))
GIT_COMMAND_TIMEOUT_SECONDS = float(os.getenv("DATAPIPELINE_GIT_TIMEOUT_SECONDS", "60"))
GIT_AUTHOR_NAME = os.getenv("DATAPIPELINE_GIT_AUTHOR_NAME", "Refresh Desk")
GIT_AUTHOR_EMAIL = os.getenv("DATAPIPELINE_GIT_AUTHOR_EMAIL", "refresh-desk@users.noreply.github.com")
QUERY_HISTORY_LIMIT = 20
QUERY_TEXT_MAX_BYTES = int(os.getenv("DATAPIPELINE_QUERY_MAX_BYTES", "262144"))
QUERY_TEST_LOGIN_TIMEOUT_SECONDS = max(1, int(os.getenv("DATAPIPELINE_QUERY_LOGIN_TIMEOUT", "10")))
QUERY_TEST_TIMEOUT_SECONDS = max(1, int(os.getenv("DATAPIPELINE_QUERY_TEST_TIMEOUT", "30")))
QUERY_TEST_ROW_LIMIT = 50
QUERY_CHANGES_API_TIMEOUT_SECONDS = float(os.getenv("DATAPIPELINE_QUERY_CHANGES_API_TIMEOUT", "60"))
QUERY_TEST_API_TIMEOUT_SECONDS = QUERY_TEST_LOGIN_TIMEOUT_SECONDS + QUERY_TEST_TIMEOUT_SECONDS + 10
QUERY_PR_API_TIMEOUT_SECONDS = float(os.getenv("DATAPIPELINE_QUERY_PR_API_TIMEOUT", "240"))
CONTENTGEN_RUNNER_ENABLED = os.getenv("CONTENTGEN_RUNNER_ENABLED", "1" if ENV_NAME == "dev" else "0") == "1"
PIPELINE_API_URLS = {"prod": PROD_API_URL, "dev": DEV_API_URL}
API_TIMEOUT_SECONDS = float(os.getenv("REFRESH_DESK_API_TIMEOUT_SECONDS", "4"))
API_DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("REFRESH_DESK_DOWNLOAD_TIMEOUT_SECONDS", "120"))
UI_POLL_ACTIVE_MS = int(os.getenv("REFRESH_DESK_ACTIVE_POLL_MS", "5000"))
UI_POLL_IDLE_MS = int(os.getenv("REFRESH_DESK_IDLE_POLL_MS", "60000"))
UI_API_WORKERS = int(os.getenv("REFRESH_DESK_API_WORKERS", "5"))
RUN_BY_LIMIT = 100

TIMEZONE = ZoneInfo(os.getenv("DATAPIPELINE_TIMEZONE", "Asia/Kolkata"))
GIT_REPO_PATH = os.getenv("DATAPIPELINE_GIT_REPO_PATH")
LEGACY_API_FILE = API_FOLDER / "data_pipeline_api.py"
SCHEDULES_FILE = Path(os.getenv("DATAPIPELINE_SCHEDULES_FILE", API_FOLDER / "data" / "schedules.json"))
ASSETS_FOLDER = API_FOLDER / "assets"
PAGES_FOLDER = API_FOLDER / "pages"
DEFAULT_SCHEDULED_PROJECTS = ("ccec",) if ENV_NAME == "prod" else ()

CUSTOMER_SQL_FOLDER = Path(os.getenv(
    "DATAPIPELINE_CUSTOMER_SQL_FOLDER",
    ENV_FOLDER / "01-queries" / "01-customer" / "02-queries" / "01-active",
))
COLLEAGUE_SQL_FOLDER = Path(os.getenv(
    "DATAPIPELINE_COLLEAGUE_SQL_FOLDER",
    ENV_FOLDER / "01-queries" / "02-colleague" / "02-queries" / "01-active",
))
OUTPUT_ARCHIVE_ROOT = "03-output"
OUTPUT_FOLDER = Path(os.getenv("DATAPIPELINE_OUTPUT_FOLDER", ENV_FOLDER / OUTPUT_ARCHIVE_ROOT))
REFRESH_STATUS_FILE = OUTPUT_FOLDER / "_refresh_status.json"
REFRESH_HISTORY_FILE = OUTPUT_FOLDER / "_refresh_history.json"
REFRESH_COMPLETE_FILE = OUTPUT_FOLDER / "_refresh_complete.json"
REFRESH_RUNS_FOLDER = OUTPUT_FOLDER / "_runs"
MISSING_DATA_REPORT_FILE = OUTPUT_FOLDER / "missing_data_report.csv"

# The registry keeps Customer and Colleague queries on separate connections.
SQL_SOURCE_CONFIG = {
    "customer": {
        "label": "Customer",
        "folder": CUSTOMER_SQL_FOLDER,
        "server": os.getenv("DATAPIPELINE_CUSTOMER_DB_SERVER", "tpc137928bg0758.tgrc.tesco.org"),
        "database": os.getenv("DATAPIPELINE_CUSTOMER_DB_NAME", "MIUsers"),
    },
    "colleague": {
        "label": "Colleague",
        "folder": COLLEAGUE_SQL_FOLDER,
        "server": os.getenv("DATAPIPELINE_COLLEAGUE_DB_SERVER", "tpc013989.tgrc.tesco.org"),
        "database": os.getenv("DATAPIPELINE_COLLEAGUE_DB_NAME", "CEC_Archives"),
    },
}

MAX_QUERY_ATTEMPTS = 3
QUERY_RETRY_DELAYS_SECONDS = (5, 10)
REFRESH_HISTORY_LIMIT = 200
SQL_JOB_RETENTION_LIMIT = max(1, int(os.getenv("DATAPIPELINE_SQL_JOB_RETENTION_LIMIT", "200")))
REFRESH_HISTORY_PAGE_SIZE = 20
REFRESH_HISTORY_REASON_LIMIT = 240
ATOMIC_REPLACE_ATTEMPTS = 10
CONSOLE_WIDTH = 100

# Separate pools prevent a slow Customer queue from starving Colleague queries.
# CEC_Archives is less tolerant of concurrent long-running ODBC sessions.
SOURCE_MAX_WORKERS = {
    "customer": int(os.getenv("DATAPIPELINE_CUSTOMER_WORKERS", "2")),
    "colleague": int(os.getenv("DATAPIPELINE_COLLEAGUE_WORKERS", "1")),
}

# ODBC / SQL Server errors that require a fresh connection before retrying.
ODBC_CONNECTION_ERROR_TOKENS = (
    "08S01",  # Communication link failure
    "08001",  # Client unable to establish connection
    "08003",  # Connection does not exist
    "08007",  # Connection failure during transaction
    "HYT00",  # Retry during login; an execution timeout is reported separately
    "HYT01",  # Connection timeout
)

REFRESH_DESK_UI_ENABLED = os.getenv("REFRESH_DESK_UI_ENABLED", "1" if ENV_NAME == "prod" else "0") == "1"
API_DOWNLOAD_CHUNK_BYTES = 65536
