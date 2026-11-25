# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, html

from layouts.layouts_ui_components import layout_ui_heading, layout_ui_panel_header

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_definitions():
    steps = [
        ("Choose input files", "CSVs from the latest refresh"),
        ("Define the data process", "Filters, groupings, metrics"),
        ("Check the output", "Preview the JSON against this week"),
        ("Add to a content process", "Then it runs with the next ContentGen"),
    ]
    return html.Section([
        layout_ui_heading("Definitions", "The data definitions behind each project's content. Browse the current data processes."),
        html.Div([
            html.H3("Build content from the app: coming in phase 2"),
            html.P(["Today a new data process is set up by hand in ", html.Code("data/2-process"),
                    " and ", html.Code("data-INDEX.xlsx"), "."], className="muted"),
            html.Ol([html.Li([html.B(title), html.Span(description)]) for title, description in steps], className="flow"),
        ], className="soon-hero"),
        html.Div(id="definitions-error"),
        html.Div([
            layout_ui_panel_header(html.Span(id="definitions-title"), "From data/2-process/2-data-process",
                                   dcc.Dropdown(id="definitions-project", placeholder="Choose a project", clearable=False)),
            html.Div(id="definitions-list"),
        ], className="panel"),
    ], className="screen")


def layout_definitions_list(entries):
    return html.Ul([
        html.Li([entry["name"], html.Span(f"{entry['file_count']} file{'s' if entry['file_count'] != 1 else ''}")])
        for entry in entries
    ], className="deflist")
