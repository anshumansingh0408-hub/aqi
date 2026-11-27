"""Quality gate tests enforcing docstring presence, type hints, line limits, and security rules.

Uses the Python AST to statically inspect source modules.
"""

import ast
import os
import unittest


class TestQuality(unittest.TestCase):
    """Quality gate test suite for static codebase inspection."""

    def setUp(self) -> None:
        """Locate target modules for static code quality inspection."""
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.target_files = [
            "advisor.py",
            "utils.py",
            "app.py",
            "air_client.py",
            "ai_client.py",
        ]

    def test_module_docstrings(self) -> None:
        """Verify each non-empty file contains a module docstring."""
        missing: list[str] = []
        for fname in self.target_files:
            fpath = os.path.join(self.base_dir, fname)
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                continue
            tree = ast.parse(content, filename=fname)
            doc = ast.get_docstring(tree)
            if not doc or not doc.strip():
                missing.append(fname)
        self.assertEqual(missing, [], f"Missing module docstrings in: {missing}")

    def test_no_aiza_keys(self) -> None:
        """Verify no source file contains hardcoded API keys starting with 'AIza' or 'gsk_'."""
        violations: list[str] = []
        for fname in self.target_files:
            fpath = os.path.join(self.base_dir, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            for line_idx, line in enumerate(content.splitlines(), start=1):
                if "AIza" in line or "gsk_" in line:
                    violations.append(f"{fname}:{line_idx}")
        self.assertEqual(violations, [], f"Hardcoded keys found in: {violations}")

    def test_function_quality_gate(self) -> None:
        """Verify docstring, typed parameters, return annotation, and body length <= 30."""
        failures: list[str] = []
        for fname in self.target_files:
            fpath = os.path.join(self.base_dir, fname)
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                continue
            tree = ast.parse(content, filename=fname)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = f"{fname}::{node.name} (line {node.lineno})"
                    doc = ast.get_docstring(node)
                    if not doc or not doc.strip():
                        failures.append(f"{fn_name}: missing docstring")
                    all_args = (
                        node.args.args
                        + getattr(node.args, "posonlyargs", [])
                        + node.args.kwonlyargs
                    )
                    for arg in all_args:
                        if arg.arg != "self" and arg.annotation is None:
                            failures.append(
                                f"{fn_name}: parameter '{arg.arg}' missing type annotation"
                            )
                    if node.args.vararg and node.args.vararg.annotation is None:
                        failures.append(
                            f"{fn_name}: *{node.args.vararg.arg} missing type annotation"
                        )
                    if node.args.kwarg and node.args.kwarg.annotation is None:
                        failures.append(
                            f"{fn_name}: **{node.args.kwarg.arg} missing type annotation"
                        )
                    if node.returns is None:
                        failures.append(f"{fn_name}: missing return type annotation")
                    length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
                    if length > 30:
                        failures.append(f"{fn_name}: body length {length} exceeds 30 lines limit")
        self.assertEqual(
            failures, [], "Quality gate violations:\n" + "\n".join(f" - {f}" for f in failures)
        )


if __name__ == "__main__":
    unittest.main()
