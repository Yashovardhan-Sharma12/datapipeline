# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from config import (
    QUERY_CHANGES_API_TIMEOUT_SECONDS,
    QUERY_PR_API_TIMEOUT_SECONDS,
    QUERY_TEST_API_TIMEOUT_SECONDS,
    QUERY_TEXT_MAX_BYTES,
    RUN_BY_LIMIT,
    UI_POLL_IDLE_MS,
)
from functions.functions_api_client import func_api_client_json
from functions.functions_filenames import func_filenames_is_direct
from functions.functions_git import (
    GitQueryError,
    func_git_open_pull_requests,
    func_git_open_query_pr,
    func_git_query_hash,
    func_git_query_history,
)
from functions.functions_sql_execution import QUERY_SOURCES, QueryNotFoundError
from functions.functions_sql_test import func_sql_test_execute
from functions.functions_ui import func_ui_api_request, func_ui_refresh_detail, func_ui_timestamp
from functions.functions_validation import func_validation_get_market

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_queries_key(source, filename):
    return f"{source}::{filename}"


def func_queries_data(state, previous=None):
    # ----------------------------------------------------------------
    # 1. Identify Reusable Data
    state = state or {}
    env = state["env"]
    latest = state["history"][0] if state["history"] else {}
    job_id = latest.get("job_id")
    manual = state.get("manual_job") or {}
    refresh_at = func_ui_timestamp(latest.get("started_at"))
    manual_at = func_ui_timestamp(manual.get("started_at"))
    if refresh_at and (manual_at is None or manual_at < refresh_at):
        manual = {}
    manual_signature = [
        manual.get("status"), [[row["filename"], row["status"], row.get("attempts")] for row in manual.get("results") or []],
    ]
    previous = previous or {}
    same_env = previous.get("env") == env
    same_refresh = same_env and previous.get("job_id") == job_id
    same_manual = same_env and previous.get("manual_signature") == manual_signature
    now = func_ui_timestamp(state["now"])
    metadata_time = func_ui_timestamp(previous.get("metadata_at"))
    metadata_fresh = metadata_time and (now - metadata_time).total_seconds() < UI_POLL_IDLE_MS / 1000
    need_metadata = not (same_refresh and same_manual and metadata_fresh)

    # ----------------------------------------------------------------
    # 2. Read Catalogue, Outputs And Latest Results
    calls = {"catalog": lambda: func_api_client_json(env, "/query-catalog")}
    if need_metadata:
        calls["files"] = lambda: func_api_client_json(env, "/output-files")
    if job_id and not same_refresh:
        calls["detail"] = lambda: func_ui_refresh_detail(env, job_id)
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {key: pool.submit(func_ui_api_request, call) for key, call in calls.items()}
        responses = {key: task.result() for key, task in futures.items()}

    files = responses["files"][0].get("files", []) if "files" in responses else previous.get("files", [])
    if "detail" in responses:
        scheduled_results = [
            {key: value for key, value in row.items() if key != "comparison_data"}
            for row in responses["detail"][0].get("results") or []
        ]
    else:
        scheduled_results = previous.get("scheduled_results", []) if same_refresh else []
    results = {}
    for row in scheduled_results + (manual.get("results") or []):
        results[func_queries_key(row["source"], row["filename"])] = row

    # ----------------------------------------------------------------
    # 3. Return Table Rows
    sources, _ = responses["catalog"]
    csvs = {file["name"].casefold(): file for file in files}
    rows = []
    for source in sources.get("sources", []):
        for name in source["files"]:
            key = func_queries_key(source["key"], name)
            row = results.get(key, {})
            csv_name = name.rsplit(".", 1)[0] + ".csv"
            csv_file = None if func_validation_get_market(name) else csvs.get(csv_name.casefold())
            attempt_times = [item["duration_seconds"] for item in row.get("attempt_details", [])]
            rows.append({
                "key": key, "source": source["key"], "source_label": source["label"], "filename": name,
                "result": row, "status": row.get("status"), "csv": csv_file,
                "duration": sum(attempt_times) if attempt_times else None,
            })
    return {
        "env": env, "job_id": job_id if not responses.get("detail", ({}, None))[1] else None,
        "scheduled_for": latest.get("scheduled_for"),
        "rows": rows, "scheduled_results": scheduled_results, "files": files, "manual_signature": manual_signature,
        "metadata_at": (state["now"] if need_metadata and not responses["files"][1]
                        else previous.get("metadata_at") if same_env else None),
        "errors": [error for _, error in responses.values() if error],
    }


def func_queries_filter(rows, term, source, result):
    term = (term or "").casefold().strip()
    return [
        row for row in rows
        if (not term or term in row["filename"].casefold())
        and (not source or row["source"] == source)
        and (not result
             or result == "complete" and row["status"] == "complete"
             or result == "issue" and (
                 row["status"] in {"failed", "empty"}
                 or (row["result"].get("validation") or {}).get("status") in {"missing_data", "error"}
                 or (row["result"].get("comparison_summary") or {}).get("difference_rows", 0) > 0
             ))
    ]


def func_queries_select(data, selected):
    keys = set(selected or [])
    return [row for row in (data or {}).get("rows", []) if row["key"] in keys]


def func_queries_run(env, rows, run_by):
    items = [{"source": row["source"], "filename": row["filename"]} for row in rows]
    return func_api_client_json(env, "/run-sql", method="POST", payload={"items": items, "run_by": run_by or None})


def func_queries_path(source, filename):
    if not isinstance(source, str) or source not in QUERY_SOURCES:
        raise ValueError("Select a customer or colleague source")
    if not func_filenames_is_direct(filename, ".sql"):
        raise ValueError("Only direct .sql filenames are allowed")
    folder = QUERY_SOURCES[source]["folder"].resolve()
    target = folder / filename
    if not target.is_file() or target.is_symlink() or target.resolve().parent != folder:
        raise QueryNotFoundError(f"SQL file not found: {filename}")
    return target


def func_queries_validate_text(sql):
    if not isinstance(sql, str) or not sql.strip() or "\0" in sql:
        raise ValueError("Enter SQL for this query")
    if len(sql.encode("utf-8")) > QUERY_TEXT_MAX_BYTES:
        raise ValueError(f"SQL must be at most {QUERY_TEXT_MAX_BYTES} bytes")
    return sql


def func_queries_read(source, filename, *, include_pulls=False):
    # ----------------------------------------------------------------
    # 1. Read The Active Query
    path = func_queries_path(source, filename)
    sql = path.read_text(encoding="utf-8-sig")
    result = {
        "source": source, "filename": path.name, "sql": sql, "base_hash": func_git_query_hash(sql),
        "history": [], "pull_requests": [],
    }

    # ----------------------------------------------------------------
    # 2. Read Git History And GitHub Changes
    try:
        result["history"] = func_git_query_history(path)
    except (GitQueryError, OSError) as exc:
        result["history_error"] = str(exc)
    if include_pulls:
        try:
            result["pull_requests"] = func_git_open_pull_requests(path)
        except (GitQueryError, OSError) as exc:
            result["pull_requests_error"] = str(exc)
    return result


def func_queries_test(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    source = payload.get("source")
    path = func_queries_path(source, payload.get("filename"))
    return func_sql_test_execute(source, path.name, func_queries_validate_text(payload.get("sql")))


def func_queries_pull_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    path = func_queries_path(payload.get("source"), payload.get("filename"))
    sql = func_queries_validate_text(payload.get("sql"))
    title, run_by = payload.get("title"), payload.get("run_by")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or len(title.splitlines()) != 1:
        raise ValueError("Enter a one-line pull request title")
    if not isinstance(run_by, str) or not 1 <= len(run_by.strip()) <= RUN_BY_LIMIT or len(run_by.splitlines()) != 1:
        raise ValueError("Enter the name to record on the pull request")
    base_hash = payload.get("base_hash")
    if base_hash is not None and (not isinstance(base_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", base_hash)):
        raise ValueError("Invalid query revision")
    return func_git_open_query_pr(path, sql, title.strip(), run_by.strip(), base_hash)


def func_queries_load_drawer(env, row, *, changes=False):
    source = quote(row["source"], safe="")
    filename = quote(row["filename"], safe="")
    return func_api_client_json(
        env, f"/queries/{source}/{filename}", params={"changes": int(changes)},
        timeout=QUERY_CHANGES_API_TIMEOUT_SECONDS if changes else None,
    )


def func_queries_preview_draft(env, row, sql):
    payload = {"source": row["source"], "filename": row["filename"], "sql": sql}
    return func_api_client_json(env, "/queries/test", method="POST", payload=payload, timeout=QUERY_TEST_API_TIMEOUT_SECONDS)


def func_queries_submit_draft(env, row, sql, title, run_by, base_hash):
    payload = {
        "source": row["source"], "filename": row["filename"], "sql": sql,
        "title": title, "run_by": run_by, "base_hash": base_hash,
    }
    return func_api_client_json(env, "/queries/pull-request", method="POST", payload=payload, timeout=QUERY_PR_API_TIMEOUT_SECONDS)


def func_queries_draft_passed(sql, editor, test):
    if not isinstance(sql, str) or not editor or not test or test.get("editor") != editor:
        return False
    return test["result"]["status"] in {"success", "empty"} and test["draft_hash"] == func_git_query_hash(sql)
