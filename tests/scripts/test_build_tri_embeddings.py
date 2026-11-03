"""Tests for scripts.build_tri_embeddings (fake Envirofacts, fake PubChem, fake embedder)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest

from config.efservice import load_efservice_settings
from config.read_across import ModelSettings, ReadAcrossSettings
from scripts import build_tri_embeddings
from scripts.build_tri_embeddings import BuildReport, Services, build_catalog, report_lines
from tests.tools.informatics import read_across_fakes as fakes
from tests.tools.informatics.read_across_fakes import FakeEmbedder, Server, pubchem_body, unit
from tools.http import RetryingClient
from tools.informatics.helpers.read_across.catalog import load_catalog, read_shards
from tools.informatics.helpers.read_across.tri_list import DELISTED, GROUP, TriListError

EFSERVICE = load_efservice_settings()

TRI_ROWS = [
    {"cas_registry_number": "110-54-3", "chem_name": "n-Hexane", "inactive_date": "9999"},
    {"cas_registry_number": "71-43-2", "chem_name": "Benzene", "inactive_date": "9999"},
    {"cas_registry_number": "N420", "chem_name": "Lead compounds", "inactive_date": "9999"},
    {"cas_registry_number": "7647-01-0", "chem_name": "Hydrochloric acid", "inactive_date": "1994"},
]
PUBCHEM = {"110-54-3": "CCCCCC", "71-43-2": "c1ccccc1"}


class Fakes:
    """Envirofacts answers ``tri_rows``; PubChem answers ``pubchem`` (CAS -> SMILES)."""

    def __init__(
        self,
        tmp_path: Path,
        tri_rows: list[dict[str, str]] | None = None,
        pubchem: dict[str, str] | None = None,
        tri_status: int = 200,
        categories: tuple[str, ...] = (),
    ) -> None:
        self.categories = fakes.category_index(tmp_path, *categories)
        self.settings: ReadAcrossSettings = fakes.settings(tmp_path)
        rows = TRI_ROWS if tri_rows is None else tri_rows
        smiles = PUBCHEM if pubchem is None else pubchem
        self.envirofacts = Server(lambda request: httpx.Response(tri_status, json=rows))
        self.pubchem = Server(lambda request: _pubchem_answer(request, smiles))
        vectors = {"CCCCCC": unit(0), "c1ccccc1": unit(1), "ClC=C(Cl)Cl": unit(2)}
        vectors["Oc1ccccc1"] = unit(5)
        self.embedder = fakes.embedder(self.settings, vectors)

    def services(self) -> Services:
        return Services(
            self.envirofacts.client,
            EFSERVICE,
            self.pubchem.client,
            self.embedder,
            self.settings,
            self.categories,
        )

    def build(self) -> BuildReport:
        return build_catalog(self.services())


def _pubchem_answer(request: httpx.Request, smiles: dict[str, str]) -> httpx.Response:
    cas = next((c for c in smiles if c in str(request.url)), None)
    if cas is None:
        return httpx.Response(404, json={"Fault": {"Code": "PUGREST.NotFound"}})
    return httpx.Response(200, json=pubchem_body(SMILES=smiles[cas]))


def test_first_build_resolves_every_chemical_on_pubchem(tmp_path: Path) -> None:
    run = Fakes(tmp_path)
    report = run.build()
    assert (report.kept, report.reused) == (2, 0)
    assert report.dropped == {GROUP: 1, DELISTED: 1}
    assert report.unresolved == ()
    assert [p.name for p in report.shards] == [
        "tri_chemicals_1.parquet",  # 110-54-3
        "tri_chemicals_7.parquet",  # 71-43-2
    ]
    assert len(run.pubchem.urls) == 2
    catalog = load_catalog(run.settings)
    assert catalog.cas == ("110-54-3", "71-43-2")
    assert catalog.names == ("n-Hexane", "Benzene")
    assert catalog.smiles == ("CCCCCC", "c1ccccc1")
    assert catalog.embeddings[1].tolist() == unit(1).tolist()
    assert catalog.molecular_weights[0] == pytest.approx(86.18, abs=0.01)
    assert all(p.stat().st_mode & 0o777 == 0o644 for p in report.shards)


def test_rebuild_reuses_stored_smiles(tmp_path: Path) -> None:
    Fakes(tmp_path).build()
    rerun = Fakes(tmp_path, pubchem={})
    report = rerun.build()
    assert (report.kept, report.reused) == (2, 2)
    assert rerun.pubchem.urls == []
    assert rerun.embedder.calls == ["CCCCCC", "c1ccccc1"]  # vectors are always recomputed


def test_newly_listed_chemical_is_resolved(tmp_path: Path) -> None:
    Fakes(tmp_path).build()
    tce = {"cas_registry_number": "79-01-6", "chem_name": "TCE", "inactive_date": "9999"}
    rerun = Fakes(tmp_path, tri_rows=[*TRI_ROWS, tce], pubchem={"79-01-6": "ClC=C(Cl)Cl"})
    report = rerun.build()
    assert (report.kept, report.reused) == (3, 2)
    assert len(rerun.pubchem.urls) == 1 and "79-01-6" in rerun.pubchem.urls[0]


def test_chemical_no_longer_listed_is_removed(tmp_path: Path) -> None:
    run = Fakes(tmp_path)
    run.build()
    Fakes(tmp_path, tri_rows=TRI_ROWS[1:]).build()
    table = read_shards(run.settings)
    assert table[run.settings.columns.cas] == ["71-43-2"]


def test_unresolvable_chemical_is_reported(tmp_path: Path) -> None:
    report = Fakes(tmp_path, pubchem={"71-43-2": "c1ccccc1"}).build()
    assert report.kept == 1
    assert report.unresolved == (("110-54-3", "PubChem has no compound for CAS number 110-54-3"),)
    assert any(line.startswith("unresolved 110-54-3") for line in report_lines(report, tmp_path))


def test_unparseable_pubchem_smiles_is_reported(tmp_path: Path) -> None:
    report = Fakes(tmp_path, pubchem={"110-54-3": "C1CC", "71-43-2": "c1ccccc1"}).build()
    assert report.unresolved == (("110-54-3", "SMILES 'C1CC' cannot be parsed"),)


def test_envirofacts_failure_leaves_the_catalog_unchanged(tmp_path: Path) -> None:
    Fakes(tmp_path).build()
    paths = sorted(fakes.settings(tmp_path).shard_paths())
    before = {p: p.read_bytes() for p in paths}
    with pytest.raises(TriListError):
        Fakes(tmp_path, tri_status=500).build()
    assert {p: p.read_bytes() for p in sorted(fakes.settings(tmp_path).shard_paths())} == before


def test_nothing_resolved_writes_nothing(tmp_path: Path) -> None:
    run = Fakes(tmp_path, pubchem={})
    with pytest.raises(ValueError, match="no TRI chemical"):
        run.build()
    assert run.settings.shard_paths() == ()
    assert not run.settings.directory.exists() or list(run.settings.directory.iterdir()) == []


def test_written_columns(tmp_path: Path) -> None:
    run = Fakes(tmp_path)
    run.build()
    table = read_shards(run.settings)
    c = run.settings.columns
    assert set(table) == {
        c.cas, c.name, c.smiles, c.molecular_weight, c.embedding, c.bits,
        c.source, c.category_codes, c.category_names,
    }  # fmt: skip
    assert table[c.source] == ["tri_list", "tri_list"]
    assert table[c.category_codes] == [[], []]
    assert all(len(v) == 768 for v in table[c.embedding])  # type: ignore[arg-type]
    assert all(len(v) == 1024 for v in table[c.bits])  # type: ignore[arg-type]


def test_main_exits_non_zero_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = Fakes(tmp_path, tri_status=500)
    _patch(monkeypatch, run)
    assert build_tri_embeddings.main([]) == 1
    assert "catalog not built" in capsys.readouterr().err
    assert run.settings.shard_paths() == ()


def test_main_writes_the_requested_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = Fakes(tmp_path)
    _patch(monkeypatch, run)
    target = tmp_path / "out"
    assert build_tri_embeddings.main(["--directory", str(target)]) == 0
    assert sorted(p.name for p in target.glob("*.parquet")) == [
        "tri_chemicals_1.parquet",
        "tri_chemicals_7.parquet",
    ]
    assert "wrote 2 chemicals to 2 shards" in capsys.readouterr().out


def _patch(monkeypatch: pytest.MonkeyPatch, run: Fakes) -> None:
    """Make ``main`` use the fakes: settings, embedder, and a client routed by policy."""

    def settings() -> ReadAcrossSettings:
        return run.settings

    def embedder(model: ModelSettings) -> FakeEmbedder:
        return run.embedder

    def client(policy: object, http: httpx.Client) -> RetryingClient:
        return run.pubchem.client if policy is run.settings.pubchem else run.envirofacts.client

    monkeypatch.setattr(build_tri_embeddings, "get_read_across_settings", settings)
    monkeypatch.setattr(build_tri_embeddings, "default_embedder", embedder)
    monkeypatch.setattr(build_tri_embeddings, "RetryingClient", client)


def test_shards_store_compact_types(tmp_path: Path) -> None:
    """float64 vectors and int64 bits made one 3.6 MB file, over the repository's limit."""
    run = Fakes(tmp_path)
    report = run.build()
    schema = pq.read_schema(report.shards[0])  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    c = run.settings.columns
    types = {n: str(schema.field(n).type) for n in schema.names}  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportUnknownVariableType]
    assert types[c.embedding] == "list<element: float>"
    assert types[c.bits] == "list<element: int8>"


def test_adding_a_chemical_leaves_other_shards_byte_identical(tmp_path: Path) -> None:
    """Why the catalog is sharded: a rebuild rewrites only the shards that changed."""
    run = Fakes(tmp_path)
    run.build()
    hexane_shard = run.settings.shard_path("1")
    before = hexane_shard.read_bytes()
    tce = {"cas_registry_number": "79-01-6", "chem_name": "TCE", "inactive_date": "9999"}
    rerun = Fakes(tmp_path, tri_rows=[*TRI_ROWS, tce], pubchem={"79-01-6": "ClC=C(Cl)Cl"})
    report = rerun.build()
    assert report.kept == 3
    assert hexane_shard.read_bytes() == before  # 110-54-3 is untouched
    assert len(report.shards) == 2  # 71-43-2 and 79-01-6 share the "7" shard


PHENOL = "108-95-2"
TOLUENE = "108-88-3"
CATEGORY_PUBCHEM = {**PUBCHEM, PHENOL: "Oc1ccccc1", TOLUENE: "Cc1ccccc1"}
CATEGORY_ROWS = (
    f"{PHENOL},N084,CHLOROPHENOLS,phenol,Organic,x",
    f"{PHENOL},N085,SECOND GROUP,phenol,Organic,x",
    "7439-92-1,N420,LEAD COMPOUNDS,lead,Inorganic,x",
    "110-54-3,N999,A GROUP,n-hexane,Organic,x",
)


def _category_run(tmp_path: Path) -> Fakes:
    return Fakes(tmp_path, pubchem=CATEGORY_PUBCHEM, categories=CATEGORY_ROWS)


def test_organic_category_member_is_added_with_its_categories(tmp_path: Path) -> None:
    run = _category_run(tmp_path)
    report = run.build()
    assert report.categories == {
        "skipped_inorganic": 1,
        "already_listed": 1,
        "added": 1,
        "unresolved": 0,
    }
    table = read_shards(run.settings)
    c = run.settings.columns
    row = table[c.cas].index(PHENOL)
    assert table[c.source][row] == "tri_category"
    assert table[c.category_codes][row] == ["N084", "N085"]
    assert table[c.category_names][row] == ["CHLOROPHENOLS", "SECOND GROUP"]


def test_inorganic_member_and_listed_chemical_are_not_duplicated(tmp_path: Path) -> None:
    run = _category_run(tmp_path)
    run.build()
    table = read_shards(run.settings)
    c = run.settings.columns
    assert "7439-92-1" not in table[c.cas]
    assert table[c.cas].count("110-54-3") == 1
    assert table[c.source][table[c.cas].index("110-54-3")] == "tri_list"


def test_member_without_a_structure_is_reported_and_left_out(tmp_path: Path) -> None:
    run = Fakes(tmp_path, categories=CATEGORY_ROWS)  # PubChem knows no phenol
    report = run.build()
    assert report.categories["unresolved"] == 1 and report.categories["added"] == 0
    assert PHENOL in [cas for cas, _ in report.unresolved]
    assert PHENOL not in read_shards(run.settings)[run.settings.columns.cas]


def test_category_build_is_byte_identical_when_repeated(tmp_path: Path) -> None:
    first = _category_run(tmp_path)
    report = first.build()
    before = {p.name: p.read_bytes() for p in report.shards}
    again = _category_run(tmp_path)
    again.pubchem = Server(lambda request: httpx.Response(404, json={}))  # structures reused
    after = {p.name: p.read_bytes() for p in again.build().shards}
    assert before == after


def test_report_lines_mention_category_outcomes(tmp_path: Path) -> None:
    run = _category_run(tmp_path)
    text = "\n".join(report_lines(run.build(), tmp_path))
    assert "category members added: 1" in text and "skipped_inorganic: 1" in text
