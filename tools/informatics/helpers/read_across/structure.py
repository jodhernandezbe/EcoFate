"""SMILES -> canonical SMILES, ECFP4 bit vector and molecular weight (RDKit)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, rdFingerprintGenerator

from config.read_across import FingerprintSettings

# RDKit sums atomic masses in atom order, so the same molecule parsed from two SMILES spellings
# differs by about 1e-13 g/mol. Rounding keeps the stored weight, and so the committed
# catalog, identical across rebuilds; 4 decimals is finer than the atomic masses themselves.
_WEIGHT_DECIMALS = 4


@dataclass(frozen=True)
class Structure:
    """A parsed molecule, reduced to what read-across needs.

    Attributes:
        smiles: Canonical SMILES (RDKit).
        bits: Morgan fingerprint bits (0/1), shape (n_bits,).
        molecular_weight: Average molecular weight, in g/mol.
    """

    smiles: str
    bits: NDArray[np.uint8]
    molecular_weight: float


def _parse(smiles: str) -> Chem.Mol | None:
    """Return the molecule, or None if ``smiles`` is blank, unparseable or has no atoms."""
    if not smiles.strip():
        return None
    _quiet = rdBase.BlockLogs()  # RDKit would print every parse error to stderr
    # The stubs type the result as Mol, but RDKit returns None for an unparseable SMILES.
    mol = cast(Chem.Mol | None, Chem.MolFromSmiles(smiles.strip()))
    del _quiet
    return mol if mol is not None and mol.GetNumAtoms() > 0 else None


def describe(smiles: str, fingerprint: FingerprintSettings) -> Structure | None:
    """Canonicalize ``smiles`` and compute its fingerprint and molecular weight.

    Args:
        smiles: Any valid SMILES.
        fingerprint: Morgan radius (2 for ECFP4) and number of bits.

    Returns:
        The structure, or None if ``smiles`` cannot be parsed.
    """
    mol = _parse(smiles)
    if mol is None:
        return None
    generator = rdFingerprintGenerator.GetMorganGenerator(
        radius=fingerprint.radius,
        fpSize=fingerprint.n_bits,
    )
    bits = np.asarray(generator.GetFingerprintAsNumPy(mol), dtype=np.uint8)
    # Average molecular weight; defined at runtime but missing from the RDKit stubs.
    weight = cast(float, Descriptors.MolWt(mol))  # pyright: ignore[reportAttributeAccessIssue]
    return Structure(Chem.MolToSmiles(mol), bits, round(float(weight), _WEIGHT_DECIMALS))
