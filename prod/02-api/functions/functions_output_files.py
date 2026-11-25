# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import csv
import io
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from config import MISSING_DATA_REPORT_FILE, OUTPUT_ARCHIVE_ROOT, OUTPUT_FOLDER, REFRESH_RUNS_FOLDER, TIMEZONE
from functions.functions_console import print_status
from functions.functions_file_io import func_file_io_replace
from functions.functions_filenames import func_filenames_is_direct

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_output_files_get_csv(filename):
    """Resolve an existing direct CSV without following links outside 03-output."""
    if not func_filenames_is_direct(filename, ".csv"):
        raise ValueError("Only direct .csv filenames are allowed")

    target = OUTPUT_FOLDER / filename
    try:
        inside_output = target.resolve().parent == OUTPUT_FOLDER.resolve()
    except (OSError, RuntimeError):
        inside_output = False
    if not inside_output or not target.is_file():
        raise FileNotFoundError(f"Output file not found: {filename}")
    return target.absolute()


def func_output_files_get_metadata(path):
    """Return the byte size, data record count, and modification time of a CSV."""
    stat = path.stat()
    rows = None
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            if path.name != MISSING_DATA_REPORT_FILE.name:
                next(reader, None)
            rows = sum(1 for row in reader if row)
    except (OSError, UnicodeError, csv.Error) as exc:
        log_message(f"Unable to count output rows | file={path.name} | {exc}", 'WARNING')

    return {
        "name": path.name,
        "size": stat.st_size,
        "rows": rows,
        "written_at": datetime.fromtimestamp(stat.st_mtime, tz=TIMEZONE).isoformat(),
    }


def func_output_files_write_csv(path, data):
    """Publish a new CSV only after pandas has finished writing it."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".csv-", suffix=".tmp", delete=False) as handle:
        temporary_path = Path(handle.name)
    try:
        data.to_csv(temporary_path, index=False, encoding="utf-8-sig")
        func_file_io_replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as exc:
            log_message(f"Unable to clean up temporary CSV | file={path.name} | {exc}", 'WARNING')


def func_output_files_list():
    files = []
    for path in sorted(OUTPUT_FOLDER.iterdir(), key=lambda path: path.name.casefold()):
        if not func_filenames_is_direct(path.name, ".csv"):
            continue
        try:
            files.append(func_output_files_get_metadata(func_output_files_get_csv(path.name)))
        except FileNotFoundError:
            continue
    return files


def func_output_files_get_selection(filenames):
    if not isinstance(filenames, list) or not filenames:
        raise ValueError("Provide a non-empty list of output filenames")
    if not all(func_filenames_is_direct(filename, ".csv") for filename in filenames):
        raise ValueError("Only direct .csv filenames are allowed")
    return list(dict.fromkeys(func_output_files_get_csv(filename) for filename in filenames))


def func_output_files_build_zip(output_files=None):
    """Create an in-memory ZIP of the current 03-output folder."""
    # ----------------------------------------------------------------
    # 1. List Files
    output_folder = OUTPUT_FOLDER.absolute()
    if output_files is None:
        output_files = []
        resolved_folder = output_folder.resolve()
        runs_dir = REFRESH_RUNS_FOLDER.name.casefold()
        for root, directories, filenames in os.walk(output_folder):
            directories[:] = [name for name in directories if name.casefold() != runs_dir]
            folder = Path(root)
            for filename in filenames:
                full_path = folder / filename
                if filename.casefold().endswith(".tmp") or not full_path.is_file():
                    continue
                resolved = full_path.resolve()
                if not resolved.is_relative_to(resolved_folder):
                    continue
                relative = resolved.relative_to(resolved_folder)
                if any(part.casefold() == runs_dir for part in relative.parts[:-1]):
                    continue
                names = (filename.casefold(), relative.name.casefold())
                if any(name.startswith("_refresh_") and name.endswith(".json") for name in names):
                    continue
                output_files.append(full_path)

    if not output_files:
        return None

    # ----------------------------------------------------------------
    # 2. Build Archive
    print_status("DOWNLOAD", f"Preparing ZIP with {len(output_files)} output file(s)")

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED
    ) as zip_file:
        for full_path in sorted(output_files, key=str):
            relative_path = full_path.relative_to(output_folder)
            archive_name = Path(OUTPUT_ARCHIVE_ROOT) / relative_path
            zip_file.write(full_path, arcname=archive_name)

    zip_buffer.seek(0)

    timestamp = datetime.now(
        TIMEZONE
    ).strftime("%Y%m%d_%H%M%S")

    download_name = f"{OUTPUT_ARCHIVE_ROOT}_{timestamp}.zip"

    print_status("DOWNLOAD", f"Sending {download_name}")

    # ----------------------------------------------------------------
    # 3. Return
    return zip_buffer, download_name
