"""Tests for the ``[ui.exposure_graph]`` loader (fixed text and units of the exposure graph)."""

from __future__ import annotations

import tomllib

import pytest

from config import exposure_graph as graph
from config.exposure_graph import parse_exposure_graph
from config.ui import get_ui_settings
from tests.config.graph_text import GRAPH


def _parse(text: str) -> graph.GraphText:
    return parse_exposure_graph(tomllib.loads(text)["ui"])


def test_values() -> None:
    text = _parse(GRAPH)
    assert text.source == "Source"
    assert text.nodes["stack"] == "Stack {number}"
    assert text.quantities["twa"] == graph.QuantityText(label="L twa", unit="u")
    assert text.reasons["missing"] == "x missing"


def test_shipped_settings_load() -> None:
    text = get_ui_settings().exposure_graph
    assert set(text.quantities) == set(graph.QUANTITIES)
    assert text.quantities["hq"].unit == ""
    assert text.reasons["worker_only"] == "the facility reports no stack release"


def test_the_worker_word_tables_are_read_from_the_shipped_settings() -> None:
    text = get_ui_settings().exposure_graph
    assert set(text.estimators) == set(graph.ESTIMATORS)
    assert set(text.settings) == {"indoor", "outdoor"}
    assert set(text.flags) == set(graph.FLAGS) and set(text.evidences) == set(graph.EVIDENCES)


def test_a_missing_word_table_entry_is_named() -> None:
    with pytest.raises(ValueError, match="ui.exposure_graph.estimators.two_zone"):
        _parse(GRAPH.replace('two_zone = "x two_zone"', ""))


def test_maps_are_read_only() -> None:
    text = _parse(GRAPH)
    with pytest.raises(TypeError):
        text.lanes["community"] = "changed"  # type: ignore[index]


def test_missing_key_is_named() -> None:
    with pytest.raises(ValueError, match="ui.exposure_graph.lanes.worker"):
        _parse(GRAPH.replace('worker = "x worker"', ""))


def test_placeholder_required() -> None:
    with pytest.raises(ValueError, match=r"nodes.stack must contain \{number\}"):
        _parse(GRAPH.replace("Stack {number}", "Stack"))


def test_unit_must_be_a_string() -> None:
    bad = GRAPH.replace(
        'twa = { label = "L twa", unit = "u" }',
        'twa = { label = "L twa", unit = 1 }',
    )
    with pytest.raises(ValueError, match="quantities.twa.unit"):
        _parse(bad)


def test_empty_label_rejected() -> None:
    with pytest.raises(ValueError, match="quantities.twa.label"):
        _parse(GRAPH.replace('label = "L twa"', 'label = " "'))


def test_missing_table_rejected() -> None:
    with pytest.raises(ValueError, match="ui.exposure_graph must be a table"):
        parse_exposure_graph({})
