"""Build the read-across catalog from the current TRI chemical list.

Reads the TRI chemical list from Envirofacts (``tri_chem_info``), keeps the discrete chemicals
still listed (a TRI group such as N420 has no single structure), and writes each one's
canonical SMILES, molecular weight, MolDeBERTa embedding and ECFP4 bits to the catalog. The
existing catalog is the structure cache: a chemical already in it keeps its SMILES, and only
newly listed chemicals are looked up on PubChem. Embeddings and bits are recomputed for every
row, so a model or fingerprint change never leaves stale vectors; the pinned model re-embeds a
given SMILES to the identical bytes, so an unchanged chemical rewrites to an identical shard.

The catalog is written as one shard per leading CAS digit, so each committed file stays small.
Shards are staged beside their targets and renamed together, so a failed build leaves the
committed catalog as it was.

The organic members of the TRI categories (``[tri_categories]``) are added as further
candidates, marked as coming from a category and carrying their category codes; inorganic
members are left out because the structure encoder is not meaningful for metals and salts, and
a member that is a discrete TRI chemical stays a TRI-list row.

Usage: ``uv run python -m scripts.build_tri_embeddings [--directory PATH]``
Default output: ``[read_across].directory``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from config.efservice import EfserviceSettings, get_efservice_settings
from config.read_across import CatalogColumns, ReadAcrossSettings, get_read_across_settings
from tools.http import RetryingClient
from tools.informatics.helpers.read_across.catalog import (
    SOURCE_TRI_CATEGORY,
    SOURCE_TRI_LIST,
    Columns,
    read_shards,
    write_columns,
)
from tools.informatics.helpers.read_across.moldeberta import SmilesEmbedder, default_embedder
from tools.informatics.helpers.read_across.pubchem import PubchemCompound, fetch_compound
from tools.informatics.helpers.read_across.structure import Structure, describe
from tools.informatics.helpers.read_across.tri_list import (
    TriChemical,
    TriListError,
    discrete_chemicals,
    fetch_rows,
)
from tools.tri_categories import Category, CategoryIndex, get_category_index

_FILE_MODE = 0o644  # a data file committed to the repository


@dataclass(frozen=True)
class Services:
    """The builder's collaborators (fakes in tests)."""

    efservice_client: RetryingClient
    efservice: EfserviceSettings
    pubchem_client: RetryingClient
    embedder: SmilesEmbedder
    settings: ReadAcrossSettings
    categories: CategoryIndex


@dataclass(frozen=True)
class Candidate:
    """One chemical to write: where it came from and the categories (if any) that list it."""

    chemical: TriChemical
    source: str
    categories: tuple[Category, ...]


@dataclass(frozen=True)
class BuildReport:
    """What one build did.

    Attributes:
        kept: Chemicals written to the catalog.
        reused: Of those, chemicals whose SMILES came from the existing catalog.
        dropped: Rows of the TRI list left out, per reason.
        unresolved: (CAS number, reason) of listed chemicals with no usable structure.
        shards: The shard files written.
        categories: Category members, by outcome: "added" (written), "skipped_inorganic",
            "already_listed" (a discrete TRI chemical, written once as such) and
            "unresolved" (no usable structure; also in ``unresolved``).
    """

    kept: int
    reused: int
    dropped: Mapping[str, int]
    unresolved: tuple[tuple[str, str], ...]
    shards: tuple[Path, ...]
    categories: Mapping[str, int]


def known_smiles(settings: ReadAcrossSettings) -> dict[str, str]:
    """CAS number -> SMILES stored in the existing catalog (empty if there is none yet).

    Only these two columns are read, so a catalog built with other embedding or fingerprint
    settings still serves as the structure cache.
    """
    columns = settings.columns
    try:
        table = read_shards(settings)
    except FileNotFoundError:
        return {}
    pairs = zip(table.get(columns.cas, []), table.get(columns.smiles, []), strict=False)
    return {c: s for c, s in pairs if isinstance(c, str) and isinstance(s, str)}


def _structure(
    chemical: TriChemical,
    known: Mapping[str, str],
    services: Services,
) -> Structure | str:
    """The chemical's structure from the cache or PubChem, or the reason there is none."""
    smiles = known.get(chemical.cas)
    if smiles is None:
        found = fetch_compound(chemical.cas, services.pubchem_client, services.settings.pubchem)
        if not isinstance(found, PubchemCompound):
            return found
        smiles = found.smiles
    structure = describe(smiles, services.settings.fingerprint)
    return structure if structure is not None else f"SMILES {smiles!r} cannot be parsed"


def _row(candidate: Candidate, structure: Structure, services: Services) -> dict[str, object]:
    c = services.settings.columns
    return {
        c.cas: candidate.chemical.cas,
        c.name: candidate.chemical.name,
        c.smiles: structure.smiles,
        c.molecular_weight: structure.molecular_weight,
        c.embedding: services.embedder(structure.smiles).astype(float).tolist(),
        c.bits: structure.bits.astype(int).tolist(),
        c.source: candidate.source,
        c.category_codes: [category.code for category in candidate.categories],
        c.category_names: [category.name for category in candidate.categories],
    }


def _as_columns(rows: Sequence[dict[str, object]], columns: CatalogColumns) -> Columns:
    names = (columns.cas, columns.name, columns.smiles, columns.molecular_weight)
    names += (columns.embedding, columns.bits)
    names += (columns.source, columns.category_codes, columns.category_names)
    return {name: [row[name] for row in rows] for name in names}


def _by_shard(
    rows: Sequence[dict[str, object]],
    settings: ReadAcrossSettings,
) -> dict[str, list[dict[str, object]]]:
    """Group rows by their CAS prefix, each shard sorted by CAS number.

    Sorting keeps a rebuild's diff small: an added chemical shifts only its own shard.
    """
    cas = settings.columns.cas
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(settings.shard_prefix(str(row[cas])), []).append(row)
    return {p: sorted(rows, key=lambda r: str(r[cas])) for p, rows in grouped.items()}


def _stage(rows: Sequence[dict[str, object]], settings: ReadAcrossSettings) -> Path:
    """Write one shard to a temporary file beside the catalog and return its path."""
    handle, temporary = tempfile.mkstemp(dir=settings.directory, suffix=".parquet.tmp")
    os.close(handle)
    write_columns(_as_columns(rows, settings.columns), Path(temporary), settings.columns)
    Path(temporary).chmod(_FILE_MODE)  # mkstemp creates the file private (0600)
    return Path(temporary)


def write_shards(rows: Sequence[dict[str, object]], settings: ReadAcrossSettings) -> list[Path]:
    """Write every shard, replacing the committed ones only once all are staged."""
    settings.directory.mkdir(parents=True, exist_ok=True)
    staged = [
        (_stage(shard, settings), settings.shard_path(prefix))
        for prefix, shard in sorted(_by_shard(rows, settings).items())
    ]
    try:
        for temporary, target in staged:
            temporary.replace(target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    targets = [target for _, target in staged]
    for stale in sorted(set(settings.shard_paths()) - set(targets)):
        stale.unlink()  # a prefix that no longer has any chemical
    return targets


def category_candidates(
    index: CategoryIndex,
    listed: set[str],
) -> tuple[list[Candidate], dict[str, int]]:
    """The organic category members that are not discrete TRI chemicals, and how the rest fell."""
    counts = {"skipped_inorganic": 0, "already_listed": 0}
    found: list[Candidate] = []
    for member in index.members.values():
        if member.cas in listed:
            counts["already_listed"] += 1
        elif not member.organic:
            counts["skipped_inorganic"] += 1
        else:
            found.append(
                Candidate(
                    TriChemical(member.cas, member.name),
                    SOURCE_TRI_CATEGORY,
                    member.categories,
                ),
            )
    return found, counts


def _resolve_all(
    candidates: Sequence[Candidate],
    known: Mapping[str, str],
    services: Services,
) -> tuple[list[dict[str, object]], list[tuple[str, str]]]:
    """A catalog row for each candidate with a usable structure, and the ones without."""
    built: list[dict[str, object]] = []
    unresolved: list[tuple[str, str]] = []
    for candidate in candidates:
        structure = _structure(candidate.chemical, known, services)
        if isinstance(structure, str):
            unresolved.append((candidate.chemical.cas, structure))
        else:
            built.append(_row(candidate, structure, services))
    return built, unresolved


def build_catalog(services: Services) -> BuildReport:
    """Rebuild the catalog from the current TRI list and the TRI category members.

    Raises:
        TriListError: If the TRI list cannot be read; the catalog is then left unchanged.
        ValueError: If no chemical could be resolved; the catalog is then left unchanged.
    """
    settings = services.settings
    rows = fetch_rows(services.efservice_client, services.efservice, settings.tri_list)
    listed = discrete_chemicals(rows, settings.tri_list)
    members, counts = category_candidates(services.categories, {c.cas for c in listed.chemicals})
    candidates = [Candidate(c, SOURCE_TRI_LIST, ()) for c in listed.chemicals] + members
    known = known_smiles(settings)
    built, unresolved = _resolve_all(candidates, known, services)
    if not built:
        raise ValueError("no TRI chemical could be resolved to a structure")
    shards = write_shards(built, settings)
    reused = sum(1 for row in built if row[settings.columns.cas] in known)
    outcome = _category_outcome(counts, members, built, settings, unresolved)
    return BuildReport(
        len(built),
        reused,
        listed.dropped,
        tuple(unresolved),
        tuple(shards),
        outcome,
    )


def _category_outcome(
    counts: dict[str, int],
    members: Sequence[Candidate],
    built: Sequence[dict[str, object]],
    settings: ReadAcrossSettings,
    unresolved: Sequence[tuple[str, str]],
) -> dict[str, int]:
    from_category = {m.chemical.cas for m in members}
    failed = {cas for cas, _ in unresolved} & from_category
    written = {str(row[settings.columns.cas]) for row in built} & from_category
    return {**counts, "added": len(written), "unresolved": len(failed)}


def report_lines(report: BuildReport, target: Path) -> list[str]:
    """Human-readable summary of a build."""
    lines = [
        f"wrote {report.kept} chemicals to {len(report.shards)} shards in {target} "
        f"({report.reused} SMILES reused)",
    ]
    lines += [f"dropped {count}: {reason}" for reason, count in sorted(report.dropped.items())]
    lines += [f"category members {reason}: {n}" for reason, n in sorted(report.categories.items())]
    lines += [f"unresolved {cas}: {reason}" for cas, reason in report.unresolved]
    return lines


def _parse(argv: Sequence[str], settings: ReadAcrossSettings) -> Path:
    parser = argparse.ArgumentParser(description="Build the TRI read-across catalog.")
    parser.add_argument("--directory", type=Path, default=settings.directory)
    return parser.parse_args(list(argv)).directory


def main(argv: Sequence[str]) -> int:
    """Build the catalog; exit status 1 (nothing written) if the TRI list cannot be used."""
    settings = get_read_across_settings()
    settings = replace(settings, directory=_parse(argv, settings))
    with httpx.Client() as http:
        services = Services(
            efservice_client=RetryingClient(get_efservice_settings(), http),
            efservice=get_efservice_settings(),
            pubchem_client=RetryingClient(settings.pubchem, http),
            embedder=default_embedder(settings.model),
            settings=settings,
            categories=get_category_index(),
        )
        try:
            report = build_catalog(services)
        except (TriListError, ValueError) as exc:
            print(f"catalog not built: {exc}", file=sys.stderr)
            return 1
    print("\n".join(report_lines(report, settings.directory)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
