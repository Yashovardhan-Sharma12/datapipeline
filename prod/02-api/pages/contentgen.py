# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import dash

import callbacks.callbacks_contentgen
from layouts.layouts_contentgen import layout_contentgen

# ----------------------------------------------------------------------------------------------------------------------
#%% Register Page
dash.register_page(__name__, path='/contentgen', name='ContentGen', order=2, layout=layout_contentgen)
