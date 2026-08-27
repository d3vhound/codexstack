from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins"
    / "codexstack"
    / "skills"
    / "work"
    / "scripts"
    / "worktree_audit.py"
)
SPEC = importlib.util.spec_from_file_location("codexstack_worktree_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


NOW = 2_000_000_000


def git(cwd: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", os.fspath(cwd), *arguments],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"},
    )


class RepositoryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "primary repo with spaces"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "CodexStack Test")
        git(self.repo, "config", "user.email", "codexstack@example.invalid")
        (self.repo / "tracked file.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "tracked file.txt")
        git(self.repo, "commit", "-m", "base")
        self.paths: list[Path] = []

    def add(self, name: str, *, commit: bool = False) -> Path:
        path = self.root / f"linked {name} worktree"
        branch = name.replace(" ", "-")
        git(self.repo, "worktree", "add", "-b", branch, os.fspath(path), "main")
        self.paths.append(path)
        if commit:
            (path / f"{name} change.txt").write_text(f"{name}\n", encoding="utf-8")
            git(path, "add", ".")
            git(path, "commit", "-m", f"{name} change")
        return path

    @staticmethod
    def head(path: Path) -> str:
        return git(path, "rev-parse", "HEAD").stdout.strip()

    def evidence_row(
        self,
        path: Path,
        *,
        active: bool = False,
        pinned: bool = False,
        last_used_at: int | None = None,
        pr: dict | None = None,
    ) -> dict:
        return {
            "path": os.fspath(path),
            "active": active,
            "pinned": pinned,
            "last_used_at": last_used_at,
            "pr": {"state": "NONE"} if pr is None else pr,
        }

    def evidence(self, *rows: dict, observed_at: int = NOW) -> dict:
        return {
            "contract_version": audit.EVIDENCE_VERSION,
            "observed_at": observed_at,
            "worktrees": list(rows),
        }

    def inspect(self, evidence: dict | None, **options) -> dict:
        return audit.audit_repository(
            self.repo,
            evidence=evidence,
            now=NOW,
            base_ref="refs/heads/main",
            **options,
        )


class WorktreeAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = RepositoryFixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def only(self, payload: dict) -> dict:
        self.assertEqual(payload["summary"]["candidates"], 1)
        return payload["worktrees"][0]

    def test_clean_merged_tree_with_explicit_inactive_evidence_is_safe(self) -> None:
        path = self.fixture.add("merged clean")
        row = self.only(
            self.fixture.inspect(
                self.fixture.evidence(self.fixture.evidence_row(path))
            )
        )
        self.assertEqual(row["path"], os.fspath(path))
        self.assertIn(" ", row["path"])
        self.assertEqual(row["bucket"], "safe")
        self.assertEqual(row["merge"], {"state": "merged", "via": "git_ancestor"})
        self.assertEqual(row["dirty"], {"kind": "clean", "tracked": 0, "untracked": 0})
        self.assertIsInstance(row["size_bytes"], int)
        self.assertTrue(row["size_complete"])
        self.assertIsInstance(row["age_days"], int)
        self.assertEqual(payload_counts := self.fixture.inspect(
            self.fixture.evidence(self.fixture.evidence_row(path))
        )["summary"], {"candidates": 1, "safe": 1, "hold": 0, "review": 0})
        self.assertEqual(payload_counts["safe"], 1)

    def test_untracked_scratch_is_distinct_and_does_not_hide_safe_merge(self) -> None:
        path = self.fixture.add("scratch")
        (path / "throwaway notes.txt").write_text("scratch\n", encoding="utf-8")
        row = self.only(
            self.fixture.inspect(
                self.fixture.evidence(self.fixture.evidence_row(path))
            )
        )
        self.assertEqual(row["bucket"], "safe")
        self.assertEqual(row["dirty"]["kind"], "scratch")
        self.assertEqual(row["dirty"]["tracked"], 0)
        self.assertEqual(row["dirty"]["untracked"], 1)
        self.assertIn("untracked_scratch", [reason["code"] for reason in row["reasons"]])

    def test_tracked_wip_and_mixed_work_are_held(self) -> None:
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                name = "mixed" if mixed else "tracked"
                path = self.fixture.add(name)
                (path / "tracked file.txt").write_text("edited\n", encoding="utf-8")
                if mixed:
                    (path / "untracked.tmp").write_text("tmp\n", encoding="utf-8")
                row = next(
                    item
                    for item in self.fixture.inspect(
                        self.fixture.evidence(
                            *(self.fixture.evidence_row(candidate) for candidate in self.fixture.paths)
                        )
                    )["worktrees"]
                    if item["path"] == os.fspath(path)
                )
                self.assertEqual(row["bucket"], "hold")
                self.assertEqual(row["dirty"]["kind"], "mixed" if mixed else "wip")
                self.assertEqual(row["dirty"]["tracked"], 1)
                self.assertIn("tracked_wip", [reason["code"] for reason in row["reasons"]])

    def test_rename_is_counted_as_one_tracked_wip_entry(self) -> None:
        path = self.fixture.add("rename")
        git(path, "mv", "tracked file.txt", "renamed file.txt")
        row = self.only(
            self.fixture.inspect(self.fixture.evidence(self.fixture.evidence_row(path)))
        )
        self.assertEqual(row["dirty"], {"kind": "wip", "tracked": 1, "untracked": 0})
        self.assertEqual(row["bucket"], "hold")

    def test_pinned_active_and_recent_use_each_override_a_safe_git_state(self) -> None:
        path = self.fixture.add("use evidence")
        cases = (
            ({"pinned": True}, "workspace_pinned"),
            ({"active": True}, "workspace_active"),
            ({"last_used_at": NOW - audit.RECENT_USE_SECONDS}, "workspace_recently_used"),
        )
        for changes, code in cases:
            with self.subTest(code=code):
                row_fields = {
                    "active": False,
                    "pinned": False,
                    "last_used_at": None,
                    **changes,
                }
                evidence_row = self.fixture.evidence_row(path, **row_fields)
                row = self.only(self.fixture.inspect(self.fixture.evidence(evidence_row)))
                self.assertEqual(row["bucket"], "hold")
                self.assertIn(code, [reason["code"] for reason in row["reasons"]])

    def test_old_use_is_not_recent_but_missing_use_evidence_requires_review(self) -> None:
        path = self.fixture.add("old use")
        old = self.fixture.evidence_row(
            path, last_used_at=NOW - audit.RECENT_USE_SECONDS - 1
        )
        safe = self.only(self.fixture.inspect(self.fixture.evidence(old)))
        self.assertEqual(safe["bucket"], "safe")
        missing = self.only(self.fixture.inspect(None))
        self.assertEqual(missing["bucket"], "review")
        self.assertIn("use_evidence_missing", [reason["code"] for reason in missing["reasons"]])

    def test_open_pr_holds_while_unknown_none_and_closed_unmerged_prs_review(self) -> None:
        path = self.fixture.add("unmerged", commit=True)
        head = self.fixture.head(path)
        cases = (
            ({"state": "OPEN", "number": 7, "head_sha": head}, "hold", "open_pr"),
            ({"state": "UNKNOWN"}, "review", "unmerged_pr_unknown"),
            ({"state": "NONE"}, "review", "unmerged_no_pr"),
            ({"state": "CLOSED", "number": 8, "head_sha": head}, "review", "unmerged_closed_pr"),
        )
        for pr, bucket, reason in cases:
            with self.subTest(pr=pr):
                evidence = self.fixture.evidence(self.fixture.evidence_row(path, pr=pr))
                row = self.only(self.fixture.inspect(evidence))
                self.assertEqual(row["bucket"], bucket)
                self.assertIn(reason, [item["code"] for item in row["reasons"]])

    def test_exact_head_merged_pr_covers_squash_merge_ancestry(self) -> None:
        path = self.fixture.add("squash", commit=True)
        pr = {"state": "MERGED", "number": 9, "head_sha": self.fixture.head(path)}
        row = self.only(
            self.fixture.inspect(
                self.fixture.evidence(self.fixture.evidence_row(path, pr=pr))
            )
        )
        self.assertEqual(row["merge"]["state"], "unmerged")
        self.assertEqual(row["bucket"], "safe")
        self.assertIn("merged_pr_confirmed", [reason["code"] for reason in row["reasons"]])

    def test_remote_branch_reports_pushed_then_ahead_without_fetching(self) -> None:
        path = self.fixture.add("remote", commit=True)
        branch = git(path, "branch", "--show-current").stdout.strip()
        head = self.fixture.head(path)
        git(self.fixture.repo, "update-ref", f"refs/remotes/origin/{branch}", head)
        initial = self.only(
            self.fixture.inspect(self.fixture.evidence(self.fixture.evidence_row(path)))
        )
        self.assertEqual(initial["remote"]["state"], "pushed")
        (path / "second.txt").write_text("second\n", encoding="utf-8")
        git(path, "add", "second.txt")
        git(path, "commit", "-m", "second")
        current = self.fixture.head(path)
        evidence = self.fixture.evidence(
            self.fixture.evidence_row(path, pr={"state": "UNKNOWN"})
        )
        after = self.only(self.fixture.inspect(evidence))
        self.assertEqual(after["head_sha"], current)
        self.assertEqual(after["remote"]["state"], "ahead")
        self.assertEqual(after["remote"]["ahead_by"], 1)
        self.assertEqual(after["remote"]["behind_by"], 0)

    def test_missing_base_ref_is_explicitly_unknown_and_never_safe(self) -> None:
        path = self.fixture.add("missing base")
        evidence = self.fixture.evidence(self.fixture.evidence_row(path))
        payload = audit.audit_repository(
            self.fixture.repo,
            evidence=evidence,
            now=NOW,
            base_ref="refs/remotes/origin/does-not-exist",
        )
        row = self.only(payload)
        self.assertEqual(payload["base"]["state"], "unavailable")
        self.assertEqual(row["merge"]["state"], "unknown")
        self.assertEqual(row["bucket"], "review")
        self.assertIn("merge_state_unknown", [reason["code"] for reason in row["reasons"]])

    def test_size_limit_is_bounded_and_incomplete_size_forces_review(self) -> None:
        path = self.fixture.add("bounded size")
        (path / "one.tmp").write_text("1", encoding="utf-8")
        (path / "two.tmp").write_text("2", encoding="utf-8")
        row = self.only(
            self.fixture.inspect(
                self.fixture.evidence(self.fixture.evidence_row(path)),
                max_size_entries=1,
            )
        )
        self.assertFalse(row["size_complete"])
        self.assertEqual(row["bucket"], "review")
        self.assertIn("size_incomplete", [reason["code"] for reason in row["reasons"]])

    def test_output_is_canonical_and_deterministically_sorted(self) -> None:
        smaller = self.fixture.add("deterministic small")
        larger = self.fixture.add("deterministic large")
        (larger / "large.bin").write_bytes(b"x" * 4096)
        evidence = self.fixture.evidence(
            self.fixture.evidence_row(smaller), self.fixture.evidence_row(larger)
        )
        first = self.fixture.inspect(evidence)
        second = self.fixture.inspect(evidence)
        encoded_first = json.dumps(first, sort_keys=True, separators=(",", ":"))
        encoded_second = json.dumps(second, sort_keys=True, separators=(",", ":"))
        self.assertEqual(encoded_first, encoded_second)
        self.assertEqual(first["worktrees"][0]["path"], os.fspath(larger))
        listed = {
            record.split("\x00", 1)[0].removeprefix("worktree ")
            for record in git(self.fixture.repo, "worktree", "list", "--porcelain", "-z").stdout.split("\x00\x00")
            if record
        }
        self.assertEqual(
            {first["main_worktree"], *(row["path"] for row in first["worktrees"])},
            listed,
        )

    def test_audit_does_not_change_status_or_refs(self) -> None:
        path = self.fixture.add("read only")
        (path / "scratch.txt").write_text("scratch\n", encoding="utf-8")
        before_status = git(path, "status", "--porcelain=v1", "-z").stdout
        before_refs = git(self.fixture.repo, "show-ref").stdout
        self.fixture.inspect(self.fixture.evidence(self.fixture.evidence_row(path)))
        self.assertEqual(git(path, "status", "--porcelain=v1", "-z").stdout, before_status)
        self.assertEqual(git(self.fixture.repo, "show-ref").stdout, before_refs)


class EvidenceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = RepositoryFixture(self.root)
        self.path = self.fixture.add("evidence target")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_stale_future_and_stale_head_evidence_are_rejected(self) -> None:
        stale = self.fixture.evidence(
            self.fixture.evidence_row(self.path), observed_at=NOW - audit.DEFAULT_EVIDENCE_AGE - 1
        )
        with self.assertRaisesRegex(audit.InputError, "stale"):
            self.fixture.inspect(stale)
        future = self.fixture.evidence(
            self.fixture.evidence_row(self.path), observed_at=NOW + audit.FUTURE_SKEW_SECONDS + 1
        )
        with self.assertRaisesRegex(audit.InputError, "future"):
            self.fixture.inspect(future)
        bad_pr = {
            "state": "OPEN",
            "number": 1,
            "head_sha": "f" * 40,
        }
        stale_head = self.fixture.evidence(self.fixture.evidence_row(self.path, pr=bad_pr))
        with self.assertRaisesRegex(audit.InputError, "stale"):
            self.fixture.inspect(stale_head)

    def test_unknown_path_parent_escape_and_alias_path_are_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        bad = self.fixture.evidence(
            {
                "path": os.fspath(outside),
                "active": False,
                "pinned": False,
                "last_used_at": None,
                "pr": {"state": "NONE"},
            }
        )
        with self.assertRaisesRegex(audit.InputError, "exact candidate"):
            self.fixture.inspect(bad)
        escaped = self.fixture.evidence(
            {
                "path": "../outside",
                "active": False,
                "pinned": False,
                "last_used_at": None,
                "pr": {"state": "NONE"},
            }
        )
        with self.assertRaisesRegex(audit.InputError, "exact absolute"):
            self.fixture.inspect(escaped)
        alias = self.root / "alias"
        alias.symlink_to(self.path, target_is_directory=True)
        aliased = self.fixture.evidence(
            {
                "path": os.fspath(alias),
                "active": False,
                "pinned": False,
                "last_used_at": None,
                "pr": {"state": "NONE"},
            }
        )
        with self.assertRaisesRegex(audit.InputError, "exact candidate"):
            self.fixture.inspect(aliased)

    def test_evidence_file_rejects_parent_paths_symlinks_duplicates_and_oversize(self) -> None:
        payload = self.fixture.evidence(self.fixture.evidence_row(self.path))
        source = self.root / "evidence.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(audit.load_evidence("evidence.json", root=self.root), payload)
        with self.assertRaisesRegex(audit.InputError, "parent"):
            audit.load_evidence("../evidence.json", root=self.root)
        linked = self.root / "linked.json"
        linked.symlink_to(source)
        with self.assertRaisesRegex(audit.InputError, "symlink"):
            audit.load_evidence("linked.json", root=self.root)
        duplicate = self.root / "duplicate.json"
        duplicate.write_text('{"contract_version":"a","contract_version":"b"}', encoding="utf-8")
        with self.assertRaisesRegex(audit.InputError, "duplicate"):
            audit.load_evidence("duplicate.json", root=self.root)
        oversized = self.root / "oversized.json"
        oversized.write_bytes(b" " * (audit.MAX_EVIDENCE_BYTES + 1))
        with self.assertRaisesRegex(audit.InputError, "exceeds"):
            audit.load_evidence("oversized.json", root=self.root)

    def test_malformed_fields_duplicates_and_unsupported_fields_are_rejected(self) -> None:
        base_row = self.fixture.evidence_row(self.path)
        cases = [
            {"contract_version": "wrong", "observed_at": NOW, "worktrees": []},
            {"contract_version": audit.EVIDENCE_VERSION, "observed_at": NOW, "worktrees": "bad"},
            self.fixture.evidence({**base_row, "active": "no"}),
            self.fixture.evidence({key: value for key, value in base_row.items() if key != "last_used_at"}),
            self.fixture.evidence({**base_row, "secret": "not accepted"}),
            self.fixture.evidence(base_row, base_row),
            self.fixture.evidence({**base_row, "pr": {"state": "OPEN", "number": 1}}),
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(audit.InputError):
                    self.fixture.inspect(value)

    def test_repository_and_evidence_symlink_boundaries_are_independent(self) -> None:
        repository_alias = self.root / "repo alias"
        repository_alias.symlink_to(self.fixture.repo, target_is_directory=True)
        with self.assertRaisesRegex(audit.InputError, "symlink"):
            audit.audit_repository(repository_alias, now=NOW, base_ref="refs/heads/main")


class CommandLineTests(unittest.TestCase):
    def test_help_describes_read_only_boundaries(self) -> None:
        completed = subprocess.run(
            [sys.executable, os.fspath(SCRIPT), "--help"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("without fetching", completed.stdout)
        self.assertIn("--evidence", completed.stdout)
        self.assertIn("safe bucket is advice only", completed.stdout)

    def test_cli_emits_machine_readable_json_and_machine_readable_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = RepositoryFixture(root)
            path = fixture.add("cli target")
            evidence = root / "evidence.json"
            evidence.write_text(
                json.dumps(fixture.evidence(fixture.evidence_row(path))), encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    os.fspath(SCRIPT),
                    os.fspath(fixture.repo),
                    "--evidence",
                    "evidence.json",
                    "--base-ref",
                    "refs/heads/main",
                    "--now",
                    str(NOW),
                ],
                cwd=root,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["contract_version"], audit.CONTRACT_VERSION)
            self.assertEqual(payload["worktrees"][0]["bucket"], "safe")
            failed = subprocess.run(
                [sys.executable, os.fspath(SCRIPT), os.fspath(root / "missing")],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(failed.returncode, 2)
            error = json.loads(failed.stderr)
            self.assertEqual(error["contract_version"], audit.CONTRACT_VERSION)
            self.assertIn("error", error)


if __name__ == "__main__":
    unittest.main()
