## Context

See proposal.md for motivation. Current state:

- `CITATION.cff` (CFF 1.2.0) has title, type, one author, repository URL, `Apache-2.0`,
  version `0.1.0`, `date-released`, keywords; no abstract, no ORCID, no DOI.
- `pyproject.toml` `version = "0.1.0"`; `LICENSE` is Apache 2.0; README "License and citation"
  points at `CITATION.cff` and GitHub's "Cite this repository" button.
- No git tag or release exists yet. Repository: `jodhernandezbe/EcoFate` on GitHub.
- Tests that guard repository files live at `tests/test_*.py` (e.g. `test_container_files.py`,
  `test_pre_commit_config.py`) and read files relative to the repository root.
- PyYAML is in `uv.lock` only as a transitive dependency; no test parses YAML today.

## Goals / Non-Goals

**Goals:**
- One metadata file that GitHub ("Cite this repository") and Zenodo both read.
- Drift between the citation and the package caught by the default test run (so by
  pre-commit and CI).

**Non-Goals:**
- Automating the release itself (tagging, changelog, publishing images): a later change.
- Calling the Zenodo API from the repository or from CI (no token, nothing to keep secret).
- Archiving data files or the MolDeBERTa model (not in the repository).

## Decisions

1. **`CITATION.cff` only, no `.zenodo.json`.** Zenodo's GitHub integration uses
   `.zenodo.json` when present and otherwise converts `CITATION.cff` (title, authors with
   ORCID and affiliation, abstract, keywords, licence, version). Keeping one file means no two
   copies to keep equal, and the test forbids a `.zenodo.json` so a second source cannot creep
   in. Alternative: `.zenodo.json` plus a test that compares the two; rejected because it
   duplicates knowledge (DRY) and `.zenodo.json` only adds control we do not need yet
   (communities, grants). If it is needed later, it replaces this rule in a new change.
2. **Concept DOI everywhere in the repository.** `CITATION.cff` `doi:` and the README badge
   use the concept DOI, which always resolves to the latest release; a version DOI would be
   wrong one release later. The README tells readers to take the version DOI from the Zenodo
   page when citing a specific version.
3. **The test parses YAML properly** (`pyyaml` and `types-pyyaml` in the `dev` group) rather
   than with regexes as the other file guards do: CFF nesting (authors list) and dates need a
   real parser, and relying on a transitive dependency would break silently. `yaml.safe_load`
   only (bandit-clean, no object construction).
4. **Licence check by mapping, not by parsing `LICENSE`.** The test reads the first lines of
   `LICENSE`, recognises the Apache 2.0 header and expects `Apache-2.0`; an unrecognised
   licence text fails with a message to extend the mapping. Simple and fails closed.
5. **Two phases of tasks.** Repository preparation (abstract, test, release checklist) is done
   and committed before the owner turns Zenodo on; the DOI and badge are added after the first
   release, because the DOI does not exist until then. The DOI test applies only when `doi` is
   present.
6. **Optional author identifiers come from the owner.** ORCID and affiliation are added only
   if the owner gives them; they are never guessed. The test checks an ORCID's form
   (`https://orcid.org/` + 16 characters in four groups) only when present.

## Risks / Trade-offs

- [Zenodo's CFF conversion ignores or maps a field differently than expected] → check the
  first Zenodo record's metadata by eye before announcing the DOI; if wrong, edit the record on
  Zenodo (allowed for metadata) and consider `.zenodo.json` in a later change.
- [A release is permanent on Zenodo] → the release checklist runs the full checks and
  detect-secrets first; nothing licence-restricted is committed (the model is downloaded at
  run time).
- [Version bumped in one file only] → the version-equality test fails in pre-commit and CI.
- [Zenodo webhook not firing (integration switched on after the release)] → only releases
  published after switching the repository on are archived; the checklist says to switch it
  on first.

## Migration Plan

1. Merge the repository preparation.
2. Owner: sign in to Zenodo with GitHub, switch on `jodhernandezbe/EcoFate`.
3. Owner: publish release `v0.1.0` (or the current version) on GitHub.
4. Copy the concept DOI from the Zenodo record into `CITATION.cff` and the README badge; merge.

Rollback: switch the repository off in Zenodo (future releases stop being archived; existing
records stay, by Zenodo's design) and remove the badge and `doi`.

## Open Questions

- The author's ORCID iD and affiliation, if any: added when the owner provides them; the
  approach does not change either way.
