# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import threading
from contextlib import closing

import pandas as pd

from config import MISSING_DATA_REPORT_FILE

# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
missing_data_report_lock = threading.Lock()

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_validation_get_current_week(customer_conn):
    """Query lookup_Calendar to get Tesco's current year_week_number where relative_week = 0."""
    try:
        with closing(customer_conn.engine.raw_connection()) as raw_conn, closing(raw_conn.cursor()) as cursor:
            cursor.execute("""
                SELECT TOP 1 year_week_number
                FROM [MIUsers].[Cockpit].[lookup_Calendar]
                WHERE relative_week = 0
                ORDER BY [date] DESC
            """)
            row = cursor.fetchone()
            return func_validation_normalize_year_week(row[0]) if row else None
    except Exception as e:
        print(f"Error fetching Tesco current week: {e}")
        return None


def func_validation_clear_missing_report():
    with missing_data_report_lock:
        MISSING_DATA_REPORT_FILE.unlink(missing_ok=True)


def func_validation_normalize_year_week(value):
    """Normalise year-week values such as 202634, 202634.0 and '202634' to one key."""
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        numeric_value = float(text.replace(",", ""))
        if numeric_value.is_integer():
            return str(int(numeric_value))
    except (TypeError, ValueError):
        pass

    return text[:-2] if text.endswith(".0") else text


def func_validation_check_actual_week(df, sql_filename, actual_week_number):
    """Check DataFrame against the Tesco week already fetched for this job."""
    if df is None or 'year_week_number' not in df.columns:
        return {"status": "validation_skipped", "message": "No year_week_number column found"}

    if not actual_week_number:
        return {"status": "error", "message": "Unable to get Tesco current week"}

    dataframe_weeks = {
        normalized_week
        for normalized_week in (
            func_validation_normalize_year_week(value)
            for value in df['year_week_number']
        )
        if normalized_week
    }

    if actual_week_number not in dataframe_weeks:
        warn_msg = f" Missing data for Tesco actual week ({actual_week_number}) in {sql_filename}"
        print(warn_msg)

        with missing_data_report_lock:
            with MISSING_DATA_REPORT_FILE.open("a", encoding="utf-8") as rpt:
                rpt.write(f"{sql_filename},{actual_week_number},MISSING\n")

        return {"status": "missing_data", "week": actual_week_number}

    print(f"Data for Tesco current week ({actual_week_number}) found in {sql_filename}")
    return {"status": "ok", "week": actual_week_number}


def func_validation_get_market(sql_filename):
    """
    Return the market code for validation SQL files.

    Examples:
        validation_uk.sql  -> UK
        validation_roi.sql -> ROI
        validation_tmi.sql -> TMI
        validation_ce.sql  -> CE

    Any future file following validation_<market>.sql is picked up automatically.
    """
    filename = os.path.basename(sql_filename).lower()

    if not (
        filename.startswith("validation_")
        and filename.endswith(".sql")
    ):
        return None

    market = filename[len("validation_"):-len(".sql")].strip()

    return market.upper() if market else None


def func_validation_build_comparison(df, only_differences=False):
    # ----------------------------------------------------------------
    # 1. Identify Metrics
    if df is None or df.empty:
        return {
            "status": "no_data",
            "message": "Validation query returned no rows"
        }

    comparison_df = df.copy()
    metric_pairs = []

    for column in comparison_df.columns:
        if column.startswith("cec_"):
            metric_name = column[len("cec_"):]
            cockpit_column = f"cockpit_{metric_name}"
            if cockpit_column in comparison_df.columns:
                metric_pairs.append((metric_name, column, cockpit_column))

    if not metric_pairs:
        return {
            "status": "error",
            "message": "No matching cec_/cockpit_ metric pairs found"
        }

    # ----------------------------------------------------------------
    # 2. Compare Metrics
    difference_columns = []

    for metric_name, cec_column, cockpit_column in metric_pairs:
        comparison_df[cec_column] = pd.to_numeric(comparison_df[cec_column], errors="coerce").fillna(0)
        comparison_df[cockpit_column] = pd.to_numeric(comparison_df[cockpit_column], errors="coerce").fillna(0)

        difference_column = f"{metric_name}_difference"
        comparison_df[difference_column] = comparison_df[cec_column] - comparison_df[cockpit_column]
        difference_columns.append(difference_column)

    comparison_df["difference_count"] = comparison_df[difference_columns].ne(0).sum(axis=1)
    comparison_df["match_status"] = comparison_df["difference_count"].apply(
        lambda x: "MATCH" if x == 0 else "DIFFERENCE"
    )

    if only_differences:
        comparison_df = comparison_df[comparison_df["difference_count"] > 0].copy()

    metric_summary = {}
    for metric_name, cec_column, cockpit_column in metric_pairs:
        difference_column = f"{metric_name}_difference"
        metric_summary[metric_name] = {
            "cec_total": float(comparison_df[cec_column].sum()) if not comparison_df.empty else 0,
            "cockpit_total": float(comparison_df[cockpit_column].sum()) if not comparison_df.empty else 0,
            "difference_total": float(comparison_df[difference_column].sum()) if not comparison_df.empty else 0,
            "difference_rows": int((comparison_df[difference_column] != 0).sum()) if not comparison_df.empty else 0
        }

    summary = {
        "total_rows": int(len(comparison_df)),
        "difference_rows": int((comparison_df["difference_count"] > 0).sum()) if not comparison_df.empty else 0,
        "matched_rows": int((comparison_df["difference_count"] == 0).sum()) if not comparison_df.empty else 0,
        "metrics_compared": [metric_name for metric_name, _, _ in metric_pairs],
        "metric_summary": metric_summary
    }

    # ----------------------------------------------------------------
    # 3. Return
    return {
        "status": "success",
        "comparison_summary": summary,
        "comparison_data": comparison_df.to_dict(orient="records")
    }
