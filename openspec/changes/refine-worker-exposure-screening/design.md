## Context

See proposal.md for why. Today `tools/assessment/helpers/occupational.py` feeds the TRI `AIR FUG`
total into `models/exposure/occupational.generation_rate`, runs a one-room box at two ventilation
tiers, and classifies with `risk_tier` into "exceedance / elevated / acceptable" from
`[occupational.thresholds]`. The community scenario uses "at or above threshold / below threshold"
(`scenarios/community.py`) and the exposure graph maps both onto "below / near / above"
(`config/exposure_graph.py`, `api/services/exposure_graph/worker.py`). The Form R activity flags
(`[conditions_of_use.flags]`), the CDR sector and the chemical's molecular weight and vapor pressure
are already resolved per assessment, so the new source term needs no new request.

Equations and defaults were checked against the EPA ChemSTEER User Guide (updated May 2015),
pages 161-180 (AP-42 Loading, Mass Transfer Coefficient and Penetration models, Tables A-2 to A-4b)
and 274-281 (Mass Balance Inhalation Model, Tables B-2 to B-2d). OSHA CEHD fields were checked on
OSHA's field definitions page and on the 2022 yearly file: there is a NAICS code, a sample type
(P = personal), a sampling time in minutes, a result with a unit code (M = mg/m^3, P = ppm, and
others such as X, Y, % that are not air concentrations) and a qualifier (about half the rows are
ND), and no CAS number. There is no API for this data: the Department of Labor API
(`apiprod.dol.gov/v4`) lists 45 datasets, 11 of them OSHA (inspections, violations, accidents),
none with sampling results. The yearly ZIPs download with a browser user agent; OSHA's HTML pages
answered 403 to a plain client.

## Goals / Non-Goals

**Goals:**
- One band definition for both pathways, in `models/` (pure) with boundaries in `config/`.
- A worker source term that is a task's vapor generation, with ChemSTEER's own defaults.
- Measured data ahead of models, with the model kept beside it for comparison.
- Remove whatever the change makes dead, in the same change.

**Non-Goals:**
- Monte Carlo, dermal or particulate exposure; equipment-specific emission factors (degreasers).
- Per-facility ventilation, throughput or concentration of the chemical in the material.
- Higher ECETOC tiers, Stoffenmanager or ART.
- Changing the community dispersion or dose; only its band wording and the shared boundaries.

## Decisions

### D1. Bands live in `commons/bands.py`, boundaries in `[risk_bands]`
`band_of(value, lower, upper)` and `highest_band([(value, lower, upper), ...])` return "high" /
"moderate" / "low" / None. They are in `commons/` (generic, pure, boundaries passed in) because
both `tools` (the worker band) and `api` (the community status in the projectors) need them, and
`api` must not import `models`. A value **at** a boundary goes to the higher band (today's worker
tier uses strict `>`; the community scenario already uses `>=`). One `config/risk_bands.py`
loader serves `tools`, the projectors and the client settings. `[occupational.thresholds]` and
`[ui.thresholds]` are deleted; `[ui.thresholds]` had the community HQ "near" band start at 0.5,
so the community moderate band now starts at 0.1, the same line the screening already uses.
*Alternative:* keep separate threshold blocks; rejected, the user wants the same three bands and
the boundaries must change together.

### D2. Vapor generation in a new pure module `models/exposure/vapor_generation.py`
Three functions (AP-42 loading, penetration, mass transfer coefficient) and
`saturation_concentration`, with the constants of the guide. `occupational.workplace_concentration`
takes the generation rate in g/s and the saturation concentration, and returns the capped value with
a flag. `generation_rate` (annual release to mg/s) is deleted. *Alternative:* cap only in the tool;
rejected, the cap is part of the ChemSTEER mass balance equation (Cv is the lesser of the two).

### D3. Activities are chosen by walking NAICS to CDR sector to generic scenario, with the TRI stage
The user's direction. The walk uses what the project already resolves per facility:

1. Primary NAICS to CDR industrial sector (IS1 to IS48): existing `data/cdr_naics_industrial_sector.csv`.
2. Sector and TSCA life cycle stage to an EPA generic scenario or OECD emission scenario document
   and its worker activities: a new bundled crosswalk `data/cdr_sector_generic_scenarios.csv`
   (`is_code, lifecycle_stage, scenario_title, document, activity_keys, source`). EPA publishes no
   such crosswalk, so it is curated here: each row is transcribed from the occupational exposure
   section of the cited document, and a sector with no applicable document has no row (never
   inferred). The user reviews the table before it ships (task 3.2).
   Built from the 60 documents of EPA's "Scenarios Documents for Screening Level Exposure and
   Release Assessment" (2019): 19 documents, 25 sectors, 48 rows. An activity is kept only where
   the document describes inhalation exposure during it (page cited); dermal-only and non-volatile
   scopes are left out. Several documents can apply to one sector and stage (e.g. machinery makers
   may degrease, coat and glue): the facility gets the union of their activities (with the generic
   operation's) and every document is named, because TRI does not say which of those uses this chemical has.
3. The stage comes from the facility's Form R Section 3 flags through the existing conditions-of-use
   crosswalk (Manufacturing, Processing, Industrial use). Only rows of the facility's stages apply.
4. Always included (the user's decision, 2026-11-12): ChemSTEER's generic operation of each stage,
   in configuration (`[occupational.stage_activities]`): Manufacturing handles the product (load
   drums, load tank trucks, sample, clean equipment); Processing and Use handle the raw material
   (unload drums, unload tank trucks, sample, clean equipment), Processing also loading its product.
   This follows the guide's definition of the three operation types and their raw material/product basis.
   A scenario row adds its activities to these and never removes one, so a document that discusses
   only drum unloading (e.g. papermaking) does not drop sampling or cleaning.

The result names the route ("generic scenario: <title>" or "ChemSTEER generic <stage> operation").
`[occupational.activities.<key>]` holds each activity's label, model, setting, hours and
typical/worst-case parameters. Container activities have hours = 8 (no throughput in TRI), stated as
an assumption. X = 1 (pure chemical). *Alternatives:* a table straight from Form R flags to
activities (my first draft; rejected by the user as less grounded than the sector walk); all
activities for every facility (rejected, it ignores what the site does).

### D4. Volatility range and ECETOC TRA
`[occupational.volatility]` holds `low_torr = 0.001`, `high_torr = 35` (ChemSTEER's AVPlow/AVPhigh).
Above the range: AP-42 loading is unaffected; evaporation activities use the ECETOC TRA tier-1
worker inhalation table (industrial, no LEV) by PROC and volatility band when the activity has a
`proc` key (sampling = PROC 8a, equipment cleaning = PROC 8a; final mapping checked against the
ECETOC TR 114 / TRA documentation during task 3.5), else the capped ChemSTEER value with a warning.
The ECETOC values must be transcribed from the published ECETOC documentation and cited in the CSV
header; if the published table cannot be obtained during implementation, the ECETOC part is not
built and the fallback applies everywhere (the spec allows "no estimate, with the reason"). Raise
this with the user rather than estimating numbers.

### D5. OSHA CEHD is a bundled summary built by a script
`scripts/build_osha_cehd_summary.py` downloads the yearly ZIPs for `[osha_cehd].years` (config),
parses the CSV inside each (verified on the 2022 file: one CSV of 33,179 rows with the columns
`NAICS_CODE`, `SAMPLING_NUMBER`, `SAMPLE_TYPE`, `BLANK_SAMPLE`, `TIME_SAMPLED`,
`IMIS_SUBSTANCE_CODE`, `SAMPLE_RESULT`, `UNIT_OF_MEASUREMENT`, `QUALIFIER`; older years may be XML
and are outside the window), filters personal non-blank samples in M or P units,
collapses per sampling number with a time-weighted average, and writes
`data/osha_cehd_summary.csv` (imis, naics_prefix, unit, n, n_nd, median, p95, first_year,
last_year) plus a header line with the window and build date. Non-detects (qualifier ND) enter the
percentile at their reported value and are counted; a median that is ND is reported as below
detection. The IMIS-to-CAS crosswalk `data/osha_imis_cas.csv` is built by the same script from
OSHA's Chemical Sampling Information pages (the substance list carries CAS numbers); a substance
without a CAS is left out. A runtime reader in `tools/assessment/helpers/monitoring/` reads both
files once (cached, copies returned). *Alternative:* download at runtime; rejected, it adds an
external dependency and seconds to a turn for data that changes yearly.

### D6. Evidence hierarchy in the tool helper
`occupational_exposure()` computes activities, looks up monitoring, and picks the headline
(monitoring, else driving activity). The result shape gains `evidence`, `activities`,
`driving_activity`, `monitoring`, `molecular_weight`, `volatility`; `VentilationTier` becomes
`WorkerCase` (setting, airflow, mixing factor, generation rate, concentration, capped, TWA, ratio,
HQ, risk, band) for `baseline` and `worst_case`. `fugitive_release_kg_per_year` stays as context.
Functions stay under 18 lines by splitting into `helpers/occupational/` (activities, monitoring,
headline, result) replacing the single module.

### D7. Fugitive-only facilities are assessed for workers
The user's decision. A facility with an `AIR FUG` row and no stack row is no longer dropped by
`fold_fugitive`: it becomes a record with no stack release, marked `worker_only`. It gets the worker
result and no community result (no stack, no dispersion, no screening bound, no population or
weather request); it is not counted among the screened or screened-out facilities and has its own
count in the summary. The stack emission rate and every stack-source list stay as they are. On the
map its marker has no community fill (an outlined marker) and the worker ring. `max_listed` and the
safety bounds apply to the stack facilities first; worker-only facilities are capped separately by a
configured number, largest fugitive release first, with what was left over reported.

### D10. Screened-out facilities keep their worker result
The user's decision, made after the first live run: 14 of the 15 Texas dichloromethane stack
facilities were screened out for the community and so had no worker figure, although the worker
result no longer depends on the stack (it comes from monitoring in the industry or from the
modelled activities). The worker screening now runs for every screened-out facility after the
tiers (`helpers/screened_workers.py`); the community stages, values, reasons and counts are
unchanged. `ScreenedOut` gains `occupational_exposure` and `operational_profile` (absent in saved
threads of an earlier form, which the projector reads as no worker result). The model reads each
screened-out summary's worker band, the band counts (`screened_out_worker_bands`, with
"not computed") and the one with the highest worker value (`screened_out_worker_highest`), ranked
like the worker-only facilities (band, then worst-case 8-hour average). On the dashboard nothing new
is drawn: the facility already shows any worker result it carries; the indoor Risk by group ranks
every facility with a worker result, and its "assessed" count there means "with a worker result".
Facilities beyond the refine safety bound (`not_assessed`) still get none; they are rare and carry
their reason. *Alternative:* a separate follow-up change (my first suggestion; the user chose to
include it here). The tool description is deliberately left unchanged: describing the new fields in it dropped
the chemical-name-only eval from 10/10 to 1/10 (2/5 with the Returns lines alone), so the model learns
of the screened-out workers from the result's `note`, which the description already says to report.

### D8. Boilerplate is executed by Sonnet 5.5 sub-agents; the main session coordinates
The user's instruction. The main session coordinates, reviews every diff and keeps the work that
needs judgement: checking equations and constants against the EPA guide (2.1, 2.2), the curated
data tables (3.2, 3.5, 4.3), the evidence hierarchy and activity selection logic (5.2 to 5.4), the
prompt wording (1.9, 9.1), the evals and the final gates (9.2 to 9.4). Boilerplate goes to
`general-purpose` agents with `model: "sonnet"` (Sonnet 5.5), each given the spec files, the design
decision and the files to touch: configuration blocks and typed loaders, schema and type plumbing,
projectors, exposure graph text, frontend wiring and fixtures, test scaffolding, renames and the
removal of dead code. Groups that do not share files run in parallel (2, 3 and 4 after 1; 6 and 7
after 5; 8 after 7). The main session runs `make check` after each group and before the next
starts, and runs the security audit at the end.

### D9. Two-zone (near-field/far-field) model for indoor open-surface activities
The user asked to include it. ChemSTEER itself has the EPA/OPPT Near-Field/Far-Field Inhalation
Exposure Model (guide pages 320-323, Table B-11a to B-11c), so its equations and defaults are used
as printed: near field 3.05 x 3.05 x 1.83 m, near-field air speed 360 m/h, far-field volume 300 m^3
(low end) or 2,000 m^3 (high end), air exchange rate 2 or 15 per hour, QNF = 0.5 x FSA x velocity,
QFF = VFF x AER, and the time-weighted near-field concentration over the activity's hours starting
from zero (it tends to G x (1/QFF + 1/QNF) for long activities). It goes in
`models/exposure/two_zone.py`. It is the estimator of indoor evaporation activities (sampling);
baseline uses the high-end room (2,000 m^3, 15/h), worst case the low-end room (300 m^3, 2/h). The
worker is taken to be in the near field. It is fed by the same vapor generation rate, so above 35
torr the ECETOC rule of D4 still comes first and the two-zone value is the fallback, capped at
saturation with the warning. Outdoor and container activities keep the mass balance, as in ChemSTEER.
*Alternative:* EPA's degreasing two-zone models with unit emission factors; not possible, TRI does
not say what equipment a facility has.

## Risks / Trade-offs

- [The sector-to-scenario crosswalk is curated, not an EPA table] → every row cites its document,
  the user reviews it before it ships, the result names the route, and every activity is listed.
- [Worker-only facilities enlarge the inventory] → separate cap and count; stack lists and the
  community screening are untouched (tests assert the stack numbers are unchanged).
- [Modelled values can still be high for volatile chemicals] → saturation cap, ECETOC band for
  evaporation, monitoring first; the band reads "screening priority".
- [OSHA inspections are targeted, not representative] → stated on every monitoring result; minimum
  sample count in config; the model shown beside it.
- [ECETOC values cannot be invented] → only transcribed from the source; otherwise the feature is
  left out with a reason (D4).
- [Breaking result shape and tier values] → API schema, generated types, fixtures, visual
  references and eval cassettes are updated in the same change; the evals are rerun 3x.
- [OSHA XML is external data] → parsed with entity expansion disabled, every field validated,
  malformed rows counted and skipped.

## Migration Plan

No stored data holds worker tiers except saved thread workspaces in PostgreSQL. Old workspaces keep
their old values; the frontend must render an unknown band as "not reported" rather than crash
(covered by a test). No database migration. Rollback is a revert of the change.

## Open Questions

- The exact ECETOC TRA PROC mapping for sampling and equipment cleaning (8a vs 8b) is confirmed from
  the ECETOC documentation during task 3.5; it does not change the specs.
- The minimum sample count and NAICS prefix lengths start at 5 values and 6/4/3 digits; they are
  configuration and can be tuned after looking at the built summary.
