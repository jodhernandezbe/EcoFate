[← Documentation index](../README.md#documentation) · [All docs](README.md)

# License and citation

EcoFate is released under the [Apache License 2.0](../LICENSE): keep the copyright and
[NOTICE](../NOTICE) files and state your changes. Third-party data and models keep their own
licences; the MolDeBERTa model used by the read-across tool is CC BY-NC-ND 4.0 (non-commercial).

Cite EcoFate with [10.5281/zenodo.24327281](https://doi.org/10.5281/zenodo.24327281) (always the
latest release; each version also has its own DOI on Zenodo) or GitHub's "Cite this repository"
button, which reads [CITATION.cff](../CITATION.cff). Zenodo archives every published GitHub release
from that file (there is deliberately no `.zenodo.json`), and `tests/test_citation.py` keeps it in
step with `pyproject.toml`. To release: bump `version` in `pyproject.toml` and `CITATION.cff` with
`date-released`, merge with CI green, tag `v<version>` on `main` and publish a GitHub release.
