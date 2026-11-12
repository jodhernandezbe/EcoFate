"""What the worker screening needs about the chemical, and the tables it reads."""

from __future__ import annotations

from dataclasses import dataclass

from config.ecetoc_tra import EcetocTraSettings, get_ecetoc_tra_settings
from config.occupational import OccupationalSettings
from config.osha_cehd import OshaCehdSettings, get_osha_cehd_settings
from tools.assessment.helpers.activities.crosswalk import Crosswalk, get_crosswalk
from tools.assessment.helpers.monitoring.cehd import MonitoringTable, get_table
from tools.assessment.helpers.occupational_bands.ecetoc import TraTable, load_table
from tools.schemas import OccupationalLimits


@dataclass(frozen=True)
class Workplace:
    """The chemical, beyond the facility, as already resolved by the properties lookup.

    Attributes:
        settings: Activities, volatility range, breathing volumes, worker schedule.
        limits: The chemical's occupational limits from PubChem (mg/m^3).
        cas: The chemical's CAS number, or None; checked before it reaches the monitoring data.
        molecular_weight: Molecular weight, g/mol, or None.
        molecular_weight_source: Where it came from, or None.
        vapor_pressure_mmhg: Vapor pressure, mmHg at about 25 degC, or None.
        vapor_pressure_source: Where it came from, or None.
    """

    settings: OccupationalSettings
    limits: OccupationalLimits
    cas: str | None
    molecular_weight: float | None
    molecular_weight_source: str | None
    vapor_pressure_mmhg: float | None
    vapor_pressure_source: str | None


@dataclass(frozen=True)
class Sources:
    """The tables and settings the screening reads (injected; the defaults are the bundled ones).

    Attributes:
        crosswalk: Sector and stage to generic scenarios.
        tra_table: ECETOC TRA tier-1 estimates.
        tra_settings: Their settings.
        osha_settings: The OSHA monitoring settings.
        monitoring: The monitoring table, or None for the configured files.
    """

    crosswalk: Crosswalk
    tra_table: TraTable
    tra_settings: EcetocTraSettings
    osha_settings: OshaCehdSettings
    monitoring: MonitoringTable | None = None


def default_sources() -> Sources:
    """The bundled tables and the configured settings (the outer edge builds the defaults)."""
    tra = get_ecetoc_tra_settings()
    return Sources(
        get_crosswalk(),
        load_table(tra.table_path),
        tra,
        get_osha_cehd_settings(),
        get_table(),
    )


def no_limits(reason: str) -> OccupationalLimits:
    """Occupational limits with nothing in them, for a chemical that was not looked up."""
    return OccupationalLimits(
        oel_twa_mg_m3=None,
        oel_source=None,
        limits={},
        reasons={},
        warnings=[reason],
    )
