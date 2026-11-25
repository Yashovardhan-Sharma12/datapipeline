# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import json
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode

from config import (
    API_DOWNLOAD_CHUNK_BYTES,
    API_DOWNLOAD_TIMEOUT_SECONDS,
    API_TIMEOUT_SECONDS,
    CONTENTGEN_API_URL,
    CONTENTGEN_TIMEOUT_SECONDS,
    PIPELINE_API_URLS,
    RUNNER_URL,
)
from functions.functions_console import print_banner, print_detail, print_status

# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


class ApiClientError(RuntimeError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def func_api_client_open(service, path, *, method="GET", payload=None, params=None, download=False, timeout=None):
    base = RUNNER_URL if service == "runner" else PIPELINE_API_URLS[service]
    url = base + path
    if params:
        url += "?" + urlencode(params, doseq=True)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/octet-stream" if download else "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    outbound = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        return urllib_request.urlopen(
            outbound, timeout=timeout or (API_DOWNLOAD_TIMEOUT_SECONDS if download else API_TIMEOUT_SECONDS),
        )
    except urllib_error.HTTPError as exc:
        with exc:
            try:
                error = json.load(exc)
                message = error.get("message") if isinstance(error, dict) else None
            except (ValueError, OSError):
                message = None
        raise ApiClientError(message or f"{service} returned HTTP {exc.code}", exc.code) from exc
    except (OSError, urllib_error.URLError) as exc:
        target = "ContentGen runner" if service == "runner" else f"{service.upper()} pipeline"
        raise ApiClientError(f"{target} is unavailable") from exc


def func_api_client_json(service, path, **options):
    try:
        with func_api_client_open(service, path, **options) as response:
            result = json.load(response)
    except (ValueError, OSError) as exc:
        raise ApiClientError(f"{service} returned an unreadable response", 502) from exc
    if not isinstance(result, dict):
        raise ApiClientError(f"{service} returned an unexpected response", 502)
    return result


def func_api_client_submit_runs(payload):
    return func_api_client_json("runner", "/runs", method="POST", payload=payload)


def func_api_client_run_contentgen(include_diagnostics):
    """Forward a manual workflow request to the ContentGen scheduler service."""
    # ----------------------------------------------------------------
    # 1. Build Request
    workflow_name = (
        "Diagnostics + ContentGen + Database Upload"
        if include_diagnostics
        else "ContentGen + Database Upload"
    )

    print_banner("MANUAL CONTENTGEN REQUEST")
    print_detail("Workflow", workflow_name)
    print_detail("Target", CONTENTGEN_API_URL)

    payload = {
        "include_diagnostics": include_diagnostics,
        "trigger_source": "datapipeline_ui"
    }

    target_url = f"{CONTENTGEN_API_URL}/run-workflow"

    # ----------------------------------------------------------------
    # 2. Send Request
    try:
        upstream_request = urllib_request.Request(
            target_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib_request.urlopen(
            upstream_request,
            timeout=CONTENTGEN_TIMEOUT_SECONDS
        ) as upstream_response:
            response_body = upstream_response.read().decode("utf-8")
            response_status = upstream_response.getcode()

        try:
            response_data = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            response_data = {"message": response_body or "ContentGen workflow accepted"}

        print_status("ACCEPTED", workflow_name)

        return {
            "status": response_data.get("status", "accepted"),
            "message": response_data.get(
                "message",
                f"{workflow_name} workflow accepted"
            ),
            "contentgen_job_id": response_data.get("job_id")
        }, response_status

    except urllib_error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
            error_data = json.loads(error_body) if error_body else {}
        except Exception:
            error_data = {}

        message = error_data.get(
            "message",
            f"ContentGen service returned HTTP {exc.code}"
        )

        print_status("FAILED", message)

        return {
            "status": "error",
            "message": message
        }, exc.code

    except urllib_error.URLError:
        message = (
            "ContentGen service is not available yet. "
            "The UI integration is ready; add the /run-workflow endpoint "
            "to 4-process-workflow-scheduler.py and start that service."
        )

        print_status("WAITING", message)

        return {
            "status": "not_configured",
            "message": message
        }, 503

    except Exception as exc:
        print_status("FAILED", str(exc))

        return {
            "status": "error",
            "message": str(exc)
        }, 500


def func_api_client_iter_download(response):
    with response:
        while chunk := response.read(API_DOWNLOAD_CHUNK_BYTES):
            yield chunk
