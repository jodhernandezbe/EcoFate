## Context

`features/map/mapData.ts` sizes markers by `emission_rate_g_s`; worker-only facilities have no rate and get
the minimum size. `layers.ts` draws a fill (community `status`), a worker ring (`occupational_exposure.risk_tier`)
and a driver ring (any `scenario_drivers` entry). `MapLegend.tsx` explains the fill and the ring and toggles
hidden statuses. Risk by group keeps its pathway labels in `features/overview/riskGroups.ts` (`PATHWAYS`).
The facility already holds `total_release` (stack, in `release_unit`, e.g. "Pounds") and
`fugitive_release_kg_per_year`. The frontend may not compute or convert values. See proposal.md for
the motivation.

## Goals / Non-Goals

**Goals:** one meaning per visual channel, and a total that the server computes once.

**Non-Goals:** the receptor radius circles, the downwind sectors and the receptor dots stay as they are.
Neither the inspector's content nor Risk by group's behaviour changes.

## Decisions

**D1. The server computes the total.** A new projector step sets `total_air_release_kg_per_year` and
`total_air_release_reason` on each facility. It converts `total_release` from `release_unit` with
`commons.units.convert`, using configured aliases (TRI spellings such as "Pounds" → "lb", "Grams" → "g").
The fugitive part is already in kg/yr and is added. The step fails closed: if the unit is unknown, the
total is None with a reason, and the fugitive part is not reported alone as the total. Rationale: summing
and converting are computations, which the frontend rules forbid. *Alternative:* size by `total_release`
only (rejected: worker-only facilities would stay unsized, and the user asked for every release).

**D2. Shared pathway list.** `PATHWAYS` and `Pathway` move to `frontend/src/lib/pathways.ts`. Risk by group
and the map both import from there, because features cannot import each other's internals. Each entry gets
a `band(facility)` accessor (outdoor → `status`; indoor → `occupational_exposure.risk_tier`) and a
`pathwayKey` (`community_inhalation` / `worker_inhalation`) used to filter `scenario_drivers`. Hard-coded
labels are kept as Risk by group has them today (moving them to client settings is out of scope).

**D3. One status key per pathway.** `statusKey(facility, pathway)` returns the band or `"none"`, and
`"none"` reads "No result on this pathway" (worker-only on the outdoor pathway falls here too). The hidden
set is reset when the pathway changes, so a hidden "High" on one pathway does not hide markers silently on
the other.

**D4. Driver ring by pathway.** `facilityCollection` takes the drivers already filtered to the chosen
pathway's `pathwayKey`. The receptor layer is fed only on the outdoor pathway. The worker ring layer and
its `worker_tier` property are deleted.

**D5. Where the state lives.** The chosen pathway is `ExposureMapCanvas` state: it is local to the map and
starts on outdoor. The dropdown sits beside the legend, styled like Risk by group's select (DESIGN.md
tokens).

## Risks / Trade-offs

- [Unknown TRI unit spellings make totals absent] → The aliases are configured. A test covers every unit
  spelling present in the bundled inventory sample, and the legend counts the facilities that have no total.
- [Colour meaning changes with the dropdown] → The dropdown's label is visible, and the legend title names
  the chosen pathway.
- [Two independent pathway pickers (map, Risk by group)] → They are kept separate on purpose. They share
  their labels through `lib/pathways.ts`.

## Migration Plan

The field is additive. An older server sends no total: every marker gets the smallest size and the legend
counts them as not reported. Revert to roll back; nothing is stored.
