## 1. Configuration

- [x] 1.1 Add `[ui.exposure_graph.worst_case]` to `config/settings.toml`: the headline quantity of each pathway (`community_inhalation = "hq"`, `worker_inhalation = "oel_ratio"`), the source node's title template, the "another facility has a higher value" note and the fixed-width caption
- [x] 1.2 Extend the typed loader in `config/exposure_graph.py` (frozen dataclass), with tests for valid input and for a missing or unknown quantity key (negative test)

## 2. Branch selection in the lane builders

- [x] 2.1 Community lane: add an optional `stack_number` (keep only that stack's release node) and `single_band` (one receptor node for the band with the highest reported dose, carrying its share, total residents and radius; the "residents" node when no dose is known). The defaults leave the per-facility graph unchanged
- [x] 2.2 Worker lane: add optional `variants` so the worst-case chain carries `worst_case` values only. The default keeps both tiers
- [x] 2.3 Tests in `tests/api/services/exposure_graph/`: one stack of three is kept; the highest-dose band is chosen (ties go to the first); no doses gives the residents node; baseline is dropped; the per-facility graphs are unchanged (regression)

## 3. Run-wide worst-case chain

- [x] 3.1 Add `worst_case_hub(chemical, text)` in `hub.py`: configured title, CAS number and chemical name facts, no facility fields
- [x] 3.2 Add `api/services/exposure_graph/worst_case.py` with the `WorstCaseLane` registry (lane → pathway key, headline quantity, selecting builder) and `build_worst_case_chain(facilities, drivers, text)`. Each lane comes from its headline driver; a lane with no driver is unavailable; an empty run gives an empty graph
- [x] 3.3 Add the no-name note to the endpoint when another quantity of the pathway is driven by a different facility
- [x] 3.5 Community receptor node in the chain: the driving scenario's most affected tracts (residents, distance, fraction of the maximum; no label, GEOID, coordinates or bearing) or its receptors note; the scenario's notes go into the endpoint warnings; extend the leak test to tract labels and coordinates
- [x] 3.4 Tests: different drivers per lane; no worker result; empty run; absent cancer risk; other-quantity note; a leak test that serialises a chain from named facilities and asserts no name, FRS ID, document control number, address, city, state or ZIP appears

## 4. Workspace contract

- [x] 4.1 Add `worst_case_chain: ExposureGraph` (default empty) to the workspace schema in `api/schemas/workspace.py`, and fill it in `api/services/state_serializer.py` from the facilities and `scenario_drivers`
- [x] 4.2 Serializer tests: the chain is rebuilt when the driver changes; it is empty before any assessment
- [x] 4.3 Export the schema, run `npm --prefix frontend run gen:types`, and check that the contract diff passes

## 5. Sankey diagram (frontend)

- [x] 5.1 Add `d3-sankey` and `@types/d3-sankey` at pinned versions, and confirm that the licence and size are acceptable
- [x] 5.2 Rewrite `features/exposure-chain/layout.ts` as a pure Sankey layout: columns by node kind, equal link values, and a minimum width derived from the card and band-label geometry (a config value could only make the cards overlap; see design D6). Unit-test that the columns follow `KINDS`, that the bands have equal widths, and that an unknown lane is laid out
- [x] 5.3 Add `SankeyDiagram`, `SankeyNode` (a focusable control with an accessible name of step, label and value, a headline value and a status pill) and `SankeyBand` (a curved path in the lane's band colour from design tokens, a quantity label at 11/12 px or larger, and a flow marker that stays still under reduced motion)
- [x] 5.4 Rewrite `ExposureChainTab` to take `chain` and `digits` only: the lane status list, the fixed-width caption, the empty state (also when the field is absent), lane highlight on hover or focus, the detail panel (Escape stops propagation), and the screen-reader connection list
- [x] 5.5 Remove `FacilityPicker`, `LanePicker`, `ChainCanvas`, `FlowEdge`, `useGraphLayout`, `viewport.ts`, `focus.ts` and `useFocusedFacility` (after a grep confirms nothing else uses them). Update `App.tsx` to pass `store.workspace.worst_case_chain`, keeping the map's `onPin` working on its own
- [x] 5.6 Remove `@xyflow/react` and `elkjs` from `package.json` if no importer is left. Update `layering.test.ts` if it names them
- [x] 5.8 Remove `WorstCaseSection` (and its test and visual references) from the Summary: `EpaOverviewRibbon` no longer renders it. Keep `components/ui/ScenarioView` for the facility inspector. Update the tests that expect the card
- [x] 5.7 Component tests: no facility name or picker is rendered; "not reported" with its reason; an unavailable lane; keyboard order and Enter; Escape; highlight

## 6. Visual checks and documentation

- [x] 6.1 Rewrite `ExposureChainTab.visual.tsx` for every state (both lanes, missing values, an unavailable lane, "high", monitoring evidence, empty; light and dark; wide and narrow). Review every new screenshot before approving with `-u`
- [x] 6.2 Run `/ui-check` on the tab in light and dark
- [x] 6.3 Update `frontend/CLAUDE.md` (the exposure-chain bullet and the library list) and `frontend/DESIGN.md` where they describe React Flow, ELK or the facility picker

## 7. Verification

- [x] 7.1 `make check` passes (pytest, ruff, pyright, bandit, function length, frontend check)
- [x] 7.2 Run the app on a real multi-facility run and confirm one chain with one lane per pathway, no facility names, and values matching the driving facilities in the map inspector, and no "Worst-case scenarios" card in the Summary (checked by the user in the live app, 2026-11-17)
- [x] 7.3 Run one security audit over the whole diff before the single commit
