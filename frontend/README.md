[← Documentation index](../README.md#documentation) · [Architecture](../docs/architecture.md) · [API](../api/README.md) · [Design system](DESIGN.md)

# frontend/

The React app of the web interface. It talks only to `api/` over `/api/v1/*` and shows only what
the API sent. Rules for coding agents: `frontend/CLAUDE.md`. The design authority (direction, tokens,
primitives, required states, copy) is [`DESIGN.md`](DESIGN.md); UI audits are in
[docs](../docs/README.md#ui-audits).

## Contents

- [Stack and layout](#stack-and-layout)
- [Web interface](#web-interface)
- [Running it](#running-it)
- [Testing](#testing)
- [What the workspace shows (and does not)](#what-the-workspace-shows-and-does-not)

## Stack and layout

React 19, TypeScript (strict), Vite and Tailwind; MapLibre GL for the map, Recharts for the age-band
bar, `d3-sankey` (layout only) for the exposure chain and Lucide for icons. Source is under
`frontend/src/`:

    components/    layout/ and ui/: domain-agnostic primitives
    features/      overview/, map/, chat/, settings/, monitoring/, exposure-chain/, auth/, welcome/
    hooks/         the event stream, stores, key status, session
    services/      apiClient.ts: the only way to reach the system
    lib/           formatting, bands, pathways, safe storage, file saving
    types/         api.ts generated from schema.json (never edited by hand)

Imports are one-way: `components/` never import `features/`, and features never import each other's
internals. Design tokens are CSS variables in `src/index.css` (light and dark). Browser storage
holds only panel sizes and the welcome sheet's per-user seen flag.

## Web interface

A local split-screen app: the assessment overview and facility map on the left, the copilot chat on the right. `frontend/` (React) talks only to `api/` (FastAPI), which runs the same agent.

The app is a session gate: signed out, it shows sign in, sign up, check email, verify, forgot and reset; signed in, it shows the workspace. An emailed link opens `/#verify=<token>` or `/#reset=<token>`; the token is read into memory, removed from the address bar and sent only in a request body.

The left rail has these entries (Monitoring only for administrators), with **Account** and **Settings** at the bottom:

- **Workspace**: the analysis view.
- **While a turn runs**: a line under the answer says what is happening ("Waiting for a worker (about 2 ahead)", "Thinking", "Running: Fetching chemical properties"), next to a **Stop** button; the header says "Queued" while the turn waits. **Stop** ends the turn after its current step (that step's results are kept) and offers **Resume**. Reloading the page, or a dropped connection, picks up the same turn where the page left it: nothing is shown twice. The turn keeps running in the worker even when the page is closed.
- **Resume**: when a turn stops for a reason you can fix (your OpenAI account ran out of credits, the key was rejected, OpenAI rate-limited or failed, the run reached its step limit, the worker stopped mid-turn, you pressed Stop, or the turn ran past the worker's time limit), the chat keeps the partial answer and tool steps and says why, with a **Resume** button (and **Open Settings** for a rejected key). Resume continues from the last finished step: your message is not sent again and finished tool calls do not run again, and the usage of both parts counts as one turn. A turn can be resumed up to `[agent].max_resumes_per_turn` times (3 by default); sending a new message instead abandons the stopped turn. Unexpected errors are not resumable.
- **Clear workspace**: asks first, then discards the conversation, overview, charts and map (on the server too).
- **Generate report**: downloads a Word document laid out like an EPA screening-level assessment (summary, chemical properties, data sources, releases, exposure, risk, uncertainties, and the assistant's last answer labelled as model-generated). Every value in it comes from the dashboard.
- **Monitoring**: lists recorded agent sessions (see [monitoring](../docs/monitoring.md)).

How a turn runs in the background is described in [worker](../worker/README.md); the endpoints the app calls are in [api](../api/docs/endpoints-and-streaming.md#endpoints).

## Running it

    npm --prefix frontend ci && npm --prefix frontend run build   # once, and after frontend changes
    uv run python -m api                                           # serves frontend/dist at http://127.0.0.1:8000

The API needs PostgreSQL and a worker; the full start-up is in [api](../api/docs/running-and-testing.md#running-it).
For frontend work with hot reload, run `uv run python -m api` in one terminal and `npm --prefix frontend run dev` in another, then open http://localhost:5173.

## Testing

    npm --prefix frontend run check         # contract diff, tsc, eslint, vitest (must pass before work is done)
    npm --prefix frontend run test:visual   # renders *.visual.tsx in Playwright Chromium, light and dark,
                                            # and compares with __screenshots__/ (references are per OS)
    npm --prefix frontend run gen:types     # regenerate src/types/api.ts after the API schema changes

`check` runs `check:contract`, `typecheck`, `lint` and `test`. After a deliberate visual change,
look at every new image before approving it with `-u`.

## What the workspace shows (and does not)

The left pane is built only from what the tools returned; a value no tool reported reads "not reported", never zero. A scope check keeps the chat on environmental exposure and answers off-topic requests with a short redirect, without running the agent.

- **Summary cards:** highest worst-case and representative hazard quotient and lifetime cancer risk with a status (below, near or above the thresholds in `[ui.thresholds]`, each said in words), the chemical with its read-across provenance, the residents and age bands within the radius, and the weather.
- **Map:** a marker per facility from the inventory, coloured by risk status and sized by emission rate; hover or focus (Tab) a marker for its inspector. Facilities, buffers and results that cannot be tied to exactly one facility are listed as unattributed, not guessed.
- **Limits, stated on screen:** the shaded wedge is a *schematic* downwind sector (the half-angle in `[ui.map]` is a drawing choice), not a modelled plume footprint; stacks have three tiers (NEI, PSTK by SCC, EPA global default); the inventory gives the TRI document control number, not a TRI facility ID; the queried chemical's name is not shown (only its CAS and any surrogate's name); the weather arrow is one downwind direction, not a wind rose.
- **Cost:** the header shows session tokens and an estimated cost from the list prices in `[ui.pricing]` (with the date they were read).
