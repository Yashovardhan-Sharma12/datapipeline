# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from config import REFRESH_HISTORY_LIMIT
from functions.functions_api_client import func_api_client_json
from functions.functions_ui import func_ui_api_request, func_ui_refresh_detail

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_history_load_older(env, before):
    page = func_api_client_json(env, "/refresh-history", params={"before": before})
    ids = [row["job_id"] for row in page["history"]]
    runs, _ = func_ui_api_request(lambda: func_api_client_json(
        "runner", "/runs", params={"env": env, "refresh_job_id": ids},
    )) if ids else ({}, None)
    return page["history"], page["next_before"], runs.get("runs", [])


def func_history_merge(rows, previous, key):
    merged = {}
    for row in rows + previous:
        merged.setdefault(row[key], row)
    return list(merged.values())[:REFRESH_HISTORY_LIMIT]


def func_history_link_runs(rows, runs):
    by_refresh = {}
    for run in runs:
        if run.get("refresh_job_id"):
            by_refresh.setdefault(run["refresh_job_id"], {})[run["run_id"]] = run

    linked = []
    for row in rows:
        contentgen = row.get("contentgen") or {}
        matched = by_refresh.get(row["job_id"], {})
        combined = dict(matched)
        for receipt in contentgen.get("runs", []):
            combined.setdefault(receipt["run_id"], receipt)
        linked.append({**row, "linked_runs": list(combined.values())})
    return linked


def func_history_is_problem(row):
    quality = row.get("quality") or {}
    return (
        row["status"] in {"failed", "completed_with_failures"}
        or (row.get("empty_queries") or 0) > 0
        or (quality.get("missing_latest_week") or 0) > 0
        or (quality.get("validation_error") or 0) > 0
        or any(run["status"] == "failed" for run in row["linked_runs"])
    )


def func_history_detail(env, job_id):
    source = func_ui_refresh_detail(env, job_id)
    keys = ("filename", "status", "message", "error", "error_detail", "last_error", "validation", "fallback_output")
    return {
        **source,
        "results": [{key: row[key] for key in keys if key in row} for row in source.get("results") or []],
    }
