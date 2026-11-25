# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import html

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_ui_heading(title, description, controls=None):
    return html.Div([html.Div([html.H2(title), html.P(description)]), controls], className="shead")


def layout_ui_panel_header(title, description=None, aside=None):
    return html.Div([html.Div([html.H3(title), html.P(description) if description is not None else None]), aside],
                    className="phead")


def layout_ui_panel(title, description, content, **props):
    return html.Div([layout_ui_panel_header(title, description), content], className="panel", **props)


def layout_ui_pill(label, kind="idle"):
    return html.Span(label, className=f"pill p-{kind}")


def layout_ui_env(env):
    return html.Span(env.upper(), className=f"env env-{env}")


def layout_ui_empty(message):
    return html.Div(message, className="empty muted")


def layout_ui_notice(messages):
    if isinstance(messages, str):
        messages = [messages]
    return html.Div([html.P(message) for message in messages], className="notice", role="status") if messages else None


def layout_ui_table(headings, rows):
    return html.Div(
        html.Table([html.Thead(html.Tr([html.Th(title, scope="col") for title in headings])), html.Tbody(rows)],
                   className="tbl"),
        className="tbl-wrap",
    )
