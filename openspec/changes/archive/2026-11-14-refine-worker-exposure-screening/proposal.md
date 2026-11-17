## Why

The worker screening puts a facility's whole annual TRI fugitive air release into one room with
generic ventilation. A TRI fugitive release is the mass that leaves the site (much of it outdoors),
not the mass generated where a worker breathes, so the result is neither an upper nor a lower bound,
has no physical ceiling, and labels almost every facility "exceedance" of an occupational limit.
The change makes the worker result defensible: honest wording and a physical cap, a generation term
taken from EPA's activity models, and measured data ahead of any model.

## What Changes

The change has five sections, built in this order.

**Section 1: an honest screening indicator**

- **BREAKING** The worker tiers "exceedance / elevated / acceptable" become the screening bands
  "high / moderate / low" (labels "High", "Moderate", "Low" screening priority). No text says a
  limit is exceeded or that an exposure is acceptable.
- Every modelled workplace concentration is capped at the chemical's saturation concentration, as
  the EPA/OPPT Mass Balance Inhalation Model does.
- The assumptions and the tool description say the result is a screening indicator.

**Section 2: activity-based generation (EPA ChemSTEER)**

- **BREAKING** The generation term is no longer the TRI fugitive release. It is the vapor
  generation rate of a worker activity (loading and unloading containers, sampling, equipment
  cleaning), from the EPA/OAQPS AP-42 Loading Model, the EPA/OPPT Penetration Model and the
  EPA/OPPT Mass Transfer Coefficient Model, with ChemSTEER's default parameters.
- The activities evaluated for a facility are chosen by a walk: its NAICS code gives its CDR
  industrial sector, and the sector with the TSCA life cycle stage from its Form R activity flags
  gives the EPA generic scenario (or OECD emission scenario document) of that industry and the
  worker activities it describes, through a bundled crosswalk that cites each document. A sector
  with no generic scenario falls back to ChemSTEER's generic manufacturing, processing or use
  operation. Each activity gets a typical and a worst-case result; the facility's worker result is
  the activity with the highest worst-case 8-hour average, and all activities are listed.
- Indoor open-surface activities use the EPA/OPPT Near-Field/Far-Field (two-zone) model, so the
  value is the air beside the source, where the worker stands.
- Chemicals above ChemSTEER's preferred vapor pressure range (35 torr): loading activities are
  computed normally; evaporation activities use the ECETOC TRA band estimate when one exists,
  otherwise the capped model value with a warning. Chemicals below the range (0.001 torr) get
  no vapor estimate, with the reason.
- The TRI fugitive release stays on the result as reported context only; it enters no equation. A
  facility with no fugitive release now still gets a worker result.
- The code and settings this makes dead (the fugitive generation rate, the plant-hours TWA path,
  the low-volatility warning threshold, the old tier names) are removed, not kept.

**Section 3: monitoring data first (OSHA CEHD)**

- A script builds a small bundled summary of OSHA's Chemical Exposure Health Data: personal air
  samples per substance and industry (NAICS), with sample count, non-detects, median and 95th
  percentile.
- When enough samples exist for the chemical in the facility's industry, the measured values are
  the headline of the worker result (median as baseline, 95th percentile as worst case) and the
  modelled values are shown beside them. Otherwise the model is the headline. The result always
  says which evidence it rests on.

**Section 4: the same three bands for the community result**

- **BREAKING** The community (stack, general population) result uses the same "high / moderate /
  low" bands, with one configured set of boundaries (hazard quotient 0.1 and 1; lifetime cancer
  risk 1e-6 and 1e-4; limit ratio 0.1 and 1 for workers). Today the scenario says "at or above
  threshold / below threshold" and the exposure graph says "below / near / above concern".
- A value exactly on a boundary falls in the higher band, for both pathways.

**Section 5: facilities that report only a fugitive release**

- A facility with a fugitive air release and no stack release is no longer dropped. It is listed as
  a worker-only facility with a worker result and no community result, counted apart from the
  stack facilities; the stack lists, emission rates and community screening counts do not change.
- A facility the community screen leaves out still gets its worker result. The screen bounds what a
  stack release does to the neighbours, not what workers breathe inside the plant, so screening a
  facility out no longer removes its worker result. The model is told how the screened-out
  facilities' workers fall in the bands and which one is highest.

## Capabilities

### New Capabilities

- `risk-bands`: the one definition of the high / moderate / low screening bands and their
  boundaries, used by the worker and the community results.
- `vapor-generation-model`: the pure equations for the vapor generation rate of an activity
  (AP-42 loading, penetration, mass transfer coefficient) and the saturation concentration.
- `worker-activity-scenarios`: which worker activities are evaluated for a facility (industry
  generic scenario and life cycle stage), their ChemSTEER default parameters, and how chemicals
  outside the preferred volatility range are treated.
- `two-zone-inhalation-model`: the EPA/OPPT Near-Field/Far-Field equations and default rooms.
- `osha-monitoring-data`: the bundled summary of OSHA personal air samples, how it is built and
  how a chemical and an industry are looked up in it.
- `ecetoc-tra-band-estimate`: the ECETOC TRA tier-1 worker inhalation estimate by process category
  and volatility band, used for evaporation activities of very volatile chemicals.

### Modified Capabilities

- `occupational-exposure-model`: generation from an activity in place of the fugitive release;
  saturation cap; outdoor ventilation defaults; TWA from the activity's hours; bands in place of tiers.
- `occupational-exposure-tool`: activities, evidence hierarchy (monitoring, model, band estimate),
  fugitive release as context only, new fail-closed reasons, new assumptions and description.
- `worst-case-scenario`: the worker scenario lists the driving activity and its evidence; every
  scenario carries a band.
- `exposure-chain`: the worker lane starts from the activity, not the fugitive release; status
  words are the bands.
- `assessment-dashboard-state`: the worker summary and the worker lane carry the activity, the
  evidence source and the bands.
- `web-ui-shell`: band words in place of tier words for both pathways; the worker section shows
  the activities, the evidence source and the monitoring summary.
- `agent-system-prompt`: how to read the worker evidence and the bands.
- `emissions-inventory-tool`: fugitive-only facilities are returned as worker-only facilities.
- `facility-assessment-tool`: worker-only facilities get a worker result and no community result.

## Impact

- `models/exposure/occupational.py` (rewritten in part), new `models/exposure/vapor_generation.py`
  and `models/exposure/bands.py`; mirrored tests.
- `tools/assessment/helpers/occupational.py`, `scenarios/worker.py`, `scenarios/community.py`,
  `tools/assessment/facilities.py` (description), `tools/schemas.py`; new helpers for activities,
  monitoring and the band estimate.
- `config/settings.toml` (`[risk_bands]`, `[occupational.activities]`, `[osha_cehd]`,
  `[ecetoc_tra]`; `[occupational.thresholds]` and `low_volatility_mmhg` removed) and loaders.
- New bundled data: `data/osha_cehd_summary.csv`, `data/osha_imis_cas.csv`,
  `data/ecetoc_tra_worker_inhalation.csv`, `data/cdr_sector_generic_scenarios.csv`; new
  `scripts/build_osha_cehd_summary.py`; new `models/exposure/two_zone.py`.
- `tools/emissions/helpers/inventory/fugitive.py` and the inventory listing (worker-only records).
- API schemas, projectors, exposure graph, settings endpoint and the generated TypeScript types;
  frontend tier pill, legend, map ring, worker card, inspector worker section, risk-by-group
  boundaries, exposure chain tab and its visual references.
- `prompts/agent_system.md`, `prompts/catalogue_judge.md`; eval cassettes that hold worker results
  must be re-recorded.
- No new runtime dependency and no new request during a turn: the OSHA and ECETOC data are bundled.
