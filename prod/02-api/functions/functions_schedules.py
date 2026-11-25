# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import json
import re
import threading
import uuid
from datetime import datetime, timedelta

from apscheduler.schedulers.base import STATE_RUNNING
from apscheduler.triggers.cron import CronTrigger

from config import (
    COLLEAGUE_SQL_FOLDER,
    CONSOLE_WIDTH,
    CONTENTGEN_API_URL,
    CONTENTGEN_RUNNER_ENABLED,
    CUSTOMER_SQL_FOLDER,
    DEFAULT_SCHEDULED_PROJECTS,
    ENV_NAME,
    MAX_QUERY_ATTEMPTS,
    OUTPUT_FOLDER,
    RUN_BY_LIMIT,
    SCHEDULES_FILE,
    SOURCE_MAX_WORKERS,
    TIMEZONE,
)
from functions.functions_console import print_banner, print_detail
from functions.functions_api_client import func_api_client_json
from functions.functions_file_io import func_file_io_write_json
from functions.functions_git import func_git_pull, git_repo_path
from functions.functions_sql_execution import QUERY_SOURCES, func_sql_get_catalog

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
schedule_lock = threading.Lock()
git_job_id = "hourly_git_pull"
schedule_groups = {
    "mon": "Mondays", "tue-sun": "Tuesday to Sunday", "daily": "Every day", "mon-fri": "Monday to Friday",
}
schedule_weekdays = {
    "mon": {0}, "tue-sun": set(range(1, 7)), "daily": set(range(7)), "mon-fri": set(range(5)),
}
prod_slots = (
    *(
        {"id": f"monday_{hour}30_refresh", "days": "mon", "time": f"{hour}:30",
         "run_contentgen": True, "include_diagnostics": hour == 13, "paused": False}
        for hour in range(13, 20)
    ),
    {"id": "monday_1900_refresh", "days": "mon", "time": "19:00", "run_contentgen": False,
     "include_diagnostics": False, "paused": False},
    {"id": "daily_1430_refresh", "days": "tue-sun", "time": "14:30", "run_contentgen": True,
     "include_diagnostics": False, "paused": False},
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Exceptions


class ScheduleConflictError(ValueError):
    """A stale schedule revision must be reopened before saving."""


# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_schedules_slots():
    return [dict(slot) for slot in prod_slots] if ENV_NAME == "prod" else []


def func_schedules_overlap(left, right):
    return left["time"] == right["time"] and bool(schedule_weekdays[left["days"]] & schedule_weekdays[right["days"]])


def func_schedules_validate_slots(slots, *, check_overlaps=True, existing_slots=()):
    if not isinstance(slots, list):
        raise ValueError("schedules must be a list")
    ids, times = set(), set()
    validated = []
    flags = ("run_contentgen", "include_diagnostics", "paused")
    previous = {slot["id"]: slot for slot in existing_slots}
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("Each schedule must be an object")
        slot_id, days, at = slot.get("id"), slot.get("days"), slot.get("time")
        if not isinstance(slot_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", slot_id) or slot_id == git_job_id:
            raise ValueError("Each schedule needs a valid ID")
        if slot_id in ids:
            raise ValueError(f"Duplicate schedule ID: {slot_id}")
        if not isinstance(days, str) or days not in schedule_groups:
            raise ValueError("Select a valid day group")
        if not isinstance(at, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", at):
            raise ValueError("Enter a time in 24-hour HH:MM format")
        if (days, at) in times:
            raise ValueError(f"{at} is already on the schedule for those days")
        if any(not isinstance(slot.get(flag), bool) for flag in flags):
            raise ValueError("Schedule flags must be true or false")
        slot = {"id": slot_id, "days": days, "time": at, **{flag: slot[flag] for flag in flags}}
        if check_overlaps:
            for other in validated:
                if not func_schedules_overlap(slot, other):
                    continue
                # An existing paused conflict can be repaired one slot at a time.
                if (slot["paused"] or other["paused"]) and previous.get(slot_id) == slot and previous.get(other["id"]) == other:
                    continue
                raise ValueError(f"{at} overlaps {schedule_groups[other['days']]}. Choose a different time or days.")
        ids.add(slot_id)
        times.add((days, at))
        validated.append(slot)
    return validated


def func_schedules_pause_existing_overlaps(slots):
    effective = []
    for slot in slots:
        if not slot["paused"]:
            conflict = next((other for other in effective if not other["paused"] and func_schedules_overlap(slot, other)), None)
            if conflict is not None:
                log_message(
                    f"Conflicting schedule paused | env={ENV_NAME} | schedule_id={slot['id']} | overlaps={conflict['id']}",
                    'WARNING',
                )
                slot = {**slot, "paused": True}
        effective.append(slot)
    return effective


def func_schedules_validate_projects(projects):
    if not isinstance(projects, list):
        raise ValueError("projects must be a list")
    for project in projects:
        if (
            not isinstance(project, str) or not project.strip() or project in {".", ".."}
            or any(char in '\\/:*?"<>|' or ord(char) < 32 for char in project)
        ):
            raise ValueError("Select valid project folder names")
    return list(dict.fromkeys(projects))


def func_schedules_read_config():
    defaults = {
        "schedules": func_schedules_slots(), "projects": list(DEFAULT_SCHEDULED_PROJECTS),
        "revision": 0, "changes": [],
    }
    if not SCHEDULES_FILE.is_file():
        return defaults
    with SCHEDULES_FILE.open(encoding="utf-8-sig") as handle:
        saved = json.load(handle)
    if not isinstance(saved, dict):
        raise ValueError("schedules.json must contain an object")
    data = {**defaults, **saved}
    data["schedules"] = func_schedules_validate_slots(data["schedules"], check_overlaps=False)
    data["projects"] = func_schedules_validate_projects(data["projects"])
    if type(data["revision"]) is not int or data["revision"] < 0 or not isinstance(data["changes"], list):
        raise ValueError("schedules.json has an invalid revision or change log")
    return data


def func_schedules_get_projects():
    with schedule_lock:
        return func_schedules_read_config()["projects"]


def func_schedules_trigger(slot):
    hour, minute = map(int, slot["time"].split(":"))
    return CronTrigger(day_of_week="*" if slot["days"] == "daily" else slot["days"],
                       hour=hour, minute=minute, timezone=TIMEZONE)


def func_schedules_next_runs(slots, now=None, limit=5):
    now = now or datetime.now(TIMEZONE)
    upcoming = []
    for slot in slots:
        if slot["paused"]:
            continue
        trigger = func_schedules_trigger(slot)
        at = trigger.get_next_fire_time(None, now + timedelta(microseconds=1))
        for _ in range(limit):
            if at is None:
                break
            upcoming.append((at, slot))
            at = trigger.get_next_fire_time(at, at)
    upcoming.sort(key=lambda item: (item[0], item[1]["id"]))
    return [{**slot, "scheduled_for": at.isoformat()} for at, slot in upcoming[:limit]]


def func_schedules_describe_config(data, now=None):
    slots = sorted(data["schedules"], key=lambda slot: (list(schedule_groups).index(slot["days"]), slot["time"]))
    return {
        "env": ENV_NAME,
        "schedules": slots,
        "projects": data["projects"],
        "revision": data["revision"],
        "last_change": data["changes"][-1] if data["changes"] else None,
        "last_project_change": data.get("last_project_change"),
        "next_runs": func_schedules_next_runs(slots, now),
        "runner_enabled": CONTENTGEN_RUNNER_ENABLED,
    }


def func_schedules_describe(now=None):
    with schedule_lock:
        return func_schedules_describe_config(func_schedules_read_config(), now)


def func_schedules_register(scheduler, slot):
    from functions.functions_refresh import func_refresh_run_scheduled

    hour, minute = map(int, slot["time"].split(":"))
    scheduler.add_job(
        func_refresh_run_scheduled,
        trigger=func_schedules_trigger(slot),
        kwargs={"refresh_hour": hour, "refresh_minute": minute, "schedule": slot},
        id=slot["id"],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )
    if slot["paused"]:
        scheduler.pause_job(slot["id"])


def func_schedules_apply(scheduler, old_slots, new_slots):
    old = {slot["id"]: slot for slot in old_slots}
    new = {slot["id"]: slot for slot in new_slots}
    for slot_id in old.keys() - new.keys():
        if scheduler.get_job(slot_id) is not None:
            scheduler.remove_job(slot_id)
    for slot_id, updated in new.items():
        previous = old.get(slot_id)
        if scheduler.get_job(slot_id) is None or previous is None or any(
            previous[key] != updated[key] for key in ("days", "time", "run_contentgen", "include_diagnostics")
        ):
            func_schedules_register(scheduler, updated)
        elif previous["paused"] != updated["paused"]:
            if updated["paused"]:
                scheduler.pause_job(slot_id)
            else:
                scheduler.resume_job(slot_id)


def func_schedules_change_record(before, after, run_by):
    old = {slot["id"]: slot for slot in before["schedules"]}
    new = {slot["id"]: slot for slot in after["schedules"]}
    added = [slot for key, slot in new.items() if key not in old]
    deleted = [slot for key, slot in old.items() if key not in new]
    changed = [{"before": old[key], "after": slot} for key, slot in new.items() if key in old and slot != old[key]]
    joined = [project for project in after["projects"] if project not in before["projects"]]
    left = [project for project in before["projects"] if project not in after["projects"]]
    return {
        "revision": after["revision"],
        "at": datetime.now(TIMEZONE).isoformat(),
        "run_by": run_by,
        "schedules": {"added": added, "changed": changed, "removed": deleted},
        "projects": {"added": joined, "removed": left, "order": after["projects"]},
    }


def func_schedules_commit(scheduler, before, after, run_by):
    # ----------------------------------------------------------------
    # 1. Prepare The Change Record
    if after["schedules"] == before["schedules"] and after["projects"] == before["projects"]:
        return before
    after["revision"] += 1
    record = func_schedules_change_record(before, after, run_by)
    after["changes"] = [*before["changes"], record]
    revision = after["revision"]
    log_message(f"Schedule change started | env={ENV_NAME} | revision={revision} | run_by={run_by}", 'INFO')
    update_jobs = scheduler is not None and after["schedules"] != before["schedules"]

    # ----------------------------------------------------------------
    # 2. Apply And Persist
    running = update_jobs and scheduler.state == STATE_RUNNING
    if running:
        scheduler.pause()
    try:
        if update_jobs:
            func_schedules_apply(scheduler, before["schedules"], after["schedules"])
        func_file_io_write_json(SCHEDULES_FILE, after)
    except Exception as exc:
        if update_jobs:
            try:
                func_schedules_apply(scheduler, after["schedules"], before["schedules"])
            except Exception as rollback_error:
                log_message(f"Schedule restore failed | env={ENV_NAME} | revision={revision} | {rollback_error}", 'ERROR')
        log_message(f"Schedule change failed | env={ENV_NAME} | revision={revision} | run_by={run_by} | {exc}", 'ERROR')
        raise
    finally:
        if running:
            scheduler.resume()

    # ----------------------------------------------------------------
    # 3. Return
    log_message(f"Schedule change finished | env={ENV_NAME} | revision={revision} | run_by={run_by}", 'INFO')
    return after


def func_schedules_update(scheduler, payload):
    if not isinstance(payload, dict) or not ({"schedules", "projects"} & payload.keys()):
        raise ValueError("Provide schedules or projects to update")
    run_by = payload.get("run_by")
    if not isinstance(run_by, str) or not 1 <= len(run_by.strip()) <= RUN_BY_LIMIT:
        raise ValueError("Enter the name to record for this schedule change")
    with schedule_lock:
        before = func_schedules_read_config()
        if "revision" in payload and (
            type(payload["revision"]) is not int or payload["revision"] != before["revision"]
        ):
            raise ScheduleConflictError("The schedule changed. Reopen the editor and try again.")
        after = dict(before)
        if "schedules" in payload:
            after["schedules"] = func_schedules_validate_slots(payload["schedules"], existing_slots=before["schedules"])
        if "projects" in payload:
            after["projects"] = func_schedules_validate_projects(payload["projects"])
        saved = func_schedules_commit(scheduler, before, after, run_by.strip())
        return func_schedules_describe_config(saved)


def func_schedules_add_project(project, run_by):
    if ENV_NAME != "prod":
        raise ValueError("Select prod to add projects to its schedule")
    if not isinstance(run_by, str) or not 1 <= len(run_by.strip()) <= RUN_BY_LIMIT:
        raise ValueError("Enter the name to record for this schedule change")
    func_schedules_validate_projects([project])
    with schedule_lock:
        before = func_schedules_read_config()
        if project in before["projects"]:
            return before["projects"]
        after = {**before, "projects": [*before["projects"], project]}
        after["last_project_change"] = {"project": project, "run_by": run_by.strip(), "at": datetime.now(TIMEZONE).isoformat()}
        return func_schedules_commit(None, before, after, run_by.strip())["projects"]


def func_schedules_new_slot(days):
    return {
        "id": f"refresh-{uuid.uuid4().hex}", "days": days, "time": "16:00",
        "run_contentgen": True, "include_diagnostics": False, "paused": False,
    }


def func_schedules_edit_slot(env, schedules, editor, run_by, *, days=None, at=None, flags=None, remove=False):
    key = editor["slot"]["id"]
    updated = [slot for slot in schedules if slot["id"] != key]
    if not remove:
        options = set(flags or [])
        updated.append({
            "id": key, "days": days, "time": (at or "").strip(),
            "run_contentgen": "run_contentgen" in options,
            "include_diagnostics": "include_diagnostics" in options,
            "paused": "paused" in options,
        })
    return func_api_client_json(env, "/api/schedules", method="PUT", payload={
        "schedules": updated, "revision": editor["revision"], "run_by": run_by,
    })


def func_schedules_edit_projects(env, selected, revision, run_by):
    return func_api_client_json(env, "/api/schedules", method="PUT", payload={
        "projects": selected or [], "revision": revision, "run_by": run_by,
    })


def func_schedules_start(scheduler):
    # ----------------------------------------------------------------
    # 1. Load Schedule And Register Jobs
    with schedule_lock:
        data = func_schedules_read_config()
        slots = func_schedules_pause_existing_overlaps(data["schedules"])
        if slots != data["schedules"]:
            func_schedules_commit(None, data, {**data, "schedules": slots}, "Refresh Desk")
        else:
            func_file_io_write_json(SCHEDULES_FILE, data)
        scheduler.add_job(
            func_git_pull,
            trigger="interval",
            hours=1,
            id=git_job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )
        func_schedules_apply(scheduler, [], slots)
        scheduler.start()

    # ----------------------------------------------------------------
    # 2. Log Configuration
    print_banner("CCEC DATA PIPELINE SCHEDULER - STARTED")
    print_detail("Timezone", TIMEZONE.key)
    for days, label in (("mon", "Monday"), ("tue-sun", "Tuesday-Sunday"), ("daily", "Every day"), ("mon-fri", "Monday-Friday")):
        times = sorted(slot["time"] for slot in slots if slot["days"] == days and not slot["paused"])
        if times:
            print_detail(label, " | ".join(times))
    if ENV_NAME == "dev" and not slots:
        print_detail("Schedule", "Dev has no schedule")
    print_detail("Customer SQL", CUSTOMER_SQL_FOLDER)
    print_detail("Colleague SQL", COLLEAGUE_SQL_FOLDER)
    print_detail("Output", OUTPUT_FOLDER)
    print_detail("ContentGen API", CONTENTGEN_API_URL)
    print_detail("Git repository", git_repo_path)
    print_detail("Git pull", "Every 1 hour (--ff-only)")
    print_detail("Query attempts", MAX_QUERY_ATTEMPTS)
    for source_info in func_sql_get_catalog():
        print_detail(
            f"{source_info['label']} queries",
            f"{source_info['count']} | {source_info['folder']}"
        )
    print_detail(
        "Worker allocation",
        " | ".join(
            f"{QUERY_SOURCES[key]['label']}={SOURCE_MAX_WORKERS.get(key, 1)}"
            for key in QUERY_SOURCES
        )
    )
    print("#" * CONSOLE_WIDTH + "\n")
    return scheduler
