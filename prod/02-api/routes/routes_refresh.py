# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from flask import jsonify, request

from config import REFRESH_HISTORY_PAGE_SIZE
from functions.functions_refresh import (
    func_refresh_get_active,
    func_refresh_get_detail,
    func_refresh_get_manual_jobs,
    func_refresh_load_history,
)
from functions.functions_sql_execution import func_sql_get_job

# ----------------------------------------------------------------------------------------------------------------------
#%% Routes


def route_refresh_history():
    try:
        before = request.args.get("before")
        history, next_before = func_refresh_load_history(
            limit=request.args.get("limit", REFRESH_HISTORY_PAGE_SIZE),
            before=before,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({
        "status": "ok",
        "history": history,
        "next_before": next_before,
        "active": func_refresh_get_active() if before is None else [],
        "manual": func_refresh_get_manual_jobs() if before is None else [],
    })


def route_refresh_detail(job_id):
    refresh = func_refresh_get_detail(job_id)
    if refresh is None:
        return jsonify({"status": "error", "message": "Refresh not found"}), 404
    return jsonify({"status": "ok", "refresh": refresh})


def route_refresh_status(job_id):
    job = func_sql_get_job(job_id)
    if job is None:
        return jsonify({"status": "error", "message": "Job not found"}), 404
    return jsonify(job)
