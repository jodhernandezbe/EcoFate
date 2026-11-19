"""Every relative link and image in the documentation points at a file and heading that exist.

Covers every tracked ``README.md`` and every Markdown file under a ``docs/`` folder. External links
(``http(s)://``, ``mailto:``) are never fetched.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
EXTERNAL = ("http://", "https://", "mailto:")


def _documents() -> list[Path]:
    """Tracked README.md files anywhere and Markdown files under any docs/ folder."""
    listed = subprocess.run(  # noqa: S603 - fixed git command, no user input
        [
            "git",
            "ls-files",
            "*README.md",
            "docs/*.md",
            "docs/**/*.md",
            "*/docs/*.md",
            "*/docs/**/*.md",
        ],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    skip = ("node_modules/", ".venv/", ".claude/", "openspec/")
    return sorted(
        {ROOT / p for p in listed if not p.startswith(skip) and "/node_modules/" not in p},
    )


def _prose_lines(text: str) -> list[str]:
    """The lines outside fenced code blocks."""
    lines: list[str] = []
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`|\*\*|__", "", heading).strip().lower()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """Every heading anchor of a Markdown file, with GitHub's -1, -2 suffixes for repeats."""
    seen: dict[str, int] = {}
    found: set[str] = set()
    for line in _prose_lines(path.read_text(encoding="utf-8")):
        match = HEADING.match(line)
        if not match:
            continue
        base = slug(match.group(2))
        count = seen.get(base, 0)
        found.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return found


def broken_links(path: Path) -> list[str]:
    """The relative links of one document whose file or heading does not exist."""
    problems: list[str] = []
    for line in _prose_lines(path.read_text(encoding="utf-8")):
        for target in LINK.findall(line):
            if target.startswith(EXTERNAL):
                continue
            file_part, _, anchor = target.partition("#")
            dest = (path.parent / file_part).resolve() if file_part else path
            if not dest.exists():
                problems.append(f"{target}: no such file")
            elif anchor and dest.suffix == ".md" and anchor.lower() not in anchors(dest):
                problems.append(f"{target}: no heading #{anchor}")
    return problems


@pytest.mark.parametrize("document", _documents(), ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(document: Path) -> None:
    assert broken_links(document) == []


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("See [b](b.md).\n", encoding="utf-8")
    assert broken_links(doc) == ["b.md: no such file"]


def test_a_missing_anchor_is_reported(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("# Judge iterations\n", encoding="utf-8")
    doc = tmp_path / "a.md"
    doc.write_text("[ok](b.md#judge-iterations) [bad](b.md#nope) [self](#gone)\n", encoding="utf-8")
    assert broken_links(doc) == ["b.md#nope: no heading #nope", "#gone: no heading #gone"]


def test_external_links_and_code_blocks_are_ignored(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text(
        "[x](https://example.org/missing)\n```\n[y](missing.md)\n```\n",
        encoding="utf-8",
    )
    assert broken_links(doc) == []


def test_slugs_follow_github(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("# Keys and BYOK\n## `make` targets\n## Notes\n## Notes\n", encoding="utf-8")
    assert anchors(doc) == {"keys-and-byok", "make-targets", "notes", "notes-1"}
