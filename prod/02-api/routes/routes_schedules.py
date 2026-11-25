# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from flask import jsonify, request

from functions.functions_api_client import ApiClientError, func_api_client_json
from functions.functions_schedules import (
    ScheduleConflictError,
    func_schedules_add_project,
    func_schedules_describe,
    func_schedules_update,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Routes


def route_schedules_list():
    try:
        return jsonify({"status": "ok", **func_schedules_describe()})
    except (ValueError, OSError) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


def route_schedules_add_project():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
    project = payload.get("project")
    try:
        discovered = func_api_client_json("runner", "/projects", params={"env": "prod"}).get("projects", [])
        if not any(row["project"] == project and row["runnable"] for row in discovered):
            raise ValueError("Select a runnable prod project")
        projects = func_schedules_add_project(project, payload.get("run_by"))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except ApiClientError as exc:
        return jsonify({"status": "error", "message": str(exc)}), exc.status
    except OSError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    return jsonify({"status": "ok", "projects": projects})


def route_schedules_update():
    from app import scheduler

    try:
        updated = func_schedules_update(scheduler, request.get_json(silent=True))
    except ScheduleConflictError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except OSError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    return jsonify({"status": "ok", **updated})
