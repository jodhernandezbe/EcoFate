"""Tests for scripts/load/stats.py: docker stats parsing and the sampler."""

from __future__ import annotations

import pytest

from scripts.load.stats import Sampler, mebibytes, percent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5GiB / 12GiB", 1536.0),
        ("512MiB / 1GiB", 512.0),
        ("100kB / 1GB", 100e3 / 2**20),
    ],
)
def test_mebibytes(text: str, expected: float) -> None:
    assert mebibytes(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "n/a", "12 furlongs / 1GiB", "--"])
def test_mebibytes_unreadable(text: str) -> None:
    assert mebibytes(text) is None


def test_percent() -> None:
    assert percent(" 12.5% ") == 12.5
    assert percent("abc") is None


def test_service_of_picks_longest_match() -> None:
    sampler = Sampler(("api", "worker", "tool-worker"))
    assert sampler.service_of("ecofate-tool-worker-1") == "tool-worker"
    assert sampler.service_of("ecofate-worker-1") == "worker"
    assert sampler.service_of("other") is None


def test_add_ignores_unknown_and_unreadable() -> None:
    sampler = Sampler(("api",))
    sampler.add({"Name": "mystery", "CPUPerc": "1%", "MemUsage": "1MiB / 2MiB"})
    sampler.add({"Name": "x-api-1", "CPUPerc": "bad", "MemUsage": "1MiB / 2MiB"})
    sampler.add({"Name": "x-api-1", "CPUPerc": "1%", "MemUsage": "bad"})
    sampler.add({})
    assert sampler.cpu == {}
    assert sampler.memory == {}


def test_result_peak_and_mean() -> None:
    sampler = Sampler(("api",))
    for cpu, mem in (("10%", "100MiB / 1GiB"), ("30%", "300MiB / 1GiB")):
        sampler.add({"Name": "x-api-1", "CPUPerc": cpu, "MemUsage": mem})
    assert sampler.result() == {
        "api": {"cpu_peak": 30.0, "cpu_mean": 20.0, "mem_peak_mib": 300.0},
    }
