# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from flask import jsonify, request

from config import ENV_FOLDER, LEGACY_API_FILE
from functions.functions_git import GitQueryError
from functions.functions_queries import func_queries_pull_request, func_queries_read, func_queries_test
from functions.functions_sql_execution import (
    QueryNotFoundError,
    func_sql_get_catalog,
    func_sql_prepare_job,
    func_sql_prepare_selected,
    func_sql_start_job,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Routes


def route_queries_catalog():
    """Return exactly what the running API can currently discover."""
    catalog = func_sql_get_catalog()
    return jsonify({
        "status": "success",
        "total_query_count": sum(source["count"] for source in catalog),
        "sources": catalog,
        "api_file": str(LEGACY_API_FILE),
        "environment_folder": str(ENV_FOLDER),
    })


def route_queries_run_sql():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
    try:
        sql_tasks = (
            func_sql_prepare_selected(data["items"])
            if "items" in data else func_sql_prepare_job(data.get("filename"), data.get("source"))
        )
        job = func_sql_start_job(sql_tasks, run_by=data.get("run_by"))
    except QueryNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except (ValueError, RuntimeError) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify(job)


def route_queries_read(source, filename):
    try:
        query = func_queries_read(source, filename, include_pulls=request.args.get("changes", "1") != "0")
    except QueryNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except OSError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    return jsonify({"status": "ok", **query})


def route_queries_test():
    try:
        result = func_queries_test(request.get_json(silent=True))
    except QueryNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify(result)


def route_queries_pull_request():
    try:
        result = func_queries_pull_request(request.get_json(silent=True))
    except QueryNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except GitQueryError as exc:
        return jsonify({"status": "error", "message": str(exc)}), exc.status
    except OSError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    return jsonify(result), 201
