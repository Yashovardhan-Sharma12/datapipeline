# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import dash

import callbacks.callbacks_queries
from layouts.layouts_queries import layout_queries

# ----------------------------------------------------------------------------------------------------------------------
#%% Register Page
dash.register_page(__name__, path='/queries', name='Queries', order=1, layout=layout_queries)
