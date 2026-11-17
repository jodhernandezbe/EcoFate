## 1. Citation metadata

- [ ] 1.1 Add `pyyaml` and `types-pyyaml` to the `dev` dependency group (`uv add --dev`); `uv.lock` updated, `uv sync --locked` passes.
- [ ] 1.2 Add an `abstract` to `CITATION.cff` (from the README overview, plain text, no invented claims); add the author's ORCID and affiliation only if the owner provides them.

## 2. Consistency test

- [ ] 2.1 Write `tests/test_citation.py`: `CITATION.cff` parses with `yaml.safe_load`; required fields present and non-empty (title, `type: software`, authors with family and given names, abstract, repository-code, license, version, date-released); each missing field named in the failure.
- [ ] 2.2 Same file: `version` equals `pyproject.toml`'s (read with `tomllib`); `license` equals the SPDX id mapped from the `LICENSE` header (Apache 2.0 -> `Apache-2.0`, unknown header fails); `date-released` is a real date not after today; no `.zenodo.json` at the root.
- [ ] 2.3 Same file: `doi`, when present, matches `^10\.\d{4,9}/\S+$`; an author `orcid`, when present, matches `^https://orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]$`. Negative tests for each rule run the checks on altered copies of the parsed data (wrong version, missing abstract, bad date, future date, malformed DOI, malformed ORCID, a `.zenodo.json` present in a temporary root).

## 3. Documentation

- [ ] 3.1 README "License and citation": a release checklist (switch the repository on in Zenodo before the first release; bump `version` in `pyproject.toml` and `CITATION.cff` together; set `date-released`; run `uv run pre-commit run --all-files`; tag `v<version>`; publish the GitHub release) and one sentence on Zenodo archiving each release.

## 4. Verification (before the first release)

- [ ] 4.1 `uv run pre-commit run --all-files` passes, including the new test and pyright on it.
- [ ] 4.2 `cffconvert --validate` (via `uvx cffconvert`) accepts `CITATION.cff`.

## 5. After the first release (owner actions first)

- [ ] 5.1 Owner: sign in to Zenodo with GitHub, switch on `jodhernandezbe/EcoFate`, publish release `v<version>`; confirm the Zenodo record's title, author, version and licence look right.
- [ ] 5.2 Add the concept DOI to `CITATION.cff` (`doi:`) and a DOI badge under the README title linking to `https://doi.org/<concept DOI>`, plus a sentence on citing a specific version's DOI; the test passes.
