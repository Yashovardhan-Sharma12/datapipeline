# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import (
    MAX_QUERY_ATTEMPTS,
    ODBC_CONNECTION_ERROR_TOKENS,
    OUTPUT_FOLDER,
    QUERY_RETRY_DELAYS_SECONDS,
    RUN_BY_LIMIT,
    SOURCE_MAX_WORKERS,
    SQL_JOB_RETENTION_LIMIT,
    SQL_SOURCE_CONFIG,
    TIMEZONE,
)
from functions.functions_console import print_status
from functions.functions_filenames import func_filenames_is_direct
from functions.functions_output_files import (
    func_output_files_get_csv,
    func_output_files_get_metadata,
    func_output_files_write_csv,
)
from functions.functions_validation import (
    func_validation_build_comparison,
    func_validation_check_actual_week,
    func_validation_get_market,
    func_validation_get_current_week,
)
from utils import mssql

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
QUERY_SOURCES = {
    key: {
        "label": source["label"],
        "folder": source["folder"],
        "conn": mssql.Connector(mssql.Config(
            server=source["server"],
            db=source["database"],
            behavior="fail",
        )),
    }
    for key, source in SQL_SOURCE_CONFIG.items()
}

jobs = {}
jobs_lock = threading.Lock()
finished_jobs = {}
week_unset = object()

# ----------------------------------------------------------------------------------------------------------------------
#%% Exceptions


class QueryNotFoundError(Exception):
    """A manual query request matched no executable SQL file."""

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_sql_initialize_output():
    """Prepare the output directory and validate the configured SQL folders."""
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    for source_config in QUERY_SOURCES.values():
        if not source_config["folder"].is_dir():
            raise FileNotFoundError(
                f"{source_config['label']} SQL source folder not found: "
                f"{source_config['folder']}"
            )


def func_sql_discover_paths(source_key):
    """Return SQL files directly from the configured source's 01-active folder.

    Customer and Colleague now use the same predictable directory convention:
      01-queries/<source>/02-queries/01-active/

    Discovery is intentionally non-recursive so only explicitly active SQL files
    are executable and dev/prod remain fully isolated by ENV_FOLDER.
    """
    source = QUERY_SOURCES.get(source_key)
    if not source:
        raise ValueError(f"Unknown query source: {source_key}")

    configured_folder = source["folder"]
    if not configured_folder.is_dir():
        return []

    return sorted(
        path for path in configured_folder.iterdir()
        if path.is_file() and path.suffix.lower() == ".sql"
    )


def func_sql_get_tasks(source_key=None, filename=None):
    """Return executable SQL tasks from one source or all configured sources."""
    # ----------------------------------------------------------------
    # 1. Initialize
    source_keys = [source_key] if source_key else list(QUERY_SOURCES.keys())
    tasks = []

    # ----------------------------------------------------------------
    # 2. Find Queries
    for key in source_keys:
        source = QUERY_SOURCES.get(key)
        if not source:
            raise ValueError(f"Unknown query source: {key}")

        discovered_paths = func_sql_discover_paths(key)

        if filename:
            if not func_filenames_is_direct(filename, ".sql"):
                raise ValueError("Only .sql filenames are allowed")
            safe_filename = filename

            matches = [path for path in discovered_paths if path.name == safe_filename]

            if len(matches) > 1:
                raise RuntimeError(
                    f"Multiple {source['label']} SQL files named {safe_filename} were found. "
                    "Please keep query filenames unique within a source."
                )

            for sql_path in matches:
                tasks.append({
                    "source": key,
                    "source_label": source["label"],
                    "path": str(sql_path),
                })
        else:
            for sql_path in discovered_paths:
                tasks.append({
                    "source": key,
                    "source_label": source["label"],
                    "path": str(sql_path),
                })

    # ----------------------------------------------------------------
    # 3. Return
    return tasks


def func_sql_get_catalog():
    """Return the live Customer/Colleague query catalogue used by the frontend."""
    catalog = []

    for source_key, source in QUERY_SOURCES.items():
        tasks = func_sql_get_tasks(source_key=source_key)
        filenames = sorted(os.path.basename(task["path"]) for task in tasks)
        catalog.append({
            "key": source_key,
            "label": source["label"],
            "folder": str(source["folder"]),
            "search_root": str(source["folder"]),
            "count": len(filenames),
            "files": filenames,
        })

    return catalog


def func_sql_validate_output_collisions(sql_tasks):
    """
    Protect the shared 03-output folder from silent overwrites when customer
    and colleague queries have the same filename.

    Validation queries do not create CSV files, so they are excluded.
    """
    output_names = {}

    for task in sql_tasks:
        filename = os.path.basename(task["path"])
        if func_validation_get_market(filename):
            continue

        output_name = os.path.splitext(filename)[0].lower() + ".csv"
        output_names.setdefault(output_name, []).append(task["source_label"])

    collisions = {
        name: sources
        for name, sources in output_names.items()
        if len(sources) > 1
    }

    if collisions:
        details = "; ".join(
            f"{name} ({', '.join(sources)})"
            for name, sources in collisions.items()
        )
        raise RuntimeError(
            "Duplicate output filenames detected across query sources. "
            f"Rename the SQL files to avoid overwriting: {details}"
        )


def func_sql_get_legacy_query_options():
    # Surface configured customer and colleague queries in one interface.
    sql_tasks = func_sql_get_tasks()

    grouped_queries = {
        "customer": [],
        "colleague": [],
    }
    for task in sql_tasks:
        grouped_queries[task["source"]].append(os.path.basename(task["path"]))

    query_options_parts = []
    for source_key in ("customer", "colleague"):
        source_label = QUERY_SOURCES[source_key]["label"]
        filenames = sorted(grouped_queries[source_key])
        if not filenames:
            continue

        query_options_parts.append(f'<optgroup label="{source_label}">')
        query_options_parts.extend(
            f'<option value="{source_key}::{filename}">{filename}</option>'
            for filename in filenames
        )
        query_options_parts.append('</optgroup>')

    query_options = "".join(query_options_parts)
    query_count = len(sql_tasks)
    return query_options, query_count


def func_sql_rewrite_drops(sql_text):
    safe_lines = []
    for line in sql_text.splitlines():
        if line.strip().lower().startswith("drop table"):
            tables = line.replace("DROP TABLE", "").split(",")
            for tbl in tables:
                tbl = tbl.strip()
                if tbl:
                    safe_lines.append(f"IF OBJECT_ID('tempdb..{tbl}') IS NOT NULL DROP TABLE {tbl};")
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines)


def func_sql_find_error_line(sql_text, identifier):
    """Find the first reference in the original SQL, with one-based line numbers."""
    references = re.sub(
        r"""'(?:''|[^'])*'|"(?:""|[^"])*"|\[(?:\]\]|[^\]])*\]|--[^\r\n]*|/\*[\s\S]*?\*/""",
        lambda match: re.sub(r"[^\r\n]", " ", match[0]) if match[0].startswith(("--", "/*")) else match[0],
        sql_text,
    )
    parts = [part.strip('[]" ') for part in identifier.split(".")]
    if not all(parts):
        return None

    quoted = [r'[\["]?' + re.escape(part) + r'[\]"]?' for part in parts]
    qualified = r"\s*\.\s*".join(quoted)
    match = re.search(rf"(?<![\w#@$]){qualified}(?![\w#@$])", references, re.IGNORECASE)
    if match is None and len(parts) > 1:
        match = re.search(rf"(?<![\w#@$]){quoted[-1]}(?![\w#@$])", references, re.IGNORECASE)
    return references.count("\n", 0, match.start()) + 1 if match else None


def func_sql_classify_error(error, sql_text="", *, connecting=False):
    """Classify a DBAPI failure, or an empty result represented by None."""
    if error is None:
        return {"kind": "empty", "message": "No rows returned"}

    # ----------------------------------------------------------------
    # 1. Parse Driver Message
    driver_error = getattr(error, "orig", error)
    args = getattr(driver_error, "args", ())
    driver_message = str(args[1]) if len(args) > 1 and re.fullmatch(r"[A-Z0-9]{5}", str(args[0])) else str(driver_error)
    states = set(re.findall(r"\b[A-Z0-9]{5}\b", driver_message.upper()))
    if args:
        states.add(str(args[0]).upper())
    message = re.sub(r"^(?:\[[^\]\r\n]+\]\s*)+", "", driver_message).strip()
    native = re.search(r"\((-?\d+)\)(?:\s+\([A-Za-z][A-Za-z0-9_]*\))?(?=\s*(?:;|$))", message)
    numbered = re.match(r"(?:Msg|Error)\s+(\d+)\b", message, re.IGNORECASE)
    code = native or numbered
    if native:
        message = message[:native.start()].strip()

    # ----------------------------------------------------------------
    # 2. Classify Failure
    timeout = (
        isinstance(driver_error, TimeoutError)
        or "HYT00" in states
        or bool(re.match(r"(?:(?:login|connection|query|execution|statement) )?timeout(?: expired|$)", message, re.I))
    )
    login_timeout = timeout and (
        connecting or bool(re.search(r"login timeout|connection timeout|\(SQL(?:Driver)?Connect\w*\)", driver_message, re.I))
    )
    if (states - {"HYT00"}).intersection(ODBC_CONNECTION_ERROR_TOKENS) or login_timeout:
        kind = "connection"
    elif timeout:
        kind = "timeout"
    else:
        kind = "sql_error"

    # ----------------------------------------------------------------
    # 3. Return
    default_message = {"connection": "Connection failed", "timeout": "Query timed out", "sql_error": "Query failed"}
    detail = {"kind": kind, "message": message or str(error) or default_message[kind], "raw_message": str(error)}
    if kind == "sql_error":
        subject = re.search(r"""(?:column name|object name|multi-part identifier)\s+['"]([^'"]+)['"]""", message, re.I)
        identifier = subject[1] if subject else None
        detail.update(
            sql_error_number=int(code[1]) if code else None,
            identifier=identifier,
            line_number=func_sql_find_error_line(sql_text, identifier) if identifier else None,
        )
    return detail


def func_sql_is_connection_error(error):
    """Return True for ODBC/network failures that require a fresh DB connection."""
    return func_sql_classify_error(error)["kind"] == "connection"


def func_sql_reset_connection(source_key, raw_conn=None, reason=None):
    """
    Remove a broken DBAPI connection from the pool and reset the SQLAlchemy pool.

    This is especially important for CEC_Archives: a direct connection can work
    while a long-lived pooled connection in the API has gone stale.
    """
    source = QUERY_SOURCES[source_key]
    source_label = source["label"]

    # SQLAlchemy raw_connection() commonly returns a ConnectionFairy which
    # supports invalidate(). Prefer invalidating the exact broken connection.
    if raw_conn is not None:
        try:
            invalidate = getattr(raw_conn, "invalidate", None)
            if callable(invalidate):
                invalidate(reason)
        except Exception:
            pass

    # Dispose idle/stale pooled connections so the next retry establishes a
    # completely fresh ODBC session. Checked-out connections are not reused
    # after they are returned.
    try:
        source["conn"].engine.dispose()
        print_status(
            "DB RESET",
            f"[{source_label}] Disposed stale connection pool; next attempt will reconnect."
        )
    except Exception as dispose_error:
        print_status(
            "WARNING",
            f"[{source_label}] Unable to dispose connection pool: {dispose_error}"
        )


def func_sql_run_file(sql_file_path, source_key, latest_week):
    # ----------------------------------------------------------------
    # 1. Initialize
    source = QUERY_SOURCES[source_key]
    source_label = source["label"]
    sql_filename = os.path.basename(sql_file_path)

    print(f"\n Executing [{source_label}] {sql_filename} ...")

    raw_conn = None
    cursor = None
    sql_text = ""
    connecting = False

    # ----------------------------------------------------------------
    # 2. Execute Queries
    try:
        sql_text = Path(sql_file_path).read_text(encoding="utf-8").replace("\ufeff", "")
        sql_script = func_sql_rewrite_drops(sql_text)
        # Always check out a connection inside the attempt. If a prior attempt
        # invalidated/disposed the pool, this gets a genuinely fresh session.
        connecting = True
        raw_conn = source["conn"].engine.raw_connection()
        cursor = raw_conn.cursor()

        # CEC_Archives has shown intermittent stale pooled connections. Test the
        # session before starting a potentially long query so a dead connection
        # fails fast and can be retried.
        if source_key == "colleague":
            cursor.execute("SELECT 1")
            cursor.fetchone()

        connecting = False
        cursor.execute(sql_script)
        df = None

        while True:
            if cursor.description:
                rows = cursor.fetchall()
                if rows:
                    columns = [desc[0] for desc in cursor.description]
                    df = pd.DataFrame.from_records(rows, columns=columns)
                    break

            if not cursor.nextset():
                break

        if df is not None:
            validation_market = func_validation_get_market(sql_filename)

            if validation_market:
                comparison_result = func_validation_build_comparison(
                    df,
                    only_differences=False
                )
                validation_result = func_validation_check_actual_week(
                    df,
                    sql_filename,
                    latest_week,
                )

                if comparison_result["status"] == "success":
                    comparison_data = comparison_result["comparison_data"]

                    for row in comparison_data:
                        row["validation_market"] = validation_market
                        row["query_source"] = source_label

                    result = {
                        "status": "success",
                        "validation": validation_result,
                        "validation_market": validation_market,
                        "query_source": source_label,
                        "comparison_summary": comparison_result["comparison_summary"],
                        "comparison_data": comparison_data
                    }
                else:
                    result = {
                        **comparison_result,
                        "validation_market": validation_market,
                        "query_source": source_label
                    }

            else:
                output_path = OUTPUT_FOLDER / (Path(sql_filename).stem + ".csv")
                validation_result = func_validation_check_actual_week(df, sql_filename, latest_week)
                func_output_files_write_csv(output_path, df)

                print(
                    f"Saved [{source_label}]: "
                    f"{output_path}"
                )

                result = {
                    "status": "success",
                    "output_file": str(output_path),
                    "validation": validation_result,
                    "query_source": source_label
                }

        else:
            print(
                f" No rows returned from "
                f"[{source_label}]: {sql_filename}"
            )

            result = {
                "status": "no_data",
                "message": "No rows returned",
                "query_source": source_label
            }

        # IMPORTANT:
        # These pipeline scripts are extract/read queries. Do NOT call
        # raw_conn.commit() unconditionally here. The previous implementation
        # committed in finally, which can trigger pyodbc SQLEndTran on a broken
        # network session and turn an otherwise completed SELECT into:
        #
        #   08S01 Communication link failure (SQLEndTran)
        #
        # If a future SQL file intentionally performs persistent writes, give it
        # an explicit transaction/commit path rather than committing every query.

        return result

    except Exception as exec_err:
        error_detail = func_sql_classify_error(exec_err, sql_text, connecting=connecting)
        connection_failure = error_detail["kind"] == "connection"

        if connection_failure:
            print_status(
                "DB LINK",
                f"[{source_label}] Connection failure in {sql_filename}: {exec_err}"
            )

            func_sql_reset_connection(
                source_key,
                raw_conn=raw_conn,
                reason=exec_err
            )

        if "3701" in str(exec_err):
            print(
                f"Ignored drop error "
                f"[{source_label}]: {exec_err}"
            )

            return {
                "status": "ignored_drop_error",
                "query_source": source_label,
                "error": str(exec_err),
                "error_detail": error_detail,
                "connection_failure": connection_failure,
            }

        print(
            f"Error executing "
            f"[{source_label}] {sql_filename}: {exec_err}"
        )

        return {
            "status": "error",
            "error": str(exec_err),
            "error_detail": error_detail,
            "query_source": source_label,
            "connection_failure": connection_failure
        }

    # ----------------------------------------------------------------
    # 3. Clean Up
    finally:
        # Cleanup must never mask the real query result/error. In particular,
        # closing a dead pyodbc connection can itself raise another 08S01.
        if cursor is not None:
            try:
                cursor.close()
            except Exception as cursor_close_error:
                if not func_sql_is_connection_error(cursor_close_error):
                    print_status(
                        "WARNING",
                        f"[{source_label}] Cursor close warning: {cursor_close_error}"
                    )

        if raw_conn is not None:
            try:
                raw_conn.close()
            except Exception as connection_close_error:
                if not func_sql_is_connection_error(connection_close_error):
                    print_status(
                        "WARNING",
                        f"[{source_label}] Connection close warning: {connection_close_error}"
                    )


def func_sql_get_fallback_output(filename):
    if func_validation_get_market(filename):
        return None

    try:
        path = func_output_files_get_csv(Path(filename).stem + ".csv")
        return func_output_files_get_metadata(path)
    except (FileNotFoundError, ValueError):
        return None
    except OSError as exc:
        log_message(f"Unable to inspect retained output | file={filename} | {exc}", 'WARNING')
        return None


def func_sql_execute_job(job_id, sql_tasks, on_progress=None, *, latest_week=week_unset):
    # ----------------------------------------------------------------
    # 1. Initialize
    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["results"] = [
            {
                "filename": os.path.basename(task["path"]),
                "source": task["source"],
                "source_label": task["source_label"],
                "status": "pending",
                "attempts": 0,
                "max_attempts": MAX_QUERY_ATTEMPTS,
                "attempt_details": [],
            }
            for task in sql_tasks
        ]

    if on_progress is not None:
        on_progress(job_id)
    print_status("JOB", f"{job_id} | {len(sql_tasks)} SQL file(s)")
    log_message(f"SQL job started | job_id={job_id}", 'INFO')
    if latest_week is week_unset:
        latest_week = func_validation_get_current_week(QUERY_SOURCES["customer"]["conn"])

    # ----------------------------------------------------------------
    # 2. Execute Queries
    def func_sql_run_task(index, task):
        # ----------------------------------------------------------------
        # 1. Initialize
        filename = os.path.basename(task["path"])
        source_label = task["source_label"]

        # ----------------------------------------------------------------
        # 2. Run Attempts
        for attempt in range(1, MAX_QUERY_ATTEMPTS + 1):
            with jobs_lock:
                entry = jobs[job_id]["results"][index]
                entry["status"] = "running" if attempt == 1 else "retrying"
                entry["attempts"] = attempt
                entry["last_error"] = None

            if on_progress is not None:
                on_progress(job_id)

            print_status(
                "START" if attempt == 1 else "RETRY",
                f"[{index + 1:02d}/{len(sql_tasks):02d}] "
                f"[{source_label}] {filename} | attempt {attempt}/{MAX_QUERY_ATTEMPTS}"
            )

            attempt_started_at = datetime.now(TIMEZONE).isoformat()
            attempt_started = time.perf_counter()
            try:
                result = func_sql_run_file(task["path"], task["source"], latest_week)
            except Exception as exc:
                result = {
                    "status": "error",
                    "error": str(exc),
                    "error_detail": func_sql_classify_error(exc),
                    "query_source": source_label,
                }

            duration = round(time.perf_counter() - attempt_started, 3)
            raw_status = result["status"]
            error_detail = result.get("error_detail")
            if raw_status == "no_data":
                error_detail = func_sql_classify_error(None)
            elif raw_status != "success" and error_detail is None:
                error_detail = func_sql_classify_error(result.get("error") or result.get("message") or raw_status)

            with jobs_lock:
                entry = jobs[job_id]["results"][index]
                entry["attempt_details"] = [*entry["attempt_details"], {
                    "attempt": attempt,
                    "started_at": attempt_started_at,
                    "duration_seconds": duration,
                    "error": error_detail,
                }]

            if error_detail is None or error_detail["kind"] != "connection":
                break

            if attempt < MAX_QUERY_ATTEMPTS:
                delay = QUERY_RETRY_DELAYS_SECONDS[min(
                    attempt - 1,
                    len(QUERY_RETRY_DELAYS_SECONDS) - 1
                )]
                failure_detail = result.get(
                    "error",
                    result.get("message", result.get("status", "unknown error"))
                )

                with jobs_lock:
                    entry = jobs[job_id]["results"][index]
                    entry["status"] = "retrying"
                    entry["last_error"] = failure_detail

                if on_progress is not None:
                    on_progress(job_id)
                retry_reason = (
                    "connection reset"
                    if result.get("connection_failure")
                    else "query failure"
                )

                print_status(
                    "WAIT",
                    f"[{source_label}] {filename} failed on attempt {attempt} "
                    f"({retry_reason}); retrying in {delay}s"
                )
                time.sleep(delay)

        # ----------------------------------------------------------------
        # 3. Record Result
        status_label = {"success": "complete", "no_data": "empty"}.get(raw_status, "failed")
        failure_detail = result.get("error") or (error_detail or {}).get("message")

        fallback_output = func_sql_get_fallback_output(filename) if status_label != "complete" else None
        with jobs_lock:
            entry = jobs[job_id]["results"][index]
            entry["status"] = status_label
            entry["raw_status"] = raw_status
            entry["attempts"] = min(
                entry.get("attempts", MAX_QUERY_ATTEMPTS),
                MAX_QUERY_ATTEMPTS
            )

            for key in (
                "output_file",
                "validation",
                "validation_market",
                "query_source",
                "comparison_summary",
                "comparison_data",
                "message",
                "error",
                "connection_failure",
            ):
                if key in result:
                    entry[key] = result[key]

            if error_detail is not None:
                entry["error_detail"] = error_detail
                entry["fallback_output"] = fallback_output
                if error_detail["kind"] != "connection":
                    entry["max_attempts"] = attempt

            if status_label == "failed":
                entry["last_error"] = failure_detail

        if on_progress is not None:
            on_progress(job_id)

        status_message = (
            f"[{index + 1:02d}/{len(sql_tasks):02d}] "
            f"[{source_label}] {filename}"
        )

        if status_label == "complete":
            print_status(
                "OK",
                f"{status_message} | attempts={jobs[job_id]['results'][index]['attempts']}"
            )
        elif status_label == "failed":
            print_status(
                "FAILED",
                f"{status_message} | failed after {attempt} attempts | "
                f"{failure_detail}"
            )
        else:
            name = fallback_output["name"] if fallback_output else "none"
            log_message(f"No rows returned | job_id={job_id} | file={filename} | retained_csv={name}", 'WARNING')

    # Use separate source-specific worker pools. Previously all Customer tasks
    # were submitted before Colleague tasks into one four-worker queue. If the
    # Customer queries were slow or blocked, Colleague could sit queued for a
    # long time and appear not to run at all. Dedicated pools guarantee that
    # both sources start independently.
    indexed_tasks_by_source = {key: [] for key in QUERY_SOURCES}
    for index, task in enumerate(sql_tasks):
        indexed_tasks_by_source.setdefault(task["source"], []).append((index, task))

    executors = []
    futures = []

    try:
        for source_key, indexed_tasks in indexed_tasks_by_source.items():
            if not indexed_tasks:
                continue

            max_workers = max(1, int(SOURCE_MAX_WORKERS.get(source_key, 1)))
            source_label = QUERY_SOURCES[source_key]["label"]

            print_status(
                "POOL",
                f"[{source_label}] {len(indexed_tasks)} query(s) | workers={max_workers}"
            )

            executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=f"{source_key}-sql",
            )
            executors.append(executor)

            for index, task in indexed_tasks:
                futures.append(executor.submit(func_sql_run_task, index, task))

        for future in as_completed(futures):
            # Surface unexpected worker-level exceptions instead of silently
            # swallowing them. Query execution errors are already converted to
            # normal failed result objects inside func_sql_run_task().
            future.result()

    except Exception as exc:
        with jobs_lock:
            if not jobs[job_id].get("scheduled_refresh"):
                jobs[job_id].update(status="failed", error=str(exc), completed_at=datetime.now(TIMEZONE).isoformat())
        log_message(f"SQL job failed | job_id={job_id} | {exc}", 'ERROR')
        raise
    finally:
        for executor in executors:
            executor.shutdown(wait=True)

    # ----------------------------------------------------------------
    # 3. Finalize Job
    # For scheduled jobs, func_refresh_run_scheduled assigns the final refresh state
    # after evaluating failed queries and the latest-week quality summary.
    with jobs_lock:
        if not jobs[job_id].get("scheduled_refresh"):
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["completed_at"] = datetime.now(TIMEZONE).isoformat()

    if on_progress is not None:
        on_progress(job_id)
    print_status("JOB DONE", job_id)
    log_message(f"SQL job finished | job_id={job_id}", 'INFO')


def func_sql_prepare_job(filename, source_key):
    # ----------------------------------------------------------------
    # 1. Validate Request
    # The frontend sends source="all" explicitly for Run all. Normalise this
    # to None so func_sql_get_tasks() scans every configured source.
    if isinstance(source_key, str) and source_key.lower() == "all":
        source_key = None

    if source_key and source_key not in QUERY_SOURCES:
        raise ValueError(f"Unknown query source: {source_key}")

    if filename:
        if not func_filenames_is_direct(filename, ".sql"):
            raise ValueError("Only direct .sql filenames are allowed")
        safe_filename = filename

        if source_key:
            sql_tasks = func_sql_get_tasks(
                source_key=source_key,
                filename=safe_filename
            )
        else:
            # Backwards-compatible behaviour: if source is omitted, locate the
            # filename across configured folders. Require an unambiguous match.
            sql_tasks = []
            for candidate_source in QUERY_SOURCES:
                sql_tasks.extend(
                    func_sql_get_tasks(
                        source_key=candidate_source,
                        filename=safe_filename
                    )
                )

            if len(sql_tasks) > 1:
                raise ValueError(
                    f"{safe_filename} exists in more than one query source. "
                    "Please specify customer or colleague."
                )

        if not sql_tasks:
            raise QueryNotFoundError(f"SQL file not found: {safe_filename}")
    else:
        # No filename means run all configured customer + colleague queries.
        sql_tasks = func_sql_get_tasks(source_key=source_key)

    # ----------------------------------------------------------------
    # 2. Validate Queries
    customer_discovered = sum(task["source"] == "customer" for task in sql_tasks)
    colleague_discovered = sum(task["source"] == "colleague" for task in sql_tasks)

    print_status(
        "DISCOVER",
        f"Manual request | Customer={customer_discovered} | "
        f"Colleague={colleague_discovered} | Total={len(sql_tasks)}"
    )

    if not sql_tasks:
        raise QueryNotFoundError("No SQL files found for the requested query source")

    func_sql_validate_output_collisions(sql_tasks)
    return sql_tasks


def func_sql_retain_finished_job(job_id):
    with jobs_lock:
        finished_jobs[job_id] = None
        while len(finished_jobs) > SQL_JOB_RETENTION_LIMIT:
            expired_id = next(iter(finished_jobs))
            del finished_jobs[expired_id]
            jobs.pop(expired_id, None)


def func_sql_run_manual_job(job_id, sql_tasks):
    try:
        func_sql_execute_job(job_id, sql_tasks)
    except Exception as exc:
        with jobs_lock:
            job = jobs[job_id]
            if job["status"] == "running":
                job.update(status="failed", error=str(exc), completed_at=datetime.now(TIMEZONE).isoformat())
                log_message(f"SQL job failed | job_id={job_id} | {exc}", 'ERROR')
        raise
    finally:
        func_sql_retain_finished_job(job_id)


def func_sql_start_job(sql_tasks, run_by=None):
    # ----------------------------------------------------------------
    # 1. Start Worker
    if run_by is not None and (not isinstance(run_by, str) or not 1 <= len(run_by.strip()) <= RUN_BY_LIMIT):
        raise ValueError("Enter the name to record for this run")
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status": "running", "results": None, "started_at": datetime.now(TIMEZONE).isoformat(),
            "run_by": run_by.strip() if run_by else None,
        }

    threading.Thread(
        target=func_sql_run_manual_job,
        args=(job_id, sql_tasks),
        daemon=True
    ).start()

    customer_count = sum(task["source"] == "customer" for task in sql_tasks)
    colleague_count = sum(task["source"] == "colleague" for task in sql_tasks)

    print_status(
        "JOB START",
        f"{job_id} | {len(sql_tasks)} query(s) | "
        f"Customer={customer_count} | Colleague={colleague_count}"
    )

    # ----------------------------------------------------------------
    # 2. Return
    return {
        "job_id": job_id,
        "status": "running",
        "query_count": len(sql_tasks),
        "customer_query_count": customer_count,
        "colleague_query_count": colleague_count,
    }


def func_sql_prepare_selected(items):
    if not isinstance(items, list) or not items:
        raise ValueError("Select one or more queries")
    tasks = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("source"), str) or item["source"] not in QUERY_SOURCES:
            raise ValueError("Each query needs a customer or colleague source")
        source = item["source"]
        filename = item.get("filename")
        if not func_filenames_is_direct(filename, ".sql"):
            raise ValueError("Only direct .sql filenames are allowed")
        key = source, filename
        if key in seen:
            continue
        seen.add(key)
        matches = func_sql_get_tasks(source_key=source, filename=filename)
        if not matches:
            raise QueryNotFoundError(f"SQL file not found: {filename}")
        tasks.extend(matches)
    func_sql_validate_output_collisions(tasks)
    return tasks


def func_sql_get_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return None

        snapshot = dict(job)
        results = job.get("results")
        if results is not None:
            snapshot["results"] = [dict(result) for result in results]
        return snapshot
