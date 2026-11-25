# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, html

from functions.functions_ui import func_ui_time, status_labels, step_labels
from layouts.layouts_ui_components import layout_ui_empty, layout_ui_heading, layout_ui_pill

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_history():
    return html.Section([
        dcc.Store(id="history-pages"),
        dcc.Store(id="history-selection"),
        dcc.Store(id="history-detail"),
        layout_ui_heading("Run history", "One line per refresh, with what ContentGen did afterwards. Open a line for the details.",
                          dcc.Checklist(id="history-problems", options=[{"label": "Problems only", "value": "issues"}],
                                        value=[], className="checklist")),
        html.Div(id="history-error"),
        html.Div([
            html.Div(id="history-rows"),
            html.Div([
                html.Span(id="history-count"),
                html.Button("Show 20 more", id="history-more", type="button", className="btn btn-sm", disabled=True),
            ], className="tfoot"),
        ], className="panel"),
    ], className="screen")


def layout_history_contentgen(row):
    contentgen = row.get("contentgen") or {}
    runs = row["linked_runs"]
    if not runs:
        label = "Queries only" if contentgen.get("status") == "not_scheduled" else "No ContentGen"
        return html.Span(label, className="muted small")
    dots = {"success": "ok", "failed": "red", "running": "blue"}
    return html.Div([
        html.Span([
            html.I(style={"background": f"var(--{dots.get(run['status'], 'idle')})"}),
            run.get("project", "ContentGen"),
        ], title=status_labels.get(run["status"], (run["status"],))[0])
        for run in runs
    ], className="cgdots")


def layout_history_rows(rows, selected, detail):
    if not rows:
        return layout_ui_empty("No refreshes match this view.")
    children = []
    last_day = None
    for row in rows:
        started = row.get("scheduled_for") or row.get("started_at")
        day = func_ui_time(started, "%A %d %b", default="Unknown date")
        if day != last_day:
            children.append(html.Div(day, className="hday"))
            last_day = day

        key = row["job_id"]
        expanded = key == selected
        status, tone = status_labels.get(row["status"], ("Unknown", "idle"))
        if row["status"] == "success":
            status = "OK"
            if row.get("empty_queries") or (row.get("quality") or {}).get("missing_latest_week"):
                status, tone = "Warning", "warn"
        children.append(html.Button([
            html.Span(func_ui_time(started), className="t"),
            html.Span(f"{row['completed_queries']} updated · {row['failed_query_count']} failed"
                      + (f" · {row['empty_queries']} empty" if row.get("empty_queries") else "")),
            html.Div(layout_history_contentgen(row), className="hide-sm"),
            html.Span(layout_ui_pill(status, tone), className="hide-sm"),
            html.Span("›", className="chev"),
        ], id={"type": "history-row", "key": key}, className="hrow", type="button",
            **{"aria-expanded": str(expanded).lower()}))
        if expanded:
            children.append(html.Div(
                layout_history_detail(row, detail) if detail and detail.get("job_id") == key
                else "Loading refresh details…", className="hdetail",
            ))
    return children


def layout_history_detail(row, detail):
    quality = detail.get("quality") or {}
    results = detail.get("results") or []
    warnings = [result for result in results if result["status"] in {"failed", "empty"}
                or (result.get("validation") or {}).get("status") == "missing_data"]
    runs = row["linked_runs"]
    handoff = row.get("contentgen") or {}
    children = [
        html.P(f"Started {func_ui_time(detail.get('started_at'))} · Finished {func_ui_time(detail.get('completed_at'))}"),
        html.P(f"Tesco week {quality['latest_year_week']} · {quality.get('missing_latest_week', 0)} queries missing it")
        if quality.get("latest_year_week") else None,
    ]
    if detail.get("error"):
        children.append(html.P(detail["error"], className="callout callout-bad"))
    if warnings:
        children.append(html.Ul([
            html.Li([
                html.Code(query["filename"]), " · ",
                (query.get("error_detail") or {}).get("message")
                or query.get("last_error") or query.get("message") or "Latest Tesco week missing",
                f" · Kept {query['fallback_output']['name']}" if query.get("fallback_output") else "",
            ]) for query in warnings
        ]))
    if runs:
        children.append(html.Ul([
            html.Li([html.Code(run.get("project", "ContentGen")), " · ",
                     status_labels.get(run["status"], (run["status"],))[0],
                     " · " + ", ".join(step_labels[step["step"]] for step in run.get("steps", []))
                     if run.get("steps") else ""])
            for run in runs
        ]))
    if handoff.get("reason"):
        children.append(html.P(handoff["reason"], className="muted"))
    if handoff.get("rejected"):
        children.append(html.Ul([html.Li(f"{item['project']} · {item['reason']}") for item in handoff["rejected"]]))
    if runs:
        children.append(dcc.Link("Open ContentGen", href="/contentgen", className="btn btn-sm"))
    return children
