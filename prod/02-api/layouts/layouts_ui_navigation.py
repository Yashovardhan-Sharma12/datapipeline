# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, html

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_ui_navigation(pathname="/", attention_count=0):
    pages = [
        ("/", "Today"), ("/queries", "Queries"), ("/contentgen", "ContentGen"),
        ("/schedules", "Schedules"), ("/history", "Run history"), ("/definitions", "Definitions"),
    ]
    links = []
    for path, label in pages:
        children = [label]
        if path == "/" and attention_count:
            children.append(html.Span(attention_count, className="count", title="Items that need attention"))
        if path == "/definitions":
            children.append(html.Span("Phase 2", className="soon"))
        links.append(dcc.Link(children, href=path, className="tab-current" if path == pathname else ""))
    return html.Div(links, className="tabs-main")
