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
from functions.functions_git import func_git_query_hash
from functions.functions_queries import (
    func_queries_data,
    func_queries_draft_passed,
    func_queries_filter,
    func_queries_load_drawer,
    func_queries_preview_draft,
    func_queries_run,
    func_queries_select,
    func_queries_submit_draft,
)
from functions.functions_ui import func_ui_download_link, func_ui_download_selected
from layouts.layouts_queries import (
    layout_queries_drawer,
    layout_queries_pull_result,
    layout_queries_table,
    layout_queries_test_result,
)
from layouts.layouts_ui_components import layout_ui_notice

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("queries-data", "data"),
    Input("ui-store-dashboard", "data"),
    State("queries-data", "data"),
)
def callback_queries_load(state, previous):
    if not state:
        raise PreventUpdate
    return func_queries_data(state, previous)


@callback(
    Output("queries-table", "children"),
    Output("queries-count", "children"),
    Output("queries-error", "children"),
    Output("queries-download-all", "href"),
    Input("queries-data", "data"),
    Input("queries-search", "value"),
    Input("queries-source", "value"),
    Input("queries-result", "value"),
    State("queries-selected", "data"),
)
def callback_queries_table(data, term, source, result, selected):
    if not data:
        raise PreventUpdate
    rows = func_queries_filter(data["rows"], term, source, result)
    return (
        layout_queries_table(rows, data["env"], selected, data["scheduled_for"]),
        f"{len(rows)} of {len(data['rows'])} queries · CSV sizes are from 03-output.",
        layout_ui_notice(data["errors"]), func_ui_download_link(data["env"]),
    )


@callback(
    Output({"type": "queries-select", "key": ALL, "env": ALL}, "value"),
    Input("queries-select-all", "n_clicks", allow_optional=True),
    State({"type": "queries-select", "key": ALL, "env": ALL}, "value"),
    prevent_initial_call=True,
)
def callback_queries_select_all(clicks, values):
    if not clicks or not values:
        raise PreventUpdate
    return [[] if all(values) else ["selected"] for _ in values]


@callback(
    Output("queries-selected", "data"),
    Input({"type": "queries-select", "key": ALL, "env": ALL}, "value"),
    Input("ui-store-env", "data"),
    State({"type": "queries-select", "key": ALL, "env": ALL}, "id"),
    State("queries-selected", "data"),
)
def callback_queries_selection(values, env, identifiers, selected):
    if ctx.triggered_id == "ui-store-env":
        return []
    visible = {item["key"]: value for item, value in zip(identifiers, values) if item["env"] == env}
    kept = [key for key in selected or [] if key not in visible or visible[key]]
    return list(dict.fromkeys(kept + [key for key, value in visible.items() if value]))


@callback(
    Output("queries-run", "disabled"),
    Output("queries-download", "disabled"),
    Input("queries-selected", "data"),
    Input("queries-data", "data"),
    Input("ui-store-dashboard", "data"),
)
def callback_queries_controls(selected, data, state):
    rows = func_queries_select(data, selected)
    active = (state or {}).get("manual_job", {}).get("status") == "running"
    return not rows or active, not any(row["csv"] for row in rows)


@callback(
    Output("queries-message", "children"),
    Output("queries-zip", "data"),
    Output("queries-submitted", "data"),
    Input("queries-run", "n_clicks"),
    Input("queries-download", "n_clicks"),
    State("queries-selected", "data"),
    State("queries-data", "data"),
    State("ui-store-env", "data"),
    State("ui-store-user-name", "data"),
    prevent_initial_call=True,
)
def callback_queries_action(run, download, selected, data, env, run_by):
    clicked = ctx.triggered_id
    if not data or data["env"] != env:
        raise PreventUpdate
    rows = func_queries_select(data, selected)
    if not rows:
        raise PreventUpdate
    try:
        if clicked == "queries-run" and run:
            job = func_queries_run(env, rows, run_by)
            return f"Started {job['query_count']} selected queries.", no_update, {"env": env, "job_id": job["job_id"]}
        if clicked == "queries-download" and download:
            filenames = list(dict.fromkeys(row["csv"]["name"] for row in rows if row["csv"]))
            if filenames:
                return "", func_ui_download_selected(env, filenames), no_update
    except ApiClientError as exc:
        return str(exc), no_update, no_update
    raise PreventUpdate


@callback(
    Output("ui-store-query-run", "data"),
    Input("queries-submitted", "data", allow_optional=True),
    prevent_initial_call=True,
)
def callback_queries_record_job(job):
    return job or no_update


@callback(
    Output("queries-drawer-selection", "data"),
    Output("queries-drawer-tab", "value"),
    Input({"type": "queries-open", "key": ALL}, "n_clicks"),
    Input("queries-close", "n_clicks"),
    Input("ui-store-env", "data"),
    prevent_initial_call=True,
)
def callback_queries_open_drawer(clicks, close, env):
    clicked = ctx.triggered_id
    if clicked in ("queries-close", "ui-store-env"):
        return None, "query"
    if not isinstance(clicked, dict) or not any(clicks or []):
        raise PreventUpdate
    return clicked["key"], "query"


@callback(
    Output("queries-drawer-detail", "data"),
    Input("queries-drawer-selection", "data"),
    Input("queries-drawer-tab", "value"),
    Input("ui-store-env", "data"),
    State("queries-data", "data"),
    State("queries-drawer-detail", "data"),
)
def callback_queries_load_drawer(key, tab, env, data, document):
    rows = func_queries_select(data, [key])
    if not rows or data["env"] != env:
        return None
    same = document and document.get("key") == key and document.get("env") == env
    if same and "sql" in document and tab != "changes":
        raise PreventUpdate
    try:
        query = func_queries_load_drawer(env, rows[0], changes=tab == "changes")
    except ApiClientError as exc:
        query = {"error": str(exc)}
    return {**query, "key": key, "env": env, "changes_loaded": tab == "changes"}


@callback(
    Output("queries-split", "className"),
    Output("queries-drawer-title", "children"),
    Output("queries-drawer-path", "children"),
    Output("queries-drawer-sql", "children"),
    Output("queries-edit-controls", "hidden"),
    Output("queries-editor-panel", "hidden"),
    Input("queries-drawer-selection", "data"),
    Input("queries-drawer-tab", "value"),
    Input("queries-data", "data"),
    Input("queries-drawer-detail", "data"),
    Input("queries-editor-session", "data"),
)
def callback_queries_drawer(key, tab, data, document, editor):
    rows = func_queries_select(data, [key])
    if not rows:
        return "split", "", "", "", True, True
    row = rows[0]
    current = {"key": key, "env": data["env"]}
    document = document if document and all(document.get(k) == v for k, v in current.items()) else {}
    editing = bool(editor and all(editor.get(k) == v for k, v in current.items()) and tab == "query")
    can_edit = "sql" in document and tab == "query" and not editing
    return (
        "split open", row["filename"], f"{row['source_label']} · {row['filename']}",
        layout_queries_drawer(row, tab, document, editing=editing), not can_edit, not editing,
    )


@callback(
    Output("queries-editor-session", "data"),
    Output("queries-draft", "value"),
    Output("queries-pr-title", "value"),
    Input("queries-edit", "n_clicks"),
    Input("queries-cancel-edit", "n_clicks"),
    Input("queries-drawer-selection", "data"),
    Input("ui-store-env", "data"),
    State("queries-drawer-detail", "data"),
    prevent_initial_call=True,
)
def callback_queries_edit(edit, cancel, key, env, document):
    clicked = ctx.triggered_id
    if clicked in ("queries-cancel-edit", "queries-drawer-selection", "ui-store-env"):
        return None, "", ""
    if not edit or not document or "sql" not in document or document["key"] != key or document["env"] != env:
        raise PreventUpdate
    return {"key": key, "env": env, "base_hash": document["base_hash"]}, document["sql"], ""


@callback(
    Output("queries-test-result", "data"),
    Output("queries-pull-result", "data"),
    Input("queries-test", "n_clicks"),
    Input("queries-save-pr", "n_clicks"),
    Input("queries-editor-session", "data"),
    State("queries-draft", "value"),
    State("queries-pr-title", "value"),
    State("queries-drawer-detail", "data"),
    State("queries-data", "data"),
    State("queries-test-result", "data"),
    State("ui-store-user-name", "data"),
    prevent_initial_call=True,
    running=[
        (Output("queries-draft-busy", "children"), "Working…", ""),
        (Output("queries-test", "disabled"), True, False),
        (Output("queries-draft-actions", "className"), "dfoot query-busy", "dfoot"),
    ],
)
def callback_queries_draft_action(tested, submitted, editor, sql, title, document, data, test, run_by):
    # ----------------------------------------------------------------
    # 0. Identify Trigger
    clicked = ctx.triggered_id
    if clicked == "queries-editor-session":
        return None, None
    if not editor or not document or not data or document.get("key") != editor["key"] or data["env"] != editor["env"]:
        raise PreventUpdate
    rows = func_queries_select(data, [editor["key"]])
    if not rows:
        raise PreventUpdate

    # ----------------------------------------------------------------
    # 1. Run A Preview Or Create A Pull Request
    try:
        if clicked == "queries-test" and tested:
            if not isinstance(sql, str) or not sql.strip():
                raise ValueError("Enter SQL for this query.")
            result = func_queries_preview_draft(editor["env"], rows[0], sql)
            return {"editor": editor, "draft_hash": func_git_query_hash(sql), "result": result}, no_update
        if clicked == "queries-save-pr" and submitted:
            if not func_queries_draft_passed(sql, editor, test):
                raise ValueError("Run a passing test for this draft first.")
            result = func_queries_submit_draft(editor["env"], rows[0], sql, title, run_by, editor["base_hash"])
            return no_update, {**result, "editor": editor, "draft_hash": func_git_query_hash(sql)}
    except (ApiClientError, ValueError) as exc:
        if clicked == "queries-test":
            result = {"status": "error", "error": {"message": str(exc)}}
            return {"editor": editor, "draft_hash": func_git_query_hash(sql or ""), "result": result}, no_update
        return no_update, {"status": "error", "message": str(exc), "editor": editor}
    raise PreventUpdate


@callback(
    Output("queries-test-output", "children"),
    Output("queries-pr-output", "children"),
    Output("queries-save-pr", "disabled"),
    Input("queries-test-result", "data"),
    Input("queries-pull-result", "data"),
    Input("queries-draft", "value"),
    Input("queries-pr-title", "value"),
    Input("ui-store-user-name", "data"),
    Input("queries-editor-session", "data"),
    State("queries-drawer-detail", "data"),
)
def callback_queries_draft_feedback(test, proposal, sql, title, run_by, editor, document):
    if not editor or not document:
        return None, None, True
    draft_hash = func_git_query_hash(sql or "")
    same_test = test and test.get("editor") == editor
    if same_test and test["draft_hash"] != draft_hash:
        preview = layout_ui_notice("The draft changed. Test it again before opening a pull request.")
    else:
        preview = layout_queries_test_result(test["result"]) if same_test else None
    same_proposal = proposal and proposal.get("editor") == editor
    submitted = same_proposal and proposal.get("draft_hash") == draft_hash
    pull = layout_queries_pull_result(proposal) if same_proposal else None
    ready = (
        func_queries_draft_passed(sql, editor, test) and title and title.strip() and run_by and run_by.strip()
        and draft_hash != editor["base_hash"] and not submitted
    )
    return preview, pull, not ready
