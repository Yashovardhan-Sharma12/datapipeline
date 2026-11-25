# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import json
import threading
import time
import uuid
from pathlib import Path

from config import ATOMIC_REPLACE_ATTEMPTS
from functions.functions_console import print_status

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_file_io_replace(temporary_path, target_path, *, max_attempts=ATOMIC_REPLACE_ATTEMPTS, json_marker=False):
    """Retry Windows sharing violations without exposing a partially written file."""
    for attempt in range(1, max_attempts + 1):
        try:
            os.replace(temporary_path, target_path)
            return
        except PermissionError:
            if attempt >= max_attempts:
                raise

            # Readers usually hold the destination file for only a few milliseconds.
            delay_seconds = min(0.10 * attempt, 1.0)
            if json_marker:
                print_status(
                    "RETRY",
                    f"JSON marker temporarily locked: {target_path.name} | "
                    f"replace attempt {attempt}/{max_attempts}; "
                    f"retrying in {delay_seconds:.1f}s"
                )
            else:
                log_message(
                    f"CSV temporarily locked | file={target_path.name} | "
                    f"attempt={attempt}/{max_attempts} | retry_in={delay_seconds:.1f}s",
                    'WARNING',
                )
            time.sleep(delay_seconds)

    raise ValueError("max_attempts must be positive")


def func_file_io_write_json(path, payload, max_attempts=ATOMIC_REPLACE_ATTEMPTS):
    """
    Write JSON atomically with Windows-safe retry behaviour.

    On Windows, os.replace() can briefly fail with WinError 5 when another
    process (for example the ContentGen scheduler, browser/API reader, antivirus
    or file indexer) has the destination JSON open. Use a unique temp file for
    every write and retry the replace for a short period instead of failing the
    whole scheduled refresh.
    """
    # ----------------------------------------------------------------
    # 1. Prepare Paths
    target_path = Path(os.path.abspath(path))
    target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = target_path.with_name(
        f".{target_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )

    # ----------------------------------------------------------------
    # 2. Write Marker
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4, default=str)
            handle.flush()
            os.fsync(handle.fileno())

        func_file_io_replace(temp_path, target_path, max_attempts=max_attempts, json_marker=True)

    # ----------------------------------------------------------------
    # 3. Clean Up
    finally:
        # If replace succeeded the temp path no longer exists. If it did not,
        # clean up the unique temporary file without masking the original error.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
