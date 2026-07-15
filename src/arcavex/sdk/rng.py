"""The one deterministic seeding site every effect draws randomness from (spec §3.2).

Determinism rule: any randomness an effect needs must come from this seeded generator, never
from ``random`` or the wall clock, so a fixed document seed gives byte-identical output. The
extension determinism lint enforces exactly this — a loaded effect that imports ``random`` or
reads the clock in ``apply`` is a reproducibility error, not a security concern.
"""

from __future__ import annotations

import hashlib

import numpy as np


def effect_rng(seed: int, node_id: str, effect_index: int) -> np.random.Generator:
    """Return the numpy generator for one effect on one node (spec §3.2 determinism rule).

    Seeded from ``sha256(seed, node_id, effect_index)`` digest bytes — a stable, cross-process
    hash, never Python's salted ``hash()``. Same inputs give a byte-identical stream; a
    different node id or effect position gives an independent one. This is the seeded-RNG *tree*:
    one document seed branches into an independent stream per (node, effect index).
    """
    key = f"{seed}\x00{node_id}\x00{effect_index}".encode()
    digest = hashlib.sha256(key).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


__all__ = ["effect_rng"]
