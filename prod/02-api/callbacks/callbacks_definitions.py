# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import Input, Output, State, callback

from layouts.layouts_definitions import layout_definitions_list
from layouts.layouts_ui_components import layout_ui_empty, layout_ui_notice

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("definitions-project", "options"),
    Output("definitions-project", "value"),
    Output("definitions-error", "children"),
    Input("ui-store-dashboard", "data"),
    State("definitions-project", "value"),
)
def callback_definitions_projects(state, project):
    if not state:
        return [], None, None
    choices = [row["project"] for row in state["projects"]]
    preferred = "ccec" if state["env"] == "prod" else "ccec-o"
    selected = project if project in choices else preferred if preferred in choices else next(iter(choices), None)
    return [{"label": name, "value": name} for name in choices], selected, layout_ui_notice(state["errors"].get("projects"))


@callback(
    Output("definitions-title", "children"),
    Output("definitions-list", "children"),
    Input("ui-store-dashboard", "data"),
    Input("definitions-project", "value"),
)
def callback_definitions_list(state, project):
    if not state or not project:
        return "Data processes", layout_ui_empty("No projects are available.")
    selected = next((row for row in state["projects"] if row["project"] == project), {})
    entries = selected.get("definitions", [])
    return f"What {project} ({state['env']}) builds today", (
        layout_definitions_list(entries) if entries else layout_ui_empty("No data process folders found for this project.")
    )
