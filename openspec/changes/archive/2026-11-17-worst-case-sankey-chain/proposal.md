## Why

The "Exposure chain" tab draws one facility at a time, so the user has to pick a facility before it says
anything. It also draws every branch of that facility: every evaluated stack, every age band, and both
ventilation tiers. What the tab should answer is narrower: how the worst case of each exposure route
arises, from the release to the value compared with a benchmark. Drawn as a Sankey diagram, that answer
needs no facility picker and names no facility.

## What Changes

- The tab draws one **worst-case chain for the whole run** instead of a chain for each facility. There is
  one lane for each pathway (outdoor air → inhalation → general population, and indoor air → inhalation →
  worker). Each lane holds only the worst-case scenario of that pathway, taken from the facility that drives
  the pathway's headline result.
- Each lane keeps only the branch behind its worst value: the stack that gives the worst hazard quotient
  (not every stack), the most exposed age band (not every band), and the worst-case ventilation tier (not
  the baseline).
- No facility is identified anywhere in the tab: no name, FRS ID, address, city, state or industry, and the
  user cannot pick a facility. The shared source node names the chemical (CAS number) only.
- **BREAKING (UI):** the facility picker, the "All pathways" lane switch, the React Flow canvas with its
  minimap, pan and zoom, and the tab's dependence on the map pin and the chat selection are removed.
- The diagram becomes a real Sankey layout: columns from source to release, pathway, route, receptor and
  endpoint, joined by curved bands coloured by the lane's screening band. The steps carry different units,
  so band width encodes no value. Every band and node is labelled with its quantity as the API sent it.
- The API adds a workspace-level `worst_case_chain` graph built by the backend. The browser still computes
  nothing and decides nothing about pathways. The per-facility `exposure_graph` stays as it is for the
  facility inspector and the report.
- **BREAKING (UI):** the Summary tab's "Worst-case scenarios" card is removed, because the chain now carries
  what it showed. The community receptor node also lists the most affected residents (residents, distance,
  fraction of the maximum) or the reason there are none, without tract IDs or coordinates. Marker pins no
  longer focus anything outside the map.
- `@xyflow/react` and `elkjs` are replaced by `d3-sankey` for the layout. The SVG is drawn by React.

## Capabilities

### New Capabilities
- `worst-case-chain`: the backend builds the anonymised, run-wide graph with one worst-case lane per pathway
  from the scenario drivers. It covers which facility feeds each lane, which branch is kept, and which
  identifying fields are left out.

### Modified Capabilities
- `exposure-chain`: the tab draws the run-wide worst-case chain as a Sankey diagram. Following a focused
  facility, the facility picker, the lane isolation and the pan, zoom and minimap requirements are replaced.
  Hover, detail panel, keyboard, status words and visual checks are kept and restated for the Sankey.
- `web-ui-shell`: the Exposure chain tab shows the run's chain. "Pinning a facility focuses it" and "The summary
  ribbon shows the driving scenario" are removed.
- `assessment-dashboard-state`: the workspace state carries the `worst_case_chain` graph, rebuilt whenever
  the facilities or the scenario drivers change.

## Impact

- Backend: `api/services/exposure_graph/` (a new run-wide builder that reuses the lane builders with branch
  selection and an anonymous hub), `api/schemas/workspace.py` (a new field), the projector that fills
  `scenario_drivers`, and `config/settings.toml` (the headline quantity of each lane and the hub's text).
- Contract: `frontend/src/types/schema.json` and the generated `types/api.ts` (a new field, no fields removed).
- Frontend: `features/exposure-chain/` is rewritten around a Sankey layout. `App.tsx` stops passing the
  focused facility to the tab. Visual references are regenerated. `frontend/CLAUDE.md` and `DESIGN.md` are
  updated where they name React Flow and ELK.
- Dependencies: add `d3-sankey` (and its types). Remove `@xyflow/react` and `elkjs` if nothing else uses
  them (only the exposure chain does today).
- No change to the agent, the tools, the models or the stored threads.
