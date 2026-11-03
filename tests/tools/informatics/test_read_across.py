"""Tests for the read-across tool (synthetic catalog, fake embedder, fake PubChem)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx
import numpy as np
import pytest

from config.read_across import ReadAcrossSettings
from models.chemistry.similarity import hybrid_scores
from tests.tools.informatics import read_across_fakes as fakes
from tests.tools.informatics.read_across_fakes import (
    FakeEmbedder,
    Server,
    answer,
    no_network,
    pubchem_body,
    unit,
)
from tools.informatics import read_across
from tools.informatics.helpers.read_across.catalog import load_catalog
from tools.informatics.read_across import ReadAcrossServices, find_surrogate
from tools.schemas import ReadAcrossMatch

ISOHEXANE = "CCCC(C)C"
CO2 = "O=C=O"
ISOHEXANE_TANIMOTO = 2 / 7  # ECFP4 bits shared with n-hexane (RDKit)


class Setup:
    """A 3-chemical catalog (n-hexane, benzene, TCE as unit vectors 0, 1, 2) and fakes."""

    def __init__(
        self,
        tmp_path: Path,
        handler: fakes.Handler = no_network,
        extra: Mapping[str, list[object]] | None = None,
        min_hybrid_score: float = 0.60,
        categories: tuple[str, ...] = (),
    ) -> None:
        self.categories = fakes.category_index(tmp_path, *categories)
        self.settings: ReadAcrossSettings = fakes.settings(
            tmp_path,
            min_hybrid_score=min_hybrid_score,
        )
        columns = fakes.catalog_columns(self.settings, extra=extra)
        fakes.write_catalog(self.settings, columns)
        self.catalog = load_catalog(self.settings)
        self.server = Server(handler)
        vectors = {ISOHEXANE: unit(0), "CCCCCC": unit(0), CO2: unit(3)}
        self.embedder: FakeEmbedder = fakes.embedder(self.settings, vectors)

    def services(self) -> ReadAcrossServices:
        return ReadAcrossServices(
            self.catalog,
            self.embedder,
            self.server.client,
            self.settings,
            self.categories,
        )

    def find(self, cas: str, **options: object) -> ReadAcrossMatch:
        return find_surrogate(cas, self.services(), **options)  # type: ignore[arg-type]


def _pubchem(smiles: str, weight: object = "86.18") -> fakes.Handler:
    return answer(pubchem_body(SMILES=smiles, MolecularWeight=weight))


def test_direct_match_makes_no_request(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    match = setup.find(" 110-54-3 ")
    assert match["is_direct_tri_match"] is True
    assert match["resolution_method"] == "direct_tri_catalog_match"
    assert match["surrogate_tri_cas"] == "110-54-3"
    assert match["surrogate_name"] == "n-Hexane"
    scores = ("moldeberta_cosine_sim", "morgan_tanimoto_sim", "hybrid_read_across_score")
    assert [match[k] for k in scores] == [1.0, 1.0, 1.0]  # type: ignore[literal-required]
    assert match["mw_scaling_factor"] == 1.0
    assert match["within_applicability_domain"] is True
    assert setup.server.urls == [] and setup.embedder.calls == []


def test_isohexane_reads_across_to_hexane(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem(ISOHEXANE))
    match = setup.find("107-83-5")
    assert match["is_direct_tri_match"] is False
    assert match["resolution_method"] == "hybrid_read_across"
    assert (match["surrogate_tri_cas"], match["surrogate_smiles"]) == ("110-54-3", "CCCCCC")
    assert match["query_smiles"] == ISOHEXANE and match["query_mw"] == 86.18
    assert match["moldeberta_cosine_sim"] == 1.0
    assert match["morgan_tanimoto_sim"] == pytest.approx(ISOHEXANE_TANIMOTO, abs=1e-4)
    expected = 0.55 * 1.0 + 0.45 * ISOHEXANE_TANIMOTO
    assert match["hybrid_read_across_score"] == pytest.approx(expected, abs=1e-4)
    # PubChem rounds MW to 0.01 g/mol; the catalog's RDKit MW is 86.178 g/mol.
    assert match["mw_scaling_factor"] == pytest.approx(1.0, abs=1e-3)
    assert match["within_applicability_domain"] is True
    assert match["warnings"] == []
    assert setup.embedder.calls == [ISOHEXANE]


def test_unrelated_molecule_is_out_of_domain(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem(CO2, "44.009"))
    match = setup.find("124-38-9")
    assert match["hybrid_read_across_score"] == 0.0
    assert match["surrogate_tri_cas"] == "110-54-3"  # still reported (ties go to the first)
    assert match["within_applicability_domain"] is False
    assert len(match["warnings"]) == 1
    assert "outside the applicability domain" in match["warnings"][0]


def _isohexane_score() -> float:
    return float(hybrid_scores(np.array([1.0]), np.array([ISOHEXANE_TANIMOTO]), 0.55)[0])


def test_score_equal_to_threshold_is_in_domain(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem(ISOHEXANE), min_hybrid_score=_isohexane_score())
    assert setup.find("107-83-5")["within_applicability_domain"] is True


def test_score_just_below_threshold_is_out_of_domain(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem(ISOHEXANE), min_hybrid_score=_isohexane_score() + 1e-9)
    assert setup.find("107-83-5")["within_applicability_domain"] is False


def _assert_unresolved(match: ReadAcrossMatch) -> None:
    assert match["resolution_method"] == "unresolved"
    assert match["surrogate_tri_cas"] is None and match["hybrid_read_across_score"] is None
    assert match["mw_scaling_factor"] is None
    assert match["within_applicability_domain"] is False


def test_invalid_cas_makes_no_request(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    match = setup.find("110-54-4")
    _assert_unresolved(match)
    assert match["query_cas"] == "110-54-4"
    assert "not valid" in match["warnings"][0]
    assert setup.server.urls == []


def test_pubchem_unavailable(tmp_path: Path) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    setup = Setup(tmp_path, fail)
    match = setup.find("107-83-5")
    _assert_unresolved(match)
    assert "could not be resolved" in match["warnings"][0]
    assert setup.embedder.calls == []


def test_failure_is_not_cached(tmp_path: Path) -> None:
    replies = [
        httpx.Response(404, json={}),
        httpx.Response(200, json=pubchem_body(SMILES="CCCCCC")),
    ]
    setup = Setup(tmp_path, lambda request: replies.pop(0))
    assert setup.find("107-83-5")["resolution_method"] == "unresolved"
    assert setup.find("107-83-5")["resolution_method"] == "hybrid_read_across"


def test_unparseable_smiles(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem("C1CC"))
    match = setup.find("107-83-5")
    _assert_unresolved(match)
    assert "'C1CC'" in match["warnings"][0] and "cannot be parsed" in match["warnings"][0]


def test_missing_molecular_weight(tmp_path: Path) -> None:
    setup = Setup(tmp_path, answer(pubchem_body(SMILES=ISOHEXANE)))
    match = setup.find("107-83-5")
    assert match["surrogate_tri_cas"] == "110-54-3"
    assert match["query_mw"] is None and match["mw_scaling_factor"] is None
    assert match["warnings"] == ["molecular weight of 107-83-5 not found in PubChem"]


def test_benchmark_filter_excludes_direct_match(tmp_path: Path) -> None:
    flags: list[object] = [False, True, False]
    setup = Setup(tmp_path, _pubchem("CCCCCC"), extra={"has_iris_benchmark": flags})
    match = setup.find("110-54-3", require_toxicity_benchmarks=True)
    assert match["is_direct_tri_match"] is False
    assert match["surrogate_tri_cas"] == "71-43-2"


def test_missing_filter_column_is_reported(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    match = setup.find("110-54-3", require_toxicity_benchmarks=True)
    assert match["is_direct_tri_match"] is True
    assert "benchmark filter not applied" in match["warnings"][0]


def test_empty_sector_filter_falls_back(tmp_path: Path) -> None:
    prefixes: list[object] = [["325"], ["324"], ["325"]]
    setup = Setup(tmp_path, extra={"naics_prefixes": prefixes})
    match = setup.find("71-43-2", sector_naics_prefix="11")
    assert match["is_direct_tri_match"] is True
    assert "all candidates were used" in match["warnings"][0]


def test_tool_uses_the_default_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup = Setup(tmp_path)
    monkeypatch.setattr(read_across, "_services", setup.services)
    result = read_across.find_tri_read_across_surrogate.invoke({"cas_number": "79-01-6"})
    assert result["surrogate_name"] == "Trichloroethylene"


def test_missing_catalog_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(read_across, "get_read_across_settings", lambda: fakes.settings(tmp_path))
    read_across._services.cache_clear()  # pyright: ignore[reportPrivateUsage]
    try:
        with pytest.raises(FileNotFoundError, match="build_tri_embeddings"):
            read_across.find_tri_read_across_surrogate.invoke({"cas_number": "79-01-6"})
    finally:
        read_across._services.cache_clear()  # pyright: ignore[reportPrivateUsage]


def test_filters_do_not_move_the_scores(tmp_path: Path) -> None:
    """The mean comes from the whole catalog, so a filter cannot change a pair's score."""
    prefixes: list[object] = [["325110"], ["324"], ["325110"]]
    setup = Setup(tmp_path, _pubchem(ISOHEXANE), extra={"naics_prefixes": prefixes})
    unfiltered = setup.find("107-83-5")
    filtered = setup.find("107-83-5", sector_naics_prefix="325")
    fields = ("surrogate_tri_cas", "moldeberta_cosine_sim", "morgan_tanimoto_sim")
    for field in (*fields, "hybrid_read_across_score", "within_applicability_domain"):
        assert unfiltered[field] == filtered[field]  # type: ignore[literal-required]


def test_query_at_the_catalog_centre_has_no_surrogate(tmp_path: Path) -> None:
    """A two-chemical catalog of unit vectors has the mean [0.5, 0.5, 0, ...] exactly."""
    s = fakes.settings(tmp_path)
    columns = fakes.catalog_columns(s, chemicals=(fakes.HEXANE, fakes.BENZENE))
    fakes.write_catalog(s, columns)
    catalog = load_catalog(s)
    mean = catalog.mean_embedding.astype(np.float32)
    assert mean.astype(np.float64).tolist() == catalog.mean_embedding.tolist()
    embedder = FakeEmbedder({fakes.canonical(CO2, s): mean}, [])
    server = Server(_pubchem(CO2, "44.009"))
    match = find_surrogate(
        "124-38-9",
        ReadAcrossServices(catalog, embedder, server.client, s, fakes.category_index(tmp_path)),
    )
    _assert_unresolved(match)
    assert match["query_smiles"] == CO2  # the chemical itself was resolved
    assert match["query_mw"] == 44.009
    assert "carries no direction" in match["warnings"][0]


CHLOROPHENOL = "95-57-8"
CHLOROPHENOL_ROW = f"{CHLOROPHENOL},N084,CHLOROPHENOLS,2-chlorophenol,Organic,x"
LEAD_ROW = "7439-92-1,N420,LEAD COMPOUNDS,lead,Inorganic,x"


def test_category_member_is_reported_without_similarity(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem("Oc1ccccc1Cl", "128.56"), categories=(CHLOROPHENOL_ROW,))
    match = setup.find(CHLOROPHENOL)
    assert match["resolution_method"] == "tri_category_member"
    assert match["is_direct_tri_match"] is False
    assert match["query_categories"] == [{"code": "N084", "name": "CHLOROPHENOLS"}]
    assert match["surrogate_tri_cas"] is None and match["hybrid_read_across_score"] is None
    assert match["mw_scaling_factor"] is None and match["within_applicability_domain"] is True
    assert "member of the TRI category N084 (CHLOROPHENOLS)" in match["warnings"][0]
    assert setup.embedder.calls == []


def test_category_member_survives_an_unresolvable_structure(tmp_path: Path) -> None:
    setup = Setup(tmp_path, answer({}, 404), categories=(LEAD_ROW,))
    match = setup.find("7439-92-1")
    assert match["resolution_method"] == "tri_category_member"
    assert match["query_smiles"] is None and match["query_mw"] is None
    assert any("could not be resolved" in w for w in match["warnings"])


def test_catalog_chemical_wins_over_its_category(tmp_path: Path) -> None:
    row = "110-54-3,N999,SOME GROUP,hexane,Organic,x"
    match = Setup(tmp_path, categories=(row,)).find("110-54-3")
    assert match["resolution_method"] == "direct_tri_catalog_match"
    assert match["query_categories"] == []


def test_a_non_member_still_reads_across(tmp_path: Path) -> None:
    setup = Setup(tmp_path, _pubchem(ISOHEXANE), categories=(CHLOROPHENOL_ROW,))
    match = setup.find("107-83-5")
    assert match["resolution_method"] == "hybrid_read_across"
    assert match["query_categories"] == [] and match["surrogate_category"] is None


def test_surrogate_that_is_a_category_member_names_its_category(tmp_path: Path) -> None:
    extra: dict[str, list[object]] = {
        "category_codes": [["N100"], [], []],
        "category_names": [["COPPER COMPOUNDS"], [], []],
    }
    setup = Setup(tmp_path, _pubchem(ISOHEXANE), extra=extra)
    match = setup.find("107-83-5")
    assert match["surrogate_category"] == {"code": "N100", "name": "COPPER COMPOUNDS"}
    assert "category N100" in match["warnings"][-1]


def test_category_row_in_the_catalog_is_not_a_direct_match(tmp_path: Path) -> None:
    extra: dict[str, list[object]] = {
        "category_codes": [["N084"], [], []],
        "category_names": [["CHLOROPHENOLS"], [], []],
    }
    row = "110-54-3,N084,CHLOROPHENOLS,hexane,Organic,x"
    match = Setup(tmp_path, extra=extra, categories=(row,)).find("110-54-3")
    assert match["resolution_method"] == "tri_category_member"
    assert match["query_smiles"] == "CCCCCC"
