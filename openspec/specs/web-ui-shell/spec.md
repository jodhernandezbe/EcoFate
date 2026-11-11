# web-ui-shell Specification

## Purpose

The split-screen browser interface: an executive dashboard and facility map on the left and the
copilot chat on the right, built to Apple Human Interface Guidelines materials and motion.

## Requirements

### Requirement: Apple HIG visual language
Surfaces SHALL use translucent materials (`backdrop-filter: blur(20px)` with a solid fallback
where unsupported), 1px hairline borders (`rgba(0,0,0,0.08)` light, `rgba(255,255,255,0.1)`
dark), the system font stack (`-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro
Text"`, Inter fallback, sans-serif), and tabular numerals for every metric. Transitions SHALL
use `cubic-bezier(0.22, 1, 0.36, 1)`. The interface SHALL follow the OS light/dark preference,
and SHALL disable non-essential motion when the user prefers reduced motion. Text and status
colours SHALL meet WCAG AA contrast, and status SHALL never be conveyed by colour alone.

#### Scenario: Dark mode
- **WHEN** the OS is in dark mode
- **THEN** the interface, the basemap and hairlines switch to their dark variants

#### Scenario: Reduced motion
- **WHEN** the user prefers reduced motion
- **THEN** camera moves jump instead of fly and spring transitions are replaced by fades

### Requirement: Scientific notation and units
Every metric SHALL be shown with its unit; very small or large values (such as cancer risk)
SHALL use scientific notation rendered as `1.2 × 10⁻⁵`; the number of significant digits
SHALL come from configuration; absent values SHALL show "not reported" (or the reason given in
the state) rather than zero or a dash that could be read as zero. Values the UI did not receive
SHALL NOT be shown.

#### Scenario: Cancer risk
- **WHEN** the state reports a cancer risk of 0.000012
- **THEN** it renders as `1.2 × 10⁻⁵`

#### Scenario: Absent value
- **WHEN** a facility has no exit temperature
- **THEN** the inspector shows "not reported" for it

### Requirement: Executive summary ribbon
The top of the left pane SHALL show four cards updated from each `workspace_update` event:
1. HQ and cancer risk: highest worst-case and representative values with a status pill
   (green below, amber near, red above the threshold of concern, each also labelled in words);
2. Chemical and read-across provenance: name (when the state has one; otherwise the CAS number stands alone, never a name from elsewhere), CAS, molecular weight, RfC/IUR with sources, and a badge
   "Direct TRI match", "Read-across surrogate" (surrogate CAS/name, hybrid score, cosine,
   Tanimoto, in/out of applicability domain) or "Unresolved"; before the read-across tool has
   run the card shows no badge;
3. Exposed population: total within the radius `r` km and a horizontal stacked bar of the age
   bands 0-4, 5-17, 18-64, 65+, with the data source;
4. Meteorology: the facility it is for (or, for a point that is not one of the facilities, its
   coordinates and that fact), wind speed (m/s), a direction arrow pointing downwind with the from-direction in
   degrees, ambient temperature (K), Pasquill-Gifford class and source.
Cards whose data comes from a screening default SHALL show a "screening default" marker.

#### Scenario: Surrogate badge
- **WHEN** the state reports a read-across surrogate within the domain
- **THEN** card 2 shows the surrogate badge with its hybrid score and "within applicability domain"

#### Scenario: Default weather
- **WHEN** meteorology's source is the screening default
- **THEN** card 4 shows the screening-default marker

#### Scenario: Chemical name
- **WHEN** the state's chemical has a name
- **THEN** card 2 shows it before the CAS number; when it has none, card 2 shows the CAS number only

### Requirement: Interactive facility map
The analysis area SHALL show a vector basemap (light and dark styles from configuration) as soon
as the page loads, framed on the configured initial view (the contiguous United States), even
when no facility has been placed. It SHALL draw one marker per placed facility, coloured by its
risk status (or neutral when not computed) and sized by emission rate on a configured scale,
with a legend whose entries (below, near, above concern, not computed) each show how many
facilities have that status and hide or show the markers of that status, with their circles,
sectors and cards, when pressed. When the framing version changes, the camera SHALL animate to fit the bounding
box, with padding that keeps the framed facilities clear of the legend. The map SHALL redraw at
its new size whenever its container changes size (splitter drag, rail or chat collapse, panel
fullscreen, window resize), leaving no blank or stretched area. A "Reset to USA view" control
on the map SHALL return the camera to the configured initial view. It SHALL animate, or jump
when the user prefers reduced motion. For a facility with receptors the map SHALL draw the
receptor radius circle. With meteorology it SHALL draw a sector toward
`(wind_direction + 180) % 360` with a configured half-angle and the radius as length, labelled
"schematic downwind sector, not a modelled plume footprint".

#### Scenario: Before any query
- **WHEN** the page has loaded and no assessment has run
- **THEN** the basemap is visible, framed on the contiguous United States, with no markers

#### Scenario: Hide and show a status
- **WHEN** the user presses the "Above concern" legend entry and later presses it again
- **THEN** the markers of facilities above concern leave the map, with their circles, sectors and cards, and the entry reads as off with its count unchanged; pressing it again brings them back

#### Scenario: Legend counts
- **WHEN** the workspace holds one facility below concern, two above and one not computed
- **THEN** the legend entries show 1, 0, 2 and 1

#### Scenario: Fit to facilities
- **WHEN** a dashboard event raises the framing version
- **THEN** the camera flies to fit all placed facilities

#### Scenario: Container resized
- **WHEN** the user collapses the chat dock
- **THEN** the map fills the wider area without blank tiles or distortion

#### Scenario: Reset view
- **WHEN** facilities are framed and the user activates "Reset to USA view"
- **THEN** the camera returns to the contiguous United States and the markers stay placed

#### Scenario: Downwind sector
- **WHEN** the wind blows from 270°
- **THEN** the sector points toward 90°

### Requirement: Facility inspector popover
Hovering or keyboard-focusing a marker SHALL open a translucent inspector anchored to it, and
it SHALL close on leave, blur or Escape. It SHALL show: facility name, FRS ID, TRI document
control number, NAICS code and title; reported release with its unit, emission rate (g/s),
operating hours (h/yr) and CAS; the TSCA life cycle stages and conditions of use the API sent,
under visible labels naming them and TSCA (each condition with its COU category, its life cycle
stage, and the TRI activity and Form R item it was mapped from with the mapping's strength), or
"not reported" with the API's note when there are none; each stack's height (m), diameter (m), exit velocity (m/s), exit
temperature (K) with its provenance tier pill; and receptor metrics: worst-case and
representative maximum concentration (µg/m³), HQ, cancer risk and population within the
radius. The card SHALL be no taller than the space between the marker and the edge of the map on
the side it opens, so that a long card scrolls inside itself and no part of it is clipped out of
reach. Markers SHALL be reachable by keyboard and announce the facility name to screen readers.

#### Scenario: Keyboard focus
- **WHEN** a marker receives keyboard focus
- **THEN** the inspector opens for that facility and Escape closes it

#### Scenario: Several stacks
- **WHEN** the facility has three NEI candidates
- **THEN** the inspector lists all three with Tier 1 pills and the HQ range across them

#### Scenario: Several conditions of use
- **WHEN** the facility has conditions in Processing and Industrial use
- **THEN** the inspector lists both stages and each condition with its activity and category

#### Scenario: No conditions
- **WHEN** the facility has no conditions of use
- **THEN** the inspector shows "not reported" with the note, never an empty list that looks like a result

#### Scenario: Long card scrolls
- **WHEN** a facility's card has more content than the room between its marker and the edge of the map
- **THEN** the card is capped at that room and scrolls inside itself, with nothing clipped out of reach

#### Scenario: Labelled provenance
- **WHEN** the card shows conditions of use
- **THEN** a visible label names them as TSCA conditions of use, another names the life cycle stages, and each condition states the TRI activity and Form R item it was mapped from

#### Scenario: Click pins the card
- **WHEN** the user clicks a marker
- **THEN** its card stays open after the pointer leaves, its sections can be folded and unfolded, and it closes by its close control, by Escape or by a click on the map

#### Scenario: Pinned card is not replaced by hovering
- **WHEN** one facility's card is pinned and the pointer moves over another marker
- **THEN** the pinned card stays and the other facility's card does not open

### Requirement: Copilot chat
The chat dock SHALL show a header with the title, a live status indicator (idle, thinking,
running a tool, error), the usage meter, a clear control and a collapse control. An empty thread
SHALL show an onboarding state with three to four suggestion chips (text from configuration)
that submit their text when clicked. Assistant messages SHALL render Markdown safely (no raw
HTML), including GitHub Flavored Markdown tables, and stream as `token` events arrive. A table
SHALL render as a real table with a header row. It SHALL sit in its own horizontal scroll area,
so a table wider than the message scrolls sideways without widening the message, the chat or
the page. The header SHALL be shaded, all columns SHALL use tabular numerals, and cell text
SHALL NOT wrap. Tool steps SHALL appear as compact pills, grouped per turn in a collapsible row,
each showing its label and a running / done / error state. Off-topic redirects SHALL render as
normal assistant messages. The chat header's clear control SHALL perform the same "Clear
workspace" action as the navigation rail, including its confirmation.

#### Scenario: Suggestion chip
- **WHEN** the user clicks a suggestion chip
- **THEN** its text is sent as the user's message and the onboarding state disappears

#### Scenario: Tool pills
- **WHEN** a turn runs four tools
- **THEN** one collapsed row shows four pills that expand on click

#### Scenario: No raw HTML
- **WHEN** an assistant message contains `<script>`
- **THEN** it is shown as text and not executed

#### Scenario: Pipe table
- **WHEN** an assistant message contains a GFM pipe table with a header row
- **THEN** it renders as a table with header cells and body rows, not as literal pipes

#### Scenario: Wide table
- **WHEN** a rendered table is wider than the chat dock
- **THEN** only that table scrolls horizontally and the chat dock width is unchanged

#### Scenario: Chat clear asks first
- **WHEN** the user activates the chat header's clear control on a workspace with results
- **THEN** the same confirmation dialog as "Clear workspace" opens

### Requirement: Usage meter
The chat header SHALL show the session's total tokens and estimated cost, and a popover SHALL
break them down by input, cached input and output tokens for the last turn and the session,
marking the cost as an estimate, "unpriced" or "lower bound" as reported.

#### Scenario: After a turn
- **WHEN** a `usage` event arrives
- **THEN** the meter updates to the new session totals

#### Scenario: Unpriced
- **WHEN** the usage event's cost is unpriced
- **THEN** the meter shows tokens and "unpriced" instead of a dollar amount

### Requirement: The assistant does not describe what it cannot see
In the web program the assistant SHALL be told that it cannot see the overview or the map, what
the map shows (every facility the inventory found, not only those listed to it) and how details
open (pointing at or moving to a marker), and SHALL say no more about the map than that.

#### Scenario: Asked to show the map
- **WHEN** the user asks the assistant to show or explain the map
- **THEN** the assistant describes only what the map places and how to open a facility's details, and speaks of its own results otherwise

### Requirement: Resizable workspace shell
The interface SHALL fill exactly the viewport (`100dvh` x `100dvw`) without page scrolling and
SHALL be divided, left to right, into a navigation rail, an analysis area and a chat dock. Each
region SHALL scroll or pan independently. Adjacent regions SHALL be separated by a splitter that
can be dragged with a pointer and moved with the arrow keys when focused. Each splitter SHALL
show a 2–4 px accent line on hover, focus and drag, show a resize cursor, and announce itself to
assistive technology as a separator with its current value. Every region SHALL keep to the
minimum and maximum sizes given by configuration: the chat dock at least its configured minimum
width in px and at most its configured maximum share of the viewport width. Panel sizes SHALL be
remembered in browser storage for the same viewer (sizes and collapsed states only), clamped to the current limits
when restored. Below the configured narrow-viewport breakpoint the rail SHALL collapse to icons
and the analysis area and chat SHALL stack behind a segmented control (Overview, Copilot), still
without page-level scroll. Both stay mounted, so nothing is lost when switching.

#### Scenario: Desktop
- **WHEN** the window is 1440 x 900 on first load
- **THEN** the rail, analysis area and chat dock are all visible within their configured limits and the document does not scroll

#### Scenario: Drag the chat splitter
- **WHEN** the user drags the splitter between the analysis area and the chat dock past the chat's configured maximum
- **THEN** the chat dock stops at its maximum share of the viewport and the map redraws at the new size

#### Scenario: Keyboard resize
- **WHEN** a splitter has keyboard focus and the user presses an arrow key
- **THEN** the adjacent regions resize by one step within their limits

#### Scenario: Long chat
- **WHEN** the chat holds more messages than fit
- **THEN** only the chat list scrolls; the overview and map stay fixed

#### Scenario: Restored sizes out of range
- **WHEN** a remembered chat width exceeds the current window's maximum
- **THEN** the dock opens at the maximum, not at the remembered width

### Requirement: Settings drawer for the API keys
Choosing Settings in the navigation rail SHALL open a bottom drawer over the workspace. The drawer
SHALL keep the workspace and the chat mounted, can be resized and maximized, closes with
Escape or its close control, and keeps focus inside it while open, returning focus on close. The
drawer SHALL hold collapsible sections: an Assistant section for the user's OpenAI key and a
read-only Data services section. The OpenAI key SHALL have a label with an info tooltip stating
that it runs the assistant and is billed to the user's own OpenAI account, a password-type input
that can be cleared, a status reading "Key stored encrypted for your account" or "No key
configured" (never any part of the key), and "Clear key", "Reset" and "Save" actions. Save SHALL
be disabled while the input is blank or a request is running. The outcome of a save or clear
SHALL be shown in an inline success or error message in the section. Inputs SHALL be cleared
after saving and by Reset, and no key SHALL be written to browser storage, the URL or logs. The
Data services section SHALL list the Census service (counts the people around a facility) and
the CompTox service (looks up chemical properties and toxicity), each with "Provided by this
installation" or "Not available on this installation" and, when unavailable, which lookups will
be missing; it SHALL have no input for any key. When the OpenAI key is not configured, the chat
input SHALL point the user to Settings and the Assistant section SHALL open expanded.

#### Scenario: Open from the rail
- **WHEN** the user activates Settings in the navigation rail
- **THEN** the drawer opens over the workspace and the map and chat stay as they were

#### Scenario: Save key
- **WHEN** the user enters their OpenAI key and saves
- **THEN** the section shows a success message and the stored state, showing no part of the key, and its input is empty

#### Scenario: Save fails
- **WHEN** the server rejects a key
- **THEN** the section shows an error message and the stored state is unchanged

#### Scenario: Data services are read-only
- **WHEN** the drawer is open
- **THEN** the Data services section shows each service's availability and contains no input or save action

#### Scenario: Optional keys missing
- **WHEN** the installation has no Census key
- **THEN** the Census entry says it is not available on this installation and which lookups will be missing

#### Scenario: No browser storage
- **WHEN** a key has been saved
- **THEN** `localStorage` and `sessionStorage` contain no key material

### Requirement: Analysis panels with fullscreen
The analysis area SHALL hold an Overview panel (the executive summary) and a Map panel, each
with a header naming it. They SHALL be separated by a splitter that can be dragged, with the
same behavior and configured limits as the other splitters. Each panel header SHALL have a
fullscreen toggle with an accessible name ("Enter fullscreen" / "Exit fullscreen"). Entering
fullscreen SHALL make that panel fill the whole workspace (rail, other panel and chat hidden but
still mounted). Exiting, by the toggle or by Escape, SHALL restore the previous layout and sizes.
Escape SHALL close an open inspector or drawer before it exits fullscreen.

#### Scenario: Map fullscreen
- **WHEN** the user activates the Map panel's fullscreen toggle
- **THEN** the map fills the workspace, redraws at the new size, and keeps its markers and camera

#### Scenario: Escape exits
- **WHEN** a panel is fullscreen and no inspector or drawer is open and the user presses Escape
- **THEN** the previous layout and panel sizes are restored

#### Scenario: Chat state survives fullscreen
- **WHEN** a turn is streaming and the user toggles the Overview panel fullscreen and back
- **THEN** the chat has kept receiving the streamed answer

### Requirement: Collapsible chat dock
The chat dock header SHALL have a collapse control that hides the dock against the right edge,
giving its width to the analysis area. While collapsed, a visible control on the right edge
SHALL restore the dock with one click at its previous width. Collapsing SHALL NOT interrupt a
streaming turn or discard the draft in the composer.

#### Scenario: Collapse during a turn
- **WHEN** a turn is streaming and the user collapses the chat
- **THEN** the analysis area takes the full width and, on restore, the streamed answer is complete or still streaming with nothing lost

### Requirement: Risk by industry, condition of use and life cycle stage
The Overview panel SHALL have a switch between its Summary view (the ribbon, the default) and a "Risk by group" view, available before anything has run, and the Risk by group view SHALL always show three sections, one grouping the facilities by NAICS 3-digit subsector (code and title), one by TSCA condition of use (life cycle stage and COU category), and one by TSCA life cycle stage. Each section SHALL hold one bar chart and a switch in its header, "Hazard quotient" / "Cancer risk" (hazard quotient by default), that chooses which of the two quantities it shows, never both at once; the choice is shared by the three sections and kept while the user goes to the summary and back. The chart SHALL show the top five groups by the chosen quantity, one bar per group, all bars in one colour, on a logarithmic axis of its own with the quantity's thresholds drawn as labelled dashed lines (near concern and concern for the hazard quotient; the lower and upper cancer-risk thresholds for the cancer risk), and SHALL name those lines under its title, which names the quantity (hazard quotient, non-cancer, unitless; lifetime cancer risk, unitless). A bar's value SHALL be the highest worst-case value of that quantity among the group's fully assessed facilities, one of the values the API sent for a facility (a selection, never a sum, mean or conversion); a facility with no worst-case value, or screened out, SHALL not contribute to it, and a group with no value for the quantity SHALL not be ranked in that chart. Where the chart has nothing to rank it SHALL say why in place of the chart: that nothing is there to show yet before a run, that nothing was assessed, or that no group has the quantity (the chemical may have no unit risk). Hovering or focusing a bar SHALL show an opaque card with the group, that quantity's highest value, the facility it comes from and that facility's worst-case concentration (µg/m³), and the number of facilities in the group with how many were assessed and how many screened out. A facility with several conditions of use SHALL appear in each of them, and that section SHALL say so. Every bar SHALL also be available as text (a visually hidden table), and a count of the facilities in the run and of those with a worst-case result SHALL be shown above the sections.

#### Scenario: One quantity at a time
- **WHEN** the workspace has assessed facilities in three industries
- **THEN** the industry section shows one chart, of the hazard quotient, with one bar per industry in one colour and its own dashed threshold lines, and the switch offers "Cancer risk"

#### Scenario: Switching the quantity
- **WHEN** the user chooses "Cancer risk" in any section
- **THEN** all three sections show their cancer-risk chart, ranked by cancer risk with its own axis and thresholds, and the hazard quotient is not drawn; the choice survives going to the summary and back

#### Scenario: Each quantity ranks on its own
- **WHEN** there are eight groups with a hazard quotient and six with a cancer risk
- **THEN** the hazard-quotient chart shows the five highest hazard quotients and the cancer-risk chart the five highest cancer risks, each saying how many groups were not shown

#### Scenario: Value is a selected one
- **WHEN** a group has two assessed facilities with worst-case HQ 2 and 5
- **THEN** its hazard-quotient bar is 5 and no combined figure is shown

#### Scenario: Hover details
- **WHEN** the user hovers or focuses a bar
- **THEN** an opaque card names the group, that chart's highest value with its facility and concentration in µg/m³, and "n facilities in this group, m assessed"

#### Scenario: No unit risk
- **WHEN** no facility has a worst-case cancer risk
- **THEN** choosing "Cancer risk" shows a message that no group has a lifetime cancer risk to rank, and the hazard-quotient chart is unaffected

#### Scenario: Several conditions of use
- **WHEN** a facility has two conditions of use
- **THEN** it counts in both groups of the condition-of-use section, which notes that facilities can appear in several bars

#### Scenario: Before anything has run
- **WHEN** the workspace has no facilities and the user opens "Risk by group"
- **THEN** the three sections are shown, each with its chart replaced by a message that there is nothing to show yet, with "0 facilities in this run"

#### Scenario: Nothing assessed
- **WHEN** facilities exist but none has a worst-case result
- **THEN** each chart says that nothing was assessed yet, with no empty plot

#### Scenario: Unknown industry
- **WHEN** a facility has no subsector
- **THEN** it is not in any industry group and the section counts it as "industry not reported"

#### Scenario: Summary first, charts one click away
- **WHEN** the workspace has facilities and the Overview panel opens
- **THEN** the summary ribbon is shown with a "Summary" / "Risk by group" switch above it, and choosing "Risk by group" shows the three sections at the top of the panel without scrolling past the ribbon

#### Scenario: Switching views
- **WHEN** the user goes to the summary and back to the charts
- **THEN** the three sections are shown again

### Requirement: Expandable chart sections
Each of the three chart sections SHALL have a control with an accessible name ("Expand section" / "Restore section") that makes it fill the Overview panel's area, hiding the other sections without unmounting them, and restoring the previous layout on the same control or Escape. Escape SHALL close an open inspector or drawer first. In a wide panel the sections SHALL sit side by side and in a narrow one stack, by the panel's width, without horizontal page scroll.

#### Scenario: Expand and restore
- **WHEN** the user expands the industry section and then restores it
- **THEN** it fills the panel while expanded, the other sections are hidden (the ribbon belongs to the other view), and the layout returns as before

#### Scenario: Escape
- **WHEN** a section is expanded and no inspector or drawer is open and the user presses Escape
- **THEN** the section is restored

#### Scenario: Panel width
- **WHEN** the panel is narrow
- **THEN** the sections stack vertically and each chart fits the width

### Requirement: Clear workspace
"Clear workspace" SHALL open an in-app confirmation dialog (not a browser dialog) that says the
conversation, overview, charts and map will be discarded and cannot be recovered, with "Clear"
and "Cancel" actions; Cancel and Escape SHALL close it without changes, and focus SHALL return
to the control that opened it. On "Clear" the interface SHALL ask the server to discard the
current thread and then show an empty chat (onboarding state), an empty overview, no charts,
and an empty map framed on the United States, with the usage meter reset and any pending
confirmation card removed; the next message SHALL start a new thread. If the server cannot
discard the thread, the interface SHALL say so and keep the current workspace unchanged. The
entry SHALL be disabled while a turn streams and when the workspace is already empty (no
messages and no results).

#### Scenario: Clear after an assessment
- **WHEN** the workspace shows messages, facilities and charts and the user confirms "Clear"
- **THEN** the chat shows the onboarding state, the overview and charts are empty, the map shows the United States with no facilities, and the usage meter reads zero

#### Scenario: Cancel
- **WHEN** the confirmation dialog is open and the user presses Escape
- **THEN** the dialog closes, the workspace is unchanged and focus returns to "Clear workspace"

#### Scenario: Disabled while streaming
- **WHEN** a turn is streaming
- **THEN** "Clear workspace" is disabled and its tooltip says a reply is in progress

#### Scenario: Server refuses
- **WHEN** the user confirms "Clear" and the server answers with an error
- **THEN** a message says the workspace could not be cleared and every message, result and map layer is still shown

### Requirement: Generate report
"Generate report" SHALL request the current thread's Word report from the server and save it
through the browser as a `.docx` file named by the server. While the request runs the entry
SHALL show a busy state and SHALL NOT start a second request. The entry SHALL be disabled while
a turn streams and while the workspace holds neither a chemical result nor a facility, with a
tooltip saying why. If the request fails, the interface SHALL show the server's generic message
and leave the workspace unchanged. The interface SHALL NOT build or alter the report's content.

#### Scenario: Download a report
- **WHEN** the workspace holds an assessed facility and the user activates "Generate report"
- **THEN** a `.docx` file is downloaded and the workspace is unchanged

#### Scenario: Nothing to report
- **WHEN** the workspace is empty
- **THEN** "Generate report" is disabled and its tooltip says there are no findings yet

#### Scenario: Report fails
- **WHEN** the server answers the report request with an error
- **THEN** a message with the generic error text is shown and no file is saved

### Requirement: Navigation rail with workspace and monitoring views
The leftmost region SHALL be a navigation rail with two states: collapsed (an icon rail of about
60 px) and expanded (resizable within its configured limits, 200–320 px by default). A toggle
next to the brand mark at the top SHALL switch between them. In order, the rail SHALL show: at
the top, the brand mark and the toggle. Below them, the entries "Workspace", "Clear workspace",
"Generate report" and, for administrators only, "Monitoring". At the bottom, an Account entry
(showing the signed-in email, with "Sign out" and account management) and a Settings entry. For
a user without the `admin` role the "Monitoring" entry SHALL NOT be rendered. The rail SHALL NOT
list runs and SHALL NOT offer a "New analysis" action. The entry for the view on screen
("Workspace" or "Monitoring") SHALL be marked as the current page, in words for assistive
technology and not by colour alone. Activating "Workspace" SHALL show the workspace, leave
fullscreen and close the Settings drawer and any open dialog. Activating "Monitoring" SHALL
show the Monitoring view and close the Settings drawer and any open dialog. The workspace
panels and the chat stay mounted and keep their state. In the collapsed state every entry SHALL
show only its icon with an accessible name and a tooltip; a disabled entry's tooltip SHALL say
why it is disabled. Signing out SHALL end the session on the server and show the sign-in
screen.

#### Scenario: Collapse and expand
- **WHEN** the user activates the toggle on an expanded rail
- **THEN** the rail collapses to icons, the analysis area widens, and the map redraws at its new size

#### Scenario: Collapsed entries remain usable
- **WHEN** the rail is collapsed and the user focuses the Settings icon
- **THEN** it announces "Settings" and opens the settings drawer when activated

#### Scenario: Entries in order
- **WHEN** the rail is expanded for an administrator
- **THEN** it shows Workspace, Clear workspace, Generate report and Monitoring in that order, then Account and Settings at the bottom, and no run list

#### Scenario: Entries for a regular user
- **WHEN** the rail is expanded for a user without the `admin` role
- **THEN** it shows Workspace, Clear workspace and Generate report, then Account and Settings, and no Monitoring entry

#### Scenario: Return to the workspace
- **WHEN** the map is fullscreen and the Settings drawer is open, and the user activates "Workspace"
- **THEN** the drawer closes and the overview, map and chat are all visible again

#### Scenario: Open Monitoring
- **WHEN** an administrator activates "Monitoring"
- **THEN** the Monitoring view is shown, "Monitoring" is announced as the current page, and returning to "Workspace" shows the panels and chat as they were left

#### Scenario: Sign out
- **WHEN** the user chooses "Sign out" from the Account entry
- **THEN** the server session is deleted and the sign-in screen replaces the workspace

### Requirement: Worker results sit with the community results
The interface SHALL show the worker (occupational) screening wherever it shows the community result, never in a separate view: the Overview summary ribbon, the facility inspector and the map. It SHALL show only values the API sent, and an absent value SHALL read "not reported", never zero.

#### Scenario: No separate view
- **WHEN** the Overview panel is open
- **THEN** it offers the same views as before (Summary and Risk by group) and no view or facility picker for the workers alone

#### Scenario: Not reported
- **WHEN** a facility has no worker result
- **THEN** every worker value of it reads "not reported" and no zero is shown

### Requirement: Worker card in the summary ribbon
The Overview summary ribbon SHALL include a "Worker exposure" card with the highest 8-hour TWA to limit ratio, worker hazard quotient and worker lifetime cancer risk over the assessed facilities, each for the baseline ventilation and the enclosed-zone worst case, with the facility each comes from and its tier in words, in the way the hazard quotient and cancer risk card names its facility. Where nothing is available it SHALL say why.

#### Scenario: Highest values
- **WHEN** several facilities have worker results
- **THEN** each figure is the highest among them and names its facility

#### Scenario: Nothing yet
- **WHEN** no facility has a worker result
- **THEN** the card shows "not reported" for each figure and the reason

### Requirement: Worker section in the facility inspector
The facility inspector (hover and pinned card) SHALL show a compact badge with the community hazard quotient and the worker tier with its limit ratio, so a user can see whether the concern comes from the stack plume or from indoor fugitive release, and a "Worker exposure" section with the facility's operating schedule (days per year, hours per day, hours per year), life cycle stage and condition of use, CDR industrial sector, fugitive release, occupational limit and its source, and for both ventilation tiers the 8-hour TWA, limit ratio, worker hazard quotient and worker cancer risk and the tier, with the warnings. The tier SHALL be written as text as well as coloured.

#### Scenario: Both results
- **WHEN** a facility has a community and a worker result
- **THEN** the badge shows both and the section lists both tiers

#### Scenario: Tier not by colour alone
- **WHEN** a tier is shown
- **THEN** it is written in words

### Requirement: Worker tier on the map
The map SHALL draw a ring around each facility marker coloured by the worker tier (none while it is not computed), keeping the marker fill for the community status and its size for the emission rate; the legend SHALL explain the ring and count the facilities of each tier, and the marker's accessible name SHALL include the worker tier.

#### Scenario: Ring and fill
- **WHEN** a facility is above concern in the community result and elevated for workers
- **THEN** its marker is filled for the community status and ringed for the elevated tier

#### Scenario: No worker result
- **WHEN** no facility has a worker result
- **THEN** no ring is drawn and the legend has no ring entry

#### Scenario: Accessible name
- **WHEN** a marker has a worker tier
- **THEN** its accessible name includes it

### Requirement: Risk by group has an exposure pathway dropdown
The Risk by group view SHALL have one dropdown, above its three sections, that chooses the exposure pathway as medium, route and receptor: "Outdoor Air → Inhalation → General Population" (the default, the community result) or "Indoor Air → Inhalation → Worker" (the worker result). The choice SHALL apply to the three sections and be kept while the user goes to the summary and back. On the indoor pathway the quantity switch SHALL offer the worker hazard quotient, the worker lifetime cancer risk and the 8-hour average over the occupational limit, each bar being the highest value among the group's assessed facilities at the baseline ventilation, and the dashed lines SHALL be the worker tier boundaries from the client settings; the tooltip SHALL give the facility and its 8-hour average. A bar's tooltip SHALL name the facility and stack that drive it. A facility with no worker value SHALL not be ranked, and a chart with nothing to rank SHALL say why. Leaving the indoor pathway while the limit ratio is shown SHALL return to the hazard quotient.

#### Scenario: Default
- **WHEN** the Risk by group view opens
- **THEN** it has one pathway dropdown, on the outdoor air pathway, and every section shows what it showed before

#### Scenario: Indoor air
- **WHEN** the user chooses the indoor air pathway
- **THEN** all three sections rank the worker values, with the worker boundaries drawn

#### Scenario: Limit ratio only for workers
- **WHEN** the outdoor air pathway is chosen
- **THEN** the limit ratio is not offered

#### Scenario: Nothing to rank
- **WHEN** no facility has a worker value
- **THEN** the chart says why, with no zero bars

#### Scenario: Bar names its driver
- **WHEN** the user hovers a bar
- **THEN** the tooltip names the facility and the stack that give its value

### Requirement: Overview has an Exposure chain tab
The Overview SHALL offer a third tab, "Exposure chain", beside Summary and Risk by group, showing the
exposure diagram of the focused facility. Summary and Risk by group SHALL be unchanged, and the diagram
SHALL keep its selection while the user switches tabs.

#### Scenario: Third tab
- **WHEN** the user opens the Overview
- **THEN** the switch offers Summary, Risk by group and Exposure chain

#### Scenario: State kept
- **WHEN** the user opens a node's detail, switches to Summary and back
- **THEN** the same node's detail is still open

### Requirement: Pinning a facility focuses it
Pinning a facility on the map (a click on its marker) SHALL report that facility to the application so the
Exposure chain tab can show it. Hovering and unpinning SHALL NOT change the focus.

#### Scenario: Pin
- **WHEN** a marker is clicked
- **THEN** the Exposure chain tab shows that facility

#### Scenario: Hover only
- **WHEN** a marker is only hovered
- **THEN** the diagram does not change

### Requirement: The summary ribbon shows the driving scenario
For each pathway and quantity that has a scenario the ribbon SHALL show the driving scenario by rendering its generic shape: the value and tier, the facility, its factors grouped as source, release, conditions and receptor model, and its most affected receptors (or the reason there are none), instead of listing every facility, stack or population. A pathway added later SHALL be shown without display code of its own. Other facilities SHALL be reachable through an explicit control that is closed by default. An absent factor SHALL read "not reported" with its reason.

#### Scenario: Driver shown
- **WHEN** a run has assessed facilities
- **THEN** each result shows only its driving scenario and a closed control for the others

#### Scenario: Nobody at the maximum
- **WHEN** a community scenario has no receptors
- **THEN** the reason it gives is shown in place of the receptors

#### Scenario: Others on request
- **WHEN** the user opens the control for the others
- **THEN** the other facilities are listed by value, each selectable

### Requirement: The facility inspector shows the worst-case scenario first
The inspector SHALL show a facility's worst-case scenarios before any list of stacks, with the stack that drives each marked in that list, and SHALL show the receptors of the community scenario with their age bands, distance and bearing. The other stacks SHALL stay in a section that is closed when the scenario names one.

#### Scenario: Driving stack marked
- **WHEN** a facility has three stacks and stack 2 drives the hazard quotient
- **THEN** the scenario names stack 2 and the stack list marks it

### Requirement: The map marks the driving facility and its receptors
The map SHALL mark the driving facility of the selected result, and when that facility is selected SHALL draw its listed receptors at their bearing and distance, without drawing the receptors of other facilities. Receptors SHALL be drawn at the coordinates the tool returned, never at a position computed in the browser, only for the results the pinned facility drives, and a tract several results name SHALL be drawn once.

#### Scenario: Receptors drawn
- **WHEN** the driving facility is pinned
- **THEN** its listed receptors are drawn at the coordinates the tool gave

#### Scenario: Receptors removed
- **WHEN** the facility is unpinned or closed
- **THEN** no receptor is drawn

### Requirement: Empty sections take their content height
A section of the executive summary that has no data SHALL occupy only the height of its content;
grid rows SHALL grow to share the panel only when they hold data. At first load the five summary
cards SHALL be visible without scrolling at the default panel size.

#### Scenario: First load
- **WHEN** the workspace has no scenario drivers
- **THEN** the worst-case section is one line high and the risk, worker, chemical, population and meteorology cards follow directly beneath it

#### Scenario: Scenarios present
- **WHEN** the workspace has scenario drivers
- **THEN** the worst-case section grows with its content as before

### Requirement: Map overlays never escape the map
The map SHALL be its own stacking context: its basemap control, legend, notices and inspector
SHALL never render above a layer that covers the analysis area (the Monitoring view, drawers,
dialogs, a fullscreen panel).

#### Scenario: Monitoring open
- **WHEN** the Monitoring view covers the analysis area
- **THEN** no map control or legend is visible over it

### Requirement: Legend before data
While no facility is mapped, the legend SHALL show one sentence saying so instead of per-status
counts; counts SHALL appear once at least one facility exists.

#### Scenario: No facilities
- **WHEN** the workspace has no facilities
- **THEN** the legend reads "No facilities mapped yet" and shows no counts

#### Scenario: Facilities present
- **WHEN** the workspace has facilities
- **THEN** each status entry shows its count

### Requirement: Disabled controls say why
A disabled navigation action SHALL expose the reason it is disabled both as a tooltip and as an
accessible description.

#### Scenario: Nothing to clear
- **WHEN** the workspace is empty and "Clear workspace" is disabled
- **THEN** the control's accessible description states the reason

### Requirement: Compartment badges in words
The welcome mark's compartment badges SHALL be sentence-case words, with compartments that are not
yet available marked "planned", and SHALL NOT use decorative separators or tracked uppercase.

#### Scenario: Welcome shown
- **WHEN** the conversation is empty
- **THEN** the badges read "Air", "Water (planned)", "Soil (planned)"

### Requirement: Absent age bands are not zero
An age band the API did not report SHALL be omitted from the population bar and listed as "not
reported" beneath it; it SHALL NOT render as a 0 % share.

#### Scenario: Band missing
- **WHEN** the receptors' age distribution lacks a band
- **THEN** the bar shows only the reported bands and the missing band is named as not reported

### Requirement: Resume an interrupted turn from the chat
When a turn is interrupted, the chat SHALL keep the assistant's partial text and tool pills,
show the interruption's fixed message beneath them, and, when the turn can be resumed, a
**Resume** button that resumes it in place: the resumed events SHALL continue the same
assistant message. For a rejected key the chat SHALL also offer to open Settings. While a turn
is running the Resume button SHALL be disabled and say why. A turn that cannot be resumed SHALL
show its message without a Resume button. The composer SHALL stay usable, and sending a new
message SHALL replace the Resume button with the new turn. When the chat restores a held thread
from its snapshot, it SHALL restore the interruption and its Resume button with it (restoring the
thread after a page reload is a separate change). The status indicator
SHALL show that the turn stopped. No dashboard panel SHALL change.

#### Scenario: Out of credits
- **WHEN** a turn is interrupted with reason `out_of_credits`
- **THEN** the message says the account has no credits and how to add them, and a Resume button is shown

#### Scenario: Resume continues the message
- **WHEN** the user presses Resume and the run answers
- **THEN** the answer streams into the same assistant message, after its earlier tool pills, and the Resume button disappears

#### Scenario: Rejected key
- **WHEN** a turn is interrupted with reason `bad_key`
- **THEN** the chat offers both Resume and a control that opens the Settings drawer

#### Scenario: Restored thread keeps Resume
- **WHEN** the chat restores a held thread whose latest turn is interrupted and resumable from its snapshot
- **THEN** the chat shows the interruption message and the Resume button again

#### Scenario: Cap reached
- **WHEN** an interrupted turn is no longer resumable
- **THEN** its message is shown without a Resume button

### Requirement: Account screens before the workspace
When the server reports no signed-in user, the interface SHALL show the account screens
instead of the workspace: sign in, sign up, check your email, verify email, forgot password and
reset password, each reachable from the others by links. They SHALL use the design system's
tokens and existing controls, label every input, show a progress state while a request runs,
show the server's user-safe message on failure, and never say whether an email has an account
beyond what the server answered. A token from an emailed link SHALL be read from the URL
fragment, sent in a request body, and removed from the address bar. No password or token SHALL
be written to browser storage. Any 401 from the API during use SHALL return the interface to
sign in without a reload and without keeping the previous user's workspace on screen.

#### Scenario: First visit
- **WHEN** an anonymous person opens the app
- **THEN** the sign-in screen is shown with links to sign up and to recover a password, and the workspace is not rendered

#### Scenario: Reset link
- **WHEN** a person opens a reset link
- **THEN** the reset screen is shown, the token is no longer in the address bar, and submitting a new password sends the token in the request body

#### Scenario: Session expires mid-use
- **WHEN** an API call returns 401 while the workspace is open
- **THEN** the sign-in screen replaces the workspace and no previous thread data remains visible

#### Scenario: No credentials in storage
- **WHEN** a user has signed up, signed in and reset a password
- **THEN** `localStorage` and `sessionStorage` contain no password and no token

### Requirement: Remaining turns shown before typing
When the daily quota applies to the signed-in user, the header SHALL show the number of turns
left today next to the usage meter, refreshed when the page loads and after every finished
turn. When no turns are left, the chat input SHALL be disabled and SHALL say that the daily
limit was reached and when it resets, in the user's local time. A 429 answer from the chat
endpoint SHALL put the interface in the same state. When the quota does not apply (disabled,
or an exempt admin), no quota figure SHALL be shown.

#### Scenario: Turns left
- **WHEN** a user with 3 turns left opens the app
- **THEN** the header says 3 turns are left today

#### Scenario: Limit reached
- **WHEN** the user's last turn of the day finishes
- **THEN** the header shows none left and the chat input is disabled with the reason and the local reset time

#### Scenario: Refused by the server
- **WHEN** the chat endpoint answers 429
- **THEN** the interface shows the same disabled state with the reset time from the response and the typed message stays in the input

#### Scenario: Exempt admin
- **WHEN** an exempt admin is signed in
- **THEN** no quota figure is shown and the chat input is enabled
