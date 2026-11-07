"""Import boundaries: the program layer never imports the web layer, and nothing imports it.

Every front end (the web API now, a background worker later) runs turns through ``app.turns``;
the transports never depend on each other.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = "api"
# Packages that must never import the web layer (a later worker package joins this list).
NOT_IMPORTING_WEB = (
    "agent",
    "app",
    "commons",
    "config",
    "evals",
    "models",
    "prompts",
    "storage",
    "tools",
)


def _imported(path: Path) -> set[str]:
    """The top-level modules a file imports (absolute imports only; the project uses no other)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _imports_web(path: Path) -> bool:
    return any(name == WEB or name.startswith(f"{WEB}.") for name in _imported(path))


@pytest.mark.parametrize("package", NOT_IMPORTING_WEB)
def test_no_package_imports_the_web_layer(package: str) -> None:
    offenders = [p.relative_to(ROOT) for p in (ROOT / package).rglob("*.py") if _imports_web(p)]
    assert offenders == []


def test_the_check_sees_an_import_of_the_web_layer(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("from api.services import agent_runner\nimport api.main\n", encoding="utf-8")
    assert _imports_web(probe)
    probe.write_text("import apis\nfrom app.turns import execute_turn\n", encoding="utf-8")
    assert not _imports_web(probe)
