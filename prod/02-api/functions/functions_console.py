# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from config import CONSOLE_WIDTH

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def print_banner(title, subtitle=None):
    """Print a consistent section banner for console / scheduler logs."""
    print("\n" + "#" * CONSOLE_WIDTH)
    print(f"# {title}")
    if subtitle:
        print(f"# {subtitle}")
    print("#" * CONSOLE_WIDTH)


def print_detail(label, value):
    print(f"  {label:<20}: {value}")


def print_status(status, message):
    print(f"[{status:<8}] {message}")
