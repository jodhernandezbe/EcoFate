The main session coordinates and reviews; boilerplate is executed by Sonnet 5.5 sub-agents
(`model: "sonnet"`), and judgement work stays in the main session (design D8). Each agent gets the
spec files of its group, the design decisions it names and the files to touch. After each group the
main session reviews the diff and runs `make check`; the next dependent group starts only when it
passes. Groups 2, 3 and 4 can run in parallel after group 1; groups 6 and 7 after group 5; group 8
follows 7. Any code or setting the change makes dead is removed in the group that makes it dead,
never kept.

## 1. Section 1: shared screening bands and the saturation cap

- [x] 1.1 Add `[risk_bands]` to `config/settings.toml` (hq 0.1/1, cancer_risk 1e-6/1e-4, oel_ratio 0.1/1) and a typed loader `config/risk_bands.py` with validation (lower < upper, finite, positive) and negative tests (spec `risk-bands`, design D1)
- [x] 1.2 Add `commons/bands.py` (`band_of`, `highest_band` returning "high" / "moderate" / "low" / None, at-boundary goes to the higher band) with tests in `tests/commons/test_bands.py` (design D1)
- [x] 1.3 Delete `risk_tier` and `_above` from `models/exposure/occupational.py`, `[occupational.thresholds]` from settings and its loader fields in `config/occupational.py`; switch `tools/assessment/helpers/occupational.py` and `scenarios/worker.py` to the bands
- [x] 1.4 Switch `tools/assessment/helpers/scenarios/community.py` from "at or above threshold / below threshold" to the band of its quantity; update `tools/schemas.py` tier types to the band literal
- [x] 1.5 Add `saturation_concentration` (spec `vapor-generation-model`) and make `workplace_concentration` cap at saturation and report whether it applied; add `[occupational].molar_volume_l_per_mol = 24.45`
- [x] 1.6 Update the assumptions text and the `tools/assessment/facilities.py` description to "screening indicator", bands and no compliance wording
- [x] 1.7 Update API schemas (`api/schemas/workspace.py`, `api/schemas/settings.py`, `api/routers/v1_settings.py`), projectors, `config/exposure_graph.py` TIERS and `api/services/exposure_graph/worker.py` (remove `TIER_STATUS` relabelling; both lanes carry the band); regenerate `frontend/src/types/api.ts`
- [x] 1.8 Frontend: `TierPill`, `MapLegend`, `layers.ts`, `ScenarioView`, `RiskGroupChart` (band boundaries on both pathways), `WorkerRiskCard`, `FacilityInspector`/`WorkerSection`, exposure chain status; an unknown band from an old saved workspace renders "not reported" (test); update fixtures and visual references
- [x] 1.9 `prompts/agent_system.md` and `prompts/catalogue_judge.md`: bands as screening priorities (spec `agent-system-prompt`)
- [x] 1.10 Grep the repository for "exceedance", "elevated", "acceptable", "at or above threshold", "below threshold", "near concern" as band values and remove every remaining use; `make check` passes

## 2. Section 2a: vapor generation equations

- [x] 2.1 Create `models/exposure/vapor_generation.py` with the AP-42 Loading, Penetration and Mass Transfer Coefficient models, constants exactly as in the ChemSTEER User Guide (May 2015) with units in every docstring (spec `vapor-generation-model`)
- [x] 2.2 Create `models/exposure/two_zone.py` (EPA/OPPT Near-Field/Far-Field model, guide pages 320-323) with the default geometry and rooms in `[occupational.two_zone]`; tests for the steady-state limit, near field above far field, proportionality and invalid inputs (spec `two-zone-inhalation-model`, design D9)
- [x] 2.3 Tests: formula scenarios evaluated independently in the test, proportionality, air-speed guards, every invalid input; mirrored under `tests/models/exposure/`

## 3. Section 2b: worker activities and the ECETOC TRA band estimate

- [x] 3.1 Add `[occupational.activities.*]` (drum and tank truck loading/unloading, liquid sampling, equipment cleaning) with the ChemSTEER defaults, `[occupational.stage_activities]` (the generic Manufacturing, Processing and Use operations, design D3), `[occupational.volatility]` (0.001 and 35 torr) and indoor/outdoor ventilation defaults; typed loaders with validation and negative tests (spec `worker-activity-scenarios`)
- [x] 3.2 Build `data/cdr_sector_generic_scenarios.csv`: for each CDR sector and life cycle stage that has an EPA generic scenario or OECD emission scenario document, transcribe the worker activities from its occupational exposure section, one cited row each; leave sectors without a document out. Add `[generic_scenarios]` config and a validating reader (unknown activity or sector raises). Show the table to the user for review before group 5 uses it; never infer a row (design D3)
- [x] 3.3 Remove `low_volatility_mmhg` and its warning; remove `generation_rate` from `models/exposure/occupational.py`
- [x] 3.4 Outdoor worst-case ventilation 26,400 x (60 x vz / 5,280) ft^3/min in `models/exposure/occupational.py` with tests (spec `occupational-exposure-model`)
- [x] 3.5 ECETOC TRA: obtain the published worker inhalation initial estimates (industrial, no LEV) and duration modifiers from ECETOC's documentation, transcribe them into `data/ecetoc_tra_worker_inhalation.csv` with the source edition in the header, and add `[ecetoc_tra]` config and a reader. If the published table cannot be obtained, stop this task and ask the user; never estimate values (design D4, spec `ecetoc-tra-band-estimate`)

## 4. Section 3a: OSHA CEHD summary

- [x] 4.1 Add `[osha_cehd]` config (yearly file URL pattern, years, NAICS prefix lengths 6/4/3, minimum values 5, output paths)
- [x] 4.2 Write `scripts/build_osha_cehd_summary.py`: download yearly ZIPs (timeouts, a configured user agent), parse the CSV in each (reject a ZIP whose member is not the expected CSV), keep personal non-blank M/P samples, time-weighted average per sampling number, write `data/osha_cehd_summary.csv` with the window and build date, count skipped rows (spec `osha-monitoring-data`, design D5)
- [x] 4.3 Build `data/osha_imis_cas.csv` from OSHA's Chemical Sampling Information substance list; leave out substances with no CAS number
- [x] 4.4 Tests of the script on a small synthetic CSV fixture (no network): filtering, collapsing, percentiles, non-detects, malformed rows
- [x] 4.5 Run the script once for real, commit the two data files, and verify live that at least one well-known solvent's CAS has rows

## 5. Section 2c and 3b: the occupational result

- [x] 5.1 Split `tools/assessment/helpers/occupational.py` into `tools/assessment/helpers/occupational/` (activities, monitoring lookup, headline, result) keeping every function under 18 lines (design D6)
- [x] 5.2 Activity selection by the walk NAICS, CDR sector, generic scenario and life cycle stage, with the generic-operation fallback and the route named; activity evaluation: typical and worst case per activity (two-zone near field for indoor evaporation activities, mass balance otherwise), saturation cap, volatility handling (below / within / above, ECETOC for evaporation above the range, else capped value with warning), driving activity (spec `worker-activity-scenarios`)
- [x] 5.3 Monitoring lookup by CAS and NAICS with fallback and minimum count, ppm to mg/m^3 conversion (explicit MW over molar volume; `commons/units.py` has no ppm), below-detection median (spec `osha-monitoring-data`)
- [x] 5.4 Evidence hierarchy and the new result shape in `tools/schemas.py` (`evidence`, `activities`, `driving_activity`, `monitoring`, `molecular_weight`, `volatility`, `WorkerCase` for baseline and worst case); fugitive release as context only (spec `occupational-exposure-tool`)
- [x] 5.5 Fail-closed reasons and assumptions; tests for every scenario of `occupational-exposure-tool` and `worker-activity-scenarios`, including that two facilities differing only in fugitive release get equal values
- [x] 5.6 Update `scenarios/worker.py` factors and receptors (activity, model, generation rate, cap, hours; monitoring factors when the evidence is monitoring) (spec `worst-case-scenario`)
- [x] 5.7 Update the assessment tool description (`tools/assessment/facilities.py`) for the evidence order, the bands and the fugitive release as context

## 6. API, workspace and exposure graph

- [x] 6.1 Update workspace schemas, projectors (`assessment`, `facilities`, `summary`, `payloads`, `ledger`) and report text for the new worker shape (spec `assessment-dashboard-state`)
- [x] 6.2 Exposure graph worker lane: activity or monitoring source node, setting, generation rate, cap, fugitive release as context; labels and units in `config/exposure_graph.py`
- [x] 6.3 Regenerate the TypeScript types and pass the contract test

## 7. Frontend

- [x] 7.1 Worker card: evidence and band per figure (spec `web-ui-shell`)
- [x] 7.2 Inspector worker section: evidence, volatility, monitoring summary, activity list with the driving one marked, fugitive release as context
- [x] 7.3 Map fill and ring both by band, legend and accessible names; Risk by group band boundaries on both pathways and evidence in the indoor tooltip
- [x] 7.4 Exposure chain worker lane and visual references for the new states (high band, monitoring evidence) in light and dark, wide and narrow (spec `exposure-chain`); run `/ui-check` on each changed surface

## 8. Section 5: worker-only facilities

- [x] 8.1 `fold_fugitive` returns fugitive-only facilities as worker-only records (no stack release, no emission rate), capped by `[tri].max_worker_only`, with the left-over count; tests that every stack number and list is unchanged (spec `emissions-inventory-tool`, design D7)
- [x] 8.2 Assessment: worker-only facilities get the occupational result and profile only, no stack, dispersion, weather or population request, and a separate count; tests that screening counts are unchanged (spec `facility-assessment-tool`)
- [x] 8.3 Workspace schema, projectors and exposure graph for a facility with no community result (community lane unavailable with the reason); regenerate types
- [x] 8.4 Frontend: outlined marker without community fill, legend entry and count, inspector text, Risk by group indoor only; visual references; `/ui-check`

## 10. Screened-out facilities keep their worker result (design D10)

- [x] 10.1 `helpers/screened_workers.py`: worker screening and profile for every screened-out facility, band counts, highest worker value, note sentence; `ScreenedOut` and the screening summary gain the fields; tool description (spec `facility-assessment-tool`)
- [x] 10.2 Projector files the screened-out worker result and profile; earlier form reads as none (spec `assessment-dashboard-state`)
- [x] 10.3 Risk by group indoor ranks every worker result (spec `web-ui-shell`)
- [x] 10.4 Live run (Texas dichloromethane), chemical-name-only eval 10x, gates and the security audit of this addition

## 9. Prompts, evals and completion

- [x] 9.1 `prompts/agent_system.md`: evidence order, bands as priorities, fugitive release not a worker measure (spec `agent-system-prompt`)
- [x] 9.2 Re-record the eval cassettes that hold worker results; run the chemical-name-only eval 10x and the other evals 3x and compare with the previous results
- [x] 9.3 One live assessment of a volatile solvent and of a low-volatility chemical through the app, checking the evidence, the bands and the warnings
- [x] 9.4 Final dead-code sweep (unused settings, helpers, schema fields, fixtures, frontend branches), `uv run pre-commit run --all-files`, `make check`, and `/security-audit`
