## Why

EcoFate can be cited today only through `CITATION.cff` and a GitHub URL, which can move or
disappear and does not identify a version. Archiving each GitHub release on Zenodo gives the
project a persistent, citable DOI: one for every release and a concept DOI that always resolves
to the latest. That is what a paper, a report or a capstone review can reference. Releases are
about to start (`add-ci-pipeline` and the deployment change version the project), so the
archive should be in place before the first one.

## What Changes

- Zenodo's GitHub integration archives every published GitHub release of the repository and
  mints a DOI for it. The owner switches it on once in Zenodo and publishes the first release;
  nothing in the repository runs Zenodo.
- `CITATION.cff` becomes the single source of the archive's metadata: Zenodo reads it when no
  `.zenodo.json` exists. It gains the fields Zenodo uses (an `abstract`; the author's ORCID and
  affiliation if the owner supplies them), and a `.zenodo.json` is deliberately not added, so two
  metadata files cannot drift (alternative weighed in design.md).
- A test keeps the metadata honest: `CITATION.cff` parses, carries every field the archive
  needs, its `version` equals `pyproject.toml`'s, its `license` matches `LICENSE`, and no
  `.zenodo.json` appears beside it.
- After the first release is archived: the concept DOI goes into `CITATION.cff` (`doi:`), and a
  DOI badge goes under the title of the README, with a line in "License and citation" saying
  how to cite a specific version.
- A short release checklist in the README (bump `version` in `pyproject.toml` and
  `CITATION.cff` together, set `date-released`, tag, publish the release).

## Capabilities

### New Capabilities

- `software-citation`: how the software is cited and archived (the citation metadata file,
  its required fields and consistency with the package, the release archive and DOI).

### Modified Capabilities

(none)

## Impact

- `CITATION.cff` (abstract, later the DOI), `README.md` (badge, citation line, release
  checklist), a new test `tests/test_citation.py`. No `.zenodo.json`.
- No Python package, frontend or workflow change; no new runtime dependency. The `dev` group
  gains `pyyaml` and `types-pyyaml` so the test parses `CITATION.cff` as YAML under strict
  pyright (PyYAML is only a transitive dependency today).
- Owner actions outside the repository: link the GitHub account in Zenodo, switch the
  repository on, publish the first release, then hand the concept DOI back.
- Releases become public archives: a release cannot be deleted from Zenodo once published, so
  nothing secret or licence-restricted may be in the tagged tree (the MolDeBERTa model is
  downloaded at run time, not committed).
