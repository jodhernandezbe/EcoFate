## 1. Backend total annual air release

- [x] 1.1 Config: the target unit (`kg/yr` → `kg`), aliases for the TRI stack release unit spellings, and the reasons (none reported, unit not convertible) in `config/settings.toml`, plus a typed loader and tests (including a negative test for a missing reason)
- [x] 1.2 Add `total_air_release_kg_per_year: float | None` and `total_air_release_reason: str | None` to `Facility` in `api/schemas/workspace.py`, with a docstring that gives the units
- [x] 1.3 Add a projector step (its own small module under `api/services/projectors/`) that sets them: stack converted with `commons.units.convert` plus fugitive; parts that are absent stay absent; it fails closed on an unknown unit (the fugitive part is not reported alone); finite numbers only
- [x] 1.4 Tests: stack + fugitive, stack only, worker-only, unknown unit, nothing reported, a non-finite input, and every unit spelling in the bundled inventory sample
- [x] 1.5 Export the schema, regenerate the types, and check that the contract diff passes

## 2. Shared pathways

- [x] 2.1 Move `PATHWAYS`/`Pathway` to `frontend/src/lib/pathways.ts`, adding a `band(facility)` accessor and a `pathwayKey`; update `features/overview/riskGroups.ts` and its importers; tests

## 3. Map markers

- [x] 3.1 `mapData.ts`: size by `total_air_release_kg_per_year` (square root, smallest size when absent); drop `worker_tier`/`worker_only` styling; status from the chosen pathway; drivers filtered by `pathwayKey`
- [x] 3.2 `layers.ts`: delete the worker ring layer; the fill colour uses the pathway status; "No result on this pathway" is outlined and neutral
- [x] 3.3 `ExposureMapCanvas.tsx`: pathway state and a dropdown next to the legend; reset the hidden set when the pathway changes; feed receptors only on the outdoor pathway
- [x] 3.4 `MapLegend.tsx`: the legend title names the pathway; entries are High, Moderate, Low and No result on this pathway, with counts and toggles; a size note ("size: total annual air release") with the not-reported count; the ring section is removed
- [x] 3.5 `FacilityInspector.tsx`: the radius comes from the same `facilityCollection` call, and the marker's accessible name gives the chosen pathway's band
- [x] 3.6 Tests: the pathway switch recolours and recounts; the hidden set resets; the driver ring follows the pathway; no worker ring; size ordering; the absent total gets the smallest size and is counted

## 4. Visual checks and documentation

- [x] 4.1 Update the map visual references (both pathways, light and dark), looking at each image before approving
- [x] 4.2 Run `/ui-check` on the map in light and dark
- [x] 4.3 Update `frontend/CLAUDE.md`/`DESIGN.md` if they describe the marker encoding

## 5. Verification

- [x] 5.1 `make check` passes
- [x] 5.2 One live run: compare the totals with the TRI values for a known facility (stack + fugitive), and check that worker-only facilities are sized and that the dropdown recolours (checked by the user in the live app, 2026-11-17)
- [x] 5.3 Fold into the single security audit before the commit
