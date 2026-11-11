# ui-check: chat live status, Stop and queued header

Surface: `features/chat/MessageStream.tsx` (status line and Stop under the streaming answer),
`features/chat/ChatDock.tsx` and `components/layout/TopHeaderBar.tsx` (header "Queued"),
`features/chat/turnStatusText.ts` (copy). Rendered by `MessageStream.visual.tsx`
(`live-queued`, `live-running`, `live-stopping`, light and dark, Chromium); each image was looked
at before approval.

| Check | Light | Dark | Evidence |
| --- | --- | --- | --- |
| Tokens only | pass | pass | Added lines use `text-fg2`, `text-fg`, `border-hairline`, `hover:bg-hairline`, `bg-fg2`; grep of the diff finds no literal colour, shadow, easing or off-scale size |
| Required states present | pass | pass | Queued ("Waiting for a worker (about 2 ahead)"), running a step ("Running: Read toxicity"), thinking, stopping (Stop disabled with reason); stopped turn falls through to the Interrupted state; DESIGN.md "Running (live status)" row added |
| Colour never the only cue | pass | pass | Header dot paired with "Queued"/"Thinking"; status line is words; Stop has icon and word |
| Focus visible | pass | pass | Stop is a native `button`, global `:focus-visible` ring applies; disabled Stop carries `title` and `aria-description` |
| Reduced motion respected | pass | pass | No new animation; the queued dot does not pulse; `.spring` only on hover, collapsed by the global rule |
| Numbers with units, absent values in words | pass | pass | Only the queue count ("about 2 ahead"), sent by the server; no scientific value |
| Copy voice | pass | pass | Sentence case; fixed texts from `turnStatusText.ts`; step labels are the server's |
| No anti-pattern | pass | pass | No new primitive (the Stop pill follows the Resume/Open Settings pill); nothing moves unprompted |
| Design document test | pass | pass | `src/designDoc.test.ts` in `npm run check` (63 files, 612 tests pass) |
| Contrast test | pass | pass | `src/contrast.test.ts` in `npm run check` |
| Screenshot test | pass | pass | `npm run test:visual`: 52 passed, including the 6 new references |
