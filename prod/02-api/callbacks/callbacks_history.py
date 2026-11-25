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
from functions.functions_history import (
    func_history_detail,
    func_history_is_problem,
    func_history_link_runs,
    func_history_load_older,
    func_history_merge,
)
from layouts.layouts_history import layout_history_rows
from layouts.layouts_ui_components import layout_ui_notice

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("history-detail", "data"),
    Input("history-selection", "data"),
    State("history-pages", "data"),
)
def callback_history_detail(selected, pages):
    if not selected or not pages:
        return None
    try:
        return func_history_detail(pages["env"], selected)
    except ApiClientError as exc:
        return {"job_id": selected, "error": str(exc)}


@callback(
    Output("history-pages", "data"),
    Output("history-error", "children"),
    Input("ui-store-dashboard", "data"),
    Input("history-more", "n_clicks"),
    State("history-pages", "data"),
)
def callback_history_pages(state, more, previous):
    # ----------------------------------------------------------------
    # 0. Identify Trigger
    if not state:
        raise PreventUpdate
    env = state["env"]
    previous = previous if previous and previous["env"] == env else {}
    selected = ctx.triggered_id == "history-more" and more

    # ----------------------------------------------------------------
    # 1. Load History Page
    if selected and previous.get("next_before"):
        try:
            rows, cursor, runs = func_history_load_older(env, previous["next_before"])
        except ApiClientError as exc:
            return no_update, layout_ui_notice(str(exc))
        return {**previous, "paged": True, "rows": func_history_merge(previous["rows"], rows, "job_id"),
                "next_before": cursor, "runs": func_history_merge(previous["runs"], runs, "run_id")}, None

    # ----------------------------------------------------------------
    # 2. Merge Poll Updates
    paged = previous.get("paged", False)
    rows = func_history_merge(state["history"], previous.get("rows", []) if paged else [], "job_id")
    runs = func_history_merge(state["runs"] + state["queue"], previous.get("runs", []) if paged else [], "run_id")
    errors = [state["errors"][key] for key in ("history", "contentgen") if key in state["errors"]]
    return {
        "env": env, "paged": paged, "rows": rows, "runs": runs,
        "next_before": previous["next_before"] if paged else state["next_before"],
    }, layout_ui_notice(list(dict.fromkeys(errors)))


@callback(
    Output("history-selection", "data"),
    Input({"type": "history-row", "key": ALL}, "n_clicks"),
    Input("ui-store-env", "data"),
    State("history-selection", "data"),
    prevent_initial_call=True,
)
def callback_history_select(clicks, env, selected):
    clicked = ctx.triggered_id
    if clicked == "ui-store-env":
        return None
    if not isinstance(clicked, dict) or not any(clicks or []):
        raise PreventUpdate
    return None if selected == clicked["key"] else clicked["key"]


@callback(
    Output("history-rows", "children"),
    Output("history-count", "children"),
    Output("history-more", "disabled"),
    Input("history-pages", "data"),
    Input("history-problems", "value"),
    Input("history-selection", "data"),
    Input("history-detail", "data"),
)
def callback_history_render(pages, problems, selected, detail):
    if not pages:
        raise PreventUpdate
    rows = func_history_link_runs(pages["rows"], pages["runs"])
    if problems:
        rows = [row for row in rows if func_history_is_problem(row)]
    return layout_history_rows(rows, selected, detail), f"{len(rows)} refreshes shown", not pages["next_before"]
