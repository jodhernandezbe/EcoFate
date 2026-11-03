"""Typed loader for the ``[evaluation]`` settings (agent evaluation in ``evals/``).

The agent's own chat model is not here: evaluations use ``[agent]`` (``config/agent.py``), the
same model the program runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.agent import chat_provider
from config.parsing import names, project_path, read_toml, require_str, section

_NAME = "evaluation"


@dataclass(frozen=True)
class EvaluationSettings:
    """Agent evaluation settings. The API key itself is never stored, only its variable name.

    Attributes:
        judge_provider: Provider of the judge model (a supported chat provider).
        judge_model: Chat model scoring the report wording.
        judge_api_key_env_var: Environment variable holding the judge provider's API key.
        live_tools: Tools that need no network and run for real during replay.
        cassette_dir: Directory of recorded tool outputs.
        report_dir: Directory evaluation reports are written to.
        catalogue: The reviewed question catalogue (CSV: question, category, type).
        catalogue_results: File name of a catalogue run's results, inside its run folder.
    """

    judge_provider: str
    judge_model: str
    judge_api_key_env_var: str
    live_tools: tuple[str, ...]
    cassette_dir: Path
    report_dir: Path
    catalogue: Path
    catalogue_results: str


def _file_name(table: dict[str, object], key: str) -> str:
    """A bare file name: non-empty, with no directory part."""
    value = require_str(table, key, _NAME).strip()
    if Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{_NAME}.{key} must be a file name without a directory")
    return value


def load_evaluation_settings(path: Path | None = None) -> EvaluationSettings:
    """Load and validate the agent evaluation settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (directories resolved against the project root).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    return EvaluationSettings(
        judge_provider=chat_provider(table, "judge_provider", _NAME),
        judge_model=require_str(table, "judge_model", _NAME).strip(),
        judge_api_key_env_var=require_str(table, "judge_api_key_env_var", _NAME).strip(),
        live_tools=names(table, "live_tools", _NAME, allow_empty=True),
        cassette_dir=project_path(table, "cassette_dir", _NAME),
        report_dir=project_path(table, "report_dir", _NAME),
        catalogue=project_path(table, "catalogue", _NAME),
        catalogue_results=_file_name(table, "catalogue_results"),
    )


@lru_cache(maxsize=1)
def get_evaluation_settings() -> EvaluationSettings:
    """Return the cached evaluation settings from the default file."""
    return load_evaluation_settings()
