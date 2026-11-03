"""Tests for config.loader."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config.loader import (
    ComptoxSettings,
    get_comptox_settings,
    load_comptox_settings,
    load_unit_settings,
)

OTHER = """
[other]
x = 1
"""

COMPTOX = """
[comptox]
base_url = "https://ctx.test/api/"
dtxsid_by_cas_path = "/c/{casrn}"
detail_by_dtxsid_path = "/d/{dtxsid}"
properties_by_dtxsid_path = "/p/{dtxsid}"
toxval_by_dtxsid_path = "/t/{dtxsid}"
source_priority = ["SRC1", "SRC2"]
api_key_header = "x-key"  # pragma: allowlist secret
api_key_env_var = "SOME_KEY_VAR"  # pragma: allowlist secret
delay_seconds = 0
timeout_seconds = 2
max_retries = 3
backoff_seconds = 1.5
accept_expired_certificate = false

[comptox.molecular_weight]
field = "mass"
unit = "mu"
target_unit = "mt"

[[comptox.properties]]
key = "a"
name = "Prop A"
target_unit = "ta"

[[comptox.properties]]
key = "b"
name = "Prop B"
target_unit = "tb"

[[comptox.toxicity_values]]
key = "x"
types = ["X"]
routes = ["Oral", "not specified"]
prefer = "lowest"
target_unit = "tx"

[[comptox.toxicity_values]]
key = "y"
types = ["Y1", "Y2"]
routes = ["inhalation"]
prefer = "highest"
target_unit = "ty"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _load(tmp_path: Path, text: str) -> ComptoxSettings:
    return load_comptox_settings(_write(tmp_path, text))


def test_comptox_default_file_loads() -> None:
    settings = load_comptox_settings()
    assert {spec.key for spec in settings.properties} >= {"vapor_pressure", "density"}
    assert "{casrn}" in settings.dtxsid_by_cas_url
    assert "{dtxsid}" in settings.detail_by_dtxsid_url
    assert "{dtxsid}" in settings.properties_by_dtxsid_url
    assert "{dtxsid}" in settings.toxval_by_dtxsid_url
    assert settings.api_key_env_var
    assert settings.source_priority


def test_default_molecular_weight() -> None:
    spec = load_comptox_settings().molecular_weight
    assert (spec.field, spec.unit, spec.target_unit) == ("averageMass", "g/mol", "g/mol")


def test_molecular_weight_explicit(tmp_path: Path) -> None:
    spec = _load(tmp_path, COMPTOX).molecular_weight
    assert (spec.field, spec.unit, spec.target_unit) == ("mass", "mu", "mt")


def test_molecular_weight_table_required(tmp_path: Path) -> None:
    head, tail = COMPTOX.split("[comptox.molecular_weight]")
    rest = tail.split("[[comptox.properties]]", 1)[1]
    with pytest.raises(ValueError, match="comptox.molecular_weight"):
        _load(tmp_path, head + "[[comptox.properties]]" + rest)


@pytest.mark.parametrize("key", ["field", "unit", "target_unit"])
def test_molecular_weight_keys_required(tmp_path: Path, key: str) -> None:
    text = (
        re.sub(rf"^{key} = .*\n", "", COMPTOX, count=1, flags=re.M)
        if key != "unit"
        else (COMPTOX.replace('unit = "mu"\n', "", 1))
    )
    with pytest.raises(ValueError, match=f"comptox.molecular_weight.{key}"):
        _load(tmp_path, text)


def test_default_toxicity_entries() -> None:
    entries = {t.key: t for t in load_comptox_settings().toxicity_values}
    assert set(entries) == {"rfd", "rfc", "sf", "iur"}
    assert entries["rfd"].types == ("RfD",)
    assert entries["rfc"].types == ("RfC",)
    assert entries["sf"].types == ("cancer slope factor",)
    assert entries["iur"].types == ("cancer unit risk",)
    assert entries["rfd"].routes == ("oral", "not specified")
    assert entries["rfc"].routes == ("inhalation", "not specified")
    assert entries["sf"].routes == ("oral",)
    assert entries["iur"].routes == ("inhalation",)
    assert [entries[k].prefer for k in ("rfd", "rfc", "sf", "iur")] == [
        "lowest",
        "lowest",
        "highest",
        "highest",
    ]


def test_default_target_units() -> None:
    settings = load_comptox_settings()
    targets = {p.key: p.target_unit for p in settings.properties}
    targets |= {t.key: t.target_unit for t in settings.toxicity_values}
    assert targets == {
        "vapor_pressure": "mmHg",
        "density": "g/cm^3",
        "rfd": "mg/(kg*day)",
        "rfc": "mg/m^3",
        "sf": "1/(mg/(kg*day))",
        "iur": "1/(ug/m^3)",
    }


def test_comptox_explicit_path(tmp_path: Path) -> None:
    settings = _load(tmp_path, COMPTOX)
    assert settings.dtxsid_by_cas_url == "https://ctx.test/api/c/{casrn}"
    assert settings.detail_by_dtxsid_url == "https://ctx.test/api/d/{dtxsid}"
    assert settings.properties_by_dtxsid_url == "https://ctx.test/api/p/{dtxsid}"
    assert settings.toxval_by_dtxsid_url == "https://ctx.test/api/t/{dtxsid}"
    assert settings.source_priority == ("SRC1", "SRC2")
    assert settings.timeout_seconds == 2.0
    assert [(p.key, p.name, p.target_unit) for p in settings.properties] == [
        ("a", "Prop A", "ta"),
        ("b", "Prop B", "tb"),
    ]
    x, y = settings.toxicity_values
    assert (x.key, x.types, x.routes, x.prefer, x.target_unit) == (
        "x",
        ("X",),
        ("oral", "not specified"),
        "lowest",
        "tx",
    )
    assert (y.key, y.types, y.prefer) == ("y", ("Y1", "Y2"), "highest")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="nope.toml"):
        load_comptox_settings(tmp_path / "nope.toml")


def test_comptox_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comptox section"):
        _load(tmp_path, OTHER)


def test_comptox_missing_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comptox.api_key_env_var"):
        _load(tmp_path, COMPTOX.replace("api_key_env_var", "other"))


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("/c/{casrn}", "/c/", "dtxsid_by_cas_path must contain"),
        ("/d/{dtxsid}", "/d/", "detail_by_dtxsid_path must contain"),
        ("/p/{dtxsid}", "/p/", "properties_by_dtxsid_path must contain"),
        ("/t/{dtxsid}", "/t/", "toxval_by_dtxsid_path must contain"),
        ("dtxsid_by_cas_path", "other", "comptox.dtxsid_by_cas_path"),
        ("detail_by_dtxsid_path", "other", "comptox.detail_by_dtxsid_path"),
        ("toxval_by_dtxsid_path", "other", "comptox.toxval_by_dtxsid_path"),
    ],
)
def test_comptox_path_validation(tmp_path: Path, old: str, new: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, COMPTOX.replace(old, new))


def test_comptox_negative_delay(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comptox.delay_seconds"):
        _load(tmp_path, COMPTOX.replace("delay_seconds = 0", "delay_seconds = -1"))


def test_comptox_certificate_waiver_must_be_a_boolean(tmp_path: Path) -> None:
    assert _load(tmp_path, COMPTOX).accept_expired_certificate is False
    with pytest.raises(ValueError, match="comptox.accept_expired_certificate"):
        _load(
            tmp_path,
            COMPTOX.replace(
                "accept_expired_certificate = false",
                'accept_expired_certificate = "yes"',
            ),
        )
    with pytest.raises(ValueError, match="comptox.accept_expired_certificate"):
        _load(tmp_path, COMPTOX.replace("accept_expired_certificate = false\n", ""))


def test_comptox_non_numeric_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comptox.timeout_seconds"):
        _load(tmp_path, COMPTOX.replace("timeout_seconds = 2", 'timeout_seconds = "x"'))


def test_comptox_retry_settings(tmp_path: Path) -> None:
    settings = _load(tmp_path, COMPTOX)
    assert (settings.max_retries, settings.backoff_seconds) == (3, 1.5)
    assert _load(tmp_path, COMPTOX.replace("max_retries = 3", "max_retries = 0")).max_retries == 0


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("max_retries = 3", "max_retries = -1", "comptox.max_retries"),
        ("max_retries = 3", "max_retries = 1.5", "comptox.max_retries"),
        ("max_retries = 3", "max_retries = true", "comptox.max_retries"),
        ("max_retries = 3\n", "", "comptox.max_retries"),
        ("backoff_seconds = 1.5", "backoff_seconds = -1", "comptox.backoff_seconds"),
        ("backoff_seconds = 1.5", 'backoff_seconds = "x"', "comptox.backoff_seconds"),
        ("backoff_seconds = 1.5\n", "", "comptox.backoff_seconds"),
    ],
)
def test_comptox_invalid_retry_settings(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, COMPTOX.replace(old, new))


def test_shipped_source_priority_names_iris_as_the_api_does() -> None:
    assert get_comptox_settings().source_priority[0] == "EPA IRIS: IRIS"


def test_source_priority_optional_but_validated(tmp_path: Path) -> None:
    without = COMPTOX.replace('source_priority = ["SRC1", "SRC2"]\n', "")
    assert _load(tmp_path, without).source_priority == ()
    with pytest.raises(ValueError, match="comptox.source_priority"):
        _load(tmp_path, COMPTOX.replace('["SRC1", "SRC2"]', '["SRC1", ""]'))


def test_comptox_requires_properties(tmp_path: Path) -> None:
    head = COMPTOX.split("[[comptox.properties]]")[0]
    with pytest.raises(ValueError, match="comptox.properties"):
        _load(tmp_path, head)


def test_comptox_duplicate_property_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unique"):
        _load(tmp_path, COMPTOX.replace('key = "b"', 'key = "a"'))


def test_comptox_requires_toxicity_values(tmp_path: Path) -> None:
    head = COMPTOX.split("[[comptox.toxicity_values]]")[0]
    with pytest.raises(ValueError, match="comptox.toxicity_values"):
        _load(tmp_path, head)


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ('types = ["X"]', "types = []", "types"),
        ('routes = ["Oral", "not specified"]', "routes = []", "routes"),
        ('routes = ["inhalation"]', 'routes = [""]', "routes"),
        ('prefer = "lowest"', 'prefer = "median"', "prefer"),
        ('prefer = "highest"', "", "prefer"),
        ('key = "x"', 'other = "x"', "comptox.toxicity_values.key"),
        ('key = "y"', 'key = "x"', "unique"),
    ],
)
def test_comptox_toxicity_entry_validation(tmp_path: Path, old: str, new: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, COMPTOX.replace(old, new))


def test_target_unit_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comptox.properties.target_unit"):
        _load(tmp_path, COMPTOX.replace('target_unit = "ta"\n', ""))
    with pytest.raises(ValueError, match="comptox.toxicity_values.target_unit"):
        _load(tmp_path, COMPTOX.replace('target_unit = "tx"\n', ""))


def test_unit_aliases_default_and_custom(tmp_path: Path) -> None:
    aliases = load_unit_settings().aliases
    assert aliases["mg/m3"] == "mg/m^3"
    assert aliases["(mg/m3)-1"] == "1/(mg/m^3)"
    assert aliases["(mg/L)-1"] == "1/(mg/L)"
    text = OTHER + '\n[units.aliases]\n"a/b" = "c"\n'
    assert load_unit_settings(_write(tmp_path, text)).aliases == {"a/b": "c"}


def test_unit_aliases_missing_table_means_none(tmp_path: Path) -> None:
    assert load_unit_settings(_write(tmp_path, OTHER)).aliases == {}


def test_unit_aliases_must_be_strings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="units.aliases.a"):
        load_unit_settings(_write(tmp_path, OTHER + "\n[units.aliases]\na = 3\n"))
    with pytest.raises(ValueError, match="units.aliases.a"):
        load_unit_settings(_write(tmp_path, OTHER + '\n[units.aliases]\na = " "\n'))
