## 1. Settings drawer

- [x] 1.1 Remove the Data services section (`SERVICES`, `ServiceEntry`, `servicesSummary` and its accordion) from `features/settings/SettingsDrawer.tsx`; keep the Assistant section expanded when no key is stored.
- [x] 1.2 Update `SettingsDrawer.test.tsx` (no Census/CompTox text or Data services section; key behaviour unchanged) and the visual fixture/snapshot.

## 2. Welcome sheet

- [x] 2.1 Add `features/welcome/useWelcome.ts`: per-user seen flag in `safeStorage` (`ecofate.welcome.seen.<id>`), `open`, `show()`, `dismiss()`; tests for first visit, dismissed, per user and storage throwing.
- [x] 2.2 Add `features/welcome/WelcomeSheet.tsx` composing `BottomDrawer` (`fitContent`): title, one-sentence intro, three numbered steps (key state + "Open Settings"; `SuggestionChips` with disabled reason; results line per Overview, Map, Chat, report and the screening-level note), "Get started". Tokens and type scale from DESIGN.md only.
- [x] 2.3 Tests: steps in order; "No key yet"/"Key stored"; chips disabled with reason without a key or while busy; picking sends the prompt and closes; "Open Settings" closes the welcome and opens Settings; Escape/close/Get started dismiss; empty suggestions sentence; no key input.

## 3. Wiring (no panel changes)

- [x] 3.1 `LeftNavRail`: add a "Welcome" item (Lucide icon, label when collapsed) calling `onWelcome`; extend `LeftNavRail.test.tsx`.
- [x] 3.2 `App.tsx`: use `useWelcome(user.id)`, render `WelcomeSheet` with key state, `config.suggestions`, `chat.busy`, send and open-Settings handlers; App test for first visit shown and reopen from the rail.

## 4. Verify and release

- [x] 4.1 `npm --prefix frontend run check`, `uv run pre-commit run --all-files`, and `/ui-check` on the welcome sheet and Settings in light and dark.
- [ ] 4.2 Ship in v0.2.2: after deploy, sign in at https://ecofate.org with a fresh browser profile, see the welcome, store the key from step 1, send an example from step 2; Settings shows no Census/CompTox.
