# Design system

Read by the `ui-craft` skill and `/ui-check` before any UI work. This describes the interface as
it is meant to be; it does not propose a restyle. Headings are fixed: `src/designDoc.test.ts`
reads the Tokens section and the command reads Required states, Copy and Anti-patterns.

## Direction

The app is a screening instrument for chemical exposure and risk: an assessor reads numbers,
their units and their status, then looks at where the plume lands. The visual language follows
Apple's Human Interface Guidelines: quiet translucent surfaces separated by hairlines, the system
typeface, tabular figures, and motion only when it answers an action. Status is always said in
words next to its colour. The memorable elements are the facility map and the exposure-chain
canvas; cards, chat and chrome stay quiet so they recede behind the data. One typeface family (the
system stack: SF Pro, then Inter) in two weights, medium for values and semibold for titles.

## Tokens

Declared in `src/index.css` (`:root` light, dark through `prefers-color-scheme`), exposed to
Tailwind as `bg-bg`, `text-fg`, `text-fg2`, `border-hairline`, `bg-ok/15` and so on. Components
use the tokens, never a literal colour, shadow, easing or font.

| Token | Light | Dark | Meaning | Use for | Never for |
| --- | --- | --- | --- | --- | --- |
| `--bg` | `#f5f5f7` | `#000000` | Page and canvas background | `body`, panel wells, hover fill of solid controls | Card fills |
| `--surface` | `rgba(255,255,255,.72)` | `rgba(30,30,32,.72)` | Translucent material behind blur | `.glass` cards, panel frames, drawers | Text, borders |
| `--surface-solid` | `#ffffff` | `#1c1c1e` | Solid material | `.glass` fallback without blur, popovers, minimap, flow controls | Decorative blocks |
| `--fg` | `#1d1d1f` | `#f5f5f7` | Primary text and icons | Values, body copy, titles of content | Captions |
| `--fg-2` | `#6e6e73` | `#a1a1a6` | Secondary text | Captions, metric labels, panel titles, "not reported", loading status | Values that matter |
| `--hairline` | `rgba(0,0,0,.08)` | `rgba(255,255,255,.1)` | The one line | 1px borders, dividers, splitters, hover fill of icon buttons | Text |
| `--accent` | `#0066cc` | `#2997ff` | Interactive | Links, primary action, focus ring, selected state, chat send | Status, decoration |
| `--accent-fg` | `#ffffff` | `#000000` | Text on accent | Labels inside accent-filled controls | Anything else |
| `--series-cancer` | `#8944ab` | `#bf5af2` | The cancer-risk series | Cancer risk bars and markers next to hazard-quotient series | Status, UI chrome |
| `--ok` | `#1b7a34` | `#32d74b` | Below the level of concern | `StatusPill`, `TierPill`, success `Banner`, scenario level | Buttons |
| `--warn` | `#a35200` | `#ff9f0a` | Near the level of concern, or a screening default | `StatusPill`, `TierPill`, "screening default" badge | Errors |
| `--bad` | `#c4001a` | `#ff6961` | Above the level of concern, or an error | `StatusPill`, `TierPill`, error `Banner`, `role="alert"` text | Emphasis |
| `--shadow` | `0 8px 30px rgba(0,0,0,.12)` | `0 8px 30px rgba(0,0,0,.5)` | Elevation of a layer over the workspace | `BottomDrawer`, `ConfirmDialog`, popovers | Cards in the flow |
| `--ease` | `cubic-bezier(.22,1,.36,1)` | same | The one easing (a settled spring) | `.spring`, `.sheet-in`, camera and splitter transitions | Linear or bounce effects |
| `--font` | system stack | same | The typeface | `body`; nothing sets another family | Monospace for data labels |

Status colours are always tinted at 15% behind their own text (`bg-ok/15 text-ok`) so the pill
reads in both schemes; the words carry the meaning, the colour confirms it.

## Type and spacing scale

| Role | Size / weight | Spacing | Notes |
| --- | --- | --- | --- |
| Micro badge | `text-[11px] font-medium` | `px-1.5 py-0.5`, `rounded-full` | "screening default", provenance badges; `text-[10px]` only inside the collapsed rail |
| Caption, label | `text-xs text-fg2` | `gap-1` between label and value | Metric labels (`<dt>`), legends, hints |
| Panel and card title | `text-xs font-semibold uppercase tracking-wider text-fg2` | `px-4 py-2` header | The only uppercase text (`PanelHeader`, `CardFrame`) |
| Sub-label, column head | `text-xs font-semibold text-fg2` (`text-[11px]` inside dense popovers and chain nodes) | | Sentence case; table column heads and section sub-titles are not panel titles |
| Body, value | `text-sm` (`font-medium tabular-nums` for values) | rows `px-3 py-2`, `gap-2` | Metric values (`<dd>`), list rows, pills |
| Chat body | `text-[15px]` | `px-5` | Assistant and user messages only |
| Section title | `text-lg` or `text-xl font-semibold tracking-tight` | `gap-3` | Card and drawer titles; never larger |
| Card interior | | `p-4`, children `gap-3` | Ribbon cards, inspector sections |

Everything numeric is tabular (`font-variant-numeric: tabular-nums` on `body`). Digits come from
the client configuration, never from a constant.

## Materials, radius and motion

- **Glass**: `.glass` is `--surface` with `backdrop-filter: blur(20px) saturate(180%)` and a
  `--hairline` border; where blur is unsupported it falls back to `--surface-solid`. Regions are
  separated by hairlines, not shadows, because the surfaces are translucent.
- **Radius ladder**: `rounded-full` for pills and icon buttons; `rounded-lg` for inputs and small
  controls; `rounded-xl` for inner cards, messages and alerts; `rounded-2xl` for glass cards,
  panels and drawers. Nothing else.
- **Elevation**: only layers over the workspace (`BottomDrawer`, `ConfirmDialog`, popovers) cast
  `--shadow`. Cards in the flow do not.
- **Motion**: `--ease` everywhere, `.spring` on hover and state transitions, `.sheet-in` (420 ms)
  for a sheet or drawer appearing. Motion answers the user's action (open, expand, confirm,
  camera fly to a pin); nothing moves on its own except the exposure chain's flowing edges, which
  show direction. Under `prefers-reduced-motion` all animation collapses to 0.01 ms and camera
  moves jump instead of fly.
- **Focus**: `:focus-visible` is a 2px `--accent` outline with 2px offset, never removed.
- **Layering ladder**: panel content < overlays inside their own region (the map is `isolate`,
  so its basemap button, legend and inspector never leave it) < a view covering the analysis area
  (`z-10`) < a fullscreen panel (`z-30`) < drawers and dialogs over a scrim. Fullscreen is CSS
  only; other regions become `inert`. Escape belongs to the topmost layer. Confirmations are
  in-page (`ConfirmDialog`), never browser dialogs.
- **Scrolling panels show their edges.** A panel that scrolls (`.scroll-edges`, on `PanelFrame`)
  draws a soft shadow at an edge only while content continues beyond it.
- **Third-party chrome follows the tokens.** The map's attribution chip uses `--surface-solid` and
  `--fg-2`; its fixed black info icon is inverted in dark.
- **Empty sections take their content height.** Grid rows share the panel only when they hold
  data; a section with one sentence never claims a band of empty space. Without scenarios the summary's rows all
  take content height; an empty card beside a populated one still matches its row.
- **Focus on a composite control** (the chat composer) is the same 2px accent ring on the
  container through `focus-within`, following its radius; the inner field draws none.

## Primitives

`components/ui/` (domain-agnostic) and `components/layout/` (the shell). Features compose these;
they do not restyle them. Adding a primitive means adding a row here.

| Primitive | What it is | Use when | Not for |
| --- | --- | --- | --- |
| `GlassCard` | Translucent `rounded-2xl` surface with hairline | Any card in the analysis area or chat | Nested inside another `GlassCard` |
| `StatusPill` | Coloured pill that also says the status in words; `null` renders "Not computed" | Community risk status (below / near / above concern) | Arbitrary tags |
| `TierPill` | Same for the occupational screening tier | Worker screening tier | Community status |
| `SegmentedBar` | Horizontal stacked bar summing to 100 with legend | Shares of a whole (age bands) | Comparing independent quantities |
| `Banner` | Inline success or error line; errors interrupt assistive technology | Result of a user action (key saved, report failed) | Persistent status |
| `AccordionSection` | Heading button that shows or hides content, `aria-expanded` | Secondary detail inside a card or drawer | Primary navigation |
| `BottomDrawer` | Modal card docked to the bottom over a scrim, resizable, Escape closes; `fitContent` opens it at its content's height until the user resizes it | Settings and long detail views | Short confirmations |
| `ConfirmDialog` | In-page confirmation over a scrim, focus trapped, returns focus | Any destructive action (clear workspace) | Information only |
| `InfoTooltip` | Info icon explaining a field on hover or focus | A field whose meaning is not obvious | Hiding required information |
| `ScenarioView` | One worst-case scenario: value and level, factors by group, receptors | Every scenario, whatever the pathway | Ad-hoc layouts per pathway |
| `BrandLogo` | The EcoFate mark with fixed artwork colours | Rail and header | Recolouring |
| `SplitWorkspace` | Rail / analysis / chat shell with splitters; stacks behind a segmented control when narrow | The one page | A second shell |
| `PanelFrame`, `PanelHeader` | Titled panel with fullscreen toggle and extra controls | Overview, map, monitoring | Cards |
| `PanelSplitter` | Draggable, keyboard-resizable divider | Between panels | Decorative lines |
| `LeftNavRail`, `TopHeaderBar`, `CopilotToggle` | Navigation and chat chrome | The shell only | Feature content |

Icons are Lucide, sized `size-4` inline and `size-7` as icon buttons; icon-only controls carry
`aria-label`.

## Required states

| State | Looks like | Says |
| --- | --- | --- |
| Loading | A `text-xs text-fg2` line with `role="status"` in the surface's final size; no spinner, no layout shift | "Loading…" or what is being fetched |
| Empty | One `text-sm text-fg2` sentence inside the card | What there is nothing of and, when useful, what would make it appear |
| Absent value | The value slot in `text-fg2` at body size, never the large headline size | "not reported", or the reason the API gave |
| Error | `role="alert"`, `text-bad`, inside a hairline `rounded-xl` box (or a plain line in the rail) | What failed and what to do; never a raw exception |
| Ready | Value in `text-sm font-medium tabular-nums` with its unit; status as a pill with words | Scientific notation as `1.2 × 10⁻⁵`; digits from configuration |
| Streaming or partial | `aria-live="polite"` text in `text-fg2` while the assistant works | What the assistant is doing (tool pill) |
| Interactive | Visible focus ring, `aria-pressed` on toggles, disabled controls dimmed and inert | Labels on every icon-only control; a disabled control says why (tooltip and `aria-description`) |

## Copy

- Sentence case everywhere except panel and card titles (uppercase by `PanelHeader` and
  `CardFrame`).
- Absent values are "not reported"; an unknown status is "Not computed" on every pill (community and worker); a default is labelled
  "screening default". Never `0`, `-`, `N/A` or an empty cell.
- Status words are exactly "Below concern", "Near concern", "Above concern". Never write
  "unreasonable risk" or any regulatory determination.
- Every number carries its unit; the UI shows only values the API sent and never computes,
  converts or rounds beyond the configured digits.
- Counts of items (pins, rows) are shown only when there are items to count; before that one
  sentence says there is nothing yet.
- Errors name the thing that failed in plain words and what the user can do next.
- Assistant Markdown renders without raw HTML.

## Anti-patterns

- A literal colour, shadow, easing or font family in a component (the EcoFate mark is the only
  exception).
- Status conveyed by colour alone, or a pill without words.
- Zero, a dash or an empty cell for an absent value; a computed or converted value.
- Thresholds, digits, chip texts or map styles hard-coded instead of read from the client
  configuration.
- A browser `confirm()` or `alert()`; a drawer or dialog that unmounts the workspace.
- Decorative motion: entrance animations per card, hover lifts, anything that moves unprompted.
- A second icon library, a monospace face for data labels, numbered markers on content that is
  not a sequence, uppercase text outside panel and card titles.
- A new primitive that duplicates one in the table above.

## Known drift

- `Metric`, `CardFrame` and `ScreeningDefault` live in `features/overview/Metric.tsx` although
  they are domain-agnostic; compose from them for ribbon cards and move them to `components/ui/`
  when a second feature needs them.
