# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages

import atexit

from apscheduler.schedulers.background import BackgroundScheduler
from dash import Dash
from flask import Flask
from flask_caching import Cache

from config import API_FOLDER, ASSETS_FOLDER, LEGACY_API_FILE, PAGES_FOLDER, REFRESH_DESK_UI_ENABLED, TIMEZONE

# ----------------------------------------------------------------------------------------------------------------------
#%% App & Cache Initialization

# Keep the service name used in Flask's startup banner and application logs.
flask_app = Flask(LEGACY_API_FILE.stem, root_path=str(API_FOLDER))
cache = Cache(flask_app, config={"CACHE_TYPE": "SimpleCache"})
scheduler = BackgroundScheduler(timezone=TIMEZONE.key)
dash_app = None
if REFRESH_DESK_UI_ENABLED:
    dash_app = Dash(
        __name__, server=flask_app, use_pages=True, pages_folder=str(PAGES_FOLDER),
        assets_folder=str(ASSETS_FOLDER), title="Refresh Desk", update_title=None,
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1, viewport-fit=cover"}],
    )

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_app_shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()


atexit.register(func_app_shutdown_scheduler)

# ----------------------------------------------------------------------------------------------------------------------
#%% Response Headers

# Keep the internal control UI fresh while the service is running.
# This also prevents an older cached JavaScript file from hiding newly added
# Customer/Colleague query sources after a Git pull or service update.
@flask_app.after_request
def func_app_add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
