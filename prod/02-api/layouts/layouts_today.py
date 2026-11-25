# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from datetime import timedelta

from dash import dcc, html

from functions.functions_today import func_today_position
from functions.functions_ui import func_ui_seconds, func_ui_time, func_ui_timestamp, status_labels, step_colours, step_labels
from layouts.layouts_ui_components import layout_ui_empty, layout_ui_panel_header, layout_ui_pill

# ----------------------------------------------------------------------------------------------------------------------
#%% Layouts


def layout_today():
    legend = html.Div([
        html.Span([html.I(className=f"s-{step_colours[step]}"), name])
        for step, name in step_labels.items()
    ] + [html.Span([html.I(className="s-fail"), "Failed step"])], className="legend")
    return html.Section([
        dcc.Store(id="today-run-selection"),
        dcc.Store(id="today-run-view"),
        dcc.Store(id="today-reload"),
        html.Div(id="today-status", className="statusline"),
        html.Div(id="today-kpis", className="kpis"),
        html.Div([
            layout_ui_panel_header(
                html.Span(id="today-lane-heading"),
                "Each bar is one run. Select a bar to see its steps.",
                legend,
            ),
            html.Div(html.Div(id="today-lanes", className="lanes"), className="lanes-scroll"),
            html.Div(id="today-lane-detail", className="detail", hidden=True),
        ], className="panel"),
        html.Div([
            layout_ui_panel_header("Needs attention", "Dismiss an item once it's handled. It stays in run history."),
            html.Div(id="today-attention"),
        ], className="panel"),
        html.Div(id="today-message", role="status", className="inline-status"),
    ], className="screen")


def layout_today_summary(state):
    history, active = state.get("history", []), state.get("active", [])
    latest = history[0] if history else {}
    quality = latest.get("quality") or {}
    ranks = [
        ("Last refresh", func_ui_time(latest.get("scheduled_for")), "Queries started on schedule" if latest else "No refresh recorded", ""),
        ("Queries updated", latest.get("completed_queries", 0), f"{latest.get('failed_query_count', 0)} failed", " k-bad" if latest.get("failed_query_count") else ""),
        ("Latest Tesco week", quality.get("latest_year_week") or "—", f"{quality.get('latest_week_present') or 0} queries with data", ""),
        ("ContentGen", "Running" if any(run["status"] == "running" for run in state.get("runs", [])) else "Idle",
         f"{sum(run['status'] == 'queued' for run in state.get('queue', []))} waiting across both environments", ""),
    ]
    if active:
        headline = f"{state['env'].title()} queries are refreshing."
        subtitle = f"{active[0]['finalised_queries']} of {active[0]['total_queries']} queries finalised."
    elif latest.get("status") == "completed_with_failures":
        headline = "The latest refresh finished with some query errors."
        subtitle = "Review the failed queries and the outputs retained for ContentGen."
    elif latest:
        headline = "The latest refresh has finished."
        subtitle = "Select a run in the chart to see its steps and results."
    else:
        headline = f"No {state['env']} refresh has been recorded yet."
        subtitle = "Query refreshes and ContentGen runs appear here as they start."
    cards = [
        html.Div([html.Span(label, className="l"), html.B(value, className="v"),
                  html.Span(foot, className="f")], className=f"kpi{kind}")
        for label, value, foot, kind in ranks
    ]
    return [html.H2(headline), html.P(subtitle, className="sub")], cards


def layout_today_attention(items):
    if not items:
        return layout_ui_empty("Nothing needs attention in this environment.")
    return [
        html.Div([
            html.Div(className=f"stripe stripe-{item['kind']}"),
            html.Div([
                html.Div([layout_ui_pill(item["label"], item["kind"]), html.B(item["title"], className="mono")],
                         className="attn-title"),
                html.Div(item.get("meta"), className="attn-meta") if item.get("meta") else None,
                html.P(item["message"], className="attn-plain"),
                html.Div([
                    html.Button("Add to prod schedule", id={"type": "today-add-project", "key": item["project"]},
                                className="btn btn-primary btn-sm", type="button")
                    if "project" in item else dcc.Link("View details", href=item["href"], className="btn btn-sm"),
                    dcc.Link("Run it now", href="/contentgen", className="btn btn-sm") if "project" in item else None,
                    html.Button("Not now" if "project" in item else "Dismiss", id={"type": "today-dismiss", "key": item["id"]},
                                className="btn btn-sm btn-quiet", type="button"),
                ], className="row"),
            ], className="attn-main"),
        ], className="attn-item")
        for item in items
    ]


def layout_today_lane_events(events, start, end, now, selected):
    # ----------------------------------------------------------------
    # 1. Render Timeline Bars
    children = []
    for event in events:
        left = func_today_position(event["start"], start, end)
        width = max(0.4, func_today_position(event["end"], start, end) - left)
        segments = []
        for step in event["steps"]:
            if not step.get("started_at"):
                continue
            name = step["step"]
            status = step["status"]
            timed = func_ui_seconds(step, now)
            decoration = " s-fail" if status == "failed" else " s-run" if status == "running" else ""
            segments.append(html.Span(className=f"s s-{step_colours[name]}{decoration}",
                                      style={"flex": max(1, timed or 0)}, title=step_labels[name]))
        if not segments:
            segments.append(html.Span(className="s s-gen s-run", style={"flex": 1}, title="Syncing inputs"))
        if event["status"] in {"failed", "completed_with_failures"}:
            flag = "bad" if event["status"] == "failed" else "warn"
            segments.append(html.Span(className=f"flag flag-{flag}"))
        key = event["id"]
        record = event["record"]
        label = record.get("project", "Queries")
        children.append(html.Button(
            segments, id={"type": "today-lane-run", "key": key, "kind": event["kind"]},
            type="button", title=f"{label} · {event['start']:%H:%M}", className="bar",
            style={"left": f"{left}%", "width": f"{width}%", "top": 12 + event["level"] * 29},
            **{"aria-pressed": "true" if selected and selected["key"] == key else "false",
               "aria-label": f"{label}, {event['start']:%H:%M}, {event['status']}"},
        ))
    return children


def layout_today_timeline(timeline, selected):
    # ----------------------------------------------------------------
    # 1. Build Axis
    lanes, start, end, now, next_refresh = timeline
    total_hours = int((end - start).total_seconds() / 3600)
    ticks = [(start + timedelta(hours=hour), f"{100 * hour / total_hours}%") for hour in range(total_hours + 1)]
    now_position = f"{func_today_position(now, start, end)}%" if start <= now <= end else None
    axis = [html.Span(at.strftime("%H:%M"), style={"left": position}) for at, position in ticks]
    if now_position:
        axis.append(html.B("Now", className="nowtag", style={"left": now_position}))
    items = [html.Div(), html.Div(axis, className="axis")]

    # ----------------------------------------------------------------
    # 2. Build Tracks
    for project, events in lanes.items():
        children = [html.I(className="hour", style={"left": position}) for _, position in ticks]
        if now_position:
            children.append(html.I(className="nowline", style={"left": now_position}))
        children.extend(layout_today_lane_events(events, start, end, now, selected))
        if project is None and next_refresh:
            next_at = func_ui_timestamp(next_refresh["scheduled_for"])
            pos = func_today_position(next_at, start, end)
            children.extend([
                html.I(className="ghost", style={"left": f"{pos}%", "width": f"{min(100 - pos, 7)}%"}),
                html.Small(f"{next_at:%H:%M} scheduled", className="ghost-label", style={"left": f"{pos}%"}),
            ])
        levels = max((event["level"] for event in events), default=0)
        items.extend([
            html.Div([html.B(project or "queries"), html.Small(f"{len(events)} run{'s' if len(events) != 1 else ''} today")],
                     className="lane-label"),
            html.Div(children, className="track", style={"height": 46 + levels * 29}),
        ])
    return items


def layout_today_refresh_detail(run, summary, *, manual=False):
    status, kind = status_labels.get(summary.get("status"), ("Running", "run"))
    results = run.get("results") or []
    failed = [item for item in results if item["status"] == "failed"]
    heading = html.Div([
        html.H4("Queries, run by hand" if manual else f"Queries, {func_ui_time(summary.get('scheduled_for'))} refresh"),
        html.Span(run["run_by"], className="muted small") if manual and run.get("run_by") else None,
        layout_ui_pill(status, kind),
    ], className="row")
    progress = html.P(
        f"{summary.get('finalised_queries', 0)} of {summary.get('total_queries', 0)} queries finalised."
    )
    sources = []
    for label in ("Customer", "Colleague"):
        rows = [item for item in results if item.get("source_label") == label]
        if rows:
            sources.append(html.Li(
                f"{label}: {sum(item['status'] == 'complete' for item in rows)} updated, "
                f"{sum(item['status'] == 'failed' for item in rows)} failed"
            ))
    return [
        html.Div([heading, progress, html.Ul(sources)]),
        html.Div([
            html.H4("Failed queries"),
            html.Ul([html.Li(f"{item['filename']} · {item.get('last_error') or item.get('reason', '')}") for item in failed])
            if failed else html.P("No query failures recorded.", className="muted"),
            dcc.Link("Run history", href="/history", className="btn btn-sm"),
        ]),
    ]


def layout_today_run_detail(run, step, log):
    from layouts.layouts_contentgen import layout_contentgen_run_detail

    return layout_contentgen_run_detail(run, step, log)
