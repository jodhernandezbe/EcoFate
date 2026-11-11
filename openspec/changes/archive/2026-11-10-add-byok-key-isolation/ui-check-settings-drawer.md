# /ui-check: Settings drawer (Assistant: OpenAI key; Data services: read-only)

Files: `frontend/src/features/settings/SettingsDrawer.tsx` (+ test, visual test),
`hooks/useKeyStatus.ts`, `services/apiClient.ts`, `App.tsx`.
Images looked at (6): `__screenshots__/SettingsDrawer.visual.tsx/settings-{no-key,stored-services,error}-{light,dark}`.

| Check | Light | Dark | Evidence |
| --- | --- | --- | --- |
| Tokens only | pass | pass | no `#`, `rgb(`, `hsl(`, shadow or easing literal in the file; `text-ok`, `text-bad`, `text-fg2`, `border-hairline`, `bg-accent` only |
| Required states present | pass | pass | no key, key stored, success outcome, error outcome, busy (disabled actions), load error, statuses not yet known (no summary shown) |
| Colour never the only cue | pass | pass | "Key stored encrypted for your account" / "No key configured"; "Provided by this installation" / "Not available on this installation"; outcome banners carry an icon and words |
| Focus visible | pass | pass | the drawer opens focused on its first control; the ring shows in the images |
| Reduced motion respected | pass | pass | no new motion; the shared `spring` class and the Accordion are unchanged |
| Numbers with units, absent in words | pass | pass | "1 of 2 available"; an unavailable service says what is missing in words |
| Copy voice | pass | pass | sentence case, plain words, says what to do ("Paste key"); no "Keychain" wording left |
| No anti-pattern | pass | pass | no input for Census or CompTox; no browser dialog; no second icon library; uppercase only in titles |
| Design document test | pass | pass | `src/designDoc.test.ts` (in `npm --prefix frontend run check`, 589 tests) |
| Contrast test | pass | pass | `src/contrast.test.ts` (same run) |
| Screenshot test | pass | pass | `npm --prefix frontend run test:visual`: 12 files, 42 tests |

Known drift (unchanged): the key input keeps `text-[15px]`, already listed in DESIGN.md.
