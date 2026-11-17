## Why

A live n-hexane run flagged every facility's workers as High. Reading the stored run showed three
reasons. The worker band took the highest of the limit ratio, a hazard quotient against the
general-population RfC (0.7 mg/m³, about 250 times below the ACGIH TLV of 176 mg/m³) and a cancer
risk, so any workplace above about 2 mg/m³ became High. The one facility with OSHA measurements
(95th percentile 66.6 mg/m³, 0.38 of the TLV) was High only through that hazard quotient. The
modelled worst case (34,029 mg/m³ for drum filling with ChemSTEER's worst-case defaults) read like
an expected exposure. Separately, the chat's Stop and Resume controls sat inside the thread, under
the answer, where they scroll away and mix controls with history.

## What Changes

- **Worker band:** the higher of the limit-ratio band and the cancer-risk band. The worker hazard
  quotient (against the RfC) sets the band only when there is no occupational limit; otherwise it is
  reported as context. The community band is unchanged.
- **Worst case is labelled an upper bound:** the graph's worst-case variant reads "worst case, upper
  bound" wherever a worst-case value is labelled (exposure chain, detail panel).
- **Worker lane names its activity:** the release step of the worker lane is titled with the
  driving activity's own name (for example "Filling drums (55 gal)"), falling back to the configured
  words when there is none.
- **Withheld titles:** the run-wide chain's anonymiser also checks step titles; a title that quotes
  the facility becomes the configured withheld title.
- **BREAKING (UI): turn controls move out of the thread.** A bar under the chat header shows the
  live status and Stop while a turn runs, and the interruption's message with Resume (and Open
  Settings for a rejected key) after a stop. The thread keeps only a "Stopped" marker.
- Not changed: the ECETOC fallback stays limited to evaporation tasks. The bundled ECETOC table holds
  only PROC 8a, and the loading model (vapor displacement) is not one of the evaporation models
  ChemSTEER's volatility range applies to; PROC 8b and 9 values would have to come from TR 114 itself.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `risk-bands`: how a worker result's band combines its quantities.
- `web-ui-shell`: "Resume an interrupted turn from the chat" and "Live turn status in the chat"
  place the controls at the top of the chat.

## Impact

- `tools/assessment/helpers/occupational/dosimetry.py` (`band_of`), the assessment tool's
  docstring (one sentence; the chemical-name-only eval must be run 10 times before it is kept),
  `prompts/catalogue_judge.md` (the judge's description of the band).
- `api/services/exposure_graph/worker.py`, `anonymise.py`, `worst_case.py`; `config/settings.toml`
  and `config/exposure_graph.py` (`withheld_title`, the worst-case variant label).
- `frontend/src/features/chat/` (`TurnControls`, `ChatDock`, `MessageStream`), `DESIGN.md`.
