# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.message import Message
from urllib.parse import quote, urlencode

from config import PIPELINE_API_URLS, RUN_BY_LIMIT, TIMEZONE, UI_API_WORKERS, UI_POLL_ACTIVE_MS, UI_POLL_IDLE_MS
from functions.functions_api_client import (
    ApiClientError,
    func_api_client_json,
    func_api_client_open,
    func_api_client_submit_runs,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
step_labels = {"query": "Queries", "diagnostics": "Diagnostics", "content_gen": "Content generation", "upload": "Database upload"}
step_colours = {"query": "query", "diagnostics": "diag", "content_gen": "gen", "upload": "up"}
status_labels = {
    "success": ("Finished", "ok"), "complete": ("Updated", "ok"), "running": ("Running", "run"),
    "completed_with_failures": ("Problem", "bad"), "failed": ("Failed", "bad"),
    "empty": ("No rows", "warn"), "stopped": ("Stopped", "idle"), "queued": ("Waiting", "idle"),
    "waiting_for_refresh": ("Waiting for refresh", "idle"), "pending": ("Pending", "idle"),
    "retrying": ("Retrying", "warn"), "skipped": ("Skipped", "idle"),
}

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_ui_env(env):
    return env if env in PIPELINE_API_URLS else "prod"


def func_ui_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp.astimezone(TIMEZONE) if timestamp.tzinfo else timestamp.replace(tzinfo=TIMEZONE)
    except ValueError:
        return None


def func_ui_time(value, fmt="%H:%M", default="—"):
    timestamp = func_ui_timestamp(value)
    return timestamp.strftime(fmt) if timestamp else default


def func_ui_seconds(record, now=None):
    start = func_ui_timestamp(record.get("started_at"))
    end = func_ui_timestamp(record.get("completed_at")) or now or datetime.now(TIMEZONE)
    return max(0, (end - start).total_seconds()) if start else None


def func_ui_duration(seconds):
    if seconds is None:
        return "—"
    units = max(0, round(seconds))
    if units < 60:
        return f"{units} s"
    hours, minutes = divmod(round(units / 60), 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def func_ui_failed_run_step(run):
    return next((step for step in run.get("steps", []) if step.get("status") == "failed"), None)


def func_ui_run_label(run):
    return {
        "scheduled": "After the scheduled refresh",
        "next_refresh": "After the next refresh",
        "retry": "Manual retry",
    }.get(run.get("trigger"), "Manual")


def func_ui_api_request(call, *, allow_missing=False):
    try:
        return call(), None
    except ApiClientError as exc:
        return {}, None if allow_missing and exc.status == 404 else str(exc)


def func_ui_dashboard(env, query_run=None):
    # ----------------------------------------------------------------
    # 1. Configure Requests
    env = func_ui_env(env)
    calls = {
        "history": lambda: func_api_client_json(env, "/refresh-history"),
        "schedule": lambda: func_api_client_json(env, "/api/schedules"),
        "projects": lambda: func_api_client_json("runner", "/projects", params={"env": env}),
        "contentgen": lambda: func_api_client_json("runner", "/runs", params={"env": env}),
    }
    if query_run and query_run.get("env") == env:
        job_id = quote(query_run["job_id"], safe="")
        calls["manual_job"] = lambda: func_api_client_json(env, f"/status/{job_id}")

    # ----------------------------------------------------------------
    # 2. Read Independent APIs
    with ThreadPoolExecutor(max_workers=UI_API_WORKERS) as pool:
        futures = {
            key: pool.submit(func_ui_api_request, call, allow_missing=key == "manual_job")
            for key, call in calls.items()
        }
        results = {key: future.result() for key, future in futures.items()}

    # ----------------------------------------------------------------
    # 3. Return
    history, _ = results["history"]
    projects, _ = results["projects"]
    contentgen, _ = results["contentgen"]
    manual_job = results.get("manual_job", ({}, None))[0]
    if manual_job.get("results"):
        manual_job = {**manual_job, "results": [
            {key: value for key, value in row.items() if key != "comparison_data"}
            for row in manual_job["results"]
        ]}
    state = {
        "env": env,
        "now": datetime.now(TIMEZONE).isoformat(),
        "active": history.get("active", []),
        "manual": history.get("manual", []),
        "history": history.get("history", []),
        "next_before": history.get("next_before"),
        "projects": projects.get("projects", []),
        "queue": contentgen.get("queue", []),
        "runs": contentgen.get("runs", []),
        "schedule": results["schedule"][0],
        "manual_job": manual_job,
        "errors": {key: error for key, (_, error) in results.items() if error},
    }
    busy = (
        state["active"] or any(run["status"] == "running" for run in state["manual"])
        or any(run["status"] in {"running", "queued"} for run in state["queue"])
    )
    if query_run and query_run.get("env") == env:
        busy = busy or manual_job.get("status") == "running"
    return state, UI_POLL_ACTIVE_MS if busy else UI_POLL_IDLE_MS


def func_ui_attention(state):
    env = state.get("env", "prod")
    issues = []
    history = state.get("history", [])
    if history:
        latest = history[0]
        for row in latest.get("failed_queries", []):
            issues.append({
                "id": f"{env}:{latest['job_id']}:{row['source_label']}:{row['filename']}",
                "kind": "bad", "label": "Query error", "title": row["filename"],
                "message": row["reason"], "meta": row["source_label"], "href": "/queries",
            })
        quality = latest.get("quality") or {}
        warnings = (quality.get("missing_latest_week") or 0, latest.get("empty_queries") or 0)
        if any(warnings):
            missing, empty = warnings
            notes = []
            if missing:
                notes.append(f"{missing} queries are missing the latest Tesco week.")
            if empty:
                notes.append(f"{empty} queries returned no rows and retained their previous CSV where available.")
            issues.append({
                "id": f"{env}:{latest['job_id']}:quality", "kind": "warn", "label": "Data warning",
                "title": "Latest refresh", "message": " ".join(notes), "href": "/history",
            })
    seen = set()
    for run in state.get("runs", []):
        project = run["project"]
        if project in seen:
            continue
        seen.add(project)
        if run["status"] == "failed":
            step = func_ui_failed_run_step(run)
            issues.append({
                "id": run["run_id"], "kind": "bad", "label": "ContentGen failed", "title": project,
                "message": (step or {}).get("error") or run.get("error") or "Open the run for details.",
                "meta": step_labels.get((step or {}).get("step")), "href": "/contentgen",
            })
    scheduled = set(state.get("schedule", {}).get("projects", []))
    if env == "prod" and "schedule" not in state.get("errors", {}):
        for project in state.get("projects", []):
            if project["new"] and project["runnable"] and project["project"] not in scheduled:
                issues.append({
                    "id": f"new:{project['project']}", "kind": "new", "label": "New project found",
                    "title": project["project"], "message": "The folder is ready to run in prod.",
                    "project": project["project"],
                })
    return issues


def func_ui_refresh_detail(env, job_id, active=False):
    key = quote(job_id, safe="")
    if active:
        return func_api_client_json(env, f"/status/{key}")
    return func_api_client_json(env, f"/refresh-history/{key}")["refresh"]


def func_ui_run_detail(run_id, step=None):
    key = quote(run_id, safe="")
    run = func_api_client_json("runner", f"/runs/{key}")["run"]
    run_steps = run.get("steps", [])
    preferred = next((item["step"] for item in run_steps if item["status"] in {"running", "failed"}), None)
    if preferred is None and run_steps:
        preferred = run_steps[-1]["step"]
    selected = step if step in {item["step"] for item in run_steps} else preferred
    log = func_api_client_json("runner", f"/runs/{key}/log/{selected}") if selected else {}
    return run, selected, log


def func_ui_submit_items(items, run_by, trigger="manual", retry_run_id=None):
    if not isinstance(run_by, str) or not 1 <= len(run_by.strip()) <= RUN_BY_LIMIT:
        raise ValueError("Enter your name in Run by before queueing runs.")
    return func_api_client_submit_runs({
        "items": items, "trigger": trigger, "refresh_job_id": None,
        "run_by": run_by.strip(), "retry_run_id": retry_run_id,
    })


def func_ui_stop_run(run_id):
    key = quote(run_id, safe="")
    return func_api_client_json("runner", f"/runs/{key}/stop", method="POST")


def func_ui_add_project(project, run_by):
    return func_api_client_json("prod", "/api/schedules/projects", method="POST",
                                payload={"project": project, "run_by": run_by})


def func_ui_download_link(env, filename=None):
    url = f"/desk-download/{func_ui_env(env)}"
    return url + "?" + urlencode({"file": filename}) if filename else url


def func_ui_download_selected(env, filenames):
    with func_api_client_open(env, "/download-output", method="POST", payload={"files": filenames}, download=True) as response:
        content = response.read()
        headers = Message()
        headers["Content-Disposition"] = response.headers.get("Content-Disposition", "")
        filename = headers.get_filename() or "03-output.zip"
    return {"content": base64.b64encode(content).decode("ascii"),
            "filename": filename, "type": "application/zip", "base64": True}
