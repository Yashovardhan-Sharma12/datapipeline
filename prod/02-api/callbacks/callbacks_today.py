# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import ALL, Input, Output, State, callback, ctx, no_update
from dash.exceptions import PreventUpdate

from functions.functions_api_client import ApiClientError
from functions.functions_today import func_today_timeline
from functions.functions_ui import func_ui_add_project, func_ui_attention, func_ui_refresh_detail, func_ui_run_detail
from layouts.layouts_today import (
    layout_today_attention,
    layout_today_refresh_detail,
    layout_today_run_detail,
    layout_today_summary,
    layout_today_timeline,
)
from layouts.layouts_ui_components import layout_ui_notice

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("today-status", "children"),
    Output("today-kpis", "children"),
    Output("today-lane-heading", "children"),
    Output("today-lanes", "children"),
    Output("today-attention", "children"),
    Input("ui-store-dashboard", "data"),
    Input("ui-store-dismissed", "data"),
    Input("today-run-selection", "data"),
)
def callback_today_overview(state, dismissed, selected):
    if not state:
        raise PreventUpdate
    summary, cards = layout_today_summary(state)
    timeline = func_today_timeline(state)
    dismissed = set(dismissed or [])
    issues = [item for item in func_ui_attention(state) if item["id"] not in dismissed]
    errors = list(dict.fromkeys(state["errors"].values()))
    if errors:
        summary.append(layout_ui_notice(errors))
    return summary, cards, f"{timeline[3]:%A} so far", layout_today_timeline(timeline, selected), layout_today_attention(issues)


@callback(
    Output("today-run-selection", "data"),
    Input({"type": "today-lane-run", "key": ALL, "kind": ALL}, "n_clicks"),
    State("ui-store-env", "data"),
    State("today-run-selection", "data"),
    prevent_initial_call=True,
)
def callback_today_select(clicks, env, selected):
    clicked = ctx.triggered_id
    if not isinstance(clicked, dict) or not any(clicks or []):
        raise PreventUpdate
    event = {**clicked, "env": env}
    return event if event != selected else no_update


@callback(
    Output("today-lane-detail", "children"),
    Output("today-lane-detail", "hidden"),
    Output("today-run-view", "data"),
    Input("today-run-selection", "data"),
    Input("ui-store-dashboard", "data"),
    State("today-run-view", "data"),
)
def callback_today_detail(selected, state, view):
    if not selected or not state or state["env"] != selected["env"]:
        return [], True, None
    key = selected["key"]
    try:
        if selected["kind"] == "contentgen":
            summary = next((row for row in state["runs"] if row["run_id"] == key), None)
        else:
            manual = selected["kind"] == "manual"
            candidates = state["manual"] if manual else state["active"] + state["history"]
            summary = next((row for row in candidates if row["job_id"] == key), None)
        if summary is None:
            return [], True, None
        record = {**selected, "status": summary["status"]}
        if record == view and summary["status"] != "running":
            raise PreventUpdate
        if selected["kind"] == "contentgen":
            return layout_today_run_detail(*func_ui_run_detail(key)), False, record
        detail = func_ui_refresh_detail(state["env"], key, active=manual or summary["status"] == "running")
        return layout_today_refresh_detail(detail, summary, manual=manual), False, record
    except ApiClientError as exc:
        return layout_ui_notice(str(exc)), False, None


@callback(
    Output("ui-store-dismissed", "data"),
    Input({"type": "today-dismiss", "key": ALL}, "n_clicks"),
    State({"type": "today-dismiss", "key": ALL}, "id"),
    State("ui-store-dismissed", "data"),
    prevent_initial_call=True,
)
def callback_today_dismiss(clicks, identifiers, dismissed):
    clicked = ctx.triggered_id
    if not isinstance(clicked, dict) or not any(value for item, value in zip(identifiers or [], clicks or []) if item == clicked):
        raise PreventUpdate
    return list(dict.fromkeys([*(dismissed or []), clicked["key"]]))


@callback(
    Output("today-message", "children"),
    Output("today-reload", "data"),
    Input({"type": "today-add-project", "key": ALL}, "n_clicks"),
    State("ui-store-user-name", "data"),
    State("ui-store-dashboard", "data"),
    prevent_initial_call=True,
)
def callback_today_add_project(add_clicks, run_by, state):
    clicked = ctx.triggered_id
    if not isinstance(clicked, dict) or not any(add_clicks or []) or not state or state["env"] != "prod":
        raise PreventUpdate
    try:
        func_ui_add_project(clicked["key"], run_by)
        return f"{clicked['key']} added to the prod schedule.", {"action": "schedule", "project": clicked["key"]}
    except ApiClientError as exc:
        return str(exc), no_update
