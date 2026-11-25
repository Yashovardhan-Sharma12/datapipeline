# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import base64
import hashlib
import json
import re
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlencode, urlsplit

from config import (
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_COMMAND_TIMEOUT_SECONDS,
    GIT_REPO_PATH,
    GITHUB_API_URL,
    GITHUB_TIMEOUT_SECONDS,
    GITHUB_TOKEN_ENV_NAME,
    GITHUB_WEB_URL,
    QUERY_HISTORY_LIMIT,
    TIMEZONE,
)
from functions.functions_console import print_banner, print_detail, print_status
from functions.functions_sql_execution import jobs, jobs_lock

# ----------------------------------------------------------------------------------------------------------------------
#%% Exceptions


class GitQueryError(RuntimeError):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------------------------------------------------------------
#%% Functions


def func_git_pull():
    """Safely fast-forward the datapipeline repository every hour."""
    # ----------------------------------------------------------------
    # 1. Acquire Pull Lock
    if not git_pull_lock.acquire(blocking=False):
        print_status("GIT", "Git pull already running. Skipping this cycle.")
        return

    # ----------------------------------------------------------------
    # 2. Pull Repository
    try:
        with jobs_lock:
            pipeline_busy = any(
                job.get("status") in {"running", "retrying"}
                for job in jobs.values()
            )

        if pipeline_busy:
            print_status("GIT", "Query execution is active. Git pull skipped.")
            return

        print_banner("GIT PULL - START")
        print_detail("Repository", git_repo_path)

        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(git_repo_path),
            capture_output=True,
            text=True,
            check=True,
        )

        if status_result.stdout.strip():
            print_status("SKIPPED", "Tracked local changes detected. Git pull skipped.")
            print(status_result.stdout.rstrip())
            return

        pull_result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(git_repo_path),
            capture_output=True,
            text=True,
            check=True,
        )

        if pull_result.stdout.strip():
            print(pull_result.stdout.rstrip())

        print_status("SUCCESS", "Git pull completed successfully.")

    except subprocess.CalledProcessError as exc:
        print_status("FAILED", f"Git pull failed with exit code {exc.returncode}")
        if exc.stdout:
            print(exc.stdout.rstrip())
        if exc.stderr:
            print(exc.stderr.rstrip())
    except Exception as exc:
        print_status("FAILED", f"Git pull failed: {exc}")
    finally:
        # ----------------------------------------------------------------
        # 3. Release Pull Lock
        git_pull_lock.release()
        print_banner("GIT PULL - COMPLETE")


def func_git_run(args, cwd, *, token=None):
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": str(index + 1),
            f"GIT_CONFIG_KEY_{index}": f"http.{GITHUB_WEB_URL}/.extraHeader",
            f"GIT_CONFIG_VALUE_{index}": f"Authorization: Basic {basic}",
        })
    operation = next((arg for arg in args if arg in {"fetch", "worktree", "commit", "push", "log", "remote", "add"}), "command")
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd), env=env, capture_output=True, check=True,
            text=True, encoding="utf-8", errors="replace", timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        ).stdout
    except subprocess.TimeoutExpired as exc:
        raise GitQueryError(f"Git {operation} timed out") from exc
    except subprocess.CalledProcessError as exc:
        if operation == "push" and "stale info" in (exc.stderr or "").casefold():
            raise GitQueryError("A branch for this query already exists for this minute", 409) from exc
        raise GitQueryError(f"Git {operation} failed (exit {exc.returncode})") from exc


def func_git_query_relative(path):
    try:
        return path.resolve().relative_to(git_repo_path).as_posix()
    except ValueError:
        raise GitQueryError("This query is outside the datapipeline Git checkout", 400) from None


def func_git_query_history(path):
    relative = func_git_query_relative(path)
    raw = func_git_run(
        ["log", f"-{QUERY_HISTORY_LIMIT}", "--format=%H%x1f%aI%x1f%s", "--", relative],
        git_repo_path,
    )
    commits = []
    for line in raw.splitlines():
        fields = line.split("\x1f", 2)
        if len(fields) == 3:
            commits.append({"sha": fields[0], "at": fields[1], "message": fields[2]})
    return commits


def func_git_origin_repo():
    remote = func_git_run(["remote", "get-url", "origin"], git_repo_path).strip()
    if "://" in remote:
        parsed = urlsplit(remote)
        host, path = parsed.hostname, parsed.path.lstrip("/")
    else:
        match = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(.+)", remote)
        host, path = match.groups() if match else (None, "")
    configured_host = urlsplit(GITHUB_WEB_URL).hostname
    identity = path.rstrip("/").removesuffix(".git")
    if not host or host.casefold() != configured_host or not re.fullmatch(r"[-\w.]+/[-\w.]+", identity, re.ASCII):
        raise GitQueryError("Git origin does not match the configured GitHub repository host")
    return identity, remote.startswith("https://")


def func_git_github_request(path, token=None, *, params=None, payload=None):
    url = GITHUB_API_URL + path + ("?" + urlencode(params) if params else "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    outbound = urllib_request.Request(url, headers=headers, data=data)
    if token:
        # Prevent the authorization header from following an HTTP redirect.
        if urlsplit(url).scheme != "https":
            raise GitQueryError("GitHub API must use HTTPS when a token is configured")
        outbound.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urllib_request.urlopen(outbound, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib_error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise GitQueryError(f"GitHub returned HTTP {status}") from exc
    except (OSError, ValueError) as exc:
        raise GitQueryError("GitHub could not be reached or returned an invalid response") from exc


def func_git_github_list(path, token, **params):
    page_size = 100
    page = 1
    while True:
        results = func_git_github_request(path, token, params={**params, "per_page": page_size, "page": page})
        if not isinstance(results, list):
            raise GitQueryError("GitHub returned an unexpected list response")
        yield from results
        if len(results) < page_size:
            break
        page += 1


def func_git_pull_request_info(repo, pull):
    return {
        "number": pull["number"],
        "title": pull["title"],
        "url": f"{GITHUB_WEB_URL}/{repo}/pull/{pull['number']}",
        "branch": pull["head"]["ref"],
        "created_at": pull.get("created_at"),
    }


def func_git_open_pull_requests(path):
    relative = func_git_query_relative(path)
    repo, _ = func_git_origin_repo()
    token = os.getenv(GITHUB_TOKEN_ENV_NAME)
    pulls = func_git_github_list(f"/repos/{repo}/pulls", token, state="open", base="main")
    return [
        func_git_pull_request_info(repo, pull)
        for pull in pulls
        if any(
            file["filename"] == relative or file.get("previous_filename") == relative
            for file in func_git_github_list(f"/repos/{repo}/pulls/{pull['number']}/files", token)
        )
    ]


def func_git_normalize_sql(sql):
    return sql.replace("\r\n", "\n").replace("\r", "\n").removeprefix("\ufeff")


def func_git_query_hash(sql):
    return hashlib.sha256(func_git_normalize_sql(sql).encode("utf-8")).hexdigest()


def func_git_stage_query(worktree, relative, sql, base_hash):
    target = worktree / relative
    if not target.is_file() or not target.resolve().is_relative_to(worktree.resolve()) or target.is_symlink():
        raise GitQueryError("The active query is missing from origin/main", 409)
    existing = target.read_bytes()
    original = existing.decode("utf-8-sig")
    if base_hash is not None and func_git_query_hash(original) != base_hash:
        raise GitQueryError("The query has changed on main. Reopen it after the next Git pull.", 409)
    content = func_git_normalize_sql(sql)
    if content == func_git_normalize_sql(original):
        raise ValueError("Make a change before opening a pull request")
    if b"\r\n" in existing:
        content = content.replace("\n", "\r\n")
    target.write_bytes(content.encode("utf-8-sig" if existing.startswith(b"\xef\xbb\xbf") else "utf-8"))
    func_git_run(["add", "--", relative], worktree)


def func_git_open_query_pr(path, sql, title, run_by, base_hash=None):
    # ----------------------------------------------------------------
    # 1. Resolve Destination
    stem = re.sub(r"[^\w-]+", "-", path.stem, flags=re.ASCII).strip("-_") or "query"
    branch = f"query-edit/{stem}-{datetime.now(TIMEZONE):%Y%m%d-%H%M}"
    branch_ref = f"refs/heads/{branch}"
    relative = path.name
    log_message(f"Pull request started | branch={branch} | file={relative} | run_by={run_by}", 'INFO')
    status = "failed"
    try:
        relative = func_git_query_relative(path)
        repo, https_origin = func_git_origin_repo()
        token = os.getenv(GITHUB_TOKEN_ENV_NAME)
        git_token = token if https_origin else None
        create_url = f"{GITHUB_WEB_URL}/{repo}/compare/main...{quote(branch, safe='/')}?expand=1"

        # ----------------------------------------------------------------
        # 2. Commit And Push From A Temporary Worktree
        with tempfile.TemporaryDirectory(prefix="refresh-desk-query-") as directory:
            worktree = Path(directory) / "checkout"
            added = False
            try:
                func_git_run(
                    ["fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main"],
                    git_repo_path, token=git_token,
                )
                func_git_run(["worktree", "add", "--detach", str(worktree), "origin/main"], git_repo_path)
                added = True
                func_git_stage_query(worktree, relative, sql, base_hash)
                func_git_run(
                    ["-c", f"user.name={GIT_AUTHOR_NAME}", "-c", f"user.email={GIT_AUTHOR_EMAIL}",
                     "commit", "-m", title, "-m", f"Requested by {run_by}"],
                    worktree,
                )
                func_git_run(
                    ["push", f"--force-with-lease={branch_ref}:", "origin", f"HEAD:{branch_ref}"],
                    worktree, token=git_token,
                )

                # ----------------------------------------------------------------
                # 3. Open Pull Request
                result = {"status": "branch_pushed", "branch": branch, "create_url": create_url}
                if token:
                    try:
                        pull = func_git_github_request(f"/repos/{repo}/pulls", token, payload={
                            "title": title, "head": branch, "base": "main",
                            "body": f"Query update for `{relative}`.\n\nRequested by {run_by}.",
                        })
                        result.update(status="opened", pull_request=func_git_pull_request_info(repo, pull))
                    except (GitQueryError, KeyError, TypeError) as exc:
                        result["message"] = str(exc) if isinstance(exc, GitQueryError) else "GitHub returned an unexpected pull request response"
                        log_message(f"Pull request API failed | branch={branch} | {result['message']}", 'WARNING')
                else:
                    result["message"] = "Branch pushed. Open the pull request in GitHub."
            finally:
                if added:
                    func_git_run(["worktree", "remove", "--force", str(worktree)], git_repo_path)
        status = result["status"]
        return result
    finally:
        log_message(f"Pull request finished | branch={branch} | file={relative} | status={status}",
                    'ERROR' if status == "failed" else 'INFO')


# ----------------------------------------------------------------------------------------------------------------------
#%% Configure
git_pull_lock = threading.Lock()
git_repo_path = GIT_REPO_PATH
