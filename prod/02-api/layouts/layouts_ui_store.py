# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc

from config import UI_POLL_IDLE_MS

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_ui_store():
    return [
        dcc.Location(id="ui-location", refresh="callback-nav"),
        dcc.Store(id="ui-store-env", data="prod"),
        dcc.Store(id="ui-store-user-name", storage_type="local"),
        dcc.Store(id="ui-store-dashboard"),
        dcc.Store(id="ui-store-query-run"),
        dcc.Store(id="ui-store-dismissed", storage_type="local", data=[]),
        dcc.Interval(id="ui-poll", interval=UI_POLL_IDLE_MS),
    ]
