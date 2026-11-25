# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, html

from functions.functions_ui import (
    func_ui_duration,
    func_ui_failed_run_step,
    func_ui_run_label,
    func_ui_seconds,
    func_ui_time,
    status_labels,
    step_colours,
    step_labels,
)
from layouts.layouts_ui_components import (
    layout_ui_empty,
    layout_ui_env,
    layout_ui_heading,
    layout_ui_panel,
    layout_ui_panel_header,
    layout_ui_pill,
    layout_ui_table,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_contentgen():
    return html.Section([
        dcc.Store(id="contentgen-selection"),
        dcc.Store(id="contentgen-view"),
        dcc.Store(id="contentgen-reload"),
        layout_ui_heading(
            "ContentGen",
            "Run diagnostics, content generation and database upload for one or more projects. "
            "Dev and prod share one queue. Prod runs go first.",
        ),
        html.Div(id="contentgen-error"),
        layout_ui_panel("Queue", "One run at a time. Progress comes from each step's log.",
                        html.Div(id="contentgen-queue", className="queue")),
        html.Div([
            html.Div([
                layout_ui_panel_header(html.Span(id="contentgen-project-title"),
                                       html.Span(id="contentgen-project-subtitle"),
                                       html.Span("None selected", id="contentgen-selection-count", className="small muted")),
                dcc.Checklist(id="contentgen-projects", options=[], value=[], className="project-options"),
            ], className="panel"),
            html.Div([
                html.Div([
                    html.H4("Steps to run"),
                    dcc.Checklist(
                        id="contentgen-steps", className="checklist",
                        options=[{"label": step_labels[step], "value": step} for step in ("diagnostics", "content_gen", "upload")],
                        value=["content_gen", "upload"],
                    ),
                    html.P("Diagnostics are skipped for projects that don't have it. Upload follows successful content generation.",
                           className="small muted"),
                ], className="bstep"),
                html.Div([
                    html.H4("Data to use"),
                    dcc.RadioItems(id="contentgen-data", value="latest", className="checklist"),
                ], className="bstep"),
                html.Div([
                    html.H4("Check and queue"),
                    html.Div(id="contentgen-review", className="review"),
                    html.Div(html.Button("Queue runs", id="contentgen-queue-button", type="button",
                                         className="btn btn-primary", disabled=True), className="row"),
                    html.P("Each run records the name you set once in this browser.", className="small muted"),
                    html.Div(id="contentgen-message", className="inline-status", role="status"),
                ], className="bstep"),
            ], className="panel"),
        ], className="cg-grid"),
        html.Div([
            layout_ui_panel_header("Recent runs", html.Span(id="contentgen-recent-subtitle")),
            html.Div(id="contentgen-recent"),
            html.Div([
                html.Label("Log step", htmlFor="contentgen-log-step", className="input-label"),
                dcc.Dropdown(id="contentgen-log-step", clearable=False),
            ], id="contentgen-log-controls", className="pbody", hidden=True),
            html.Div(id="contentgen-run-detail", className="detail", hidden=True),
        ], className="panel", id="contentgen-recent-runs"),
    ], className="screen")


def layout_contentgen_status(run):
    status = run["status"]
    label, kind = status_labels.get(status, (status.title(), "idle"))
    if status == "failed":
        step = func_ui_failed_run_step(run)
        if step:
            label = f"Failed at {step_labels[step['step']].lower()}"
    return layout_ui_pill(label, kind)


def layout_contentgen_project_options(projects, scheduled):
    options = []
    for project in projects:
        label = project["project"]
        last = project.get("last_run")
        disabled = not project["runnable"] or not project["enabled"]
        targets = ", then ".join(project.get("upload_targets", []))
        names = ", ".join(step_labels[step] for step in project["steps"])
        info = project["reason"] or names
        if project["runnable"] and not project["enabled"]:
            info += " · Prod runs open after the dev pilot"
        options.append({
            "value": label,
            "disabled": disabled,
            "label": html.Span([
                html.Span([
                    label,
                    layout_ui_pill("New", "new") if project["new"] and label not in scheduled else None,
                    html.Small("On the schedule", className="muted") if label in scheduled else None,
                ], className="proj-name"),
                layout_ui_pill("Can't run") if not project["runnable"]
                else layout_contentgen_status(last) if last else layout_ui_pill("Never run"),
                html.Span([
                    html.Span([
                        html.Span([html.I(className=f"s-{step_colours[step]}") for step in project["steps"]],
                                  className="stepchips"), info,
                    ]),
                    html.Span(f"Uploads to {targets}") if targets else None,
                ], className="proj-sub"),
            ], className="proj project-choice" + (" off" if disabled else "")),
        })
    return options


def layout_contentgen_queue(queue):
    if not queue:
        return layout_ui_empty("The queue is empty.")
    waiting = 0
    has_prod = any(run["env"] == "prod" and run["status"] == "queued" for run in queue)
    items = []
    for run in queue:
        active = run["status"] == "running"
        waiting += not active
        step = next((step for step in run["steps"] if step["status"] == "running"), {})
        progress = run.get("progress") if active else None
        label = step_labels.get(step.get("step"), "Syncing inputs") if active else status_labels[run["status"]][0]
        if run.get("stop_requested"):
            label = "Stopping"
        elif run["env"] == "dev" and run["status"] == "queued" and has_prod:
            label = "Waiting for prod runs"
        note = ", then ".join(step_labels[step["step"]] for step in run["steps"])
        if progress:
            note += f" · Content process {progress['current']} of {progress['total']}"
        items.append(html.Div([
            html.Span("" if active else waiting, className="pos"),
            html.Span([run["project"], layout_ui_env(run["env"])], className="proj-name"),
            layout_ui_pill(label, "run" if active else "idle"),
            html.Span(f"{note} · {func_ui_run_label(run)} · {run['run_by']}", className="qsub"),
            html.Div(html.Span(style={"width": f"{100 * progress['current'] / progress['total']}%"}),
                     className="prog") if progress else None,
            html.Div([
                html.Button("Live log", type="button", className="btn btn-sm",
                            id={"type": "contentgen-open", "key": run["run_id"], "place": "queue"}) if active else None,
                html.Button("Stop" if active else "Remove from queue",
                            id={"type": "contentgen-stop", "key": run["run_id"]},
                            disabled=run.get("stop_requested"), type="button", className="btn btn-sm btn-quiet"),
            ], className="row queue-actions"),
        ], className="qitem running" if active else "qitem"))
    return items


def layout_contentgen_review(review):
    total = sum(row["seconds"] for row in review) if all(row["seconds"] is not None for row in review) else None
    return [
        html.Ol([
            html.Li([
                html.Span(row["item"]["project"], className="mono"), " ", layout_ui_env(row["item"]["env"]),
                " · " + ", then ".join(step_labels[step] for step in row["item"]["steps"]),
                f" · About {func_ui_duration(row['seconds'])}" if row["seconds"] is not None else " · No estimate yet",
                html.Small(" · No diagnostics step", className="muted") if row["no_diagnostics"] else None,
            ]) for row in review
        ]),
        html.P("Prod runs go ahead of waiting dev runs." if review[0]["item"]["env"] == "prod"
               else "Dev runs start once no prod run is waiting."),
        html.P(f"About {func_ui_duration(total)} in all, based on the last five runs.", className="small muted")
        if total is not None else None,
    ]


def layout_contentgen_recent(runs):
    if not runs:
        return layout_ui_empty("No ContentGen runs recorded in this environment.")
    rows = [
        html.Tr([
            html.Td(html.Span(run["project"], className="proj-name")),
            html.Td(func_ui_time(run["started_at"] or run["queued_at"], "%d %b %H:%M"), className="num"),
            html.Td(func_ui_run_label(run)),
            html.Td(", ".join(step_labels[step["step"]] for step in run["steps"])),
            html.Td(html.Button(
                layout_contentgen_status(run), type="button", className="btn btn-quiet btn-sm",
                id={"type": "contentgen-open", "key": run["run_id"], "place": "recent"},
            )),
            html.Td(func_ui_duration(func_ui_seconds(run)), className="r"),
        ]) for run in runs
    ]
    return layout_ui_table(("Project", "Started", "Trigger", "Steps", "Result", "Took"), rows)


def layout_contentgen_run_detail(run, selected, log, *, retry=False):
    lines = log.get("lines") or []
    step_list = html.Ul([
        html.Li([
            html.Span(className=f"sw s-{step_colours[step['step']]}" + (" s-fail" if step["status"] == "failed" else "")),
            html.Span(f"{step_labels[step['step']]} · {status_labels.get(step['status'], (step['status'],))[0]}"
                      + (f" (exit code {step['exit_code']})" if step["exit_code"] is not None else "")),
            html.Span(f"{func_ui_time(step['started_at'])} to {func_ui_time(step['completed_at'])}", className="t"),
        ]) for step in run["steps"]
    ], className="steps")
    failed = func_ui_failed_run_step(run)
    retry_label = "Run upload only" if failed and failed["step"] == "upload" and any(
        step["step"] == "content_gen" and step["status"] == "success" for step in run["steps"]
    ) else "Run again"
    return [
        html.Div([
            html.Div([html.H4(run["project"]), layout_ui_env(run["env"]), layout_contentgen_status(run)], className="row"),
            html.P(f"{func_ui_run_label(run)} · {run['run_by']}", className="small muted"),
            step_list,
            html.P(run["error"], className="small muted") if run.get("error") else None,
            html.Div([
                html.Button(retry_label, id={"type": "contentgen-retry", "key": run["run_id"]},
                            className="btn btn-sm", type="button") if retry and run["status"] == "failed" else None,
                html.A("Full log", href=f"/contentgen/runs/{run['run_id']}/log/{selected}?full=1",
                       className="btn btn-sm btn-quiet") if selected and lines else None,
            ], className="row"),
        ], className="stack"),
        html.Div([
            html.H4("Last lines of the log"),
            html.Pre("\n".join(lines), className="err") if lines else html.P("No log lines are available yet.", className="muted"),
        ]),
    ]
