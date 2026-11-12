"""Build the bundled OSHA monitoring data: air-sample summary and IMIS-CAS crosswalk.

Summary mode (default). OSHA publishes its Chemical Exposure Health Data (CEHD) as one ZIP per
year, with no API. Each ZIP holds one CSV of inspection samples (the delimiter, quoting and
byte-order mark differ by year; they are detected). A row is kept only when it is a personal
sample (``SAMPLE_TYPE`` P), not a blank (``BLANK_SAMPLE`` is not Y and the qualifier does not
hold the blank marker), its unit code is in ``[osha_cehd.units]`` (mg/m^3 or ppm), its result
is a finite number >= 0 and its sampling time is positive. Every other row is skipped and counted
by reason; the build never stops for a row. Rows with the same (SAMPLING_NUMBER, IMIS substance
code, unit) become one value, their average weighted by ``TIME_SAMPLED`` (a non-detect only if
every row is one). For each (IMIS code, NAICS prefix of each configured length, unit) the file
holds the number of values, the number of non-detects, the median, the 95th percentile and the
first and last year sampled. Non-detects enter the statistics at their reported value. Units are
never converted here. Percentiles use linear interpolation between order statistics (the
default of ``numpy.percentile``, ``statistics.quantiles(method="inclusive")``): the p-th
percentile of n sorted values sits at zero-based position p * (n - 1).

Crosswalk mode (``--crosswalk``). Walks OSHA's Occupational Chemical Database listing
(https://www.osha.gov/chemicaldata/search), whose rows state a chemical's CAS number and its
analyte code(s) (IMIS no.). Only pairs OSHA states on one row are kept; a row without a valid
CAS number (format and check digit) is left out, an IMIS code claimed by two different CAS
numbers is dropped, and nothing is ever matched by name.

Usage: ``uv run python -m scripts.build_osha_cehd_summary [--crosswalk]``
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import math
import re
import sys
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from config.osha_cehd import OshaCehdSettings, get_osha_cehd_settings

Fetch = Callable[[str], bytes]
REQUIRED = (
    "SAMPLING_NUMBER",
    "NAICS_CODE",
    "DATE_SAMPLED",
    "SAMPLE_TYPE",
    "BLANK_SAMPLE",
    "TIME_SAMPLED",
    "IMIS_SUBSTANCE_CODE",
    "SAMPLE_RESULT",
    "UNIT_OF_MEASUREMENT",
    "QUALIFIER",
)
MAX_MEMBER_BYTES = 200_000_000
MAX_PAGES = 200
YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
NAICS = re.compile(r"\d{2,6}")
CAS = re.compile(r"\d{2,7}-\d{2}-\d")
IMIS = re.compile(r"[0-9A-Z]{4}")
SUMMARY_COLUMNS = (
    "imis",
    "naics_prefix",
    "unit",
    "n",
    "n_nd",
    "median",
    "p95",
    "first_year",
    "last_year",
)
CROSSWALK_COLUMNS = ("imis_code", "cas", "substance", "source")
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
LINK = re.compile(r'href="/chemicaldata/(\d+)"[^>]*>(.*?)</a>', re.S)
CELLS = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
ITEM = re.compile(r"<li>(.*?)</li>", re.S)
CHEMICAL_URL = "https://www.osha.gov/chemicaldata/{record}"


@dataclass(frozen=True)
class Sample:
    """One accepted sample row."""

    sampling: str
    imis: str
    naics: str
    unit: str
    minutes: float
    result: float
    nondetect: bool
    year: int


@dataclass
class Group:
    """The samples of one sampling number, substance and unit, being averaged."""

    naics: str
    weighted: float
    minutes: float
    all_nd: bool
    year: int


@dataclass(frozen=True)
class Value:
    """One time-weighted value of a sampling number, substance and unit."""

    imis: str
    naics: str
    unit: str
    result: float
    nondetect: bool
    year: int


@dataclass(frozen=True)
class SummaryRow:
    """One line of the summary file."""

    imis: str
    naics_prefix: str
    unit: str
    n: int
    n_nd: int
    median: float
    p95: float
    first_year: int
    last_year: int


@dataclass
class Report:
    """Rows read, kept and skipped by reason."""

    read: int = 0
    kept: int = 0
    skipped: Counter[str] = field(default_factory=Counter[str])


def percentile(sorted_values: list[float], fraction: float) -> float:
    """The ``fraction`` percentile of ascending ``sorted_values`` by linear interpolation.

    Position is ``fraction * (n - 1)`` (zero-based); this equals ``numpy.percentile``.
    """
    if not sorted_values:
        raise ValueError("no values")
    position = fraction * (len(sorted_values) - 1)
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _number(text: str) -> float | None:
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _year(text: str, default: int) -> int:
    found = YEAR.search(text)
    return int(found.group(1)) if found else default


def _naics(text: str) -> str:
    code = text.strip()
    return code if NAICS.fullmatch(code) else ""


def classify(row: dict[str, str], settings: OshaCehdSettings, file_year: int) -> Sample | str:
    """The accepted sample of ``row``, or the reason it is skipped."""
    if any(column not in row for column in REQUIRED):
        return "row too short"
    qualifier = row["QUALIFIER"].strip().strip(",").upper()
    if row["SAMPLE_TYPE"].strip().upper() != "P":
        return "not a personal sample"
    if row["BLANK_SAMPLE"].strip().upper() == "Y" or settings.blank_marker.upper() in qualifier:
        return "blank sample"
    unit = settings.units.get(row["UNIT_OF_MEASUREMENT"].strip())
    if unit is None:
        return "unit not accepted"
    return _measured(row, settings, unit, qualifier, file_year)


def _measured(
    row: dict[str, str],
    settings: OshaCehdSettings,
    unit: str,
    qualifier: str,
    file_year: int,
) -> Sample | str:
    result, minutes = _number(row["SAMPLE_RESULT"]), _number(row["TIME_SAMPLED"])
    sampling, imis = row["SAMPLING_NUMBER"].strip(), row["IMIS_SUBSTANCE_CODE"].strip()
    if result is None or result < 0:
        return "result not a non-negative number"
    if minutes is None or minutes <= 0:
        return "no positive sampling time"
    if not sampling or not imis:
        return "no sampling number or substance code"
    nondetect = qualifier in {q.upper() for q in settings.nondetect_qualifiers}
    naics, year = _naics(row["NAICS_CODE"]), _year(row["DATE_SAMPLED"], file_year)
    return Sample(sampling, imis, naics, unit, minutes, result, nondetect, year)


def csv_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    """The one CSV file of the ZIP; raises when there is none, several, or it is too large."""
    members = [m for m in archive.infolist() if m.filename.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(f"expected exactly one CSV in the ZIP, found {len(members)}")
    if members[0].file_size > MAX_MEMBER_BYTES:
        raise ValueError(f"{members[0].filename} is larger than {MAX_MEMBER_BYTES} bytes")
    return members[0]


def decode(raw: bytes) -> str:
    """Decode a CSV as UTF-8 (a byte-order mark dropped), else Latin-1."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def dict_rows(text: str) -> Iterator[dict[str, str]]:
    """Rows of a CEHD CSV as header-keyed dicts; the delimiter and line quoting are detected.

    Raises:
        ValueError: If the header lacks a required column.
    """
    first = text.split("\n", 1)[0].strip().strip('"')
    pipe = first.count("|") > first.count(",")
    if pipe:
        lines = [_unquote(line) for line in text.split("\n")]
        reader = csv.reader(lines, delimiter="|", quoting=csv.QUOTE_NONE)
    else:
        reader = csv.reader(io.StringIO(text, newline=""))
    header = [name.strip().strip('"').rstrip(",").upper() for name in next(reader, list[str]())]
    missing = [column for column in REQUIRED if column not in header]
    if missing:
        raise ValueError(f"the CSV header lacks {', '.join(missing)}")
    return (dict(zip(header, fields, strict=False)) for fields in reader if any(fields))


def _unquote(line: str) -> str:
    line = line.rstrip("\r")
    return line[1:-1] if len(line) > 1 and line[0] == line[-1] == '"' else line


def read_year(
    raw_zip: bytes,
    year: int,
    settings: OshaCehdSettings,
    groups: dict[tuple[str, str, str], Group],
    report: Report,
) -> None:
    """Read one year's ZIP into ``groups`` and ``report``."""
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        text = decode(archive.read(csv_member(archive)))
    for row in dict_rows(text):
        report.read += 1
        outcome = classify(row, settings, year)
        if isinstance(outcome, str):
            _count(report, outcome)
        else:
            report.kept += 1
            add_sample(groups, outcome)


def _count(report: Report, reason: str) -> None:
    report.skipped[reason] += 1


def add_sample(groups: dict[tuple[str, str, str], Group], sample: Sample) -> None:
    """Fold ``sample`` into the group of its sampling number, substance and unit."""
    key = (sample.sampling, sample.imis, sample.unit)
    group = groups.get(key)
    if group is None:
        groups[key] = Group(sample.naics, 0.0, 0.0, True, sample.year)
        group = groups[key]
    group.weighted += sample.result * sample.minutes
    group.minutes += sample.minutes
    group.all_nd = group.all_nd and sample.nondetect
    group.naics = group.naics or sample.naics
    group.year = min(group.year, sample.year)


def collapse(groups: dict[tuple[str, str, str], Group]) -> list[Value]:
    """One time-weighted value per group."""
    return [
        Value(imis, g.naics, unit, g.weighted / g.minutes, g.all_nd, g.year)
        for (_, imis, unit), g in groups.items()
    ]


def summarise(values: Iterable[Value], lengths: tuple[int, ...]) -> list[SummaryRow]:
    """Statistics per (substance, NAICS prefix, unit); a value skips lengths its NAICS lacks."""
    buckets: dict[tuple[str, str, str], list[Value]] = {}
    for value in values:
        for length in lengths:
            if len(value.naics) >= length:
                key = (value.imis, value.naics[:length], value.unit)
                buckets.setdefault(key, []).append(value)
    return [_row(key, members) for key, members in sorted(buckets.items())]


def _row(key: tuple[str, str, str], members: list[Value]) -> SummaryRow:
    results = sorted(v.result for v in members)
    years = [v.year for v in members]
    return SummaryRow(
        key[0],
        key[1],
        key[2],
        len(members),
        sum(v.nondetect for v in members),
        percentile(results, 0.5),
        percentile(results, 0.95),
        min(years),
        max(years),
    )


def write_summary(
    rows: list[SummaryRow],
    output: Path,
    years: tuple[int, int],
    built: date,
) -> None:
    """Write the summary: a ``#`` comment line with window and date, then a CSV."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            f"# OSHA CEHD personal air samples, years {years[0]}-{years[1]}, built {built}\n",
        )
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(SUMMARY_COLUMNS)
        for r in rows:
            fields = (
                r.imis,
                r.naics_prefix,
                r.unit,
                r.n,
                r.n_nd,
                f"{r.median:.6g}",
                f"{r.p95:.6g}",
            )
            writer.writerow((*fields, r.first_year, r.last_year))


def build_summary(settings: OshaCehdSettings, fetch: Fetch, built: date) -> Report:
    """Download every configured year, summarise, write the file and return the report."""
    groups: dict[tuple[str, str, str], Group] = {}
    report = Report()
    for year in settings.years:
        read_year(fetch(settings.url_pattern.format(year=year)), year, settings, groups, report)
    rows = summarise(collapse(groups), settings.naics_prefix_lengths)
    write_summary(rows, settings.summary_path, (settings.years[0], settings.years[-1]), built)
    return report


def cas_is_valid(text: str) -> bool:
    """Whether ``text`` is a CAS number: the format and the check digit."""
    if not CAS.fullmatch(text):
        return False
    digits = text.replace("-", "")
    total = sum(int(d) * w for w, d in enumerate(reversed(digits[:-1]), start=1))
    return total % 10 == int(digits[-1])


def _text(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def listing_rows(page: str) -> list[tuple[str, str, str, list[str]]]:
    """(record id, substance, CAS text, IMIS codes) of each row of an OSHA listing page."""
    out: list[tuple[str, str, str, list[str]]] = []
    for row in ROW.findall(page):
        link, cells = LINK.search(row), CELLS.findall(row)
        if link is not None and len(cells) >= 3:
            codes = [_text(item) for item in ITEM.findall(cells[2])]
            out.append(
                (link.group(1), _text(link.group(2)), _text(cells[1]), [c for c in codes if c]),
            )
    return out


def crosswalk_pairs(
    fetch: Fetch,
    settings: OshaCehdSettings,
    skipped: Counter[str],
) -> Iterator[tuple[str, str, str, str]]:
    """(IMIS code, CAS, substance, source URL) pairs OSHA states, page after page.

    Entries that are not a clean pair (no valid CAS number, an analyte code with a note such
    as "(total); request using analyte code 9135") are left out and counted in ``skipped``.
    """
    for number in range(MAX_PAGES):
        rows = listing_rows(fetch(settings.crosswalk_url_pattern.format(page=number)).decode())
        if not rows:
            return
        for record, name, cas, codes in rows:
            for code in codes or [""]:
                reason = _pair_problem(code, cas)
                if reason:
                    skipped[reason] += 1
                else:
                    yield code, cas, name, CHEMICAL_URL.format(record=record)


def _pair_problem(code: str, cas: str) -> str:
    if not cas_is_valid(cas):
        return "no valid CAS number"
    return "" if IMIS.fullmatch(code) else "analyte code is not a plain four-character code"


def unambiguous(pairs: Iterable[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    """The pairs, sorted, without an IMIS code that OSHA gives two different CAS numbers."""
    by_code: dict[str, set[str]] = {}
    unique = sorted(set(pairs))
    for code, cas, _, _ in unique:
        by_code.setdefault(code, set()).add(cas)
    return [p for p in unique if len(by_code[p[0]]) == 1]


def build_crosswalk(settings: OshaCehdSettings, fetch: Fetch, skipped: Counter[str]) -> int:
    """Build and write the crosswalk; returns the number of pairs written."""
    pairs = unambiguous(crosswalk_pairs(fetch, settings, skipped))
    settings.crosswalk_path.parent.mkdir(parents=True, exist_ok=True)
    with settings.crosswalk_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CROSSWALK_COLUMNS)
        writer.writerows(pairs)
    return len(pairs)


def http_fetch(settings: OshaCehdSettings) -> Fetch:
    """A fetcher with the configured User-Agent and timeout (built at the outer edge)."""
    client = httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.timeout_s,
        follow_redirects=True,
    )

    def fetch(url: str) -> bytes:
        response = client.get(url)
        response.raise_for_status()
        return response.content

    return fetch


def print_report(report: Report) -> None:
    """Print rows read, kept and skipped by reason."""
    print(f"rows read: {report.read}, kept: {report.kept}")
    for reason, count in sorted(report.skipped.items()):
        print(f"skipped, {reason}: {count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--crosswalk",
        action="store_true",
        help="build the IMIS-CAS crosswalk instead",
    )
    args = parser.parse_args(argv)
    settings = get_osha_cehd_settings()
    fetch = http_fetch(settings)
    if args.crosswalk:
        skipped = Counter[str]()
        print(
            f"wrote {build_crosswalk(settings, fetch, skipped)} pairs to {settings.crosswalk_path}",
        )
        for reason, count in sorted(skipped.items()):
            print(f"left out, {reason}: {count}")
        return 0
    print_report(build_summary(settings, fetch, date.today()))
    print(f"wrote {settings.summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
