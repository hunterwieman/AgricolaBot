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

from dataclasses import dataclass
from typing import Callable

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
# The FIELD band and the virtual walk (user ruling 3 — whole-phase-per-player)
# ---------------------------------------------------------------------------
# Within the FIELD segment — windows before_field_phase .. after_field_phase,
# the take included — the starting player resolves their ENTIRE segment first,
# then the other player theirs (ruling 3, PROVISIONAL: the user dislikes the
# later-player advantage; revisit if distortive). Everywhere else the walk is
# window-major (both players per window, SP first).
#
# The walk cursor (`GameState.harvest_cursor`) therefore indexes a VIRTUAL walk
# rather than the raw ladder: the FIELD band appears once per player, in seat-
# resolve order. For 2 players the virtual sequence is
#
#   [w0, w1,  band(SP: w2..w6),  band(other: w2..w6),  w7..w16]
#
# (22 positions). `walk_position` decodes a virtual cursor into (window_index,
# band_player): band_player is the single player whose band pass this position
# belongs to, or None outside the band (window-major). Decoding needs
# `starting_player`, which is fixed for the duration of a harvest (SP changes
# only via WORK-phase actions). With N players the band would simply repeat N
# times — the shape 4p needs (CLAUDE.md Phase 3).
#
# The FEED and BREED segments are NOT banded yet: their frames already resolve
# SP-first within each window, and realizing ruling 3's whole-segment-per-player
# ordering there is deferred until a window in those segments has a member card
# whose ordering it would change.
FIELD_BAND_START: int = WINDOW_INDEX["before_field_phase"]
FIELD_BAND_END: int = WINDOW_INDEX["after_field_phase"]        # inclusive
FIELD_BAND_LEN: int = FIELD_BAND_END - FIELD_BAND_START + 1

WALK_LENGTH: int = len(HARVEST_WINDOWS) + FIELD_BAND_LEN       # 2-player


def walk_position(cursor: int, starting_player: int) -> tuple[int, int | None]:
    """Decode a virtual walk cursor into (window_index, band_player | None).

    band_player is the player whose FIELD-band pass the position belongs to
    (windows in the band fire for that ONE player), or None for a window-major
    position (fires for both players, SP first)."""
    if cursor < FIELD_BAND_START:
        return cursor, None
    first_pass_end = FIELD_BAND_START + FIELD_BAND_LEN
    if cursor < first_pass_end:
        return cursor, starting_player
    second_pass_end = first_pass_end + FIELD_BAND_LEN
    if cursor < second_pass_end:
        return cursor - FIELD_BAND_LEN, 1 - starting_player
    return cursor - FIELD_BAND_LEN, None


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

    "field_phase" — a sentinel — is nonetheless registrable: the FIELD
    during-window hosts free-order triggers and pre-take flat autos on that
    event (design doc §4a/§4d; a "field_phase" trigger is what makes the walk
    push the PendingFieldPhase host). The FEED and BREED sentinels are not —
    in-feeding effects ride the HARVEST_CONVERSIONS seam and the FEED/BREED
    frames' own machinery, never a window event.
    """
    assert window_id in WINDOW_INDEX and window_id not in ("feeding", "breeding"), (
        f"not a registrable harvest window: {window_id!r}")
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


# ---------------------------------------------------------------------------
# Harvest-occasion registries (the payload-bearing seam — design doc §4d)
# ---------------------------------------------------------------------------
# The global firing system deliberately carries no event payload
# (CARD_ENGINE_IMPLEMENTATION.md §8). Harvesting-consequence cards need one —
# "what did this harvesting event take, and from where?" — so they register here
# instead, with (state, owner_idx, occasion) signatures reading the
# `HarvestOccasion` manifest (defined in `agricola/pending.py` beside the frame
# that logs it). Two kinds, mirroring the global auto/trigger split:
#
# - AUTOS fire mechanically right after each occasion applies, wherever it is
#   emitted — the walk's inline take, a CommitFieldTake at the during-frame, a
#   fired additional-harvest trigger, or a bare `field_take` call (Bumper Crop /
#   Harvest Festival Planning trigger the EFFECT, not the phase — ruling 4 —
#   yet non-phase-keyed consequences still attach through the occasion).
#   Members: Slurry Spreader (per emptied grain/veg entry), Crack Weeder /
#   Potato Harvester (per veg unit), and the ruled take-ONCE cards Grain Sieve /
#   Barley Mill (ruling 9: gate on `occasion.source == "take"` — they read the
#   take's specifics, never a card-granted extra harvest). All migrate here
#   from the legacy pre-take `harvest_field` snapshot idiom.
# - TRIGGERS are optional per-occasion offers (Potato Ridger, Food Merchant,
#   Melon Patch's granted plow). No member is implemented; the registry fixes
#   the shape now, and the SURFACING machinery (offering them at the
#   during-frame per logged occasion) lands with the first member — the same
#   loud-guard pattern as the skip seam above.


@dataclass(frozen=True)
class OccasionEntry:
    """One registered per-occasion effect.

    eligibility_fn signature: (state, owner_idx, occasion) -> bool
    apply_fn signature:        (state, owner_idx, occasion) -> GameState
    """
    card_id: str
    eligibility_fn: Callable
    apply_fn: Callable


HARVEST_OCCASION_AUTOS: list[OccasionEntry] = []
HARVEST_OCCASION_TRIGGERS: list[OccasionEntry] = []


def register_harvest_occasion_auto(card_id, eligibility_fn, apply_fn) -> None:
    """Register an automatic per-occasion consequence (card-module import time)."""
    HARVEST_OCCASION_AUTOS.append(OccasionEntry(card_id, eligibility_fn, apply_fn))


def register_harvest_occasion_trigger(card_id, eligibility_fn, apply_fn) -> None:
    """Register an optional per-occasion trigger (card-module import time).
    Registry-only seam today: the during-frame surfacing lands with the first
    member card, and `apply_harvest_occasion_autos`'s guard below keeps the
    gap loud rather than silent."""
    HARVEST_OCCASION_TRIGGERS.append(OccasionEntry(card_id, eligibility_fn, apply_fn))


def apply_harvest_occasion_autos(state, owner_idx: int, occasion):
    """Fire every owned, eligible per-occasion AUTO for one harvest occasion, in
    registration order. Called wherever an occasion is emitted. A no-op at two
    list checks when nothing is registered — the Family fast path."""
    if HARVEST_OCCASION_TRIGGERS:
        raise NotImplementedError(
            "a card registered a per-occasion TRIGGER but the during-frame "
            "surfacing for occasion triggers is not built yet — build it with "
            "that card (HARVEST_WINDOWS_DESIGN.md §4d)")
    for e in HARVEST_OCCASION_AUTOS:
        p = state.players[owner_idx]
        if (e.card_id in p.occupations or e.card_id in p.minor_improvements) \
                and e.eligibility_fn(state, owner_idx, occasion):
            state = e.apply_fn(state, owner_idx, occasion)
    return state
