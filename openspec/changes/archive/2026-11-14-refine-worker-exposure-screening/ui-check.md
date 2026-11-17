# UI check: worker views (refine-worker-exposure-screening)

Surfaces: inspector worker section (`features/map/WorkerSection.tsx`, `WorkerDetail.tsx`,
`FoldSection.tsx`, `FacilityInspector`, `FacilityHoverCard`, incl. worker-only facilities), map
legend and markers (`MapLegend.tsx`, `layers.ts`), Overview worker card (`WorkerRiskCard.tsx`),
Risk by group (`RiskGroupChart.tsx`, `RiskGroupSection.tsx`), exposure chain worker lane.

New screenshot test: `features/map/WorkerSection.visual.tsx` (model, monitoring, absent,
worker-only, legend), light and dark. Every new image was opened before it was kept.

| Check | Light | Dark | Evidence |
| --- | --- | --- | --- |
| Tokens only | pass | pass | No literal colour, shadow, easing or font family in the surface; `text-[11px]` is the documented dense-popover size (23 uses at HEAD); `layers.ts` colour fallbacks are token fallbacks present at HEAD |
| Required states present | pass | pass | Ready (model, monitoring), absent ("Worker exposure: not reported."), worker-only, below-detection median with its reason (unit test), empty legend rows hidden |
| Colour never the only cue | pass | pass | Every band is a pill with "High/Moderate/Low"; legend rows carry words; marker accessible names include both bands in words |
| Focus visible | pass | pass | Disclosure and legend entries are native buttons with the shared focus ring; unchanged primitives |
| Reduced motion respected | pass | pass | Only the disclosure chevron rotates on toggle; `index.css` sets transition durations to 0.01 ms under `prefers-reduced-motion` |
| Numbers with units, absent in words | pass | pass | mg/m^3, mmHg, kg/yr, h/day shown; absent values read "not reported" or the API's reason, never 0 |
| Copy voice | pass | pass | Sentence case; "screening priority" wording; no "exceeds", "exceedance" or "acceptable" (grep) |
| No anti-pattern | pass | pass | No new primitive; no decorative motion; uppercase only in an existing panel title |
| Design document test | pass | pass | `src/designDoc.test.ts` in `npm run check` |
| Contrast test | pass | pass | `src/contrast.test.ts` in `npm run check` |
| Screenshot test | pass | pass | `npm run test:visual`: 16 files, 66 tests |

Fixed during the check: the monitoring fixture had no activities and a baseline that did not
match its median (the backend always carries the modelled activities under monitoring); the
monitoring state was clipped by the 900 px viewport (one activity in that state); the legend
needed a positioned container to render in the test.

Not covered visually: the WebGL map itself (markers are checked by unit tests of the layer
expressions and accessible names).
