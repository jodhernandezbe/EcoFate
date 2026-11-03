"""Exposure metric tool."""

from __future__ import annotations

from langchain_core.tools import tool

from config.exposure import get_exposure_settings
from tools.exposure.helpers.facility import assess_facility
from tools.schemas import FacilityExposure, Meteorology, Population, StackParameters, Toxicity


@tool
def calculate_exposure_metrics(
    emission_rate: float,
    stacks: list[StackParameters],
    meteorology: Meteorology,
    population: Population,
    toxicity: Toxicity,
) -> FacilityExposure:
    """Compute screening-level air concentration, dose and health risk for a facility's stacks.

    Purpose:
        Use this once the source, the release geometry, the weather, the people and the
        toxicity benchmarks are known, to learn how much of the chemical people may breathe
        and how that compares with health benchmarks. It evaluates every stack it is given in
        one call: pass ALL of a facility's candidate stacks together in `stacks` (all the NEI
        candidates exactly as returned, never a subset, never one call per stack; or the one
        SCC-based stack when the NEI has none), and report the `range` it returns with the
        per-stack results. It does not look anything up; every input comes from the other
        tools, exactly as they returned it. One call per facility: each facility has its own
        emission rate, weather and population.

    Scope:
        This is the community (neighbourhood) result only. It does not screen the people who
        work in the plant; that worker screening, from the facility's fugitive release, is
        part of the batch facility assessment, which gives both results for every facility. A
        complete assessment of a chemical therefore comes from the batch assessment, not from
        this tool alone; use this one when a single facility's community result is what is
        needed with inputs you already hold, and say that the worker result was not computed.

    Method:
        The U.S. EPA SCREEN3 screening procedure, flat terrain, rural dispersion, no building
        downwash, no mixing-height limit, one source, no deposition or chemistry. The WORST
        CASE is the highest ground-level centerline concentration over EPA's 54 combinations
        of stability class and 10 m wind speed and over distances from 100 m to 10 km; the
        REPRESENTATIVE case uses only the weather you pass in. The 1-hour maximum is turned
        into an annual average with EPA's screening factor before it is compared with chronic
        benchmarks. The worst case may fall where nobody lives; it is a screening bound, not
        a prediction for a place.

    Args:
        emission_rate: The facility's emission rate, g/s (the `emission_rate` of the
            emissions inventory).
        stacks: Every candidate stack of the facility, each with `stack_height` (m),
            `stack_diameter` (m), `exit_velocity` (m/s) and `exit_temperature` (K): the whole
            `candidates` list of the NEI result, or a one-item list with the SCC-based
            (generic) stack. A stack with a null value cannot be used; it gets a null result
            and the others are still evaluated.
        meteorology: The meteorology result: 10 m `wind_speed` (m/s), `stability_class`,
            `ambient_temperature` (K), with its `source`.
        population: The population result: `age_distribution` (percent per age band) with its
            `source`. It selects which age bands get a dose.
        toxicity: `rfc` (mg/m3) and `iur` ((ug/m3)^-1) from the chemical properties; either
            may be null, and the matching risk is then null.

    Returns:
        A dict with:
        - results: one entry per stack, in the order given, numbered by `stack_number` (from
          1) and echoing its four stack values, each with, for the WORST CASE:
          - max_concentration: annual-average ground-level concentration at the maximum, ug/m3
          - max_concentration_1h: the 1-hour maximum, ug/m3
          - distance_m, stability_class, wind_speed (10 m, m/s), effective_release_height
            (m): where and under which weather the maximum occurs
          - hq: hazard quotient (annual exposure concentration / RfC); above 1 means the
            exposure exceeds the non-cancer benchmark
          - cancer_risk: lifetime excess cancer risk (exposure concentration x IUR); 1e-6 is
            one in a million
          - add: average daily dose of the most exposed age band, mg/(kg*day); add_band names
            it and add_by_band gives every band that has residents. Doses differ by age
            (children breathe more per kg); hq and cancer_risk do not, because the RfC and IUR
            are concentration-based.
          - representative: the same concentration, distance, class, wind, height, hq and
            cancer_risk fields for the representative weather (it does not exceed the worst
            case)
          - stack_source and warnings (see below)
        - range: for max_concentration (ug/m3), hq and cancer_risk, the `low` and `high`
          value over the stacks and the `low_stack` and `high_stack` behind each; an entry is
          null when no stack has that quantity, and `range` is null when no stack could be
          evaluated; `range.representative` holds the same three ranges for the
          representative weather. This is the range to report, worst case and representative
          case side by side.
        - stacks_given, stacks_evaluated: how many stacks were passed and how many have a
          result
        - warnings: facility-level notes, such as stacks that could not be evaluated.
        A null number means it could not be computed, and the warnings say why (missing stack
        value, missing RfC or IUR, invalid input); nothing is ever defaulted or guessed, so a
        null must be reported, not filled in. In each result, `stack_source` echoes where the stack
        came from; a stack that is the EPA global default or a process default is generic (short,
        cold and slow), so concentrations, hq and cancer_risk can be far higher than for the
        facility's real stack: report that with the numbers. Each result's `warnings` also say
        when the weather or the population input was itself a generic default, when the
        maximum is at the edge of the range, and that the worst case may be where nobody
        lives; pass these on.
        These are screening estimates, not regulatory determinations.
    """
    return assess_facility(
        emission_rate,
        stacks,
        meteorology,
        population,
        toxicity,
        get_exposure_settings(),
    )
