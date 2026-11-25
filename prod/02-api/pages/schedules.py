# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import dash

import callbacks.callbacks_schedules
from layouts.layouts_schedules import layout_schedules

# ----------------------------------------------------------------------------------------------------------------------
#%% Register Page
dash.register_page(__name__, path='/schedules', name='Schedules', order=3, layout=layout_schedules)
