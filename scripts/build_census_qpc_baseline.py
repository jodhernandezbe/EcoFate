"""Build the plant-hours baseline from the Census Bureau's plant capacity utilization survey (QPC).

Downloads the workbook of the release two quarters behind the current one (``[qpc].lag_quarters``),
reads "Average plant hours per week in operation" from the "FULL Utilization Rates" tab, and
writes one row per four-digit NAICS code to ``[qpc].output_path``. A four-digit code gets a value
only when one published row covers it entirely; finer rows, aggregates, withheld cells and
implausible values are listed and left out, never guessed. Nothing is written unless every check
passes, and the write replaces the old file atomically.

Usage: ``uv run python -m scripts.build_census_qpc_baseline [-o output]``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from config.industry import get_industry_settings
from config.qpc import QpcSettings, get_qpc_settings
from scripts.qpc.download import fetch_workbook
from scripts.qpc.errors import QpcDataError, QpcError
from scripts.qpc.output import Provenance, write_baseline
from scripts.qpc.release import Release, release_for, release_url
from scripts.qpc.table import Extraction, check_edition, extract
from scripts.qpc.workbook import read_sheets

THREE_DIGITS = 3
FOUR_DIGITS = 4


def load_children(
    path: Path,
    code_column: str,
    vintage_column: str,
    edition: int,
) -> dict[str, tuple[str, ...]]:
    """Three-digit code -> its four-digit codes in ``edition``, from the NAICS titles table."""
    try:
        handle = path.open(encoding="utf-8", newline="")
    except OSError as error:
        raise QpcDataError(
            f"cannot read {path} (run scripts.build_naics_titles): {error}",
        ) from error
    found: dict[str, set[str]] = {}
    with handle:
        for row in csv.DictReader(handle):
            code = (row.get(code_column) or "").strip()
            if row.get(vintage_column) == str(edition) and len(code) >= FOUR_DIGITS:
                found.setdefault(code[:THREE_DIGITS], set()).add(code[:FOUR_DIGITS])
    return {three: tuple(sorted(fours)) for three, fours in found.items()}


def build(
    settings: QpcSettings,
    release: Release,
    workbook: bytes,
    children: dict[str, tuple[str, ...]],
) -> Extraction:
    """Read and validate the workbook; returns what to write and what was left out."""
    sheets = read_sheets(
        workbook,
        (settings.sheet_name, settings.intro_sheet_name),
        settings.max_bytes,
    )
    check_edition(sheets[settings.intro_sheet_name], settings)
    return extract(sheets[settings.sheet_name], release, settings, children)


def _report(
    release: Release,
    url: str,
    digest: str,
    extraction: Extraction,
    output: Path,
) -> None:
    count = sum(len(e.codes) for e in extraction.entries)
    print(f"QPC {release.label} {url} sha256={digest[:12]}")
    print(f"wrote {count} four-digit codes from {len(extraction.entries)} rows to {output}")
    print(f"skipped {len(extraction.skipped)} rows:")
    for s in extraction.skipped:
        print(f"  {s.source_naics or '-':<14} {s.source_title[:48]:<48} {s.reason}")


def run(
    settings: QpcSettings,
    output: Path,
    today: date,
    client: httpx.Client,
    titles_path: Path,
) -> None:
    """Download, validate and write; a `QpcError` is raised before `output` is touched."""
    release = release_for(today, settings.lag_quarters)
    url = release_url(settings.url_template, release)
    data = fetch_workbook(
        url, release, client=client, host=settings.allowed_host,
        timeout=settings.timeout_seconds, max_bytes=settings.max_bytes,
    )  # fmt: skip
    children = load_children(
        titles_path,
        get_industry_settings().titles_code_column,
        settings.titles_vintage_column,
        settings.naics_edition,
    )
    extraction = build(settings, release, data, children)
    digest = hashlib.sha256(data).hexdigest()
    info = Provenance(url, digest, today.isoformat(), settings.naics_edition, settings.sheet_name)
    write_baseline(extraction, release, info, output)
    _report(release, url, digest, extraction, output)


def main(
    argv: list[str] | None = None,
    *,
    today: Callable[[], date] = date.today,
    client: httpx.Client | None = None,
    settings: QpcSettings | None = None,
    titles_path: Path | None = None,
) -> int:
    """Run the build; returns 0, or 1 with the reason on stderr when a check fails."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    settings = settings or get_qpc_settings()
    titles = titles_path or get_industry_settings().titles_path
    parser.add_argument("-o", "--output", type=Path, default=settings.output_path)
    args = parser.parse_args(argv)
    try:
        with client or httpx.Client() as http:
            run(settings, args.output, today(), http, titles)
    except QpcError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
