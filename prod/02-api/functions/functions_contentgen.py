# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from urllib.parse import quote

from functions.functions_api_client import func_api_client_json
from functions.functions_ui import func_ui_failed_run_step, func_ui_submit_items

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_contentgen_review(state, projects, steps, use_data):
    env = state["env"]
    if not projects:
        raise ValueError("Select one or more projects.")
    if not steps:
        raise ValueError("Pick at least one step.")
    if "upload" in steps and "content_gen" not in steps:
        raise ValueError("Database upload needs content generation. Untick upload to run diagnostics alone.")
    if use_data == "next_refresh" and (
        not state["schedule"].get("next_runs") or not state["schedule"].get("runner_enabled")
    ):
        raise ValueError(f"No {env} refresh is available for ContentGen.")

    records = {record["project"]: record for record in state["projects"] if record["runnable"] and record["enabled"]}
    review = []
    for name in projects:
        record = records.get(name)
        if record is None:
            raise ValueError(f"{name} is unavailable for {env} runs.")
        selected = [step for step in record["steps"] if step in steps]
        if not selected:
            raise ValueError(f"None of the selected steps are available for {name}.")
        if "upload" in selected and "content_gen" not in selected:
            raise ValueError(f"Content generation is unavailable for {name}.")
        estimates = record["estimates"]
        review.append({
            "item": {"env": env, "project": name, "steps": selected},
            "seconds": sum(estimates[step] for step in selected) if all(step in estimates for step in selected) else None,
            "no_diagnostics": "diagnostics" in steps and "diagnostics" not in selected,
        })
    return review


def func_contentgen_retry(run_id, run_by):
    key = quote(run_id, safe="")
    run = func_api_client_json("runner", f"/runs/{key}")["run"]
    failed = func_ui_failed_run_step(run)
    steps = [step["step"] for step in run["steps"]]
    if failed and failed["step"] == "upload" and any(
        step["step"] == "content_gen" and step["status"] == "success" for step in run["steps"]
    ):
        steps = ["upload"]
    items = [{"env": run["env"], "project": run["project"], "steps": steps}]
    return func_ui_submit_items(items, run_by, trigger="retry", retry_run_id=run_id)
