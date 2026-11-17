## Purpose

How EcoFate is cited and archived: one citation metadata file, kept consistent with the
package, from which every published release is archived with a persistent DOI.

## ADDED Requirements

### Requirement: Single citation metadata source
The repository SHALL describe how to cite the software in exactly one machine-readable file,
`CITATION.cff` (Citation File Format 1.2.0), and SHALL NOT contain a second archive metadata
file (`.zenodo.json`). That file SHALL carry a title, a type of `software`, at least one author
with family and given names, an abstract, the repository URL, a licence, a version and a
release date.

#### Scenario: Complete metadata
- **WHEN** the test suite runs
- **THEN** `CITATION.cff` parses as YAML and every required field is present and non-empty

#### Scenario: Second metadata file added
- **WHEN** a `.zenodo.json` is added to the repository root
- **THEN** the test suite fails, naming `CITATION.cff` as the one source

#### Scenario: Missing field
- **WHEN** a required field such as the abstract is removed from `CITATION.cff`
- **THEN** the test suite fails and names the field

### Requirement: Citation consistent with the package
The `version` in `CITATION.cff` SHALL equal the `version` in `pyproject.toml`, the `license`
SHALL be the SPDX identifier of the licence in `LICENSE`, and `date-released` SHALL be a valid
ISO 8601 date (YYYY-MM-DD) not in the future.

#### Scenario: Version bumped in one file only
- **WHEN** `pyproject.toml` says `0.2.0` and `CITATION.cff` still says `0.1.0`
- **THEN** the test suite fails, naming both values

#### Scenario: Invalid release date
- **WHEN** `date-released` is not a real calendar date, or is after today
- **THEN** the test suite fails

### Requirement: Every release archived with a DOI
Each published GitHub release of the repository SHALL be archived on Zenodo with the metadata
from `CITATION.cff`, receiving a version DOI, and all versions SHALL share one concept DOI. Once
the concept DOI exists, `CITATION.cff` SHALL record it as `doi` and the README SHALL show it as a
badge that links to the Zenodo record and say how to cite a specific version.

#### Scenario: Release published
- **WHEN** the owner publishes a GitHub release
- **THEN** a Zenodo record with that release's version and a new version DOI appears under the concept DOI

#### Scenario: DOI recorded
- **WHEN** the concept DOI has been minted
- **THEN** `CITATION.cff` has `doi` set to it in the form `10.5281/zenodo.<digits>`, and the README badge links to `https://doi.org/` followed by that DOI

#### Scenario: Malformed DOI
- **WHEN** `CITATION.cff` has a `doi` that is not of the form `10.<digits>/<suffix>`
- **THEN** the test suite fails
