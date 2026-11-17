# UI check — Exposure chain (Sankey) and map markers/legend

Date: 2026-11-14. Surfaces: `frontend/src/features/exposure-chain/*`, `features/map/{MapLegend,ExposureMapCanvas,FacilityInspector,layers,mapData}`, `lib/pathways.ts`.

| Check | Light | Dark | Evidence |
| --- | --- | --- | --- |
| Tokens only | pass | pass | No literal colour, shadow or easing in the components. `layers.ts` reads `--ok/--warn/--bad/--fg-2/--accent/--surface-solid`; the hex values there are only fallbacks when a token is missing (an existing pattern, needed by MapLibre paint). Sizes are `text-[11px]` (documented for chain cards and band labels) and the scale steps. |
| Required states present | pass | pass | Chain: ready (`both-lanes-wide`), empty (`empty`), absent values (`missing-values`), unavailable lane (`community-only`), detail (`receptor-detail`, `worker-endpoint-detail`), highlight. Map legend: outdoor and indoor with counts, "No result on this pathway", the count of releases not reported. |
| Colour never the only cue | pass | pass | Bands are pills with the words High, Moderate and Low on endpoints and lane status. Legend entries are words with counts. A marker's accessible name gives the band of the chosen pathway in words. |
| Focus visible | pass | pass | Chain steps are buttons with the global `:focus-visible` ring; a focused step scrolls into view (tests). Map dropdown is a native `select` with `aria-label`. |
| Reduced motion respected | pass | pass | `SankeyBand` drops the moving dots under `prefers-reduced-motion` (the arrowheads stay); the visual test "stops the flow…" covers it. The flow dots are the exception DESIGN.md documents. |
| Numbers with units, absent values in words | pass | pass | Values carry units via `lib/format`; an absent value shows the API's reason ("not reported by the tool", "no dose reported"), never 0 or "-". |
| Copy voice | pass | pass | Sentence case; no regulatory wording; the caption explains the fixed band width; the empty state says what would make the chain appear. |
| No anti-pattern | pass | pass | No new icon library, no unprompted motion beyond the documented flow dots, no hard-coded thresholds; pathway labels come from one shared `lib/pathways.ts`. |
| Design document test | pass | pass | `src/designDoc.test.ts` + `contrast.test.ts`: 31 passed. |
| Contrast test | pass | pass | `src/contrast.test.ts` passed; the band-label pills use `bg-solid` with `text-fg`/`text-fg2`. |
| Screenshot test | pass | pass | `npm run test:visual`: 72 passed. Images viewed: chain both-lanes (wide, narrow start and end), receptor-detail, worker-endpoint-detail, missing-values, worker-lane-highlighted, empty; map legend indoor (dark). |
| Map canvas markers (sizes, fill, driver ring) | not run | not run | MapLibre is not rendered by the screenshot suite. Covered by `mapData`/`ExposureMapCanvas` unit tests; to see in the live run (map task 5.2). |
