[← Documentation index](../README.md#documentation) · [Architecture](../docs/architecture.md) · [Tools](../tools/README.md)

# models/

Pure, deterministic NumPy equations: no LLM or LangChain imports, no I/O, no hidden state. Every
function validates its inputs with `ValueError` and states its physical units in its docstring
(for example g/s, mg/m^3, mg/(kg*day)). The tools call these functions; the equations never know
about tools. Rules for coding agents: `models/CLAUDE.md`.

## Contents

- [Modules](#modules)
- [Sources](#sources)
- [Running and testing](#running-and-testing)
- [Adding a model](#adding-a-model)

## Modules

| Folder | Module | What it computes |
|---|---|---|
| `transport/` | `dispersion.py` | Briggs rural dispersion coefficients, the Gaussian plume with ground reflection |
| | `plume_rise.py` | buoyancy flux, final plume rise, stack-tip downwash |
| | `wind_profile.py` | wind speed at a height (power law) |
| | `screening.py` | SCREEN3-style worst case: the maximum ground-level concentration over weather and distance |
| `weather/` | `stability.py` | Pasquill-Gifford stability class |
| | `meteorology.py` | hourly classification and the annual summary (prevailing direction, representative values) |
| `receptors/` | `population.py` | scaling a tract count to a circle, age bands |
| | `geometry.py` | distance and bearing between coordinates |
| `exposure/` | `dose.py` | average and lifetime average daily dose |
| | `inhalation.py` | exposure concentration, dose by age band, hazard quotient and cancer risk from RfC and IUR |
| | `risk.py` | emission rate, hazard quotient, cancer risk |
| | `occupational.py`, `two_zone.py`, `vapor_generation.py` | the worker screening: workplace concentration, 8-hour average, OEL ratio, vapor generation |
| `chemistry/` | `similarity.py` | cosine, Tanimoto and the hybrid read-across score, leave-one-out calibration |
| | `air_units.py` | ppm to mg/m^3 |

Shared type aliases are in `_types.py`.

## Sources

The method references are named in the module docstrings, for example EPA SCREEN3
(EPA-454/B-95-004) and the 1-hour to annual factor (EPA-454/R-92-019) in `transport/screening.py`;
EPA Risk Assessment Guidance for Superfund Part F, the EPA Regional Screening Levels and the 2011
Exposure Factors Handbook in `exposure/inhalation.py`. Constants and their sources are in the
`[exposure]` tables of `config/settings.toml`, not in the equations. The tool-level description of
the method and its limits is in [tools](../tools/README.md#tool-reference).

## Running and testing

Tests mirror the folders under `tests/models/` and need no network:

    uv run pytest tests/models

## Adding a model

Put the module in the folder it belongs to (or a new folder with an `__init__.py` when none fits),
write a pure function with units in the docstring and `ValueError` for invalid inputs, and add its
tests under `tests/models/`. Then call it from a tool; see
[Adding a tool](../tools/README.md#adding-a-tool).
