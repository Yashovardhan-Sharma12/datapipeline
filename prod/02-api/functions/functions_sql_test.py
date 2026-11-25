# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import math
import re
import time
import uuid
from contextlib import closing
from datetime import date, datetime, time as datetime_time

from config import QUERY_TEST_LOGIN_TIMEOUT_SECONDS, QUERY_TEST_ROW_LIMIT, QUERY_TEST_TIMEOUT_SECONDS
from functions.functions_sql_execution import QUERY_SOURCES, func_sql_classify_error, func_sql_rewrite_drops
from utils import mssql

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
sql_token_pattern = re.compile(
    r"""--[^\r\n]*|/\*|(?:N?'(?:''|[^'])*')|\[(?:\]\]|[^\]])*\]|"(?:""|[^"])*"|[\w@#$]+|[^\s]""",
    re.I,
)
comment_marker_pattern = re.compile(r"/\*|\*/")
unguarded_drop_pattern = re.compile(
    r"^[ \t]*DROP[ \t]+TABLE[ \t]+(#[\w]+(?:[ \t]*,[ \t]*#[\w]+)*)[ \t]*;?[ \t]*$",
    re.I | re.M,
)
preview_openings = {
    "SELECT", "WITH", "DECLARE", "SET", "IF", "BEGIN", "CREATE", "ALTER", "DROP", "INSERT",
    "UPDATE", "DELETE", "TRUNCATE", "PRINT", "WAITFOR",
}
outside_transaction = {
    "COMMIT", "ROLLBACK", "EXEC", "EXECUTE", "OPENROWSET", "OPENQUERY", "OPENDATASOURCE",
    "BULK", "BACKUP", "RESTORE", "DBCC", "SHUTDOWN", "RECONFIGURE", "KILL", "USE", "GRANT", "DENY", "REVOKE",
    "SEND", "RECEIVE", "WRITETEXT", "UPDATETEXT", "MERGE",
}

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_sql_test_tokens(sql):
    cursor = 0
    while match := sql_token_pattern.search(sql, cursor):
        token = match[0]
        cursor = match.end()
        if token == "/*":
            depth = 1
            while depth:
                marker = comment_marker_pattern.search(sql, cursor)
                if marker is None:
                    return
                depth += 1 if marker[0] == "/*" else -1
                cursor = marker.end()
        elif not token.startswith("--"):
            yield token.upper(), match.start()


def func_sql_test_safety_error(sql):
    """Keep preview writes scoped to local temporary objects and the driver transaction."""
    # ----------------------------------------------------------------
    # 1. Inspect SQL Tokens
    tokens = list(func_sql_test_tokens(sql))
    words = [word for word, _ in tokens]
    first = next((index for index, word in enumerate(words) if word != ";"), None)
    if first is None:
        return {"kind": "empty", "message": "Enter a query to test."}

    def func_sql_test_error(index, message):
        return {
            "kind": "sql_error", "message": message,
            "sql_error_number": None, "line_number": sql.count("\n", 0, tokens[index][1]) + 1,
        }

    def func_sql_test_is_temporary(index):
        target = words[index].strip('[]"') if index < len(words) else ""
        unqualified = index + 1 >= len(words) or words[index + 1] != "."
        return unqualified and (
            target.startswith("#") and not target.startswith("##")
            or target.startswith("@") and not target.startswith("@@")
        )

    # ----------------------------------------------------------------
    # 2. Reject Statements With Persistent Or External Effects
    if words[first] not in preview_openings:
        return func_sql_test_error(first, "Start the preview with a query or a local temporary-table statement.")
    for index, word in enumerate(words):
        following = words[index + 1:index + 4]
        if word in outside_transaction or (
            word in {"BEGIN", "SAVE"} and following and following[0] in {"TRAN", "TRANSACTION", "DISTRIBUTED"}
        ):
            return func_sql_test_error(index, f"{word} is unavailable in a rollback-only test.")
        if word == "NEXT" and following[:2] == ["VALUE", "FOR"]:
            return func_sql_test_error(index, "Sequence values cannot be rolled back.")
        if word in {"CREATE", "ALTER", "DROP", "TRUNCATE"}:
            if not following or following[0] != "TABLE":
                return func_sql_test_error(index, "Tests can only create, alter or drop local temporary tables.")
            target = index + (4 if following == ["TABLE", "IF", "EXISTS"] else 2)
            if not func_sql_test_is_temporary(target):
                return func_sql_test_error(index, "Tests can only write to local temporary tables or table variables.")
            while target + 1 < len(words) and words[target + 1] == ",":
                target += 2
                if not func_sql_test_is_temporary(target):
                    return func_sql_test_error(index, "Tests can only write to local temporary tables or table variables.")
        if word in {"INTO", "UPDATE", "INSERT", "DELETE"}:
            target = index + 1
            if following and following[0] in {"INTO", "FROM"}:
                target += 1
            if not func_sql_test_is_temporary(target):
                return func_sql_test_error(index, "Tests can only write to local temporary tables or table variables.")
    return None


def func_sql_test_json_value(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (date, datetime, datetime_time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "0x" + bytes(value).hex()
    return str(value)


def func_sql_test_preview_sql(sql):
    drops = {index for word, index in func_sql_test_tokens(sql) if word == "DROP"}

    def func_sql_test_replace_drop(match):
        offset = match.start() + len(match[0]) - len(match[0].lstrip(" \t"))
        return func_sql_rewrite_drops(f"DROP TABLE {match[1]}") if offset in drops else match[0]

    return unguarded_drop_pattern.sub(func_sql_test_replace_drop, sql)


def func_sql_test_fetch(cursor):
    columns = []
    while True:
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchmany(QUERY_TEST_ROW_LIMIT + 1)
            if rows:
                return {
                    "status": "success",
                    "columns": columns,
                    "rows": [[func_sql_test_json_value(value) for value in row] for row in rows[:QUERY_TEST_ROW_LIMIT]],
                    "truncated": len(rows) > QUERY_TEST_ROW_LIMIT,
                }
        if not cursor.nextset():
            return {"status": "empty", "columns": columns, "rows": [], "error": func_sql_classify_error(None)}


def func_sql_test_execute(source, filename, sql):
    # ----------------------------------------------------------------
    # 1. Check SQL And Open An Isolated Connection
    test_id = str(uuid.uuid4())
    started = time.perf_counter()
    log_message(f"Query test started | test_id={test_id} | source={source} | file={filename}", 'INFO')
    stage = "validation"
    guard = func_sql_test_safety_error(sql)
    if guard is not None:
        result = {"status": "error", "error": guard}
    else:
        try:
            stage = "connect"
            odbc = QUERY_SOURCES[source]["conn"].engine.url.query["odbc_connect"]
            with closing(mssql.pyodbc.connect(
                odbc, autocommit=False, timeout=QUERY_TEST_LOGIN_TIMEOUT_SECONDS,
            )) as connection:
                # ----------------------------------------------------------------
                # 2. Preview And Roll Back
                try:
                    stage = "execute"
                    connection.timeout = QUERY_TEST_TIMEOUT_SECONDS
                    with closing(connection.cursor()) as cursor:
                        cursor.execute(func_sql_test_preview_sql(sql))
                        result = func_sql_test_fetch(cursor)
                finally:
                    try:
                        connection.rollback()
                    except Exception as exc:
                        stage = "rollback"
                        log_message(f"Query test rollback failed | test_id={test_id} | {type(exc).__name__}", 'ERROR')
                        raise
        except Exception as exc:
            detail = func_sql_classify_error(exc, sql, connecting=stage == "connect")
            if stage == "rollback":
                detail["message"] = "Could not verify rollback of the test transaction."
            result = {"status": "error", "error": detail}

    # ----------------------------------------------------------------
    # 3. Return
    status = result["status"]
    log_message(f"Query test finished | test_id={test_id} | source={source} | file={filename} | status={status}",
                'WARNING' if status == "error" else 'INFO')
    return {**result, "test_id": test_id, "duration_seconds": round(time.perf_counter() - started, 3)}
