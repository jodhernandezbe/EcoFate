"""Import boundaries: nothing imports the web layer or the worker, and the worker imports only
what it is allowed.

Every front end (the web API and the background worker) runs turns through ``app.turns``; the
transports never depend on each other.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = "api"
WORKER = "worker"
# What the worker may import from the project (anything else of the project is refused).
WORKER_ALLOWED = ("app", "agent", "config", "storage", "tools.credentials", WORKER)
PROJECT = ("agent", "api", "app", "commons", "config", "evals", "models", "prompts", "storage")
PROJECT_PACKAGES = (*PROJECT, "tools", WORKER, "scripts")
# Packages that must never import the web layer.
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
    WORKER,
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


def _imports(path: Path, package: str) -> bool:
    return any(name == package or name.startswith(f"{package}.") for name in _imported(path))


def _project_imports(path: Path) -> set[str]:
    return {n for n in _imported(path) if n.split(".", 1)[0] in PROJECT_PACKAGES}


def _allowed_for_worker(name: str) -> bool:
    return any(name == allowed or name.startswith(f"{allowed}.") for allowed in WORKER_ALLOWED)


def test_the_worker_imports_only_what_it_may() -> None:
    offenders = {
        str(path.relative_to(ROOT)): sorted(
            n for n in _project_imports(path) if not _allowed_for_worker(n)
        )
        for path in (ROOT / WORKER).rglob("*.py")
    }
    assert {path: names for path, names in offenders.items() if names} == {}


@pytest.mark.parametrize("package", [*PROJECT, "tools", "scripts"])
def test_nothing_imports_the_worker(package: str) -> None:
    offenders = [p.relative_to(ROOT) for p in (ROOT / package).rglob("*.py") if _imports(p, WORKER)]
    assert offenders == []


def test_the_worker_check_sees_a_forbidden_import(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("from tools.registry import x\nimport prompts.registry\nfrom app import y\n")
    names = {n for n in _project_imports(probe) if not _allowed_for_worker(n)}
    assert names == {"tools.registry", "prompts.registry"}
    probe.write_text("from tools.credentials import HOLDERS\nimport celery\n")
    assert {n for n in _project_imports(probe) if not _allowed_for_worker(n)} == set()
