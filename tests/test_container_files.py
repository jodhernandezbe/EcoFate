"""Static checks of the container files: no secret in the image, loopback-only port, Makefile."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "compose.yaml").read_text()
MAKEFILE = (ROOT / "Makefile").read_text()
README = (ROOT / "README.md").read_text()
_SECRET_NAME = re.compile(r"^\s*(?:ENV|ARG)\s+.*?\b\w*(?:_KEY|_TOKEN|_PASSWORD)\b", re.I | re.M)


def _ignored(path: str) -> bool:
    """Whether ``.dockerignore`` excludes ``path`` (last matching rule wins, ``!`` re-includes)."""
    ignored = False
    for raw in (ROOT / ".dockerignore").read_text().splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        keep = rule.startswith("!")
        pattern = rule.removeprefix("!").rstrip("/").removeprefix("**/")
        if fnmatch.fnmatch(path, pattern) or path.startswith(pattern + "/"):
            ignored = not keep
    return ignored


def test_dockerignore_excludes_env_files_but_keeps_the_template() -> None:
    assert _ignored(".env")
    assert _ignored(".env.local")
    assert not _ignored(".env.example")


def test_dockerignore_excludes_caches_and_raw_data() -> None:
    for path in (".venv", ".cache/scc_index", "evals/reports/x.html", "data/raw/a.zip", ".git"):
        assert _ignored(path), path
    assert not _ignored("data/pstk.csv")


def test_compose_publishes_the_api_only_on_loopback() -> None:
    published = re.findall(r'^\s*-\s*"([^"]+)"', COMPOSE.split("ports:")[1], re.M)[:1]
    assert published == ["127.0.0.1:8000:8000"]
    assert "0.0.0.0" not in COMPOSE


def test_no_dockerfile_env_or_arg_names_a_secret() -> None:
    assert _SECRET_NAME.findall(DOCKERFILE) == []


def test_secret_name_check_catches_a_key() -> None:
    assert _SECRET_NAME.findall("ENV OPENAI_API_KEY=x\nARG LOGFIRE_TOKEN\n")


def test_final_runtime_stage_runs_as_a_non_root_user() -> None:
    runtime = DOCKERFILE.split("AS runtime")[1].split("\nFROM ")[0]
    users = re.findall(r"^USER\s+(\S+)", runtime, re.M)
    assert users and users[-1] not in {"root", "0"}


def test_api_target_launches_in_container_mode() -> None:
    api = DOCKERFILE.split("AS api")[1]
    assert 'CMD ["python", "-m", "api", "--container"]' in api


def test_every_makefile_target_in_the_readme_exists() -> None:
    targets = set(re.findall(r"^([a-z-]+):", MAKEFILE, re.M))
    mentioned = set(re.findall(r"`make ([a-z-]+)`", README))
    assert mentioned, "the README lists the Makefile targets"
    assert mentioned <= targets
