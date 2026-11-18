## Context

The workspace (`App.tsx` → `Workspace`) already has everything the welcome needs: the key state
(`useKeyStatus`), the example prompts (`useClientConfig().suggestions`, from `[ui.display]`), a
send function (`chat.send`), a way to open Settings, and the `BottomDrawer` primitive. The
dashboard panels must not change; new UI enters through the rail, a hook and `App.tsx`.

## Goals / Non-Goals

**Goals:** one calm sheet that a new user reads in under 30 seconds; the first useful action
(store the key, then ask) is one click away; no new primitive, token or backend field.

**Non-Goals:** a multi-page carousel or product tour with coach marks over the panels; server-side
"seen" state; changes to Overview, Map or Chat components; removing the services field from the
API (`/api/keys` keeps reporting it; the UI simply stops showing it).

## Decisions

- **One sheet, three steps, not a carousel.** Apple-style onboarding favours a single "What's
  new / welcome" screen with a few rows (icon, bold title, one sentence) and one primary button.
  Steps are numbered because they are a real sequence (DESIGN.md allows numbers only then).
- **Composes `BottomDrawer` with `fitContent`** – same material, scrim, focus trap and Escape as
  Settings; no new primitive in DESIGN.md. Content keeps `max-w-md`-like readable width.
- **Live step state.** Step 1 shows the real key state, so returning to the welcome after saving
  the key shows "Key stored"; step 2 chips enable as soon as the key exists.
- **Chips reuse `SuggestionChips`** from `features/chat` (already "one click sends"), passing a
  disabled reason; picking closes the sheet then calls `chat.send`. No chat component changes.
- **Seen flag in `safeStorage`** under `ecofate.welcome.seen.<user id>` – a per-viewer
  convenience (allowed by its doc comment); failure shows the sheet again, never errors. No
  sensitive data stored. Alternative (server column) rejected: needs a migration and API for a
  cosmetic preference.
- **`useWelcome(userId)` hook** owns open/seen state: `open`, `show()`, `dismiss()`; first-visit
  open is computed once on mount.
- **Ordering with Settings:** "Open Settings" dismisses the welcome first, then opens Settings, so
  only one drawer is ever open (Escape belongs to the topmost layer).
- **Settings:** delete `SERVICES`, `ServiceEntry`, `servicesSummary` and the Data services
  accordion; the Assistant section stays (as the only section, still expanded when no key).

## Risks / Trade-offs

- Clearing site data shows the welcome again – acceptable for a convenience flag.
- Operators lose the UI hint that Census/CompTox are unavailable; the tools still state a missing
  key in the answer and the operator sees it in logs. Accepted: users cannot act on it.
- Visual snapshots of Settings change and must be regenerated; reviewed with `/ui-check`.
