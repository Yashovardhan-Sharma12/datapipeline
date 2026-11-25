# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from configparser import ConfigParser
from pathlib import Path
from zoneinfo import ZoneInfo

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_config_read(path, *, required=False):
    settings = ConfigParser(interpolation=None)
    settings.optionxform = str.upper
    try:
        with path.open(encoding="utf-8-sig") as handle:
            settings.read_file(handle)
    except FileNotFoundError:
        if required:
            raise
    else:
        log_message(f"Pipeline configuration loaded | file={path}", 'INFO')
    return {section.casefold(): dict(settings[section]) for section in settings.sections()}


def func_config_get(name, default=None):
    return os.getenv(name, config_values.get(name, default))


def func_config_find_repo(api_folder):
    for folder in api_folder.parents:
        if (folder / ".git").exists():
            return folder
    environment_parent = api_folder.parent.parent
    return environment_parent.parent if environment_parent.name == "src" else environment_parent


def func_config_resolve_path(value):
    return (REPO_FOLDER / Path(value).expanduser()).resolve()


def func_config_find_environment(api_folder, repo_folder, env):
    if api_folder.parent.name.casefold() == env:
        return api_folder.parent
    candidates = (api_folder.parent.with_name(env), repo_folder / "src" / env, repo_folder / env)
    return next((folder for folder in candidates if (folder / "01-queries").is_dir()), candidates[0])


# ----------------------------------------------------------------------------------------------------------------------
#%% Configure

# Locate the checkout from this file in either src/<env>/02-api or <env>/02-api.
API_FOLDER = Path(__file__).resolve().parent
REPO_FOLDER = func_config_find_repo(API_FOLDER)
config_override = os.getenv("DATAPIPELINE_CONFIG_FILE")
base_settings = func_config_read(API_FOLDER / "config.ini")
local_settings = func_config_read(
    func_config_resolve_path(config_override) if config_override else API_FOLDER / "config.local.ini",
    required=bool(config_override),
)
base_common = base_settings.get("common", {})
local_common = local_settings.get("common", {})
config_values = {**base_common, **local_common}
folder_hint = func_config_resolve_path(func_config_get("DATAPIPELINE_ENV_FOLDER", API_FOLDER.parent))
ENV_NAME = func_config_get("ENV_NAME", folder_hint.name).strip().casefold()
if ENV_NAME not in {"prod", "dev"}:
    raise ValueError("Set ENV_NAME to prod or dev when the pipeline folder has a different name.")
config_values = {
    **base_common, **base_settings.get(ENV_NAME, {}),
    **local_common, **local_settings.get(ENV_NAME, {}),
}
ENV_FOLDER = func_config_resolve_path(func_config_get(
    "DATAPIPELINE_ENV_FOLDER", func_config_find_environment(API_FOLDER, REPO_FOLDER, ENV_NAME),
))

DATAPIPELINE_HOST = func_config_get("DATAPIPELINE_HOST", "0.0.0.0")
DATAPIPELINE_PORT = int(func_config_get("DATAPIPELINE_PORT", "8001" if ENV_NAME == "dev" else "8000"))
PROD_API_URL = func_config_get("PROD_API_URL", "http://127.0.0.1:8000").rstrip("/")
DEV_API_URL = func_config_get("DEV_API_URL", "http://127.0.0.1:8001").rstrip("/")
RUNNER_URL = func_config_get("RUNNER_URL", "http://127.0.0.1:9100").rstrip("/")
CONTENTGEN_API_URL = func_config_get("CONTENTGEN_API_URL", "http://127.0.0.1:9100").rstrip("/")
CONTENTGEN_TIMEOUT_SECONDS = int(func_config_get("CONTENTGEN_TIMEOUT_SECONDS", "10"))
GITHUB_TOKEN_ENV_NAME = func_config_get("GITHUB_TOKEN_ENV_NAME", "GITHUB_TOKEN")
GITHUB_WEB_URL = func_config_get("DATAPIPELINE_GITHUB_URL", "https://github.com").rstrip("/")
GITHUB_API_URL = func_config_get(
    "DATAPIPELINE_GITHUB_API_URL",
    "https://api.github.com" if GITHUB_WEB_URL == "https://github.com" else GITHUB_WEB_URL + "/api/v3",
).rstrip("/")
GITHUB_TIMEOUT_SECONDS = float(func_config_get("DATAPIPELINE_GITHUB_TIMEOUT_SECONDS", "10"))
GIT_COMMAND_TIMEOUT_SECONDS = float(func_config_get("DATAPIPELINE_GIT_TIMEOUT_SECONDS", "60"))
GIT_AUTHOR_NAME = func_config_get("DATAPIPELINE_GIT_AUTHOR_NAME", "Refresh Desk")
GIT_AUTHOR_EMAIL = func_config_get("DATAPIPELINE_GIT_AUTHOR_EMAIL", "refresh-desk@users.noreply.github.com")
QUERY_HISTORY_LIMIT = 20
QUERY_TEXT_MAX_BYTES = int(func_config_get("DATAPIPELINE_QUERY_MAX_BYTES", "262144"))
QUERY_TEST_LOGIN_TIMEOUT_SECONDS = max(1, int(func_config_get("DATAPIPELINE_QUERY_LOGIN_TIMEOUT", "10")))
QUERY_TEST_TIMEOUT_SECONDS = max(1, int(func_config_get("DATAPIPELINE_QUERY_TEST_TIMEOUT", "30")))
QUERY_TEST_ROW_LIMIT = 50
QUERY_CHANGES_API_TIMEOUT_SECONDS = float(func_config_get("DATAPIPELINE_QUERY_CHANGES_API_TIMEOUT", "60"))
QUERY_TEST_API_TIMEOUT_SECONDS = QUERY_TEST_LOGIN_TIMEOUT_SECONDS + QUERY_TEST_TIMEOUT_SECONDS + 10
QUERY_PR_API_TIMEOUT_SECONDS = float(func_config_get("DATAPIPELINE_QUERY_PR_API_TIMEOUT", "240"))
CONTENTGEN_RUNNER_ENABLED = func_config_get("CONTENTGEN_RUNNER_ENABLED", "1" if ENV_NAME == "dev" else "0") == "1"
PIPELINE_API_URLS = {"prod": PROD_API_URL, "dev": DEV_API_URL}
API_TIMEOUT_SECONDS = float(func_config_get("REFRESH_DESK_API_TIMEOUT_SECONDS", "4"))
API_DOWNLOAD_TIMEOUT_SECONDS = float(func_config_get("REFRESH_DESK_DOWNLOAD_TIMEOUT_SECONDS", "120"))
UI_POLL_ACTIVE_MS = int(func_config_get("REFRESH_DESK_ACTIVE_POLL_MS", "5000"))
UI_POLL_IDLE_MS = int(func_config_get("REFRESH_DESK_IDLE_POLL_MS", "60000"))
UI_API_WORKERS = int(func_config_get("REFRESH_DESK_API_WORKERS", "5"))
RUN_BY_LIMIT = 100

TIMEZONE = ZoneInfo(func_config_get("DATAPIPELINE_TIMEZONE", "Asia/Kolkata"))
GIT_REPO_PATH = func_config_resolve_path(func_config_get("DATAPIPELINE_GIT_REPO_PATH", REPO_FOLDER))
LEGACY_API_FILE = API_FOLDER / "data_pipeline_api.py"
SCHEDULES_FILE = func_config_resolve_path(func_config_get(
    "DATAPIPELINE_SCHEDULES_FILE", ENV_FOLDER / API_FOLDER.name / "data" / "schedules.json",
))
ASSETS_FOLDER = API_FOLDER / "assets"
PAGES_FOLDER = API_FOLDER / "pages"
DEFAULT_SCHEDULED_PROJECTS = ("ccec",) if ENV_NAME == "prod" else ()

CUSTOMER_SQL_FOLDER = func_config_resolve_path(func_config_get(
    "DATAPIPELINE_CUSTOMER_SQL_FOLDER",
    ENV_FOLDER / "01-queries" / "01-customer" / "02-queries" / "01-active",
))
COLLEAGUE_SQL_FOLDER = func_config_resolve_path(func_config_get(
    "DATAPIPELINE_COLLEAGUE_SQL_FOLDER",
    ENV_FOLDER / "01-queries" / "02-colleague" / "02-queries" / "01-active",
))
OUTPUT_ARCHIVE_ROOT = "03-output"
OUTPUT_FOLDER = func_config_resolve_path(func_config_get("DATAPIPELINE_OUTPUT_FOLDER", ENV_FOLDER / OUTPUT_ARCHIVE_ROOT))
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
        "server": func_config_get("DATAPIPELINE_CUSTOMER_DB_SERVER", "tpc137928bg0758.tgrc.tesco.org"),
        "database": func_config_get("DATAPIPELINE_CUSTOMER_DB_NAME", "MIUsers"),
    },
    "colleague": {
        "label": "Colleague",
        "folder": COLLEAGUE_SQL_FOLDER,
        "server": func_config_get("DATAPIPELINE_COLLEAGUE_DB_SERVER", "tpc013989.tgrc.tesco.org"),
        "database": func_config_get("DATAPIPELINE_COLLEAGUE_DB_NAME", "CEC_Archives"),
    },
}

MAX_QUERY_ATTEMPTS = 3
QUERY_RETRY_DELAYS_SECONDS = (5, 10)
REFRESH_HISTORY_LIMIT = 200
SQL_JOB_RETENTION_LIMIT = max(1, int(func_config_get("DATAPIPELINE_SQL_JOB_RETENTION_LIMIT", "200")))
REFRESH_HISTORY_PAGE_SIZE = 20
REFRESH_HISTORY_REASON_LIMIT = 240
ATOMIC_REPLACE_ATTEMPTS = 10
CONSOLE_WIDTH = 100

# Separate pools prevent a slow Customer queue from starving Colleague queries.
# CEC_Archives is less tolerant of concurrent long-running ODBC sessions.
SOURCE_MAX_WORKERS = {
    "customer": int(func_config_get("DATAPIPELINE_CUSTOMER_WORKERS", "2")),
    "colleague": int(func_config_get("DATAPIPELINE_COLLEAGUE_WORKERS", "1")),
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

REFRESH_DESK_UI_ENABLED = func_config_get("REFRESH_DESK_UI_ENABLED", "1" if ENV_NAME == "prod" else "0") == "1"
API_DOWNLOAD_CHUNK_BYTES = 65536
