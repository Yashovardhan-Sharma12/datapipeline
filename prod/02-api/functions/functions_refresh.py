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
from datetime import datetime, timedelta, timezone
from itertools import islice

from config import (
    COLLEAGUE_SQL_FOLDER,
    CONSOLE_WIDTH,
    CONTENTGEN_RUNNER_ENABLED,
    CUSTOMER_SQL_FOLDER,
    ENV_NAME,
    MAX_QUERY_ATTEMPTS,
    OUTPUT_FOLDER,
    REFRESH_COMPLETE_FILE,
    REFRESH_HISTORY_FILE,
    REFRESH_HISTORY_LIMIT,
    REFRESH_HISTORY_PAGE_SIZE,
    REFRESH_HISTORY_REASON_LIMIT,
    REFRESH_RUNS_FOLDER,
    REFRESH_STATUS_FILE,
    TIMEZONE,
)
from functions.functions_api_client import ApiClientError, func_api_client_submit_runs
from functions.functions_console import print_banner, print_detail, print_status
from functions.functions_file_io import func_file_io_write_json as func_refresh_write_json
from functions.functions_filenames import func_filenames_is_direct
from functions.functions_sql_execution import (
    QUERY_SOURCES,
    func_sql_execute_job,
    func_sql_get_tasks,
    func_sql_retain_finished_job,
    func_sql_validate_output_collisions,
    jobs,
    jobs_lock,
)
from functions.functions_validation import (
    func_validation_clear_missing_report,
    func_validation_get_current_week,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
refresh_file_lock = threading.RLock()
summary_query_fields = (
    "total_queries", "finalised_queries", "completed_queries",
    "retrying_queries", "running_queries", "pending_queries", "progress_percent", "empty_queries",
)
summary_quality_fields = (
    "latest_year_week", "total_queries", "latest_week_present", "missing_latest_week",
    "no_year_week_column", "validation_error", "failed_queries", "empty_queries",
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_refresh_read_history_file():
    if not REFRESH_HISTORY_FILE.is_file():
        return []
    try:
        with REFRESH_HISTORY_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    except Exception as exc:
        print_status("WARNING", f"Unable to read refresh history: {exc}")
        return []


def func_refresh_short_reason(reason):
    if not reason:
        return None
    reason = " ".join(str(reason).split())
    if len(reason) > REFRESH_HISTORY_REASON_LIMIT:
        return reason[:REFRESH_HISTORY_REASON_LIMIT - 1] + "…"
    return reason


def func_refresh_build_summary(snapshot):
    """Keep progress, counts and short failure reasons for the history index."""
    # ----------------------------------------------------------------
    # 1. Summarise Failures
    candidates = snapshot.get("failed_queries")
    if not isinstance(candidates, list):
        candidates = [row for row in (snapshot.get("results") or []) if row.get("status") == "failed"]
    failed_queries = []
    for row in candidates:
        detail = row.get("error_detail") or {}
        reason = row.get("reason") or detail.get("message") or row.get("last_error") or row.get("error")
        failed_queries.append({
            "filename": row.get("filename", "unknown"),
            "source_label": row.get("source_label", "Unknown"),
            "status": "failed",
            "reason": func_refresh_short_reason(reason or "Query failed"),
            "kind": row.get("kind") or detail.get("kind"),
        })

    # ----------------------------------------------------------------
    # 2. Return
    quality = snapshot.get("quality")
    failed_count = snapshot.get("failed_query_count", snapshot.get("failed_queries"))
    return {
        **{key: snapshot.get(key) for key in ("job_id", "scheduled_for", "started_at", "completed_at", "status")},
        **{key: snapshot.get(key, 0) for key in summary_query_fields},
        "quality": {key: quality.get(key) for key in summary_quality_fields} if quality is not None else None,
        "error": func_refresh_short_reason(snapshot.get("error")),
        "failed_query_count": failed_count if isinstance(failed_count, int) else len(failed_queries),
        "failed_queries": failed_queries,
        # The legacy ContentGen scheduler looks for failed names in results.
        "results": failed_queries,
        "contentgen": snapshot.get("contentgen"),
    }


def func_refresh_parse_timestamp(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TIMEZONE)


def func_refresh_history_timestamp(record):
    for key in ("started_at", "scheduled_for", "completed_at"):
        value = record.get(key)
        if isinstance(value, str):
            try:
                return func_refresh_parse_timestamp(value)
            except ValueError:
                continue
    return datetime.min.replace(tzinfo=timezone.utc)


def func_refresh_load_history(limit=REFRESH_HISTORY_PAGE_SIZE, before=None):
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        raise ValueError("limit must be an integer") from None
    if not 1 <= limit <= REFRESH_HISTORY_LIMIT:
        raise ValueError(f"limit must be between 1 and {REFRESH_HISTORY_LIMIT}")

    cursor = None
    if before is not None:
        if "T" not in before and " " not in before:
            raise ValueError("before must be an ISO datetime")
        try:
            cursor = func_refresh_parse_timestamp(before)
        except ValueError:
            raise ValueError("before must be an ISO datetime") from None

    with refresh_file_lock:
        records = func_refresh_read_history_file()
    records.sort(key=func_refresh_history_timestamp, reverse=True)
    if cursor is not None:
        records = [record for record in records if func_refresh_history_timestamp(record) < cursor]
    page = records[:limit]
    next_before = func_refresh_history_timestamp(page[-1]).isoformat() if len(records) > limit else None
    return [func_refresh_build_summary(record) for record in page], next_before


def func_refresh_get_active():
    with jobs_lock:
        active = [
            (job_id, job) for job_id, job in jobs.items()
            if job.get("scheduled_refresh") and job.get("status") == "running"
        ]
    snapshots = [func_refresh_build_snapshot(job_id, job) for job_id, job in active]
    snapshots.sort(key=func_refresh_history_timestamp, reverse=True)
    return [func_refresh_build_summary(snapshot) for snapshot in snapshots if snapshot["status"] == "running"]


def func_refresh_get_manual_jobs():
    with jobs_lock:
        manual = list(islice(
            ((job_id, job) for job_id, job in reversed(jobs.items()) if not job.get("scheduled_refresh") and job.get("started_at")),
            REFRESH_HISTORY_PAGE_SIZE,
        ))
    summaries = []
    for job_id, job in manual:
        snapshot = func_refresh_build_snapshot(job_id, job)
        if snapshot["status"] == "completed":
            snapshot["status"] = "completed_with_failures" if snapshot["failed_queries"] else "success"
        summaries.append(func_refresh_build_summary(snapshot))
    return summaries


def func_refresh_detail_path(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id):
        return None
    filename = f"{job_id}.json"
    return REFRESH_RUNS_FOLDER / filename if func_filenames_is_direct(filename, ".json") else None


def func_refresh_get_detail(job_id):
    path = func_refresh_detail_path(job_id)
    if path is None:
        return None
    try:
        with refresh_file_lock:
            if not path.is_file() or path.resolve().parent != REFRESH_RUNS_FOLDER.resolve():
                return None
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError) as exc:
        log_message(f"Unable to read refresh detail | refresh_job_id={job_id} | {exc}", 'WARNING')
        return None


def func_refresh_remove_detail(path):
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log_message(f"Unable to remove expired refresh detail | refresh_job_id={path.stem} | {exc}", 'WARNING')


def func_refresh_save_history(records, previous):
    records.sort(key=func_refresh_history_timestamp, reverse=True)
    retained = records[:REFRESH_HISTORY_LIMIT]
    if retained != previous:
        func_refresh_write_json(REFRESH_HISTORY_FILE, retained)

    retained_ids = {record.get("job_id") for record in retained}
    for job_id in {record.get("job_id") for record in records[REFRESH_HISTORY_LIMIT:]} - retained_ids:
        path = func_refresh_detail_path(job_id)
        if path is not None:
            func_refresh_remove_detail(path)
    return retained


def func_refresh_prune_orphaned_details(retained):
    """Clean up details that aged out before history retention deleted them."""
    if len(retained) < REFRESH_HISTORY_LIMIT or not REFRESH_RUNS_FOLDER.is_dir():
        return
    retained_ids = {record.get("job_id") for record in retained}
    oldest = func_refresh_history_timestamp(retained[-1])
    if oldest == datetime.min.replace(tzinfo=timezone.utc):
        return
    for path in REFRESH_RUNS_FOLDER.iterdir():
        try:
            if (
                path.stem not in retained_ids and path == func_refresh_detail_path(path.stem)
                and not path.is_symlink() and path.is_file() and path.stat().st_mtime < oldest.timestamp()
            ):
                func_refresh_remove_detail(path)
        except OSError as exc:
            log_message(f"Unable to inspect expired refresh detail | refresh_job_id={path.stem} | {exc}", 'WARNING')


def func_refresh_migrate_history():
    """Extract detail from the old history format before replacing its index."""
    with refresh_file_lock:
        records = func_refresh_read_history_file()
        summaries = []
        for record in records:
            detail_path = func_refresh_detail_path(record.get("job_id"))
            if detail_path is None:
                continue
            if not isinstance(record.get("failed_queries"), list) and not detail_path.exists():
                func_refresh_write_json(detail_path, record)
            summaries.append(func_refresh_build_summary(record))
        retained = func_refresh_save_history(summaries, records)
        try:
            func_refresh_prune_orphaned_details(retained)
        except OSError as exc:
            log_message(f"Unable to inspect refresh detail storage | {exc}", 'WARNING')


def func_refresh_build_quality_summary(results, latest_week):
    """Summarise latest Tesco week coverage across query results."""
    # ----------------------------------------------------------------
    # 1. Initialize
    summary = {
        "latest_year_week": latest_week,
        "total_queries": len(results),
        "latest_week_present": 0,
        "missing_latest_week": 0,
        "no_year_week_column": 0,
        "validation_error": 0,
        "failed_queries": 0,
        "empty_queries": 0,
        "missing_latest_week_files": [],
        "no_year_week_column_files": [],
        "validation_error_files": [],
        "failed_query_files": [],
    }

    # ----------------------------------------------------------------
    # 2. Count Results
    for result in results:
        label = f"[{result.get('source_label', 'Unknown')}] {result.get('filename', 'unknown')}"

        if result.get("status") == "failed":
            summary["failed_queries"] += 1
            summary["failed_query_files"].append(label)
            continue

        if result.get("status") == "empty":
            summary["empty_queries"] += 1
            continue

        validation = result.get("validation") or {}
        validation_status = validation.get("status")

        if validation_status == "ok":
            summary["latest_week_present"] += 1
        elif validation_status == "missing_data":
            summary["missing_latest_week"] += 1
            summary["missing_latest_week_files"].append(label)
        elif validation_status == "validation_skipped":
            summary["no_year_week_column"] += 1
            summary["no_year_week_column_files"].append(label)
        else:
            summary["validation_error"] += 1
            summary["validation_error_files"].append(label)

    # ----------------------------------------------------------------
    # 3. Return
    return summary


def func_refresh_build_snapshot(job_id, job=None):
    """Build a serialisable progress snapshot for a scheduled refresh."""
    with jobs_lock:
        job = dict(jobs[job_id] if job is None else job)
        results = [dict(item) for item in (job.get("results") or [])]

    total = len(results)
    finalised = sum(item.get("status") in {"complete", "empty", "failed"} for item in results)
    completed = sum(item.get("status") == "complete" for item in results)
    empty = sum(item.get("status") == "empty" for item in results)
    failed = sum(item.get("status") == "failed" for item in results)
    retrying = sum(item.get("status") == "retrying" for item in results)
    running = sum(item.get("status") == "running" for item in results)
    pending = sum(item.get("status") == "pending" for item in results)

    snapshot = {
        "job_id": job_id,
        "scheduled_for": job.get("scheduled_for"),
        "started_at": job.get("started_at"),
        "updated_at": datetime.now(TIMEZONE).isoformat(),
        "completed_at": job.get("completed_at"),
        "status": job.get("status", "running"),
        "error": job.get("error"),
        "total_queries": total,
        "finalised_queries": finalised,
        "completed_queries": completed,
        "empty_queries": empty,
        "failed_queries": failed,
        "retrying_queries": retrying,
        "running_queries": running,
        "pending_queries": pending,
        "progress_percent": round((finalised / total) * 100, 1) if total else 0,
        "quality": job.get("quality"),
        "contentgen": job.get("contentgen"),
        "results": results,
    }
    return snapshot


def func_refresh_persist_snapshot(job_id):
    """Publish live progress without copying query payloads into history."""
    with refresh_file_lock:
        snapshot = func_refresh_build_snapshot(job_id)
        progress = {
            **snapshot,
            "results": [
                {
                    key: row[key] for key in (
                        "filename", "source", "source_label", "status", "attempts", "max_attempts", "last_error",
                    ) if key in row
                }
                for row in snapshot["results"]
            ],
        }
        func_refresh_write_json(REFRESH_STATUS_FILE, progress)


def func_refresh_finalize(job_id):
    """Write immutable run detail, then publish the history and legacy marker."""
    with refresh_file_lock:
        detail_path = func_refresh_detail_path(job_id)
        if detail_path is None:
            raise ValueError("Invalid refresh job ID")
        if detail_path.is_file():
            snapshot = func_refresh_get_detail(job_id)
            if snapshot is None:
                raise OSError(f"Could not reload refresh detail for {job_id}")
        else:
            snapshot = func_refresh_build_snapshot(job_id)
            if snapshot["status"] == "running":
                raise ValueError("A running refresh cannot be finalised")
            func_refresh_write_json(detail_path, snapshot)

        summary = func_refresh_build_summary(snapshot)
        previous = func_refresh_read_history_file()
        history = [summary] + [item for item in previous if item.get("job_id") != job_id]
        func_refresh_save_history(history, previous)
        # Keep the old scheduler's complete/partial/failed handshake and failed result list.
        func_refresh_write_json(REFRESH_STATUS_FILE, {
            **summary,
            "failed_queries": summary["failed_query_count"],
            "updated_at": snapshot["updated_at"],
        })


def func_refresh_get_scheduled_time(refresh_hour, refresh_minute):
    now = datetime.now(TIMEZONE)
    scheduled_for = now.replace(
        hour=refresh_hour,
        minute=refresh_minute,
        second=0,
        microsecond=0,
    )
    if scheduled_for > now:
        scheduled_for -= timedelta(days=1)
    return scheduled_for


def func_refresh_prepare_contentgen(schedule):
    from functions.functions_schedules import func_schedules_get_projects

    option = dict(schedule or {})
    option["projects"] = []
    if CONTENTGEN_RUNNER_ENABLED and option.get("run_contentgen", True):
        try:
            option["projects"] = func_schedules_get_projects()
        except (OSError, ValueError) as exc:
            option["projects_error"] = str(exc)
    return option


def func_refresh_handoff(job_id, schedule, completed_at, status):
    if not CONTENTGEN_RUNNER_ENABLED:
        return {"status": "not_started", "reason": "ContentGen runner is disabled for this environment"}
    if status not in {"success", "completed_with_failures"}:
        return {"status": "not_started", "reason": "The refresh did not complete"}

    # ----------------------------------------------------------------
    # 1. Build Scheduled Request
    try:
        if schedule.get("projects_error"):
            raise ValueError(schedule["projects_error"])
        projects = schedule["projects"]
        steps = ["content_gen", "upload"]
        if schedule.get("include_diagnostics"):
            steps.insert(0, "diagnostics")
        log_message(f"Scheduled ContentGen hand-off started | refresh_job_id={job_id} | env={ENV_NAME}", 'INFO')
        response = func_api_client_submit_runs({
            "items": [{"env": ENV_NAME, "project": project, "steps": steps} for project in projects],
            "env": ENV_NAME,
            "trigger": "scheduled",
            "refresh_job_id": job_id,
            "refresh_completed_at": completed_at,
            "run_by": "Scheduled refresh",
        })

        # ----------------------------------------------------------------
        # 2. Record Runner Receipt
        runs = response.get("runs", [])
        released = response.get("released", 0)
        rejected = response.get("rejected", [])
        log_message(f"Scheduled ContentGen hand-off finished | refresh_job_id={job_id} | runs={len(runs)} | released={released}", 'INFO')
        result = {"status": "queued" if runs or released else "not_scheduled",
                  "runs": runs, "released": released, "rejected": rejected}
        if not runs and not released and rejected:
            result.update(status="not_started", reason="No scheduled project could run")
        return result
    except (ApiClientError, ValueError, OSError) as exc:
        reason = str(exc)
        log_message(f"Scheduled ContentGen not started | refresh_job_id={job_id} | env={ENV_NAME} | {reason}", 'WARNING')
        return {"status": "not_started", "reason": reason}


def func_refresh_run_scheduled(refresh_hour, refresh_minute, schedule=None):
    """
    Run all configured customer and colleague SQL files.

    Each failed query is attempted up to MAX_QUERY_ATTEMPTS times. A refresh
    that still has query failures after the final attempt is marked
    completed_with_failures, but is released to ContentGen using the
    _refresh_status.json handshake.
    """
    # ----------------------------------------------------------------
    # 1. Initialize
    refresh_started_at = datetime.now(TIMEZONE)
    scheduled_for = func_refresh_get_scheduled_time(refresh_hour, refresh_minute)
    schedule = func_refresh_prepare_contentgen(schedule)

    print_banner(
        "CCEC DATA REFRESH - START",
        refresh_started_at.strftime("%A, %d %B %Y | %H:%M:%S IST")
    )
    print_detail("Scheduled for", scheduled_for.isoformat())
    print_detail("Customer SQL", CUSTOMER_SQL_FOLDER)
    print_detail("Colleague SQL", COLLEAGUE_SQL_FOLDER)
    print_detail("Output folder", OUTPUT_FOLDER)
    print_detail("Max attempts", MAX_QUERY_ATTEMPTS)

    sql_tasks = func_sql_get_tasks()

    if not sql_tasks:
        func_validation_clear_missing_report()
        print_status("SKIPPED", "No SQL files found in the configured query folders.")
        return

    func_sql_validate_output_collisions(sql_tasks)

    job_id = str(uuid.uuid4())
    customer_count = sum(task["source"] == "customer" for task in sql_tasks)
    colleague_count = sum(task["source"] == "colleague" for task in sql_tasks)

    print_detail("Queries found", len(sql_tasks))
    print_detail("Customer queries", customer_count)
    print_detail("Colleague queries", colleague_count)
    print_detail("Job ID", job_id)
    print("-" * CONSOLE_WIDTH)

    for index, task in enumerate(sql_tasks, start=1):
        print(
            f"  {index:02d}. [{task['source_label']}] "
            f"{os.path.basename(task['path'])}"
        )

    print("-" * CONSOLE_WIDTH)

    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "results": None,
            "scheduled_refresh": True,
            "scheduled_for": scheduled_for.isoformat(),
            "started_at": refresh_started_at.isoformat(),
            "completed_at": None,
            "quality": None,
            "error": None,
        }

    log_message(f"Scheduled refresh started | refresh_job_id={job_id}", 'INFO')
    latest_week = None

    # ----------------------------------------------------------------
    # 2. Run Refresh
    try:
        func_validation_clear_missing_report()
        func_refresh_persist_snapshot(job_id)
        latest_week = func_validation_get_current_week(QUERY_SOURCES["customer"]["conn"])
        print_status("RUNNING", f"Executing {len(sql_tasks)} SQL file(s)...")
        func_sql_execute_job(
            job_id, sql_tasks, on_progress=func_refresh_persist_snapshot, latest_week=latest_week,
        )

        # ----------------------------------------------------------------
        # 3. Finalize Refresh
        with jobs_lock:
            job_results = [dict(item) for item in (jobs[job_id].get("results") or [])]

        completed_results = [
            result for result in job_results
            if result.get("status") == "complete"
        ]
        failed_results = [
            result for result in job_results
            if result.get("status") == "failed"
        ]

        quality = func_refresh_build_quality_summary(job_results, latest_week)
        completed_at = datetime.now(TIMEZONE)
        final_status = "success" if not failed_results else "completed_with_failures"

        with jobs_lock:
            jobs[job_id]["status"] = final_status
            jobs[job_id]["completed_at"] = completed_at.isoformat()
            jobs[job_id]["quality"] = quality
            jobs[job_id]["error"] = None

        print("-" * CONSOLE_WIDTH)
        print_detail("Completed", len(completed_results))
        print_detail("Failed after retry", len(failed_results))
        print_detail("Latest Tesco week", quality.get("latest_year_week") or "Unknown")
        print_detail("Latest week present", quality["latest_week_present"])
        print_detail("Missing latest week", quality["missing_latest_week"])
        print_detail("No year_week column", quality["no_year_week_column"])
        print_detail("Validation errors", quality["validation_error"])

        if quality["missing_latest_week_files"]:
            print_status(
                "MISSING",
                "Latest week absent: " + ", ".join(quality["missing_latest_week_files"])
            )

        if failed_results:
            failed_files = [
                f"[{result.get('source_label', 'Unknown')}] "
                f"{result.get('filename', 'unknown')}"
                for result in failed_results
            ]
            attempts = max(result["attempts"] for result in failed_results)
            print_status(
                "PARTIAL",
                f"{len(failed_results)} query(s) failed after "
                f"{attempts} attempts: {', '.join(failed_files)}"
            )
            print_status(
                "CONTINUE",
                "Datapipeline finalised with failures; ContentGen may proceed "
                "using the latest available output files."
            )
        else:
            # Keep the historical success-only marker for the UI / backwards compatibility.
            success_marker = {
                "job_id": job_id,
                "status": "success",
                "scheduled_for": scheduled_for.isoformat(),
                "completed_at": completed_at.isoformat(),
                "files_processed": len(sql_tasks),
                "customer_files_processed": customer_count,
                "colleague_files_processed": colleague_count,
                "quality": quality,
            }
            func_refresh_write_json(REFRESH_COMPLETE_FILE, success_marker)
            print_status("SUCCESS", "All customer and colleague SQL files completed successfully.")

        refresh_duration = completed_at - refresh_started_at
        print_detail("Refresh status", final_status)
        print_detail("Refresh status marker", REFRESH_STATUS_FILE)
        print_detail("Duration", str(refresh_duration).split(".")[0])

        print_banner(
            "CCEC DATA REFRESH - COMPLETE",
            completed_at.strftime("%A, %d %B %Y | %H:%M:%S IST")
        )
        log_message(
            f"Scheduled refresh finished | refresh_job_id={job_id} | status={final_status}",
            'INFO',
        )

    except Exception as exc:
        failed_at = datetime.now(TIMEZONE)
        print_status("FAILED", str(exc))

        with jobs_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["completed_at"] = failed_at.isoformat()
            jobs[job_id]["error"] = str(exc)
            current_results = jobs[job_id].get("results") or []
            if current_results:
                jobs[job_id]["quality"] = func_refresh_build_quality_summary(current_results, latest_week)

        print_banner(
            "CCEC DATA REFRESH - FAILED",
            failed_at.strftime("%A, %d %B %Y | %H:%M:%S IST")
        )
        log_message(f"Scheduled refresh failed | refresh_job_id={job_id} | {exc}", 'ERROR')

    with jobs_lock:
        status = jobs[job_id]["status"]
        completed_at = jobs[job_id]["completed_at"]
    contentgen = func_refresh_handoff(job_id, schedule, completed_at, status)
    with jobs_lock:
        jobs[job_id]["contentgen"] = contentgen

    try:
        func_refresh_finalize(job_id)
    except OSError as exc:
        log_message(f"Unable to persist refresh final state | refresh_job_id={job_id} | {exc}", 'ERROR')
        raise
    finally:
        func_sql_retain_finished_job(job_id)


def func_refresh_last_success_text():
    last_refresh = "No successful scheduled refresh recorded"
    if REFRESH_COMPLETE_FILE.is_file():
        try:
            with REFRESH_COMPLETE_FILE.open("r", encoding="utf-8") as marker_file:
                marker = json.load(marker_file)

            completed_at = datetime.fromisoformat(marker["completed_at"])
            last_refresh = completed_at.astimezone(
                TIMEZONE
            ).strftime("%d %b %Y, %H:%M:%S IST")
        except Exception:
            last_refresh = "Refresh marker available"

    return last_refresh
