"""Tests for scripts.check_function_length."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_function_length import find_violations, main


def _function(body_lines: int, *, doc: bool = False) -> str:
    docstring = '    """Docstring.\n\n    More.\n    """\n' if doc else ""
    body = "".join(f"    x{i} = {i}\n" for i in range(body_lines))
    return f"def f():\n{docstring}{body}"


def test_at_the_limit_passes() -> None:
    assert find_violations(_function(18), 18) == []


def test_over_the_limit_is_reported() -> None:
    assert find_violations(_function(19), 18) == [(1, "f", 19)]


def test_docstring_blank_lines_and_comments_are_not_counted() -> None:
    source = _function(18, doc=True) + "\n    # a comment\n\n    # another\n"
    assert find_violations(source, 18) == []


def test_multiline_statements_count_every_line() -> None:
    source = "def f():\n    x = [\n" + "        1,\n" * 17 + "    ]\n"
    assert find_violations(source, 18) == [(1, "f", 19)]


def test_nested_functions_count_toward_the_outer_one() -> None:
    inner = "".join(f"        y{i} = {i}\n" for i in range(10))
    source = "def outer():\n    def inner():\n" + inner + "    a = 1\n" * 9
    assert [name for _, name, _ in find_violations(source, 18)] == ["outer"]


def test_methods_and_async_functions_are_checked() -> None:
    method = "class C:\n    def m(self):\n" + "        x = 1\n" * 19
    coroutine = "async def g():\n" + "    x = 1\n" * 19
    assert [name for _, name, _ in find_violations(method, 18)] == ["m"]
    assert [name for _, name, _ in find_violations(coroutine, 18)] == ["g"]


def test_signature_is_not_counted() -> None:
    params = "".join(f"    p{i}: int,\n" for i in range(30))
    assert find_violations(f"def f(\n{params}) -> None:\n    pass\n", 18) == []


def test_empty_and_docstring_only_functions_are_fine() -> None:
    assert find_violations('def f():\n    """Only a docstring."""\n', 18) == []


def test_main_reports_and_sets_exit_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(_function(19))
    good = tmp_path / "good.py"
    good.write_text(_function(3))
    assert main([str(good)]) == 0
    assert main([str(good), str(bad)]) == 1
    assert "bad.py:1: f() has 19 body lines (max 18)" in capsys.readouterr().out


def test_main_max_option(tmp_path: Path) -> None:
    path = tmp_path / "m.py"
    path.write_text(_function(5))
    assert main(["--max", "4", str(path)]) == 1
    assert main(["--max", "5", str(path)]) == 0
