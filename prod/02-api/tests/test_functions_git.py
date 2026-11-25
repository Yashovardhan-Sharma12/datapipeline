# ----------------------------------------------------------------------------------------------------------------------
#%% Log
import os
from utils.logger.logger import log_message
log_message(f"File: {os.path.relpath(__file__)}", 'INFO')

# ----------------------------------------------------------------------------------------------------------------------
#%% Import Packages
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from functions import functions_git as git

# ----------------------------------------------------------------------------------------------------------------------
#%% Tests


class GitQueryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = Path(folder.name).resolve()
        self.path = self.repo / "src/prod/01-queries/contact.sql"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"\xef\xbb\xbfSELECT 1\r\n")
        self.relative = self.path.relative_to(self.repo)
        self.commands = []
        self.worktree = None
        patcher = patch.object(git, "git_repo_path", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def func_test_git_command(self, args, cwd, **kwargs):
        self.commands.append((args, Path(cwd)))
        if args[:3] == ["remote", "get-url", "origin"]:
            return "git@github.com:owner/datapipeline.git\n"
        if args[:3] == ["worktree", "add", "--detach"]:
            self.worktree = Path(args[3])
            target = self.worktree / self.relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b"\xef\xbb\xbfSELECT 1\r\n")
        if args[:1] == ["push"]:
            self.assertEqual((self.worktree / self.relative).read_bytes(), b"\xef\xbb\xbfSELECT 2\r\n")
        return ""

    def test_uses_worktree_for_git_and_opens_pull_request(self):
        reply = {"number": 7, "title": "Change contact query", "head": {"ref": "query-edit/contact"}}
        with (
            patch.dict(os.environ, {git.GITHUB_TOKEN_ENV_NAME: "fake-token"}),
            patch.object(git, "func_git_run", side_effect=self.func_test_git_command),
            patch.object(git, "func_git_github_request", return_value=reply) as api,
        ):
            result = git.func_git_open_query_pr(
                self.path, "SELECT 2\n", "Change contact query", "Tester", git.func_git_query_hash("SELECT 1\r\n"),
            )
        self.assertEqual(result["status"], "opened")
        self.assertEqual(result["pull_request"]["number"], 7)
        self.assertRegex(result["branch"], r"^query-edit/contact-\d{8}-\d{4}$")
        self.assertEqual(api.call_args.kwargs["payload"]["base"], "main")
        push, directory = next((args, cwd) for args, cwd in self.commands if args[0] == "push")
        self.assertEqual(directory, self.worktree)
        self.assertEqual(push[-1], f"HEAD:refs/heads/{result['branch']}")
        self.assertEqual(push[1], f"--force-with-lease=refs/heads/{result['branch']}:")
        commit, directory = next((args, cwd) for args, cwd in self.commands if "commit" in args)
        self.assertEqual(directory, self.worktree)
        self.assertIn("Requested by Tester", commit)
        self.assertEqual(self.commands[-1][0][:2], ["worktree", "remove"])
        self.assertFalse(self.worktree.exists())
        self.assertEqual(self.path.read_bytes(), b"\xef\xbb\xbfSELECT 1\r\n")

    def test_tokenless_flow_pushes_and_returns_a_create_link(self):
        with (
            patch.dict(os.environ, {git.GITHUB_TOKEN_ENV_NAME: ""}),
            patch.object(git, "func_git_run", side_effect=self.func_test_git_command),
            patch.object(git, "func_git_github_request") as api,
        ):
            result = git.func_git_open_query_pr(self.path, "SELECT 2\n", "Change contact query", "Tester")
        self.assertEqual(result["status"], "branch_pushed")
        self.assertIn(f"/compare/main...{result['branch']}?expand=1", result["create_url"])
        api.assert_not_called()
        self.assertEqual(self.commands[-1][0][:2], ["worktree", "remove"])

    def test_stale_revision_cleans_up_without_pushing(self):
        with patch.object(git, "func_git_run", side_effect=self.func_test_git_command):
            with self.assertRaises(git.GitQueryError) as error:
                git.func_git_open_query_pr(self.path, "SELECT 2\n", "Change contact query", "Tester", "0" * 64)
        self.assertEqual(error.exception.status, 409)
        self.assertFalse(any(args[0] == "push" for args, _ in self.commands))
        self.assertEqual(self.commands[-1][0][:2], ["worktree", "remove"])

    def test_changes_lists_only_open_prs_for_the_requested_file(self):
        pulls = [
            {"number": 4, "title": "Same filename in another source", "head": {"ref": "other"}},
            {"number": 9, "title": "Contact SQL update", "head": {"ref": "other-branch"}},
        ]

        def func_test_github_list(path, token, **params):
            if path.endswith("/pulls"):
                self.assertEqual(params, {"state": "open", "base": "main"})
                return pulls
            if "/4/" in path:
                return [{"filename": "src/dev/01-queries/contact.sql"}]
            return [{"filename": self.relative.as_posix()}]

        with (
            patch.object(git, "func_git_run", side_effect=self.func_test_git_command),
            patch.object(git, "func_git_github_list", side_effect=func_test_github_list),
        ):
            self.assertEqual([pull["number"] for pull in git.func_git_open_pull_requests(self.path)], [9])
