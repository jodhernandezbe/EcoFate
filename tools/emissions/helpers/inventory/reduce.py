"""Validate TRI release rows and keep the latest reporting year per medium and facility."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple, TypedDict

from commons.units import UnitConversionError
from config.loader import EmissionsSettings, TriSettings
from tools.emissions.helpers.inventory.conditions import Conditions, ConditionsFor, not_requested
from tools.emissions.helpers.inventory.rate import (
    HoursFor,
    OperatingHours,
    fixed_hours,
    to_emission_rate,
)
from tools.schemas import ConditionOfUse, EmissionRecord

Row = Mapping[str, object]
Flags = tuple[tuple[str, str], ...]
"""(``tri_chem_activity`` column, Form R section) pairs."""


@dataclass(frozen=True)
class Location:
    """Facility coordinates, in decimal degrees (north positive, west negative)."""

    latitude: float
    longitude: float


Locator = Callable[[Sequence[str]], Mapping[str, Location]]
"""Gives the coordinates of many FRS IDs at once; an ID it cannot locate is left out."""


@dataclass(frozen=True)
class Place:
    """Descriptive facility fields taken from a report row."""

    name: str | None
    address: str | None
    city: str | None
    county: str | None
    state: str | None
    zip_code: str | None


@dataclass(frozen=True)
class Report:
    """One validated TRI row. ``quantity`` is None unless it is a usable amount with a unit."""

    facility_id: str
    medium: str
    year: int
    doc_ctrl_num: str | None
    quantity: float | None
    unit: str | None
    place: Place
    location: Location | None
    naics_code: str | None = None
    activities: frozenset[str] = frozenset()  # Form R Section 3 items the submission reports
    activity_seen: bool = False  # whether the row carried any activity column


@dataclass
class Slot:
    """What is kept for one (medium, facility): its latest year and best coordinates."""

    year: int
    doc_ctrl_num: str | None  # control number of the kept year's submission (highest, if several)
    naics_code: str | None  # primary NAICS code of that same submission
    quantity: float | None
    unit: str | None
    summed: int  # number of usable quantities added into `quantity`
    place: Place
    location: Location | None
    location_year: int
    activities: frozenset[str] = frozenset()  # union over the latest year's summed reports
    activity_seen: bool = False


class _Resolvers(NamedTuple):
    """The injected per-facility lookups used when a record is built."""

    hours_for: HoursFor
    conditions_for: ConditionsFor | None


class _Amount(NamedTuple):
    """A slot's usable quantity, its unit as reported, and its coordinates."""

    quantity: float
    unit: str
    location: Location


@dataclass
class Stats:
    """Counts of what was dropped or combined, for warnings."""

    skipped_rows: int = 0
    secondary_naics: int = 0
    outside_window: int = 0
    no_quantity: int = 0
    no_location: int = 0
    from_frs: int = 0
    bad_unit: int = 0
    mixed_units: int = 0
    combined: int = 0
    no_activity: int = 0

    def warnings(self) -> list[str]:
        """Return one message per non-zero count."""
        labels = (
            ("skipped_rows", "rows skipped (no facility ID or year, or a medium not configured)"),
            ("secondary_naics", "rows ignored: a secondary NAICS code of a submission kept once"),
            ("outside_window", "rows ignored: reported before the window of recent years"),
            ("no_quantity", "facilities omitted: no usable release quantity in their latest year"),
            ("no_location", "facilities omitted: no usable coordinates in any row"),
            ("from_frs", "facilities located from their FRS record (TRI had no coordinates)"),
            ("bad_unit", "facilities omitted: release unit is not a convertible mass unit"),
            ("mixed_units", "same-year reports ignored: unit differs from the first report"),
            ("combined", "facilities whose latest-year reports were added together"),
            ("no_activity", "rows without TRI activity data (conditions of use unknown)"),
        )
        return [f"{getattr(self, key)} {text}" for key, text in labels if getattr(self, key)]


def _text(value: object) -> str | None:
    """Return ``value`` stripped if it is non-blank text, else None."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _finite(value: object) -> float | None:
    """Return ``value`` as a float if it is a finite number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _year(value: object) -> int | None:
    """Return a reporting year from a digit string or integer, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = _text(value)
    return int(text) if text is not None and text.isascii() and text.isdigit() else None


def _quantity(row: Row, settings: TriSettings) -> tuple[float | None, str | None]:
    """Return (quantity, unit); the quantity is None unless finite, non-negative, with a unit."""
    unit = _text(row.get(settings.fields["unit"]))
    amount = _finite(row.get(settings.fields["quantity"]))
    if unit is None or amount is None or amount < 0:
        return None, unit
    return amount, unit


def _facility_id(row: Row, settings: TriSettings) -> str | None:
    for column in settings.facility_id_fields:
        identifier = _text(row.get(column))
        if identifier is not None:
            return identifier
    return None


def _signed_longitude(magnitude: float, state: str | None, settings: TriSettings) -> float | None:
    """Return the signed longitude, or None when the hemisphere cannot be determined.

    TRI gives western longitudes as positive numbers; only the configured east-of-Greenwich
    states keep a positive sign.
    """
    if state is None:
        return None
    east = {code.upper() for code in settings.east_longitude_states}
    return abs(magnitude) if state.upper() in east else -abs(magnitude)


def _location(row: Row, settings: TriSettings) -> Location | None:
    fields = settings.fields
    latitude = _finite(row.get(fields["latitude"]))
    raw_longitude = _finite(row.get(fields["longitude"]))
    if latitude is None or raw_longitude is None:
        return None
    state = _text(row.get(fields["state"]))
    longitude = _signed_longitude(raw_longitude, state, settings)
    if longitude is None or not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return Location(latitude, longitude)


def _place(row: Row, settings: TriSettings) -> Place:
    def get(key: str) -> str | None:
        return _text(row.get(settings.fields[key]))

    return Place(
        get("facility_name"),
        get("address"),
        get("city"),
        get("county"),
        get("state"),
        get("zip_code"),
    )


def _naics(row: Row, settings: TriSettings) -> str | None:
    """The row's NAICS code: 2 to 6 digits (sector to industry level), else None."""
    value = row.get(settings.fields["naics_code"])
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    code = _text(value)
    return code if code is not None and code.isdigit() and 2 <= len(code) <= 6 else None


def is_secondary_naics(row: Row, settings: TriSettings) -> bool:
    """Whether the row repeats a submission for one of its secondary NAICS codes.

    A row without the indicator (no NAICS row joined) is not secondary and is kept.
    """
    flag = row.get(settings.fields["naics_primary"])
    return flag is not None and str(flag).strip() not in ("1", "")


def _flag_set(value: object) -> bool:
    """Whether a flag column holds the number 1 or the text "1" (never a boolean)."""
    if isinstance(value, bool):
        return False
    return value == 1 or _text(value) == "1"


def _activities(row: Row, flags: Flags) -> tuple[frozenset[str], bool]:
    """The Form R sections whose flag is set, and whether any flag column was sent."""
    seen = any(column in row for column, _ in flags)
    return frozenset(section for column, section in flags if _flag_set(row.get(column))), seen


def _report_key(row: Row, settings: TriSettings) -> tuple[str, str, int] | None:
    """(facility ID, medium, reporting year) of a row, or None if any is missing."""
    facility_id = _facility_id(row, settings)
    medium = _text(row.get(settings.fields["medium"]))
    year = _year(row.get(settings.fields["year"]))
    if facility_id is None or medium is None or year is None:
        return None
    return facility_id, medium, year


def parse_report(row: Row, settings: TriSettings, flags: Flags = ()) -> Report | None:
    """Validate one TRI row.

    Args:
        row: A row of the joined TRI release query (untrusted).
        settings: TRI settings naming the columns to read.
        flags: (activity column, Form R section) pairs to read; none reads no activities.

    Returns:
        The report, or None if the row has no facility ID, medium or reporting year. An
        unusable quantity or location does not drop the row here: it is carried as None.
    """
    key = _report_key(row, settings)
    if key is None:
        return None
    quantity, unit = _quantity(row, settings)
    activities, seen = _activities(row, flags)
    return Report(
        *key,
        _text(row.get(settings.fields["doc_ctrl_num"])),
        quantity,
        unit,
        _place(row, settings),
        _location(row, settings),
        _naics(row, settings),
        activities,
        seen,
    )


def _new_slot(report: Report) -> Slot:
    return Slot(
        year=report.year,
        doc_ctrl_num=report.doc_ctrl_num,
        naics_code=report.naics_code,
        quantity=report.quantity,
        unit=report.unit,
        summed=0 if report.quantity is None else 1,
        place=report.place,
        location=report.location,
        location_year=report.year,
        activities=report.activities,
        activity_seen=report.activity_seen,
    )


def _take_year(slot: Slot, report: Report) -> None:
    """Make ``report`` (a later year) the slot's year-level data."""
    slot.year = report.year
    slot.doc_ctrl_num = report.doc_ctrl_num
    slot.naics_code = report.naics_code
    slot.quantity = report.quantity
    slot.unit = report.unit
    slot.summed = 0 if report.quantity is None else 1
    slot.place = report.place
    slot.activities, slot.activity_seen = report.activities, report.activity_seen


def _keep_highest_submission(slot: Slot, report: Report) -> None:
    """Keep the highest control number of the year's reports, and that submission's NAICS."""
    if report.doc_ctrl_num is not None and (
        slot.doc_ctrl_num is None or report.doc_ctrl_num > slot.doc_ctrl_num
    ):
        slot.doc_ctrl_num, slot.naics_code = report.doc_ctrl_num, report.naics_code
    elif slot.naics_code is None:
        slot.naics_code = report.naics_code


class LatestReports:
    """Folds report rows into one record per (medium, facility) at its latest year.

    Reports of the same facility, medium and year are added together (separate forms with
    different quantities; summing is the conservative choice). Coordinates come from the
    facility's most recent row that has valid ones, since the latest row often lacks them.
    """

    def __init__(self, settings: TriSettings, first_year: int, flags: Flags = ()) -> None:
        """Args: TRI settings; the first reporting year that counts (older rows are ignored);
        the activity flags to read (none reads no activities)."""
        self._settings = settings
        self._read_media = (*settings.media, settings.fugitive_medium)
        self._flags = flags
        self._first_year = first_year
        self._slots: dict[tuple[str, str], Slot] = {}
        self.stats = Stats()

    def add_rows(self, rows: Sequence[Row]) -> None:
        """Fold a page of rows into the running result."""
        for row in rows:
            self._add(row)

    def _add(self, row: Row) -> None:
        if is_secondary_naics(row, self._settings):
            self.stats.secondary_naics += 1
            return
        report = parse_report(row, self._settings, self._flags)
        if report is None or report.medium not in self._read_media:
            self.stats.skipped_rows += 1
            return
        if report.year < self._first_year:
            self.stats.outside_window += 1
            return
        self.stats.no_activity += bool(self._flags) and not report.activity_seen
        key = (report.medium, report.facility_id)
        slot = self._slots.get(key)
        if slot is None:
            self._slots[key] = _new_slot(report)
            return
        self._merge(slot, report)

    def _merge(self, slot: Slot, report: Report) -> None:
        if report.year > slot.year:
            _take_year(slot, report)
        elif report.year == slot.year:
            self._combine(slot, report)
        if report.location is not None and (
            slot.location is None or report.year > slot.location_year
        ):
            slot.location, slot.location_year = report.location, report.year

    def _combine(self, slot: Slot, report: Report) -> None:
        if report.quantity is None:
            return
        if slot.quantity is None:
            slot.quantity, slot.unit, slot.summed = report.quantity, report.unit, 1
            slot.doc_ctrl_num, slot.naics_code = report.doc_ctrl_num, report.naics_code
            slot.activities, slot.activity_seen = report.activities, report.activity_seen
        elif slot.unit != report.unit:
            self.stats.mixed_units += 1
        else:
            slot.quantity += report.quantity
            slot.summed += 1
            slot.activities |= report.activities
            slot.activity_seen = slot.activity_seen or report.activity_seen
            _keep_highest_submission(slot, report)

    def records(
        self,
        emissions: EmissionsSettings,
        aliases: Mapping[str, str] | None = None,
        locate: Locator | None = None,
        hours_for: HoursFor | None = None,
        conditions_for: ConditionsFor | None = None,
    ) -> list[EmissionRecord]:
        """Return the kept records, converting each release to an emission rate.

        Args:
            emissions: Emission-rate assumptions (the default operating hours per year).
            aliases: Source unit spelling -> Pint-parsable unit string.
            locate: Gives the coordinates of many FRS IDs in one call; asked once, and only for
                facilities that have a usable quantity but no coordinates in any TRI row.
            hours_for: Gives a facility's operating hours from its NAICS code; without it every
                facility gets the default hours of ``emissions``.
            conditions_for: Gives a facility's TSCA conditions of use from its activities;
                without it the records have none and say so.

        Returns:
            One record per (medium, facility) with a usable latest-year quantity and
            coordinates; the others are counted in ``stats``.
        """
        resolvers = _Resolvers(hours_for or fixed_hours(emissions), conditions_for)
        located = self._locate_missing(locate)
        found = (
            self._record(key, slot, resolvers, aliases, located)
            for key, slot in self._slots.items()
        )
        records = [record for record in found if record is not None]
        self.stats.combined = sum(slot.summed > 1 for slot in self._slots.values())
        return records

    def _locate_missing(self, locate: Locator | None) -> Mapping[str, Location]:
        """Ask ``locate`` once for every facility with a usable quantity but no coordinates."""
        missing = list(
            dict.fromkeys(
                key[1]
                for key, slot in self._slots.items()
                if slot.location is None and slot.quantity is not None and slot.unit is not None
            ),
        )
        return locate(missing) if locate is not None and missing else {}

    def _located(
        self,
        facility_id: str,
        slot: Slot,
        located: Mapping[str, Location],
    ) -> Location | None:
        """Return the slot's coordinates, or those ``locate`` found when TRI gave none."""
        if slot.location is not None:
            return slot.location
        found = located.get(facility_id)
        if found is None:
            self.stats.no_location += 1
        else:
            self.stats.from_frs += 1
        return found

    def _amount(
        self,
        facility_id: str,
        slot: Slot,
        located: Mapping[str, Location],
    ) -> _Amount | None:
        """Return the slot's quantity, unit and location, or count why it is unusable."""
        if slot.quantity is None or slot.unit is None:
            self.stats.no_quantity += 1
            return None
        location = self._located(facility_id, slot, located)
        return None if location is None else _Amount(slot.quantity, slot.unit, location)

    def _record(
        self,
        key: tuple[str, str],
        slot: Slot,
        resolvers: _Resolvers,
        aliases: Mapping[str, str] | None,
        located: Mapping[str, Location],
    ) -> EmissionRecord | None:
        amount = self._amount(key[1], slot, located)
        if amount is None:
            return None
        hours = resolvers.hours_for(slot.naics_code)
        try:
            rate = to_emission_rate(amount.quantity, amount.unit, hours.hours_per_year, aliases)
        except UnitConversionError:
            self.stats.bad_unit += 1
            return None
        return EmissionRecord(
            **_reported(key, slot, amount, rate, hours),
            **_conditions(slot, resolvers.conditions_for),
            **_where(slot.place, amount.location),
        )


class _Industry(TypedDict):
    naics_code: str | None
    naics_title: str | None
    naics_subsector: str | None
    naics_subsector_title: str | None


class _Reported(_Industry):
    frs_id: str
    facility_name: str | None
    environmental_medium: str
    reporting_year: int
    doc_ctrl_num: str | None
    eis_ids: list[str]
    eis_note: str | None
    total_release: float
    unit: str
    emission_rate: float
    operating_hours_per_year: float
    operating_hours_source: str
    fugitive_release_kg_per_year: float | None
    fugitive_reporting_year: int | None


class _Conditions(TypedDict):
    conditions_of_use: list[ConditionOfUse]
    lifecycle_stages: list[str]
    conditions_note: str | None


class _Where(TypedDict):
    latitude: float
    longitude: float
    address: str | None
    city: str | None
    county: str | None
    state: str | None
    zip_code: str | None


def _industry(slot: Slot) -> _Industry:
    """The code; the titles are filled by the tool from the local Census tables."""
    return {
        "naics_code": slot.naics_code,
        "naics_title": None,
        "naics_subsector": None,
        "naics_subsector_title": None,
    }


def _reported(
    key: tuple[str, str],
    slot: Slot,
    amount: _Amount,
    rate: float,
    hours: OperatingHours,
) -> _Reported:
    medium, facility_id = key
    return {
        "frs_id": facility_id,
        "facility_name": slot.place.name,
        "environmental_medium": medium,
        "reporting_year": slot.year,
        "doc_ctrl_num": slot.doc_ctrl_num,
        **_industry(slot),
        "eis_ids": [],  # filled by the tool for the listed facilities
        "eis_note": None,
        "total_release": amount.quantity,
        "unit": amount.unit,
        "emission_rate": rate,
        "operating_hours_per_year": hours.hours_per_year,
        "operating_hours_source": hours.source,
        "fugitive_release_kg_per_year": None,  # filled by the lookup from the fugitive medium
        "fugitive_reporting_year": None,
    }


def _conditions(slot: Slot, conditions_for: ConditionsFor | None) -> _Conditions:
    found: Conditions = (
        not_requested()
        if conditions_for is None
        else conditions_for(slot.activities, slot.activity_seen)
    )
    return {
        "conditions_of_use": found.conditions_of_use,
        "lifecycle_stages": found.lifecycle_stages,
        "conditions_note": found.note,
    }


def _where(place: Place, location: Location) -> _Where:
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "address": place.address,
        "city": place.city,
        "county": place.county,
        "state": place.state,
        "zip_code": place.zip_code,
    }
