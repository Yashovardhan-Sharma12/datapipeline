# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import ALL, Input, Output, State, callback, ctx, no_update
from dash.exceptions import PreventUpdate

from config import TIMEZONE
from functions.functions_api_client import ApiClientError
from functions.functions_schedules import func_schedules_edit_projects, func_schedules_edit_slot, func_schedules_new_slot
from functions.functions_ui import func_ui_time
from layouts.layouts_schedules import layout_schedules_next, layout_schedules_times
from layouts.layouts_ui_components import layout_ui_notice

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("schedules-title", "children"),
    Output("schedules-times", "children"),
    Output("schedules-next", "children"),
    Output("schedules-last-change", "children"),
    Output("schedules-error", "children"),
    Input("ui-store-dashboard", "data"),
    Input("schedules-editor", "data"),
)
def callback_schedules_view(state, editor):
    if not state:
        raise PreventUpdate
    env = state["env"]
    schedule = state["schedule"]
    latest = schedule.get("last_change") or schedule.get("last_project_change")
    change = f"Last change by {latest['run_by']} · {func_ui_time(latest['at'], '%d %b %H:%M')}" if latest else ""
    zone = "IST" if TIMEZONE.key == "Asia/Kolkata" else TIMEZONE.key
    active = editor["slot"]["id"] if editor and editor["env"] == env else None
    return (
        f"{env.title()} refresh times ({zone})",
        layout_schedules_times(schedule.get("schedules", []), env, active),
        layout_schedules_next(schedule), change, layout_ui_notice(state["errors"].get("schedule")),
    )


@callback(
    Output("schedules-projects", "options"),
    Output("schedules-projects", "value"),
    Output("schedules-project-version", "data"),
    Input("ui-store-dashboard", "data"),
    State("schedules-project-version", "data"),
)
def callback_schedules_projects(state, version):
    if not state or "revision" not in state["schedule"]:
        raise PreventUpdate
    current = state["schedule"]["projects"]
    choices = list(dict.fromkeys(current + [project["project"] for project in state["projects"] if project["runnable"]]))
    new_version = {"env": state["env"], "revision": state["schedule"]["revision"]}
    return [{"label": project, "value": project} for project in choices], current if version != new_version else no_update, new_version


@callback(
    Output("schedules-editor", "data"),
    Input({"type": "schedules-slot", "key": ALL}, "n_clicks"),
    Input({"type": "schedules-add", "days": ALL}, "n_clicks"),
    Input("schedules-cancel", "n_clicks"),
    Input("ui-store-env", "data"),
    State("ui-store-dashboard", "data"),
    prevent_initial_call=True,
)
def callback_schedules_open(slots, additions, cancel, env, state):
    clicked = ctx.triggered_id
    if clicked in ("schedules-cancel", "ui-store-env"):
        return None
    if not isinstance(clicked, dict) or not state or state["env"] != env or "revision" not in state["schedule"]:
        raise PreventUpdate
    if clicked["type"] == "schedules-add" and any(additions or []):
        slot = func_schedules_new_slot(clicked["days"])
        is_new = True
    elif clicked["type"] == "schedules-slot" and any(slots or []):
        slot = next((slot for slot in state["schedule"]["schedules"] if slot["id"] == clicked["key"]), None)
        is_new = False
    else:
        raise PreventUpdate
    if slot is None:
        raise PreventUpdate
    return {"slot": slot, "env": env, "revision": state["schedule"]["revision"], "new": is_new}


@callback(
    Output("schedules-editor-fields", "hidden"),
    Output("schedules-editor-hint", "hidden"),
    Output("schedules-days", "value"),
    Output("schedules-time", "value"),
    Output("schedules-flags", "value"),
    Output("schedules-remove", "hidden"),
    Input("schedules-editor", "data"),
)
def callback_schedules_form(editor):
    if not editor:
        return True, False, None, "", [], True
    slot = editor["slot"]
    flags = [key for key in ("run_contentgen", "include_diagnostics", "paused") if slot[key]]
    return False, True, slot["days"], slot["time"], flags, editor["new"]


@callback(
    Output("schedules-message", "children"),
    Output("schedules-reload", "data"),
    Output("schedules-editor", "data", allow_duplicate=True),
    Input("schedules-save", "n_clicks"),
    Input("schedules-remove", "n_clicks"),
    Input("schedules-projects-save", "n_clicks"),
    State("schedules-editor", "data"),
    State("schedules-days", "value"),
    State("schedules-time", "value"),
    State("schedules-flags", "value"),
    State("schedules-projects", "value"),
    State("schedules-project-version", "data"),
    State("ui-store-dashboard", "data"),
    State("ui-store-env", "data"),
    State("ui-store-user-name", "data"),
    prevent_initial_call=True,
    running=[
        (Output("schedules-save", "disabled"), True, False),
        (Output("schedules-remove", "disabled"), True, False),
        (Output("schedules-projects-save", "disabled"), True, False),
    ],
)
def callback_schedules_save(save, remove, project_save, editor, days, at, flags, projects, version, state, env, run_by):
    # ----------------------------------------------------------------
    # 0. Identify Trigger
    clicked = ctx.triggered_id
    if not state or state["env"] != env:
        raise PreventUpdate

    # ----------------------------------------------------------------
    # 1. Apply Changes
    try:
        if clicked == "schedules-projects-save" and version and version["env"] == env:
            result = func_schedules_edit_projects(env, projects, version["revision"], run_by)
            return "Scheduled projects saved.", result, no_update
        if clicked not in {"schedules-save", "schedules-remove"} or not editor or editor["env"] != env:
            raise PreventUpdate
        deleting = clicked == "schedules-remove"
        result = func_schedules_edit_slot(
            env, state["schedule"]["schedules"], editor, run_by, days=days, at=at, flags=flags, remove=deleting,
        )
        return "Schedule time removed." if deleting else "Schedule saved.", result, None
    except ApiClientError as exc:
        return str(exc), no_update, no_update
