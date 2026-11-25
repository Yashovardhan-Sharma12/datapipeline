# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from datetime import datetime, timedelta

from config import TIMEZONE
from functions.functions_ui import func_ui_timestamp

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_today_run_events(row, now, kind):
    start = func_ui_timestamp(row.get("started_at"))
    if start is None or start.date() != now.date():
        return None
    ended = func_ui_timestamp(row.get("completed_at")) or now
    if kind in {"refresh", "manual"}:
        steps = [{"step": "query", "status": row["status"], "started_at": row["started_at"],
                  "completed_at": row.get("completed_at")}]
        identity = row["job_id"]
    else:
        steps = row["steps"]
        identity = row["run_id"]

    return {"kind": kind, "id": identity, "status": row["status"], "start": start,
            "end": max(ended, start + timedelta(minutes=2)), "steps": steps, "record": row}


def func_today_timeline(state):
    # ----------------------------------------------------------------
    # 1. Build Lanes For The Selected Environment
    now = func_ui_timestamp(state.get("now")) or datetime.now(TIMEZONE)
    lanes = {None: []}
    for project in state.get("projects", []):
        if project["runnable"]:
            lanes[project["project"]] = []
    for row in state.get("active", []) + state.get("history", []):
        event = func_today_run_events(row, now, "refresh")
        if event:
            lanes[None].append(event)
    for row in state.get("manual", []):
        event = func_today_run_events(row, now, "manual")
        if event:
            lanes[None].append(event)
    for row in state.get("runs", []):
        event = func_today_run_events(row, now, "contentgen")
        if event:
            lanes.setdefault(row["project"], []).append(event)

    # ----------------------------------------------------------------
    # 2. Assign Positions To Overlapping Runs
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_refresh = next((
        entry for entry in state.get("schedule", {}).get("next_runs", [])
        if func_ui_timestamp(entry["scheduled_for"]).date() == now.date()
    ), None)
    earliest = midnight + timedelta(hours=12)
    latest = midnight + timedelta(hours=20)
    for lane in lanes.values():
        lane.sort(key=lambda event: event["start"])
        levels = []
        for event in lane:
            start, end = event["start"], event["end"]
            earliest, latest = min(start, earliest), max(end, latest)
            level = next((index for index, free in enumerate(levels) if free <= start), len(levels))
            if level == len(levels):
                levels.append(end)
            else:
                levels[level] = end
            event["level"] = level

    start_hour = earliest.hour
    end_hour = 24 if latest.date() != now.date() else min(24, latest.hour + bool(latest.minute or latest.second))
    if next_refresh:
        next_time = func_ui_timestamp(next_refresh["scheduled_for"])
        start_hour = min(start_hour, next_time.hour)
        end_hour = max(end_hour, min(next_time.hour + 1, 24))
    timeline_start = midnight + timedelta(hours=start_hour)
    timeline_end = midnight + timedelta(hours=end_hour)

    # ----------------------------------------------------------------
    # 3. Return
    return lanes, timeline_start, timeline_end, now, next_refresh


def func_today_position(value, start, end):
    return 100 * min(1, max(0, (value - start).total_seconds() / (end - start).total_seconds()))
