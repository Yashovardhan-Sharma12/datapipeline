# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import dash

import callbacks.callbacks_history
from layouts.layouts_history import layout_history

# ----------------------------------------------------------------------------------------------------------------------
#%% Register Page
dash.register_page(__name__, path='/history', name='Run history', order=4, layout=layout_history)
