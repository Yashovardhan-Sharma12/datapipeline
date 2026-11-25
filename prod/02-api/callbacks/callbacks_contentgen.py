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
from functions.functions_contentgen import func_contentgen_retry, func_contentgen_review
from functions.functions_ui import func_ui_run_detail, func_ui_stop_run, func_ui_submit_items, func_ui_time, step_labels
from layouts.layouts_contentgen import (
    layout_contentgen_project_options,
    layout_contentgen_queue,
    layout_contentgen_recent,
    layout_contentgen_review,
    layout_contentgen_run_detail,
)
from layouts.layouts_ui_components import layout_ui_notice

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("contentgen-project-title", "children"),
    Output("contentgen-project-subtitle", "children"),
    Output("contentgen-projects", "options"),
    Output("contentgen-queue", "children"),
    Output("contentgen-recent", "children"),
    Output("contentgen-recent-subtitle", "children"),
    Output("contentgen-data", "options"),
    Output("contentgen-error", "children"),
    Input("ui-store-dashboard", "data"),
)
def callback_contentgen_load(state):
    if not state:
        raise PreventUpdate
    env = state["env"]
    schedule = state["schedule"]
    next_runs = schedule.get("next_runs", [])
    recent = state["history"][0] if state["history"] else {}
    latest_label = "Latest files"
    if recent.get("completed_at"):
        latest_label += f" · {func_ui_time(recent['completed_at'], '%d %b %H:%M')}"
    next_label = f"Wait for the {func_ui_time(next_runs[0]['scheduled_for'], '%a %H:%M')} refresh" if next_runs else "Wait for the next refresh"
    errors = list(dict.fromkeys(state["errors"][key] for key in ("projects", "contentgen", "history") if key in state["errors"]))
    return (
        f"{env.title()} projects",
        f"Found in src/{env}/projects. Checked every minute and after each git pull.",
        layout_contentgen_project_options(state["projects"], schedule.get("projects", [])),
        layout_contentgen_queue(state["queue"]),
        layout_contentgen_recent(state["runs"]),
        "Scheduled and manual runs in prod" if env == "prod" else "Test runs in dev",
        [{"label": latest_label, "value": "latest"},
         {"label": next_label, "value": "next_refresh", "disabled": not next_runs or not schedule.get("runner_enabled")}],
        layout_ui_notice(errors),
    )


@callback(
    Output("contentgen-selection-count", "children"),
    Output("contentgen-review", "children"),
    Output("contentgen-queue-button", "children"),
    Output("contentgen-queue-button", "disabled"),
    Input("contentgen-projects", "value"),
    Input("contentgen-steps", "value"),
    Input("contentgen-data", "value"),
    Input("ui-store-dashboard", "data"),
)
def callback_contentgen_review(projects, steps, use_data, state):
    if not state:
        return "None selected", "Loading projects…", "Queue runs", True
    count = len(projects or [])
    line = f"{count} selected" if count else "None selected"
    try:
        review = func_contentgen_review(state, projects, steps, use_data)
    except ValueError as exc:
        return line, str(exc), "Queue runs", True
    return line, layout_contentgen_review(review), f"Queue {count} run{'s' if count != 1 else ''}", False


@callback(
    Output("contentgen-message", "children"),
    Output("contentgen-projects", "value"),
    Output("contentgen-data", "value"),
    Output("contentgen-reload", "data"),
    Input("contentgen-queue-button", "n_clicks"),
    Input({"type": "contentgen-stop", "key": ALL}, "n_clicks"),
    Input({"type": "contentgen-retry", "key": ALL}, "n_clicks"),
    Input("ui-store-env", "data"),
    State("contentgen-projects", "value"),
    State("contentgen-steps", "value"),
    State("contentgen-data", "value"),
    State("ui-store-dashboard", "data"),
    State("ui-store-user-name", "data"),
    prevent_initial_call=True,
)
def callback_contentgen_action(submit, stop, retry, env, projects, steps, data, state, run_by):
    # ----------------------------------------------------------------
    # 0. Identify Trigger
    clicked = ctx.triggered_id
    if clicked == "ui-store-env":
        return "", [], "latest", no_update
    if not state or state["env"] != env:
        raise PreventUpdate

    # ----------------------------------------------------------------
    # 1. Process Action
    try:
        if clicked == "contentgen-queue-button" and submit:
            review = func_contentgen_review(state, projects, steps, data)
            trigger = "next_refresh" if data == "next_refresh" else "manual"
            receipt = func_ui_submit_items([line["item"] for line in review], run_by, trigger)
            count = len(receipt["runs"])
            return f"Queued {count} run{'s' if count != 1 else ''}. Prod runs start first.", [], no_update, receipt
        if isinstance(clicked, dict) and clicked["type"] == "contentgen-stop" and any(stop or []):
            receipt = func_ui_stop_run(clicked["key"])
            message = "Removed from the queue." if receipt["run"]["status"] == "stopped" else "Stop requested."
            return message, no_update, no_update, receipt
        if isinstance(clicked, dict) and clicked["type"] == "contentgen-retry" and any(retry or []):
            receipt = func_contentgen_retry(clicked["key"], run_by)
            return "Retry queued.", no_update, no_update, receipt
    except (ApiClientError, ValueError) as exc:
        return str(exc), no_update, no_update, no_update
    raise PreventUpdate


@callback(
    Output("contentgen-selection", "data"),
    Input({"type": "contentgen-open", "key": ALL, "place": ALL}, "n_clicks"),
    Input("ui-store-env", "data"),
    prevent_initial_call=True,
)
def callback_contentgen_select(clicks, env):
    clicked = ctx.triggered_id
    if clicked == "ui-store-env":
        return None
    if not isinstance(clicked, dict) or not any(clicks or []):
        raise PreventUpdate
    return clicked["key"]


@callback(
    Output("contentgen-run-detail", "children"),
    Output("contentgen-run-detail", "hidden"),
    Output("contentgen-log-controls", "hidden"),
    Output("contentgen-log-step", "options"),
    Output("contentgen-log-step", "value"),
    Output("contentgen-view", "data"),
    Input("contentgen-selection", "data"),
    Input("contentgen-log-step", "value"),
    Input("ui-store-dashboard", "data"),
    State("contentgen-view", "data"),
)
def callback_contentgen_detail(run_id, step, state, view):
    if not run_id or not state:
        return [], True, True, [], None, None
    active = any(run["run_id"] == run_id and run["status"] == "running" for run in state["queue"])
    prior = view or {}
    if prior.get("run_id") != run_id:
        step = None
    elif ctx.triggered_id == "ui-store-dashboard" and not active and prior.get("status") not in {"running", "queued"}:
        raise PreventUpdate
    try:
        run, selected, log = func_ui_run_detail(run_id, step)
    except ApiClientError as exc:
        return layout_ui_notice(str(exc)), False, True, [], None, None
    options = [{"label": step_labels[row["step"]], "value": row["step"]} for row in run["steps"]]
    return (
        layout_contentgen_run_detail(run, selected, log, retry=True), False, False, options, selected,
        {"run_id": run_id, "status": run["status"]},
    )
