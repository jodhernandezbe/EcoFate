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
catalogue_labels = "human.json"
catalogue_judged = "verdicts.json"
judge_timeout_seconds = 45
judge_temperature = 0.0
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


def test_judge_files_and_timeout(tmp_path: Path) -> None:
    settings = load_evaluation_settings(_write(tmp_path, EVALUATION))
    assert (settings.catalogue_labels, settings.catalogue_judged) == ("human.json", "verdicts.json")
    assert settings.judge_timeout_seconds == 45
    assert settings.judge_temperature == 0.0


def test_judge_temperature_absent_means_provider_default(tmp_path: Path) -> None:
    text = "\n".join(ln for ln in EVALUATION.splitlines() if not ln.startswith("judge_temperature"))
    assert load_evaluation_settings(_write(tmp_path, text)).judge_temperature is None


def test_shipped_catalogue_exists() -> None:
    settings = get_evaluation_settings()
    assert settings.catalogue.is_file()
    assert settings.catalogue_results == "catalogue.json"
    assert (settings.catalogue_labels, settings.catalogue_judged) == ("labels.json", "judged.json")
    assert settings.judge_timeout_seconds > 0


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
        ("catalogue_labels", 'catalogue_labels = "a/b.json"', "evaluation.catalogue_labels"),
        ("catalogue_judged", 'catalogue_judged = ""', "evaluation.catalogue_judged"),
        ("judge_timeout_seconds", "judge_timeout_seconds = 0", "evaluation.judge_timeout"),
        ("judge_timeout_seconds", 'judge_timeout_seconds = "x"', "evaluation.judge_timeout"),
        ("judge_temperature", "judge_temperature = -0.1", "evaluation.judge_temperature"),
        ("judge_temperature", "judge_temperature = 2.5", "evaluation.judge_temperature"),
        ("judge_temperature", 'judge_temperature = "0"', "evaluation.judge_temperature"),
    ],
)
def test_invalid_entry_names_key(tmp_path: Path, line_start: str, new_line: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_evaluation_settings(_replace(tmp_path, line_start, new_line))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="evaluation section is missing"):
        load_evaluation_settings(_write(tmp_path, "[other]\nx = 1\n"))
