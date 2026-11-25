# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
from urllib.parse import quote

from flask import Response, jsonify, request, send_file

from config import PIPELINE_API_URLS
from functions.functions_api_client import ApiClientError, func_api_client_iter_download, func_api_client_open
from functions.functions_filenames import func_filenames_is_direct
from functions.functions_output_files import (
    func_output_files_build_zip,
    func_output_files_get_csv,
    func_output_files_get_selection,
    func_output_files_list,
)

# ----------------------------------------------------------------------------------------------------------------------
#%% Routes


def route_downloads_output_files():
    return jsonify({"status": "ok", "files": func_output_files_list()})


def route_downloads_single_file(filename):
    try:
        path = func_output_files_get_csv(filename)
        return send_file(path, mimetype="text/csv", as_attachment=True, download_name=path.name)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except FileNotFoundError:
        return jsonify({"status": "error", "message": f"Output file not found: {filename}"}), 404


def route_downloads_archive():
    try:
        paths = None
        if request.method == "POST":
            data = request.get_json(silent=True)
            paths = func_output_files_get_selection(data.get("files") if isinstance(data, dict) else None)
        archive = func_output_files_build_zip(paths)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except FileNotFoundError as exc:
        message = str(exc) if exc.filename is None else f"Output file not found: {os.path.basename(exc.filename)}"
        return jsonify({"status": "error", "message": message}), 404

    if archive is None:
        return jsonify({
            "status": "error",
            "message": "No output files are currently available to download",
        }), 404

    zip_buffer, download_name = archive
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


def route_downloads_by_environment(env):
    if env not in PIPELINE_API_URLS:
        return jsonify({"status": "error", "message": "Unknown environment"}), 404
    filename = request.args.get("file")
    path = "/download-output"
    if filename is not None:
        if not func_filenames_is_direct(filename, ".csv"):
            return jsonify({"status": "error", "message": "Only direct .csv filenames are allowed"}), 400
        path += "/" + quote(filename, safe="")
    try:
        upstream = func_api_client_open(env, path, method=request.method, download=True)
    except ApiClientError as exc:
        return jsonify({"status": "error", "message": str(exc)}), exc.status
    response = Response(
        func_api_client_iter_download(upstream), status=upstream.status,
        headers={key: upstream.headers[key] for key in ("Content-Type", "Content-Disposition") if key in upstream.headers},
    )
    response.call_on_close(upstream.close)
    return response
