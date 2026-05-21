"""Experimental tooling for swapping the active fence universe.

The active fence universe — which set of candidate pastures the Build Fences
enumerator considers — is held in three module-level constants on
`agricola.legality`:

    ACTIVE_FENCE_UNIVERSE_ENTRIES
    ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES
    ACTIVE_FENCE_UNIVERSE_SET

All three must point at the same universe. They default to RESTRICTED
(see `agricola.fences` for the four layered universes
RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL).

This module provides three pieces of tooling for cleanly swapping among them
during experiments and tests:

  - `active_universe(spec)`: context manager that saves/swaps/restores the
    trio for the duration of a with-block.
  - `restrict_to(predicate, base=...)`: derive a custom universe by filtering
    an existing one through a per-entry predicate.
  - `NAMED_UNIVERSES` + `current_universe()`: registry of the four built-in
    universes and an accessor for the currently-active triple.

Note: the legality-module enumerators (`_any_legal_pasture_commit` and
`_enumerate_pending_build_fences`) resolve the active universe at CALL time,
not at function-definition time. This means a reassignment inside
`active_universe(...)` takes effect immediately for every call site that
doesn't pass explicit kwargs — including all production call sites.
"""
from __future__ import annotations

import contextlib
from typing import Callable, Iterator, Union

from agricola import legality
from agricola.fences import (
    PastureCandidate,
    UNIVERSE_EXTENDED_ENTRIES,
    UNIVERSE_EXTENDED_SET,
    UNIVERSE_EXTENDED_SMALLEST_ENTRIES,
    UNIVERSE_FAMILY_ENTRIES,
    UNIVERSE_FAMILY_SET,
    UNIVERSE_FAMILY_SMALLEST_ENTRIES,
    UNIVERSE_FULL_ENTRIES,
    UNIVERSE_FULL_SET,
    UNIVERSE_FULL_SMALLEST_ENTRIES,
    UNIVERSE_RESTRICTED_ENTRIES,
    UNIVERSE_RESTRICTED_SET,
    UNIVERSE_RESTRICTED_SMALLEST_ENTRIES,
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# A universe is the (entries, smallest_entries, set) triple expected by the
# legality enumerators. `smallest_entries` is the 1×1 subset of `entries`,
# used by the fast path in `_any_legal_pasture_commit`. `set` is the bitmap
# membership filter used by `_check_entry_legal` for subdivision-membership.
Universe = tuple[
    tuple[PastureCandidate, ...],   # entries
    tuple[PastureCandidate, ...],   # smallest_entries (1×1 subset of entries)
    frozenset,                      # universe_set (cells_bm membership filter)
]

# Either a name registered in NAMED_UNIVERSES or a literal Universe triple.
UniverseSpec = Union[str, Universe]


# ---------------------------------------------------------------------------
# Named universes
# ---------------------------------------------------------------------------

NAMED_UNIVERSES: dict[str, Universe] = {
    "restricted": (
        UNIVERSE_RESTRICTED_ENTRIES,
        UNIVERSE_RESTRICTED_SMALLEST_ENTRIES,
        UNIVERSE_RESTRICTED_SET,
    ),
    "extended": (
        UNIVERSE_EXTENDED_ENTRIES,
        UNIVERSE_EXTENDED_SMALLEST_ENTRIES,
        UNIVERSE_EXTENDED_SET,
    ),
    "family": (
        UNIVERSE_FAMILY_ENTRIES,
        UNIVERSE_FAMILY_SMALLEST_ENTRIES,
        UNIVERSE_FAMILY_SET,
    ),
    "full": (
        UNIVERSE_FULL_ENTRIES,
        UNIVERSE_FULL_SMALLEST_ENTRIES,
        UNIVERSE_FULL_SET,
    ),
}


def current_universe() -> Universe:
    """Return the currently-active (entries, smallest_entries, set) triple.

    Reads `legality.ACTIVE_FENCE_UNIVERSE_*` at call time. Useful for tests
    that want to capture the current triple before swapping.
    """
    return (
        legality.ACTIVE_FENCE_UNIVERSE_ENTRIES,
        legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES,
        legality.ACTIVE_FENCE_UNIVERSE_SET,
    )


def _resolve(spec: UniverseSpec) -> Universe:
    """Accept a name string or a Universe triple; return the triple."""
    if isinstance(spec, str):
        try:
            return NAMED_UNIVERSES[spec]
        except KeyError:
            raise ValueError(
                f"Unknown universe name {spec!r}; expected one of "
                f"{sorted(NAMED_UNIVERSES)} or a 3-tuple "
                f"(entries, smallest_entries, set)."
            )
    if isinstance(spec, tuple) and len(spec) == 3:
        return spec  # type: ignore[return-value]
    raise TypeError(
        f"Expected a universe name (str) or a 3-tuple "
        f"(entries, smallest_entries, set); got {type(spec).__name__}."
    )


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def active_universe(spec: UniverseSpec) -> Iterator[Universe]:
    """Swap the active fence universe for the duration of a with-block.

    `spec` is either a named universe ("restricted" | "extended" | "family"
    | "full") or a 3-tuple (entries, smallest_entries, set) — typically one
    returned by `restrict_to(...)`.

    Saves and restores the previous trio even if the block raises, and is
    safe to nest.

    Example:
        with active_universe("extended"):
            actions = legal_actions(state)   # uses EXTENDED
        # Back to whatever was active before.

    Implementation: reassigns the three `legality.ACTIVE_FENCE_UNIVERSE_*`
    module constants. The enumerators read those constants at call time,
    so default-kwarg call sites (including all production paths) pick up
    the swap automatically.
    """
    entries, smallest_entries, universe_set = _resolve(spec)
    saved = (
        legality.ACTIVE_FENCE_UNIVERSE_ENTRIES,
        legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES,
        legality.ACTIVE_FENCE_UNIVERSE_SET,
    )
    try:
        legality.ACTIVE_FENCE_UNIVERSE_ENTRIES = entries
        legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES = smallest_entries
        legality.ACTIVE_FENCE_UNIVERSE_SET = universe_set
        yield (entries, smallest_entries, universe_set)
    finally:
        (
            legality.ACTIVE_FENCE_UNIVERSE_ENTRIES,
            legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES,
            legality.ACTIVE_FENCE_UNIVERSE_SET,
        ) = saved


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def restrict_to(
    predicate: Callable[[PastureCandidate], bool],
    *,
    base: UniverseSpec = "full",
) -> Universe:
    """Build a derived universe by filtering `base` through `predicate`.

    `base` defaults to UNIVERSE_FULL (the largest universe; any smaller
    universe is a subset). `predicate` is called once per candidate entry;
    entries returning True are kept.

    The returned triple is suitable for `active_universe(...)` or as kwargs
    to any enumerator call site:

        small = restrict_to(lambda e: e.cells_bm.bit_count() <= 6, base="extended")
        with active_universe(small):
            ...

    The returned `smallest_entries` is the 1×1 subset of the kept entries
    (preserving the fast-path semantic). The returned set contains
    every kept entry's `cells_bm`.

    Order is preserved from `base`.
    """
    base_entries, _, _ = _resolve(base)
    entries = tuple(e for e in base_entries if predicate(e))
    smallest_entries = tuple(e for e in entries if e.cells_bm.bit_count() == 1)
    universe_set = frozenset(e.cells_bm for e in entries)
    return entries, smallest_entries, universe_set
