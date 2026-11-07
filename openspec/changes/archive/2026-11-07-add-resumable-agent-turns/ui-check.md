# ui-check: chat interrupted-turn notice

Surface: `frontend/src/features/chat/MessageStream.tsx` (`StopNotice`), `ChatDock.tsx` (status),
`components/layout/TopHeaderBar.tsx` ("Stopped"). Visual test: `MessageStream.visual.tsx`
(resumable, busy, bad_key, not resumable), references approved after viewing all 8 images.

| Check | Light | Dark | Evidence |
| --- | --- | --- | --- |
| Tokens only | pass | pass | grep for `#`, `rgb(`, `hsl(`, `cubic-bezier`, `shadow-[` in the surface: none; `bg-accent`, `text-accent-fg`, `border-hairline`, `text-fg2`, `bg-fg2` |
| Required states present | pass | pass | resumable, busy (disabled with reason), bad_key (+ Open Settings), not resumable (message only); `stop-*` screenshots |
| Colour never the only cue | pass | pass | pause icon + server message in words; header says "Stopped" beside its dot |
| Focus visible | pass | pass | global `:focus-visible` accent outline (`index.css:117`) applies to both buttons |
| Reduced motion respected | pass | pass | only `.spring` transition on press; `prefers-reduced-motion` rule (`index.css:107`) |
| Numbers with units, absent values in words | pass | pass | no numbers on the surface |
| Copy voice | pass | pass | only the server's fixed message; sentence case "Resume", "Open Settings"; disabled reason "A turn is running; Resume is available when it ends." |
| No anti-pattern | pass | pass | no new primitive, no browser dialog, no decorative motion; dashboard panels untouched |
| Design document test | pass | pass | `designDoc.test.ts` passes; "Interrupted" row added to Required states |
| Contrast test | pass | pass | `contrast.test.ts` passes |
| Screenshot test | pass | pass | `npm run test:visual`: 24 passed (8 new) |
