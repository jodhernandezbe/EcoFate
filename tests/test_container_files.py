"""Static checks of the container files: no secret in the image, loopback-only port, Makefile."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

import yaml

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


def _service(name: str) -> str:
    """The block of one compose service (its indented lines)."""
    match = re.search(rf"^  {name}:\n((?:    .*\n|\s*\n)+)", COMPOSE, re.M)
    assert match, f"compose.yaml has no service {name}"
    return match.group(1)


def _published(block: str) -> list[str]:
    ports = block.split("ports:")[1] if "ports:" in block else ""
    return re.findall(r'^\s*-\s*"([^"]+)"', ports, re.M)[:1] if ports else []


def test_compose_publishes_the_api_only_on_loopback() -> None:
    assert _published(_service("api")) == ["127.0.0.1:8000:8000"]
    assert "0.0.0.0" not in COMPOSE


def test_database_is_not_published_outside_the_dev_profile() -> None:
    assert "ports:" not in _service("db")
    assert "ports:" not in _service("migrate")
    forwarder = _service("db-port")
    assert re.search(r"^    profiles: \[dev\]$", forwarder, re.M)
    assert _published(forwarder) == ["127.0.0.1:5432:5432"]


def test_every_published_port_is_on_loopback() -> None:
    published = re.findall(r'^\s*-\s*"([^"]*:\d+:\d+)"', COMPOSE, re.M)
    assert published
    assert all(port.startswith("127.0.0.1:") for port in published)


def test_api_waits_for_the_migrations_and_the_database() -> None:
    api = _service("api")
    assert re.search(r"migrate:\n\s+condition: service_completed_successfully", api)
    assert re.search(r"db:\n\s+condition: service_healthy", api)
    migrate = _service("migrate")
    assert '"python", "-m", "storage", "upgrade"' in migrate
    assert re.search(r"db:\n\s+condition: service_healthy", migrate)


def test_migrate_gets_the_database_url_but_not_the_api_keys() -> None:
    migrate = _service("migrate")
    assert "env_file" not in migrate
    assert "*database-url" in migrate


def test_database_password_comes_from_env_only() -> None:
    assert re.search(r"POSTGRES_PASSWORD: \$\{POSTGRES_PASSWORD:\?", COMPOSE)
    assert "DATABASE_URL" not in DOCKERFILE


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


# --- compose.prod.yaml (production on the VM) -----------------------------------------------


class _ComposeLoader(yaml.SafeLoader):
    """A safe loader that also reads Compose's merge tags as plain values."""


def _tagged(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)  # pyright: ignore[reportArgumentType]


_ComposeLoader.add_constructor("!override", _tagged)
_ComposeLoader.add_constructor("!reset", _tagged)
PROD: dict[str, Any] = yaml.load((ROOT / "compose.prod.yaml").read_text(), Loader=_ComposeLoader)  # noqa: S506  # nosec B506 - a SafeLoader subclass
SERVICES: dict[str, Any] = PROD["services"]


def test_production_publishes_no_host_port() -> None:
    assert SERVICES["api"]["ports"] == []
    assert all(not service.get("ports") for service in SERVICES.values())


def test_production_services_use_the_production_settings_profile() -> None:
    for name in ("api", "worker", "migrate"):
        assert SERVICES[name]["environment"]["ECOFATE_SETTINGS_PROFILE"] == "production", name


def test_production_images_are_pinned_and_app_images_come_from_ghcr() -> None:
    for name in ("api", "worker", "migrate"):
        assert SERVICES[name]["image"].startswith("ghcr.io/jodhernandezbe/ecofate-"), name
        assert ":${ECOFATE_TAG:?" in SERVICES[name]["image"], name
    assert re.fullmatch(r"cloudflare/cloudflared:\d{4}\.\d+\.\d+", SERVICES["cloudflared"]["image"])


def test_the_tunnel_token_stays_out_of_the_app_containers() -> None:
    assert SERVICES["cloudflared"]["env_file"] == ["/opt/ecofate/tunnel.env"]
    for name in ("api", "worker"):
        assert SERVICES[name]["env_file"] == ["/opt/ecofate/.env.prod"], name


def test_production_containers_rotate_their_logs_and_have_memory_limits() -> None:
    for name, service in SERVICES.items():
        assert service["logging"]["options"]["max-size"], name
        assert service["mem_limit"], name


def test_dev_only_services_are_not_switched_on_in_production() -> None:
    assert not {"db-port", "redis-port", "mailpit"} & SERVICES.keys()
