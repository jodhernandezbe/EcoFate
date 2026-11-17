## 1. Worker band

- [x] 1.1 `band_of`: higher of limit-ratio and cancer-risk bands; hazard quotient only without a limit
- [x] 1.2 Tests in `tests/tools/assessment/helpers/occupational/test_dosimetry.py` (hazard quotient ignored with a limit, cancer risk counts, no limit, nothing computed)
- [x] 1.3 Update `prompts/catalogue_judge.md`; explain a band the cancer risk lifts above the limit ratio's in the facility's notes (`tools/assessment/helpers/view.py`), with tests
- [x] 1.4 Run the chemical-name-only eval 10 times and keep the docstring edit only if the CAS rule holds (reworded docstring: 9/10, so it was reverted; with the docstring unchanged and the facility note: 10/10)

## 2. Exposure chain text

- [x] 2.1 Worker release step titled with the driving activity's name (fallback to configured words), with tests
- [x] 2.2 Worst-case variant labelled "worst case, upper bound"; fixtures and screenshots regenerated and viewed
- [x] 2.3 Anonymiser checks step titles (`withheld_title` in config), with a leak test

## 3. Turn controls

- [x] 3.1 `TurnControls` under the chat header (Running: status + Stop; Stopped: message + Resume/Open Settings)
- [x] 3.2 `MessageStream` keeps only a "Stopped" marker; tests moved to `TurnControls.test.tsx`
- [x] 3.3 Visual references regenerated and viewed (stop resumable, bad key, final; live queued, running, stopping; light and dark)
- [x] 3.4 Update `frontend/DESIGN.md` Running and Interrupted rows

## 4. Verification

- [x] 4.1 `make check` (pre-commit on all files)
- [x] 4.2 Security audit of the new diff, recorded
