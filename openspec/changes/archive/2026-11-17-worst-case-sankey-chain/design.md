## Context

Today `build_exposure_graph(facility, text)` (`api/services/exposure_graph/`) builds a graph for each
facility: a hub titled with the facility's name, a community lane with every evaluated stack and every
age band, and a worker lane with both ventilation tiers. The frontend tab (`features/exposure-chain/`)
draws the focused facility's graph with React Flow and ELK, and offers a facility picker and a lane switch.
`state_serializer.py` already computes `scenario_drivers(facilities)`, one driver per (pathway, quantity)
with its `frs_id` and, for community, the `stack_number`. See proposal.md for the motivation.

## Goals / Non-Goals

**Goals:**
- Build one anonymised, run-wide graph on the server from data that already exists (facilities and
  drivers), reusing the lane builders rather than duplicating them.
- Draw it as a Sankey diagram in SVG with no pan/zoom canvas, keeping the existing node kinds, detail
  panel, status words and accessibility.

**Non-Goals:**
- No change to the per-facility `exposure_graph`, the facility inspector, the report, the map or the
  Overview's worst-case card.
- No proportional band widths, and no aggregation across facilities.

## Decisions

**D1. The server builds the chain, as a new field.** `worst_case_chain: ExposureGraph` goes on the
workspace state and is filled in `state_serializer.py` next to `scenario_drivers`, by a new
`build_worst_case_chain(facilities, drivers, text)` in `api/services/exposure_graph/worst_case.py`.
*Alternative:* the frontend picks lanes out of the driving facilities' `exposure_graph`. That was
rejected: the frontend rules say a lane or node is a backend decision, and every facility's graph would
still carry names to the browser for this tab. Reusing the `ExposureGraph` shape means no new schema
types, and the frontend's `graph.ts`, `kinds.ts` and the detail panel keep working.

**D2. Lane builders take a branch selection.** Each lane builder gains an optional keyword (community:
`stack_number` and `single_band=True`; worker: `variants=("worst_case",)`). The defaults keep today's
per-facility graph unchanged. A `WorstCaseLane` registry in `worst_case.py` maps each lane to its
pathway key and its configured headline quantity, and to a builder that applies the selection. A new
pathway stays one module plus one registry entry.
*Alternative:* filter the full per-facility graph after it is built (drop the nodes of other stacks and
bands). That was rejected: it is fragile to node-id conventions and still needs the per-band dose to
choose the band.

**D3. Which facility feeds a lane.** It is the driver of the pathway's headline quantity. That quantity
is configured in `[ui.exposure_graph.worst_case]`: `community_inhalation = "hq"` and
`worker_inhalation = "oel_ratio"`. The endpoint's other quantities come from the same facility. When
another quantity's driver is a different facility, a configured note (no name) is added to the endpoint's
warnings. This keeps the rule that a scenario never mixes facilities.
*Alternative:* one lane per (pathway, quantity). That was rejected: it duplicates the whole lane for
cancer risk and doubles the diagram.

**D4. Choosing the most exposed band** is `max` over the band doses the tool reported (a selection, not
a computation). Ties go to the first band in the reported order. With no doses, the single "residents"
node is used.

**D5. Anonymous hub.** A new `worst_case_hub(chemical, text)` node is titled with configured text (for
example "Reported release of <chemical>"). Its facts are the CAS number and chemical name only. The
release quantities move to each lane's release node, which already carries them for the community stack.
The worker activity node already has the generation rate. A unit test serialises a chain built from
facilities with names, FRS IDs and addresses, and asserts that none of those strings appear.

**D6. Sankey layout with `d3-sankey`, rendered by React as SVG.** Nodes get `value = 1` per link, so
bands have equal width (the units differ; see the Risks). `nodeAlign` is set by node kind: the column is
the index of the node's kind in `KINDS`, so every lane's steps line up. The layout runs in a pure
`layout.ts` (input graph and size, output positioned nodes and link paths) that is unit-tested. The SVG
has a `viewBox`, fills the width, and has a minimum width derived from the geometry (columns × card width plus the gaps
that hold the band labels), below which the container scrolls. It is not a client-config value: a
smaller value would only make the cards overlap. Labels are HTML overlays, or `<text>` at 11–12 px or larger.
*Alternatives:* keep React Flow and style its edges as thick bands. That was rejected: it is not a Sankey
layout, and the canvas, minimap and zoom are what the user found noisy. Recharts' `Sankey` was also
rejected: it gives too little control over node rendering, focus and labels.

**D7. Remove the focus plumbing from the tab.** `ExposureChainTab` takes `chain` (the graph) and `digits`
only. `useFocusedFacility` and `focus.ts` are removed if nothing else uses them; the map keeps its own
pinned state. `FacilityPicker`, `LanePicker`, `ChainCanvas`, `FlowEdge`, `useGraphLayout` and `viewport.ts`
are replaced by `SankeyDiagram`, `SankeyNode` and `SankeyBand`.

**D8. Remove the Summary's worst-case card.** `WorstCaseSection` and its tests are deleted, and
`EpaOverviewRibbon` no longer renders it. `components/ui/ScenarioView` stays, because the facility
inspector uses it. To keep what the card showed, the chain's community receptor node carries the driving
scenario's most affected tracts (residents, distance and fraction as indexed quantities) or its receptors
note. Tract labels, coordinates and bearing are left out because they locate the facility. The
scenario's notes become endpoint warnings.

## Risks / Trade-offs

- [Equal band widths can be read as equal flows] → A caption under the diagram (configured text) says that
  the width is fixed and that the labels carry the values. The spec forbids encoding a value in the width.
- [Lanes from different facilities can look like one plant] → Each lane is visually separate with its own
  pathway header, and the source node's text says it is the worst case of each route in the run.
- [Removing the picker loses per-facility chains in the UI] → The per-facility data stays in the facility
  inspector and the report. The spec's REMOVED migration says so.
- [`d3-sankey` is unmaintained-but-stable (v0.12)] → It is small, has no runtime dependencies beyond
  `d3-array`/`d3-shape`, and is used only inside the pure `layout.ts`, so it is easy to replace.
- [Dropping `@xyflow/react`/`elkjs` touches the bundle and `layering.test.ts`] → Remove them only after a
  grep confirms no other importer; update `frontend/CLAUDE.md` in the same change.

## Migration Plan

This is an additive field on the server, so an older frontend ignores `worst_case_chain`. The new
frontend shows the empty state when the field is absent (an older server). Deploy the server and the
frontend together as usual. Rollback is a revert; there is no stored data to migrate (threads hold tool
results, and the chain is derived on every serialisation).
