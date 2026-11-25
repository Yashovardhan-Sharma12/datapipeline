# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import dcc, html

from functions.functions_ui import func_ui_download_link, func_ui_duration, func_ui_time, status_labels
from layouts.layouts_ui_components import layout_ui_empty, layout_ui_heading, layout_ui_notice, layout_ui_panel_header, layout_ui_pill, layout_ui_table

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_queries():
    toolbar = html.Div([
        html.Div([
            dcc.Input(id="queries-search", type="search", placeholder="Find a query", className="search"),
            html.Div([
                html.Label("Source", htmlFor="queries-source"),
                dcc.Dropdown(id="queries-source", clearable=False, value="", options=[
                    {"label": "Customer and colleague", "value": ""},
                    {"label": "Customer", "value": "customer"}, {"label": "Colleague", "value": "colleague"},
                ]),
            ], className="field"),
            html.Div([
                html.Label("Last run", htmlFor="queries-result"),
                dcc.Dropdown(id="queries-result", clearable=False, value="", options=[
                    {"label": "Any result", "value": ""}, {"label": "Errors and warnings", "value": "issue"},
                    {"label": "Updated", "value": "complete"},
                ]),
            ], className="field"),
        ], className="left"),
        html.Div([
            html.Button("Run selected", id="queries-run", className="btn", disabled=True, type="button"),
            html.Button("Download selected", id="queries-download", className="btn", disabled=True, type="button"),
            html.A("Download all", id="queries-download-all", className="btn btn-primary", href="/desk-download/prod"),
        ], className="right"),
    ], className="toolbar")
    return html.Section([
        dcc.Store(id="queries-data"),
        dcc.Store(id="queries-selected", data=[]),
        dcc.Store(id="queries-drawer-selection"),
        dcc.Store(id="queries-drawer-detail"),
        dcc.Store(id="queries-editor-session"),
        dcc.Store(id="queries-test-result"),
        dcc.Store(id="queries-pull-result"),
        dcc.Store(id="queries-submitted"),
        dcc.Download(id="queries-zip"),
        layout_ui_heading(
            "Queries",
            "Every active query, what it produced in the last refresh, and its CSV. "
            "Open a query to read it, test a change, or propose a pull request.",
        ),
        html.Div(id="queries-message", role="status", className="inline-status"),
        html.Div(id="queries-error"),
        html.Div([
            html.Div([toolbar, html.Div(id="queries-table"), html.Div(id="queries-count", className="tfoot")], className="panel"),
            html.Div([
                html.Div([
                    html.Div([html.H3(id="queries-drawer-title", className="mono"), html.Div(id="queries-drawer-path", className="path")]),
                    html.Button("Close", id="queries-close", type="button", className="btn btn-sm"),
                ], className="phead"),
                dcc.Tabs(id="queries-drawer-tab", value="query", children=[
                    dcc.Tab(label="Query", value="query"), dcc.Tab(label="Last error", value="error"),
                    dcc.Tab(label="Changes", value="changes"),
                ]),
                html.Div(id="queries-drawer-sql", className="query-drawer-content"),
                html.Div([
                    html.Button("Edit query", id="queries-edit", type="button", className="btn"),
                ], id="queries-edit-controls", className="dfoot", hidden=True),
                layout_queries_editor(),
            ], className="drawer panel", **{"aria-label": "Query detail"}),
        ], id="queries-split", className="split"),
    ], className="screen")


def layout_queries_editor():
    return html.Div([
        html.Label("Edit query", htmlFor="queries-draft", className="screen-reader-only"),
        dcc.Textarea(id="queries-draft", className="editor", spellCheck=False),
        html.Div([
            html.Div([
                html.Button("Test query", id="queries-test", type="button", className="btn"),
                html.Button("Cancel", id="queries-cancel-edit", type="button", className="btn btn-quiet"),
            ], className="row"),
            html.P(id="queries-draft-busy", className="inline-status", role="status"),
            html.Div(id="queries-test-output", role="status"),
            html.Div([
                html.Label("What changed?", htmlFor="queries-pr-title"),
                dcc.Input(id="queries-pr-title", type="text", maxLength=200, placeholder="Pull request title"),
            ], className="field"),
            html.Div(html.Button("Open pull request", id="queries-save-pr", type="button", className="btn btn-primary",
                                 disabled=True), className="row"),
            html.P("Refreshes use main until the pull request is merged and the next Git pull runs.", className="muted small"),
            html.Div(id="queries-pr-output", role="status"),
        ], id="queries-draft-actions", className="dfoot"),
    ], id="queries-editor-panel", hidden=True)


def layout_queries_file(row, env):
    csv = row["csv"]
    if csv is None:
        return html.Span("Comparison only" if row["filename"].lower().startswith("validation_") else "—", className="muted")
    size = csv["size"]
    label = f"{size / 1_048_576:.1f} MB" if size >= 1_048_576 else f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
    return html.A(label, href=func_ui_download_link(env, csv["name"]), className="btn btn-sm",
                  title=f"Download {csv['name']} · {func_ui_time(csv['written_at'], '%d %b %H:%M')}",
                  **{"aria-label": f"Download {csv['name']}"})


def layout_queries_row(row, env, selected):
    # ----------------------------------------------------------------
    # 1. Read Last Result
    result = row["result"]
    status, kind = status_labels.get(row["status"], ("No result", "idle"))
    validation = result.get("validation") or {}
    comparison = result.get("comparison_summary") or {}
    if comparison.get("difference_rows", 0):
        status, kind = f"{comparison['difference_rows']} differences", "warn"
    week, week_class = {
        "ok": ("Present", "wk-ok"), "missing_data": ("Missing", "wk-miss"),
        "validation_skipped": ("No week column", "wk-na"),
    }.get(validation.get("status"), ("Not checked", "wk-na"))
    csv = row["csv"] or {}
    key = row["key"]

    # ----------------------------------------------------------------
    # 2. Build Table Row
    return html.Tr([
        html.Td(dcc.Checklist(
            id={"type": "queries-select", "key": key, "env": env},
            options=[{"label": html.Span(f"Select {row['filename']}", className="screen-reader-only"), "value": "selected"}],
            value=["selected"] if key in selected else [],
            className="select-cell",
        )),
        html.Td(html.Button(row["filename"], id={"type": "queries-open", "key": key}, type="button",
                            className="btn btn-quiet fname")),
        html.Td(row["source_label"]),
        html.Td(layout_ui_pill(status, kind), className="table-status"),
        html.Td(csv.get("rows") if csv.get("rows") is not None else "—", className="r"),
        html.Td(func_ui_duration(row["duration"]), className="r"),
        html.Td(html.Span(week, className=week_class)),
        html.Td(layout_queries_file(row, env), className="r"),
    ])


def layout_queries_table(rows, env, selected, scheduled_for):
    if not rows:
        return layout_ui_empty("No queries match these filters.")
    time = func_ui_time(scheduled_for, default=None)
    result = f"{time} result" if time else "Last result"
    all_rows = html.Button("All", id="queries-select-all", type="button", className="btn btn-sm btn-quiet",
                           title="Toggle selection for all visible queries")
    return layout_ui_table(
        (all_rows, "Query", "Source", result, "Rows", "Took", "Tesco week", "CSV"),
        [layout_queries_row(row, env, set(selected or [])) for row in rows],
    )


def layout_queries_drawer(row, tab, document, *, editing=False):
    result = row["result"]
    error = result.get("error_detail") or {}
    retained = result.get("fallback_output")
    if tab == "changes":
        return layout_queries_changes(document)
    if tab == "query":
        if editing:
            return None
        if "sql" not in document:
            return html.Div(layout_ui_notice(document["error"]) if document.get("error") else "Loading query…", className="pbody")
        lines = document["sql"].splitlines() or [""]
        return html.Div([
            html.Div([
                layout_ui_notice(error.get("message")) if error else None,
                dcc.Clipboard(content=document["sql"], title="Copy SQL", className="query-copy"),
            ], className="pbody row"),
            html.Pre([
                html.Span(line or " ", className="ln hl" if index == error.get("line_number") else "ln")
                for index, line in enumerate(lines, start=1)
            ], className="code"),
        ])
    if not error and not (result.get("error") or result.get("last_error")):
        return html.P("No error was recorded for the latest result.", className="muted pbody")
    fields = [
        ("Kind", (error.get("kind") or "error").replace("_", " ").title()),
        ("SQL Server", f"Error {error['sql_error_number']}" if error.get("sql_error_number") is not None else None),
        ("Line", error.get("line_number")),
        ("Message", error.get("message") or result.get("last_error") or result.get("error")),
        ("Output", f"Kept {retained['name']} from {func_ui_time(retained['written_at'], '%d %b %H:%M')}" if retained else None),
    ]
    return html.Div([
        html.Dl([component for label, value in fields if value is not None
                 for component in (html.Dt(label), html.Dd(value))], className="kv"),
        html.Ul([
            html.Li(f"Attempt {item['attempt']} · {func_ui_duration(item['duration_seconds'])} · "
                    f"{(item.get('error') or {}).get('message', 'Finished')}")
            for item in result.get("attempt_details", [])
        ]),
        html.Details([html.Summary("Full error"), html.Pre(error["raw_message"], className="err")], className="raw")
        if error.get("raw_message") else None,
    ], className="pbody")


def layout_queries_changes(document):
    if "sql" not in document:
        return html.Div(layout_ui_notice(document["error"]) if document.get("error") else "Loading changes…", className="pbody")
    pulls = [
        html.Li([
            html.B(f"#{pull['number']}"),
            html.Span("Open", className="pill p-run"),
            html.Div([html.A(pull["title"], href=pull["url"], target="_blank", rel="noopener"),
                      html.Div(pull["branch"], className="small muted mono")]),
        ]) for pull in document.get("pull_requests", [])
    ]
    commits = [
        html.Li([
            html.Span(func_ui_time(commit["at"], "%d %b"), className="t"),
            html.Span(commit["sha"][:7], className="mono muted"), html.Span(commit["message"]),
        ]) for commit in document.get("history", [])
    ]
    return html.Div([
        html.H4("Open pull requests"),
        layout_ui_notice(document.get("pull_requests_error"))
        if document.get("pull_requests_error") else html.P("Loading open pull requests…", className="muted")
        if not document.get("changes_loaded") else html.Ul(pulls, className="nextlist")
        if pulls else html.P("No open pull requests for this query.", className="muted"),
        html.H4("Git history"),
        layout_ui_notice(document.get("history_error")) if document.get("history_error") else html.Ul(commits, className="nextlist")
        if commits else html.P("No commits found for this file.", className="muted"),
    ], className="pbody stack")


def layout_queries_test_result(result):
    if not result:
        return None
    error = result.get("error") or {}
    if result["status"] == "error":
        line = f" · Line {error['line_number']}" if error.get("line_number") else ""
        return html.Div(f"{error.get('message', 'Test failed')}{line}", className="callout callout-bad")
    if result["status"] == "empty":
        return html.Div("Test finished and returned no rows. The transaction was rolled back.", className="callout callout-warn")
    rows = result["rows"]
    count = f"First {len(rows)} rows" if result.get("truncated") else f"{len(rows)} rows"
    return [
        html.Div(f"Test passed · {count} · {func_ui_duration(result.get('duration_seconds'))} · Transaction rolled back.",
                 className="callout callout-ok"),
        layout_ui_table(tuple(result["columns"]), [
            html.Tr([html.Td(value if value is not None else "—") for value in row]) for row in rows
        ]),
    ]


def layout_queries_pull_result(result):
    if not result:
        return None
    if result.get("status") == "error":
        return html.Div(result["message"], className="callout callout-bad")
    pull = result.get("pull_request")
    if pull:
        return html.Div([
            html.Span("Pull request opened."),
            html.A(f"View PR #{pull['number']}", href=pull["url"], target="_blank", rel="noopener", className="btn btn-sm"),
        ], className="callout callout-ok row")
    return html.Div([
        html.Span(result.get("message") or "Branch pushed."),
        html.A("Create pull request", href=result["create_url"], target="_blank", rel="noopener", className="btn btn-sm"),
    ], className="callout callout-info row")
