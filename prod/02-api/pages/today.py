# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import dash

import callbacks.callbacks_today
from layouts.layouts_today import layout_today

# ----------------------------------------------------------------------------------------------------------------------
#%% Register Page
dash.register_page(__name__, path='/', name='Today', order=0, layout=layout_today)
