## Context

See proposal.md. The worker band was `highest_band(ratio, hq, risk)`; the chat drew `LiveLine` and
`StopNotice` inside each assistant message.

## Decisions

**D1. Cancer risk stays in the worker band.** Dropping it with the hazard quotient would understate
carcinogens whose limit is not health-protective for cancer (benzene: a TLV ratio of 0.6 can sit
beside a lifetime risk above 1e-4). Only the RfC hazard quotient is demoted, because the RfC is a
general-population value for lifelong continuous exposure, not a workplace benchmark.

**D2. No new ECETOC categories.** The table is built from TR 114 and holds only values read in the
source (PROC 8a). Adding PROC 8b or 9 without the source would invent numbers. The drum and truck
loading model is vapor displacement, valid at high vapor pressure; the overestimate came from the
worst-case room defaults, which the "upper bound" label now states.

**D3. One controls bar, owned by `ChatDock`.** `TurnControls` reads `busy`, the live status and the
latest message's interruption; it shows Running (status + Stop) or Stopped (message + Resume/Open
Settings) or nothing. `MessageStream` no longer takes any turn action; it marks an interrupted
message with "Stopped" only, so the reason is not shown twice.

## Risks / Trade-offs

- [The tool docstring sentence changed] → Run the chemical-name-only eval 10 times before keeping it
  (prompt and docstring edits have regressed the CAS rule before). Outcome: the reworded sentence
  gave 9/10, so the docstring was left unchanged and the rule goes in a facility note, shown only
  when the cancer risk lifts the band above the limit ratio's (10/10).
- [A stored thread's worker bands were computed with the old rule] → Bands are recomputed when the
  assessment runs again; stored threads keep what their tools returned.
