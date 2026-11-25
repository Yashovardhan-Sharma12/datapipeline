# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages

from dash import html, page_container
from flask import render_template

from app import dash_app, flask_app as app, func_app_shutdown_scheduler, scheduler
from config import DATAPIPELINE_HOST, DATAPIPELINE_PORT, ENV_NAME
from functions.functions_refresh import func_refresh_last_success_text, func_refresh_migrate_history
from functions.functions_schedules import func_schedules_start
from functions.functions_sql_execution import (
    func_sql_get_legacy_query_options,
    func_sql_initialize_output,
)
from layouts.layouts_ui_header import layout_ui_header, layout_ui_header_context
from layouts.layouts_ui_navigation import layout_ui_navigation
from layouts.layouts_ui_store import layout_ui_store
from routes.routes_contentgen import route_contentgen_proxy, route_contentgen_run
from routes.routes_downloads import (
    route_downloads_archive,
    route_downloads_by_environment,
    route_downloads_output_files,
    route_downloads_single_file,
)
from routes.routes_queries import (
    route_queries_catalog,
    route_queries_pull_request,
    route_queries_read,
    route_queries_run_sql,
    route_queries_test,
)
from routes.routes_refresh import route_refresh_detail, route_refresh_history, route_refresh_status
from routes.routes_schedules import route_schedules_add_project, route_schedules_list, route_schedules_update

# ----------------------------------------------------------------------------------------------------------------------
#%% Base Layout

if dash_app is not None:
    import callbacks.callbacks_ui_navigation

    dash_app.layout = html.Div([
        *layout_ui_store(),
        layout_ui_header(),
        html.Nav(layout_ui_navigation(), id="ui-navigation", className="tabnav", **{"aria-label": "Refresh Desk sections"}),
        html.Main([layout_ui_header_context(), page_container], className="main"),
        html.Footer(html.Span("Refresh Desk | CCEC"), className="footer"),
    ])

# ----------------------------------------------------------------------------------------------------------------------
#%% Routes


def route_ui_home():
    query_options, query_count = func_sql_get_legacy_query_options()
    return render_template(
        "data_pipeline.html",
        query_options=query_options,
        query_count=query_count,
        last_refresh=func_refresh_last_success_text(),
        environment_name=ENV_NAME,
        api_port=DATAPIPELINE_PORT,
    )


func_sql_initialize_output()
func_refresh_migrate_history()

app.add_url_rule("/legacy", "home", route_ui_home, methods=["GET"])
if dash_app is None:
    app.add_url_rule("/", "legacy_home", route_ui_home, methods=["GET"])
app.add_url_rule("/query-catalog", "query_catalog_endpoint", route_queries_catalog, methods=["GET"])
app.add_url_rule("/queries/<source>/<filename>", view_func=route_queries_read, methods=["GET"])
app.add_url_rule("/queries/test", view_func=route_queries_test, methods=["POST"])
app.add_url_rule("/queries/pull-request", view_func=route_queries_pull_request, methods=["POST"])
app.add_url_rule("/output-files", view_func=route_downloads_output_files, methods=["GET"])
app.add_url_rule("/download-output", "download_output", route_downloads_archive, methods=["GET", "POST"])
app.add_url_rule("/download-output/<filename>", view_func=route_downloads_single_file, methods=["GET"])
app.add_url_rule("/desk-download/<env>", view_func=route_downloads_by_environment, methods=["GET"])
app.add_url_rule("/run-contentgen", "run_contentgen_endpoint", route_contentgen_run, methods=["POST"])
app.add_url_rule("/contentgen/<path:path>", view_func=route_contentgen_proxy, methods=["GET", "POST"])
app.add_url_rule("/refresh-history", "refresh_history_endpoint", route_refresh_history, methods=["GET"])
app.add_url_rule("/refresh-history/<job_id>", view_func=route_refresh_detail, methods=["GET"])
app.add_url_rule("/run-sql", "run_sql_endpoint", route_queries_run_sql, methods=["POST"])
app.add_url_rule("/status/<job_id>", "get_status", route_refresh_status, methods=["GET"])
app.add_url_rule("/api/schedules", view_func=route_schedules_list, methods=["GET"])
app.add_url_rule("/api/schedules", view_func=route_schedules_update, methods=["PUT"])
app.add_url_rule("/api/schedules/projects", view_func=route_schedules_add_project, methods=["POST"])

# ----------------------------------------------------------------------------------------------------------------------
#%% Main Execution


def func_main_run():
    func_schedules_start(scheduler)

    try:
        app.run(
            host=DATAPIPELINE_HOST,
            port=DATAPIPELINE_PORT,
            debug=False,
            use_reloader=False,
        )
    finally:
        func_app_shutdown_scheduler()


if __name__ == "__main__":
    func_main_run()
