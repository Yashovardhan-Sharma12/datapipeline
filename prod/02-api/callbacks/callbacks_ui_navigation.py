# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from dash import Input, Output, State, callback, ctx, html, no_update

from functions.functions_ui import func_ui_attention, func_ui_dashboard, func_ui_time
from layouts.layouts_ui_navigation import layout_ui_navigation

# ----------------------------------------------------------------------------------------------------------------------
#%% Callbacks Definitions


@callback(
    Output("ui-store-env", "data"),
    Output("ui-env-prod", "aria-pressed"),
    Output("ui-env-dev", "aria-pressed"),
    Output("ui-dev-banner", "hidden"),
    Input("ui-env-prod", "n_clicks"),
    Input("ui-env-dev", "n_clicks"),
    prevent_initial_call=True,
)
def callback_ui_navigation_environment(prod_clicks, dev_clicks):
    env = "dev" if ctx.triggered_id == "ui-env-dev" else "prod"
    return env, str(env == "prod").lower(), str(env == "dev").lower(), env == "prod"


@callback(
    Output("ui-run-by", "value"),
    Output("ui-store-user-name", "data"),
    Input("ui-run-by", "value"),
    Input("ui-store-user-name", "modified_timestamp"),
    State("ui-store-user-name", "data"),
)
def callback_ui_navigation_name(name, modified, saved):
    if ctx.triggered_id != "ui-run-by":
        return saved or "", no_update
    value = (name or "").strip()
    return value, value if value != saved else no_update


@callback(
    Output("ui-store-dashboard", "data"),
    Output("ui-poll", "interval"),
    Input("ui-store-env", "data"),
    Input("ui-poll", "n_intervals"),
    Input("today-reload", "data", allow_optional=True),
    Input("contentgen-reload", "data", allow_optional=True),
    Input("schedules-reload", "data", allow_optional=True),
    Input("ui-store-query-run", "data"),
)
def callback_ui_navigation_poll(env, ticks, today_reload, contentgen_reload, schedules_reload, query_run):
    return func_ui_dashboard(env, query_run)


@callback(
    Output("ui-context-clock", "children"),
    Output("ui-navigation", "children"),
    Input("ui-location", "pathname"),
    Input("ui-store-dashboard", "data"),
    Input("ui-store-dismissed", "data"),
)
def callback_ui_navigation_context(pathname, state, dismissed):
    # ----------------------------------------------------------------
    # 1. Initialize
    if not state:
        return "", layout_ui_navigation(pathname or "/")
    history = state.get("history", [])
    week = ((history[0].get("quality") or {}).get("latest_year_week")) if history else None
    env = state["env"]
    upcoming = state["schedule"].get("next_runs", [])

    # ----------------------------------------------------------------
    # 2. Build Context
    clock = [html.B(func_ui_time(state["now"], "%a %d %b, %H:%M %Z"))]
    if week:
        clock.append(html.Span(f"Tesco week {week}"))
    if upcoming:
        clock.append(html.Span(f"Next {env} refresh {func_ui_time(upcoming[0]['scheduled_for'], '%a %H:%M')}"))
    elif "schedule" not in state["errors"]:
        clock.append(html.Span(f"{env.title()} has no schedule"))
    seen = set(dismissed or [])
    count = sum(item["id"] not in seen for item in func_ui_attention(state))

    # ----------------------------------------------------------------
    # 3. Return
    return clock, layout_ui_navigation(pathname or "/", count)
