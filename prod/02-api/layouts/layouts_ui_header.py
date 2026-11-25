# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, get_asset_url, html

from config import RUN_BY_LIMIT

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_ui_header():
    return html.Header([
        html.Div(className="spacer"),
        html.Div([
            html.H1(["Refresh Desk", html.Span(" - CCEC", className="a"), html.Span(".", className="stop")], className="t"),
            html.Div("Powered by Enterprise Analytics", className="sub"),
        ], className="ptitle"),
        html.Div(html.Img(src=get_asset_url("images/logo.png"), alt="Tesco"), className="logo-slot"),
    ], className="topbar")


def layout_ui_header_context():
    return html.Div([
        html.Div([
            html.Div(id="ui-context-clock", className="clock"),
            html.Div([
                html.Div([
                    html.Button("Prod", id="ui-env-prod", type="button", **{"aria-pressed": "true"}),
                    html.Button("Dev (testing)", id="ui-env-dev", type="button", **{"aria-pressed": "false"}),
                ], className="seg", role="group", **{"aria-label": "Environment"}),
                html.Div([
                    html.Label("Run by", htmlFor="ui-run-by", className="input-label"),
                    dcc.Input(id="ui-run-by", type="text", debounce=True, maxLength=RUN_BY_LIMIT,
                              placeholder="Your name", className="rd-input"),
                ], className="row"),
            ], className="right"),
        ], className="ctx"),
        html.Div(
            "You're looking at dev. Use it to test changes. Weekly refreshes run in prod, "
            "and dev has no schedule unless you add one.",
            id="ui-dev-banner", className="devnote", hidden=True,
        ),
    ])
