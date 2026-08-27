from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "codexstack" / "skills" / "work" / "scripts" / "model_policy.py"
SPEC = importlib.util.spec_from_file_location("model_policy", SCRIPT)
assert SPEC and SPEC.loader
model_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_policy)


class ModelPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.temporary.name)

    def tearDown(self) -> None:
        os.chdir(self.previous)
        self.temporary.cleanup()

    def write(self, roles: dict) -> Path:
        path = Path("models.json")
        path.write_text(json.dumps({"contract": model_policy.CONTRACT, "roles": roles}), encoding="utf-8")
        return path

    def test_all_upstream_roles_and_panel_sizes_validate(self) -> None:
        example = json.loads(
            (ROOT / "plugins" / "codexstack" / "skills" / "work" / "assets" / "model-policy.example.json").read_text()
        )
        result = model_policy.validate_policy(example, set())
        self.assertEqual(set(result["roles"]), model_policy.ALL_ROLES)
        self.assertFalse(result["fallback_roles"])
        self.assertTrue(all(size == 4 for size in result["panel_sizes"].values()))

    def test_real_models_must_come_from_observed_available_set(self) -> None:
        value = {"contract": model_policy.CONTRACT, "roles": {"bug-fix": "gpt-current"}}
        with self.assertRaisesRegex(model_policy.PolicyError, "unavailable model IDs"):
            model_policy.validate_policy(value, set())
        result = model_policy.validate_policy(value, {"gpt-current"})
        self.assertEqual(result["roles"]["bug-fix"], "gpt-current")

    def test_aliases_are_always_valid_and_missing_roles_fall_back(self) -> None:
        result = model_policy.validate_policy(
            {"contract": model_policy.CONTRACT, "roles": {"swarm workers": "auto"}},
            set(),
        )
        self.assertIn("bug-fix", result["fallback_roles"])
        self.assertEqual(result["roles"]["swarm workers"], "auto")

    def test_unknown_roles_and_invalid_panel_shapes_fail(self) -> None:
        with self.assertRaisesRegex(model_policy.PolicyError, "unknown roles"):
            model_policy.load_policy(str(self.write({"invented": "auto"})))
        with self.assertRaisesRegex(model_policy.PolicyError, "list of 1 through"):
            model_policy.validate_policy(
                {"contract": model_policy.CONTRACT, "roles": {"arena runners": []}},
                set(),
            )

    def test_reader_rejects_duplicate_json_keys(self) -> None:
        path = Path("models.json")
        path.write_text(
            '{"contract":"codexstack.models.v1","roles":{"bug-fix":"auto","bug-fix":"inherit-parent"}}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(model_policy.PolicyError, "duplicate JSON key: bug-fix"):
            model_policy.load_policy(str(path))

    def test_reader_rejects_absolute_parent_symlink_and_oversize_paths(self) -> None:
        path = self.write({"bug-fix": "auto"})
        with self.assertRaisesRegex(model_policy.PolicyError, "relative"):
            model_policy.load_policy(str(path.resolve()))
        with self.assertRaisesRegex(model_policy.PolicyError, "relative"):
            model_policy.load_policy("../models.json")
        link = Path("link.json")
        link.symlink_to(path)
        with self.assertRaisesRegex(model_policy.PolicyError, "non-symlink"):
            model_policy.load_policy(str(link))
        large = Path("large.json")
        large.write_text("x" * (model_policy.MAX_BYTES + 1), encoding="utf-8")
        with self.assertRaisesRegex(model_policy.PolicyError, "exceeds"):
            model_policy.load_policy(str(large))

    def test_cli_is_deterministic_json_and_read_only(self) -> None:
        path = self.write({"bug-fix": "gpt-current", "how critics": ["auto", "gpt-current"]})
        before = path.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            code = model_policy.main([str(path), "--available", "gpt-current"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["valid"])
        self.assertEqual(result["panel_sizes"]["how critics"], 2)
        self.assertEqual(path.read_bytes(), before)

        output = io.StringIO()
        with redirect_stdout(output):
            code = model_policy.main([str(path)])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["valid"])


if __name__ == "__main__":
    unittest.main()
