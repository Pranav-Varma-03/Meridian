"""Static guardrails for production application logging paths."""

import ast
from pathlib import Path

APPLICATION_ROOT = Path(__file__).parents[1] / "app"
DIRECT_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def test_application_code_has_no_direct_logger_emission_paths() -> None:
    violations: list[str] = []

    for path in APPLICATION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in DIRECT_LOG_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
            ):
                violations.append(
                    f"{path.relative_to(APPLICATION_ROOT)}:{node.lineno}: logger.{node.func.attr}"
                )

    assert violations == [], "Unsafe application logging paths found: " + ", ".join(
        violations
    )
