# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import re

from flask import Response, jsonify, request

from functions.functions_api_client import (
    ApiClientError,
    func_api_client_iter_download,
    func_api_client_open,
    func_api_client_run_contentgen,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Routes


def route_contentgen_run():
    data = request.get_json(silent=True) or {}
    include_diagnostics = bool(data.get("include_diagnostics", False))
    payload, status = func_api_client_run_contentgen(include_diagnostics)
    return jsonify(payload), status


def route_contentgen_proxy(path):
    run = r"runs/[0-9a-f-]{36}"
    read_path = path in {"health", "projects", "runs"} or re.fullmatch(
        rf"{run}(?:/log/(?:diagnostics|content_gen|upload))?", path,
    )
    write_path = path == "runs" or re.fullmatch(rf"{run}/stop", path)
    if (request.method in {"GET", "HEAD"} and not read_path) or (request.method == "POST" and not write_path):
        return jsonify({"status": "error", "message": "ContentGen endpoint not found"}), 404
    try:
        upstream = func_api_client_open(
            "runner", f"/{path}", method=request.method,
            params=request.args.to_dict(flat=False),
            payload=request.get_json(silent=True) if request.method == "POST" else None,
            download=request.args.get("full") == "1",
        )
    except ApiClientError as exc:
        return jsonify({"status": "error", "message": str(exc)}), exc.status
    response = Response(
        func_api_client_iter_download(upstream), status=upstream.status,
        headers={key: upstream.headers[key] for key in ("Content-Type", "Content-Disposition") if key in upstream.headers},
    )
    response.call_on_close(upstream.close)
    return response
