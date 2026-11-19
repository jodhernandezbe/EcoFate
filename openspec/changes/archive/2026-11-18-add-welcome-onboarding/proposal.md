## Why

A first-time visitor who signs in to https://ecofate.org lands on an empty workspace (empty
overview, empty map, a chat box) and does not know what to do first: the assistant needs the
user's own OpenAI key before anything works, and nothing says so until a question fails. Good
app onboarding answers "what is this, what do I do first, what will I get" in one short screen,
then gets out of the way. Separately, the Settings drawer lists the Census and CompTox data
services, which only the operator configures; a user can do nothing about them, so the section
only adds noise. Both ship in v0.2.2 so production needs a single further deploy.

## What Changes

- New welcome sheet shown on a user's first visit to the workspace, with three numbered steps:
  1. **Add your OpenAI key** – the key's state in words and an "Open Settings" action (done
     state once a key is stored).
  2. **Ask a question** – the configured example prompts as clickable chips; a click closes the
     sheet and sends that prompt (disabled, saying why, until a key is stored).
  3. **Read the results** – one line each on the Overview, the Map, the Chat and the report.
- "Get started" closes it; it is remembered per user in this browser (convenience only; if
  storage is unavailable it simply shows again). A new rail item, **Welcome**, reopens it.
- Settings drawer: the read-only Data services section (Census, CompTox) is removed; the drawer
  holds only the OpenAI key. The API and operator keys are unchanged.
- Dashboard panels (Overview, Map, Chat) are not modified; wiring is through `LeftNavRail`, a
  hook and `App.tsx`.

## Capabilities

### New Capabilities
- `welcome-onboarding`: the first-visit welcome sheet, its three steps, dismissal and reopening.

### Modified Capabilities
- `web-ui-shell`: the Settings drawer no longer has a Data services section (the rail's
  Welcome item is specified in `welcome-onboarding`).
- `api-key-vault`: Settings no longer reports which operator data services are unavailable
  (tools still report a missing operator key in the answer).

## Impact

- Frontend: new `features/welcome/` (sheet + `useWelcome` hook), `LeftNavRail` (one item),
  `App.tsx` (wiring), `SettingsDrawer` (section removed) and their tests and visual snapshots;
  `DESIGN.md` gets no new primitive (the sheet composes `BottomDrawer`).
- No API, schema, config or backend change (`suggestions` already come from
  `[ui.display]` via the client configuration).
- Release: part of v0.2.2 with the deployment documentation.
