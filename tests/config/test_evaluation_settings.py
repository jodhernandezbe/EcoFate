"""Tests for the ``[evaluation]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.evaluation import get_evaluation_settings, load_evaluation_settings
from config.parsing import PROJECT_ROOT

EVALUATION = """
[evaluation]
judge_provider = " OpenAI "
judge_model = "judge-test"
judge_api_key_env_var = "TEST_KEY_VAR"  # pragma: allowlist secret
live_tools = ["offline_tool"]
cassette_dir = "evals/test_cassettes"
report_dir = "/tmp/test_reports"
catalogue = "evals/test_catalogue.csv"
catalogue_results = "results.json"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in EVALUATION.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_evaluation_settings(_write(tmp_path, EVALUATION))
    assert settings.judge_provider == "openai"
    assert settings.judge_model == "judge-test"
    assert settings.judge_api_key_env_var == "TEST_KEY_VAR"  # pragma: allowlist secret
    assert settings.live_tools == ("offline_tool",)


def test_relative_dir_resolved_against_project_root(tmp_path: Path) -> None:
    settings = load_evaluation_settings(_write(tmp_path, EVALUATION))
    assert settings.cassette_dir == PROJECT_ROOT / "evals/test_cassettes"
    assert settings.report_dir == Path("/tmp/test_reports")
    assert settings.catalogue == PROJECT_ROOT / "evals/test_catalogue.csv"


def test_catalogue_results_is_a_bare_file_name(tmp_path: Path) -> None:
    settings = load_evaluation_settings(_write(tmp_path, EVALUATION))
    assert settings.catalogue_results == "results.json"


def test_shipped_catalogue_exists() -> None:
    settings = get_evaluation_settings()
    assert settings.catalogue.is_file()
    assert settings.catalogue_results == "catalogue.json"


def test_empty_live_tools_allowed(tmp_path: Path) -> None:
    path = _replace(tmp_path, "live_tools", "live_tools = []")
    assert load_evaluation_settings(path).live_tools == ()


def test_shipped_settings_load() -> None:
    settings = get_evaluation_settings()
    assert settings.judge_provider == "openai"
    assert "calculate_exposure_metrics" in settings.live_tools


@pytest.mark.parametrize(
    ("line_start", "new_line", "key"),
    [
        ("judge_provider", 'judge_provider = "other"', "evaluation.judge_provider"),
        ("judge_model", 'judge_model = " "', "evaluation.judge_model"),
        ("judge_model", "judge_model = 3", "evaluation.judge_model"),
        ("judge_api_key_env_var", 'judge_api_key_env_var = ""', "evaluation.judge_api_key"),
        ("live_tools", 'live_tools = "x"', "evaluation.live_tools"),
        ("cassette_dir", "cassette_dir = 1", "evaluation.cassette_dir"),
        ("report_dir", 'report_dir = ""', "evaluation.report_dir"),
        ("catalogue =", "catalogue = 7", "evaluation.catalogue"),
        ("catalogue_results", 'catalogue_results = ""', "evaluation.catalogue_results"),
        ("catalogue_results", 'catalogue_results = "a/b.json"', "evaluation.catalogue_results"),
        ("catalogue_results", 'catalogue_results = ".."', "evaluation.catalogue_results"),
    ],
)
def test_invalid_entry_names_key(tmp_path: Path, line_start: str, new_line: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_evaluation_settings(_replace(tmp_path, line_start, new_line))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="evaluation section is missing"):
        load_evaluation_settings(_write(tmp_path, "[other]\nx = 1\n"))
