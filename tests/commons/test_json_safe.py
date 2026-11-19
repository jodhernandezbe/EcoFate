"""``json_safe``: strict JSON data out, non-finite numbers absent, non-data refused."""

from __future__ import annotations

import json
import math

import pytest

from commons.json_safe import json_safe


def test_plain_data_is_copied() -> None:
    source = {"a": [1, 2.5, "x", None, True], "b": {"c": (1, 2)}}
    copy = json_safe(source)
    assert copy == {"a": [1, 2.5, "x", None, True], "b": {"c": [1, 2]}}
    assert copy is not source
    json.dumps(copy, allow_nan=False)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_number_becomes_absent(bad: float) -> None:
    assert json_safe({"x": [bad]}) == {"x": [None]}


@pytest.mark.parametrize("bad", [object(), {1, 2}, b"bytes", {1: "x"}, {"a": object()}])
def test_something_that_is_not_data_is_refused(bad: object) -> None:
    with pytest.raises(TypeError):
        json_safe(bad)
