# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from pathlib import PureWindowsPath

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_filenames_is_direct(filename, suffix):
    """Check for a direct filename that is valid on Windows and POSIX."""
    if not isinstance(filename, str) or not filename.lower().endswith(suffix):
        return False
    if not filename[:-len(suffix)] or any(
        char in '\\/:*?"<>|' or ord(char) < 32 for char in filename
    ):
        return False
    return not PureWindowsPath(filename).is_reserved()
