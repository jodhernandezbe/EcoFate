# frontend/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `frontend/`.

- React + TypeScript (strict) + Vite + Tailwind; MapLibre GL for the map, Recharts for the
  age-band bar, React Flow + ELK for the exposure chain, Lucide for icons (react-icons only for the `TbMessageChatbot` copilot toggle and the
  `AiOutlineClear` chat clear button).
  Commands: `npm --prefix frontend ci`, `run build`, `run check` (contract diff, tsc, eslint,
  vitest). `check` must pass before work is done. `run test:visual` renders `*.visual.tsx` in
  Playwright Chromium (light and dark) and compares screenshots with `__screenshots__/`; after a
  deliberate change, look at every new image before approving it with `-u` (references are per OS).
- Feature-driven layout with one-way imports: `components/` (`layout/`, `ui/`: domain-agnostic
  HIG primitives) -> `features/` (`overview/`, `map/`, `chat/`, `settings/`, `monitoring/`, `exposure-chain/`, `auth/`) -> `App.tsx`.
  `hooks/` (stream, stores, key status) and `services/apiClient.ts` serve features;
  `components/` never import `features/`, and features never import each other's internals.
- `features/exposure-chain` is the Overview's "Exposure chain" tab (composed by `App.tsx` as a slot):
  it draws the focused facility's `exposure_graph` (a map pin, the tab's picker, else the chat's
  selection) exactly as the API built it, laid out by ELK (`layout.ts`) on a React Flow canvas with
  flowing, labelled edges. It never decides what a pathway is: a new lane or node is a backend change
  (`api/services/exposure_graph/`). Quantities are formatted with `lib/format` only.
- Layout: `components/layout/SplitWorkspace` divides the window into rail | analysis (overview
  over map) | chat with `react-resizable-panels` splitters. Limits come from `layout` in the
  client config, never from constants. Fullscreen is CSS only (nothing unmounts; the others go
  `inert`), so the map keeps its camera and the chat its stream. The map watches its own
  container with a `ResizeObserver`; nothing else calls `map.resize()`. Escape belongs to the
  topmost layer: a layer that handles it calls `preventDefault()` and `stopPropagation()`.
- The rail's "Monitoring" shows `features/monitoring` over the analysis area through
  `SplitWorkspace`'s `covering` prop: the overview and map stay mounted underneath (inert, same
  size), the chat is untouched, and "Workspace" removes it. The view reads only
  `/api/v1/monitoring/*`, shows what Logfire returned (absent figures as "not reported"), and
  never asks for a token (the server holds it).
- `App` is a session gate (`hooks/useSession`, `GET /api/v1/auth/me`): while nobody is signed in it
  shows `features/auth` (sign in, sign up, check email, verify, forgot, reset) and the workspace is
  not mounted; signed in, `Workspace` is mounted keyed by user. Any 401 the API answers during use
  (`apiClient.onUnauthorized`; the `/auth/*` routes are exempt) returns to sign-in, so no previous
  user's data stays on screen. An emailed link opens `/#verify=<token>` or `/#reset=<token>`: the
  token is read into memory, removed from the address bar and sent only in a request body. The rail
  shows Monitoring to `role === "admin"` only; its Account entry opens `features/auth/AccountDrawer`
  (sign out, change password, sign out everywhere, delete account behind a password dialog).
- Browser storage holds panel sizes only (through `lib/safeStorage`, which never throws); never
  keys, runs, messages, passwords, tokens or the account. The page holds one workspace (one thread) at a time; the conversation
  lives on the server, and "Clear workspace" (always behind `components/ui/ConfirmDialog`)
  discards it there. The Word report is built by the server; the browser only saves the file
  (`lib/saveFile`).
- Talk to the system only through `/api/v1/*` via `services/apiClient.ts`; never call tools,
  the agent or assessment services directly. Only basemap tiles are fetched by the browser.
- `src/types/api.ts` is generated from `src/types/schema.json` (exported from `api/schemas/`);
  never edit it by hand, regenerate with `npm run gen:types`. `types/workspace.ts` only
  re-exports names from it.
- Show only values the API sent. Never compute, estimate or convert scientific values; an
  absent value renders as "not reported" (or its reason), never as 0 or "-".
- Display settings (thresholds, chips, digits, map styles) come from
  `GET /api/v1/settings/client`; never hard-code them.
- Never write the API key (or any part of it) to localStorage, sessionStorage, the URL or the
  console; clear the key input after saving. Render assistant Markdown without raw HTML.
- Design tokens live as CSS variables in `src/index.css` (light and dark); components use
  them, not literal colours. The one exception is the EcoFate mark (`components/ui/BrandLogo`),
  whose fixed artwork colours match `public/logo.svg` and `public/favicon.svg`. Respect `prefers-reduced-motion` and `prefers-color-scheme`.
- `DESIGN.md` in this folder is the design authority: direction, token meanings, scale,
  primitives, required states, copy and anti-patterns. Use the `ui-craft` skill for any UI work;
  compose from the primitives it lists and extend the document in the same change when a token
  or primitive is added (`src/designDoc.test.ts` keeps its token table equal to `index.css`).
- Run `/ui-check <surface>` (light and dark, checklist with evidence, visual and contrast tests)
  before UI work is called done; a `fail` row means the work is not finished.
- Pure helpers (formatting, SSE parsing, store reducers) get Vitest tests beside them.
