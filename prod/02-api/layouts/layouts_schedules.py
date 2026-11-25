# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, html

from functions.functions_schedules import schedule_groups
from functions.functions_ui import func_ui_time
from layouts.layouts_ui_components import layout_ui_heading, layout_ui_panel, layout_ui_panel_header

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_schedules_editor():
    return html.Div([
        html.P("Select a time to change it, or add a new one.", id="schedules-editor-hint", className="muted"),
        html.Div([
            html.Div([
                html.Label("Days", htmlFor="schedules-days"),
                dcc.Dropdown(
                    id="schedules-days", clearable=False,
                    options=[{"label": name, "value": value} for value, name in schedule_groups.items()],
                ),
            ], className="field"),
            html.Div([
                html.Label("Time (24-hour)", htmlFor="schedules-time"),
                dcc.Input(id="schedules-time", type="text", placeholder="HH:MM", maxLength=5, className="rd-input"),
            ], className="field"),
            dcc.Checklist(
                id="schedules-flags", className="checklist",
                options=[
                    {"label": "Run ContentGen after the queries", "value": "run_contentgen"},
                    {"label": "Include diagnostics", "value": "include_diagnostics"},
                    {"label": "Paused", "value": "paused"},
                ],
            ),
            html.Div([
                html.Button("Save time", id="schedules-save", type="button", className="btn btn-primary"),
                html.Button("Cancel", id="schedules-cancel", type="button", className="btn"),
                html.Button("Remove time", id="schedules-remove", type="button", className="btn btn-quiet"),
            ], className="row"),
        ], id="schedules-editor-fields", className="editor-panel", hidden=True),
        html.P(id="schedules-message", className="inline-status", role="status"),
    ], className="pbody editor-panel")


def layout_schedules():
    return html.Section([
        dcc.Store(id="schedules-editor"),
        dcc.Store(id="schedules-project-version"),
        dcc.Store(id="schedules-reload"),
        layout_ui_heading(
            "Schedules",
            "Each refresh time runs the queries, then ContentGen for the projects listed below. Changes apply from the next run.",
        ),
        html.Div(id="schedules-error"),
        html.Div([
            html.Div([
                html.Div([
                    layout_ui_panel_header(html.Span(id="schedules-title"), "A blue underline means diagnostics run too."),
                    html.Div(id="schedules-times"),
                ], className="panel"),
                layout_ui_panel(
                    "Projects that follow this schedule",
                    "Other projects still run when you queue them from ContentGen.",
                    html.Div([
                        html.Label("Scheduled projects", htmlFor="schedules-projects", className="input-label"),
                        dcc.Dropdown(id="schedules-projects", multi=True, placeholder="Choose projects"),
                        html.Div(html.Button("Save projects", id="schedules-projects-save", type="button", className="btn"),
                                 className="row"),
                    ], className="pbody editor-panel"),
                ),
            ], className="stack"),
            html.Div([
                layout_ui_panel("Change a time", None, layout_schedules_editor()),
                layout_ui_panel("Next runs", None, html.Ul(id="schedules-next", className="nextlist pbody")),
                html.P(id="schedules-last-change", className="small muted"),
            ], className="stack"),
        ], className="sched-grid"),
    ], className="screen")


def layout_schedules_slot(slot, active):
    status = "Paused" if slot["paused"] else "Queries + ContentGen" if slot["run_contentgen"] else "Queries only"
    style = ("tchip" + (" diag" if slot["include_diagnostics"] else "")
             + (" qonly" if not slot["run_contentgen"] else "") + (" paused" if slot["paused"] else ""))
    return html.Button(
        [html.B(slot["time"]), html.Small(status)], id={"type": "schedules-slot", "key": slot["id"]},
        className=style, type="button", **{"aria-pressed": str(active == slot["id"]).lower()},
    )


def layout_schedules_times(slots, env, active):
    groups = []
    for group, label in schedule_groups.items():
        rows = [layout_schedules_slot(slot, active) for slot in slots if slot["days"] == group]
        if rows or group == "daily":
            rows.append(html.Button(
                "Add a time", id={"type": "schedules-add", "days": group},
                type="button", className="tchip add",
            ))
            groups.append(html.Div([html.B(label), html.Div(rows, className="chips")], className="dayrow"))
    if not slots:
        message = "Dev has no schedule." if env == "dev" else "No refresh times are configured."
        groups.insert(0, html.P(message, className="pbody muted"))
    return groups


def layout_schedules_next(schedule):
    projects = ", ".join(schedule.get("projects", []))
    return [
        html.Li([
            html.Span(func_ui_time(slot["scheduled_for"], "%a %d %b")),
            html.B(func_ui_time(slot["scheduled_for"]), className="t"),
            html.Span(f"Queries, then {projects}" if schedule.get("runner_enabled") and projects and slot["run_contentgen"]
                      else "Queries" if schedule.get("runner_enabled") or not slot["run_contentgen"] else "Queries · Runner disabled"),
        ]) for slot in schedule.get("next_runs", [])
    ] or [html.Li(html.Span("No runs scheduled.", className="muted"))]
