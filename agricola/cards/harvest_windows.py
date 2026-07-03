"""The harvest timing-window ladder (card game only).

Design of record: ``design_docs/cards/HARVEST_WINDOWS_DESIGN.md`` (+ the dated user
rulings there and in ``CARD_DEFERRED_PLANS.md``). The harvest detours the round walk on
rounds {4, 7, 9, 11, 13, 14}; printed card text names many distinct instants around and
inside its FIELD → FEED → BREED sub-phases ("at the start of each harvest", "after the
field phase", "at the end of each harvest", …). This module is the data side of that
ladder: the ordered window table, the registration index that drives hosting, and the
skip-guard seam. The walk that consumes it is ``engine._advance_harvest``.

Three entries are SENTINELS, not simple windows — they name the engine's own harvest
machinery threaded between the windows:

- ``"field_phase"``  — the FIELD during-window (the crop take + the field-phase card
  hook; today the two-stage ``field_triggers_offered`` machinery, to be rebuilt on the
  take-occasion manifest per the design doc §4).
- ``"feeding"``      — the FEED payment frames (``PendingHarvestFeed`` + the
  ``HARVEST_CONVERSIONS`` seam), untouched by the window work.
- ``"breeding"``     — the BREED frames (``PendingHarvestBreed``), untouched.

Every other entry is a *simple window*: its id doubles as the trigger/auto EVENT string
(``register(<window_id>, …)`` / ``register_auto(<window_id>, …)`` — the
``PendingPreparation``/"start_of_round" literal-event precedent), autos fire mechanically
inside the walk (starting player first), and a per-player ``PendingHarvestWindow`` choice
frame is pushed only for a player with an eligible registered trigger. No registrations →
no frames, no autos → a cardless harvest walks the ladder at a few dict lookups per
window and is byte-identical to the pre-ladder engine (the Family fast path).

Window ordering is load-bearing and rules-derived (the four-slot timing model; see the
design doc §1, including the resolved post-breeding-timeline ruling of 2026-07-03:
after-the-breeding-phase is INSIDE the harvest, end-of-harvest is the last chance for
in-harvest conversions, immediately-after / after are outside).
"""
from __future__ import annotations

# The ladder, in resolve order. Simple-window ids are also event strings; the three
# sentinels are handled specially by engine._advance_harvest and never fire as events.
HARVEST_WINDOWS: tuple[str, ...] = (
    "immediately_before_harvest",    # 1
    "start_of_harvest",              # 2
    "before_field_phase",            # 3
    "start_of_field_phase",          # 4
    "field_phase",                   # 5  (sentinel — the FIELD during-window)
    "end_of_field_phase",            # 6
    "after_field_phase",             # 7
    "start_of_feeding",              # 8
    "feeding",                       # 9  (sentinel — the FEED payment frames)
    "immediately_after_feeding",     # 10
    "after_feeding",                 # 11
    "start_of_breeding",             # 12
    "breeding",                      # 13/14 (sentinel — the BREED frames)
    "after_breeding",                # 15
    "end_of_harvest",                # 16 — the last chance for in-harvest conversions
    "immediately_after_harvest",     # 17 — outside the harvest
    "after_harvest",                 # 18 — outside the harvest
)

WINDOW_INDEX: dict[str, int] = {w: i for i, w in enumerate(HARVEST_WINDOWS)}

SENTINEL_WINDOWS: frozenset = frozenset({"field_phase", "feeding", "breeding"})


# ---------------------------------------------------------------------------
# Hosting index (the should_host_space / HARVEST_FIELD_CARDS pattern)
# ---------------------------------------------------------------------------
# window_id -> the card ids registered to fire there. Consulted per player when the
# walk reaches the window; empty (the Family game) → O(1) skip, no frame ever built.
HARVEST_WINDOW_CARDS: dict[str, set[str]] = {}


def register_harvest_window_hook(card_id: str, window_id: str) -> None:
    """Index `card_id` as firing in harvest window `window_id`.

    Called at card-module import alongside the card's ``register(<window_id>, …)``
    (optional trigger) or ``register_auto(<window_id>, …)`` (automatic effect).
    A card may register in more than one window (Dentist: bank at start_of_harvest,
    payout during feeding).
    """
    assert window_id in WINDOW_INDEX and window_id not in SENTINEL_WINDOWS, (
        f"not a simple harvest window: {window_id!r}")
    HARVEST_WINDOW_CARDS.setdefault(window_id, set()).add(card_id)


def owns_window_card(player_state, window_id: str) -> bool:
    """Does this player own (has PLAYED) any card registered on `window_id`?
    O(1) on the Family fast path (no index entry)."""
    cards = HARVEST_WINDOW_CARDS.get(window_id)
    if not cards:
        return False
    return bool(cards & (player_state.occupations | player_state.minor_improvements))


# ---------------------------------------------------------------------------
# Skip guards (the seam; no card sets these yet)
# ---------------------------------------------------------------------------
# Two skip shapes exist in the catalog (design doc §3, user rulings 1-2 of 2026-07-03):
#
# - Lunchtime Beer (E58): at start_of_harvest the player may skip the FIELD and
#   BREEDING phases of that harvest. A skipped phase has no boundaries (ruling 1,
#   definite): windows 3-7 and 12-15 are suppressed for that player.
# - Layabout (C108): the player skips their next WHOLE harvest, feeding included.
#   The harvest's OUTER boundaries survive (ruling 2 — CONTESTED, BGA disagrees):
#   windows 17-18 still fire; windows 2-16 are suppressed. Whether window 1
#   (immediately_before_harvest) fires for a Layabout player is OPEN (design doc §8
#   question 2) — resolve before Layabout is implemented.
#
# Neither card is implemented, so `window_skipped` is a structural seam with a hard
# fast path: HARVEST_SKIP_CARDS is empty until a skip-capable card registers into it,
# and the walk pays one truthiness test per call. When the cards land, their latches
# live in CardStore (the state-placement rule) and this predicate reads them.
HARVEST_SKIP_CARDS: set[str] = set()


def window_skipped(state, player_idx: int, window_id: str) -> bool:
    """Is `window_id` suppressed for this player this harvest (a phase/harvest skip)?
    Always False until a skip-capable card (Lunchtime Beer, Layabout) is implemented
    and registers into HARVEST_SKIP_CARDS."""
    if not HARVEST_SKIP_CARDS:
        return False
    raise NotImplementedError(
        "a skip-capable card registered into HARVEST_SKIP_CARDS but window_skipped "
        "has no latch logic yet — implement it with the card (design doc §3)")
