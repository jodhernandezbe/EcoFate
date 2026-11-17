## Why

Each map marker encodes too much at once: the fill is the community band, a ring is the worker band, the
size is the stack emission rate, and an outer ring marks a driver. A worker-only facility gets a fixed
size because it has no stack release. Reading a marker means decoding three channels from two different
pathways. The user wants one meaning per channel: size is how much the facility releases in total,
colour is the band of one pathway the user chooses, and the outer ring marks the facility that drives
that pathway's worst case.

## What Changes

- **Size:** marker size becomes the facility's **total annual air release**, the stack (point) release
  plus the TRI fugitive release, in kg/yr. The backend computes it, converting the reported stack unit
  with the shared unit converter, and adds it to each facility. Worker-only facilities get a real size
  from their fugitive release. A facility whose total cannot be established (an unconvertible unit, no
  release at all) gets the smallest size, and the legend says that its release was not reported.
- **Pathway dropdown:** the map gets a pathway dropdown with the same choices as Risk by group:
  "Outdoor Air → Inhalation → General Population" (the default) and "Indoor Air → Inhalation → Worker".
  Marker colour is the screening band of the chosen pathway: the community band, or the worker band. A
  facility with no result on that pathway is drawn as "No result on this pathway". The legend counts and
  hides markers by the band of the chosen pathway.
- **BREAKING (UI):** the worker-band ring around markers is removed, together with its legend section.
- The **driver ring** stays, but marks the facility that drives a worst-case result of the chosen
  pathway. Receptors are drawn only on the outdoor pathway, as today, for the pinned driver.
- The pathway labels move to one shared place in the frontend, so the map and Risk by group cannot drift
  apart.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `web-ui-shell`: "Interactive facility map" (size by total annual air release, colour by the chosen
  pathway, and a pathway dropdown). "The map marks the driving facility and its receptors" now depends on
  the pathway. "Worker tier on the map" is removed.
- `assessment-dashboard-state`: each facility carries its total annual air release, or the reason it has
  none.

## Impact

- Backend: `api/schemas/workspace.py` (a new facility field and its reason), the facility projector
  (`api/services/projectors/facilities.py`), `config/settings.toml` (target unit, unit aliases for TRI
  spellings, reason text), tests. Contract: `schema.json` and `types/api.ts` regenerated.
- Frontend: `features/map/` (`mapData.ts`, `layers.ts`, `MapLegend.tsx`, `ExposureMapCanvas.tsx`,
  `FacilityInspector.tsx`), a shared `lib/pathways.ts` used by `features/overview/riskGroups.ts`, tests and
  visual references.
- No change to the agent, the tools, the models or the stored threads.
- Sequenced after `worst-case-sankey-chain`, which edits `App.tsx` and the map's `onPin`.
