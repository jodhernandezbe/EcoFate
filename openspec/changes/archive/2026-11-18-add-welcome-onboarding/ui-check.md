# /ui-check: features/welcome/WelcomeSheet.tsx (redesign)

| Check | Light | Dark | Evidence |
| --- | --- | --- | --- |
| Tokens only | pass | pass | accent, fg, fg2, ok, hairline, bg-solid, --shadow; `text-[15px]` and `text-3xl` are documented rows (Welcome title, Welcome feature); scrim `bg-black/30` is the shared ConfirmDialog/BottomDrawer scrim |
| Required states | pass | pass | no key (example disabled with reason, Settings link), key stored, busy (unit test), no suggestions (unit test) |
| Colour never the only cue | pass | pass | "Key stored." / "No key yet." in words |
| Focus visible | pass | pass | Continue focused on open with the 2px accent ring (screenshots) |
| Reduced motion | pass | pass | only `.sheet-in` and `.spring`, collapsed by the global rule |
| Numbers with units / absent values | pass | pass | no values shown |
| Copy voice | pass | pass | sentence case; "screening level, not a regulatory determination" |
| No anti-pattern | pass | pass | no browser dialog, no hover lift, no entrance per card, one icon library |
| Design document test | pass | pass | `src/designDoc.test.ts` |
| Contrast test | pass | pass | `src/contrast.test.ts` |
| Screenshot test | pass | pass | `WelcomeSheet.visual.tsx`, 4 images reviewed before `-u` |
