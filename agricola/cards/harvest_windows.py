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

- ``"field_phase"``  — the FIELD during-window (the crop take — with the
  take-modifier fold-ins — hosted by ``PendingFieldPhase`` when the player has a
  during-window decision, inline otherwise; design doc §4, as built).
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
in-harvest conversions, after-the-harvest is outside — and per the 2026-07-05 ruling
"immediately after each harvest" is the SAME instant as "after each harvest", one
window, not two).
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
    "after_feeding",                 # 10 — user ruling 2026-07-05: "immediately after
    #                                       the feeding phase" and "after the feeding
    #                                       phase" are the SAME instant (one window, was
    #                                       two); Social Benefits resolves before Farm
    #                                       Store via the standing autos-before-triggers
    #                                       ordering, no separate window needed.
    "start_of_breeding",             # 12
    "breeding",                      # 13/14 (sentinel — the BREED frames)
    "after_breeding",                # 15
    "end_of_harvest",                # 16 — the last chance for in-harvest conversions
    "after_harvest",                 # 17 — outside the harvest. User ruling 2026-07-05:
    #                                       "immediately after each harvest" and "after
    #                                       each harvest" name the SAME instant (there is
    #                                       no separate immediately_after_harvest window).
    #                                       Any OTHER "immediately …" phrasing in card
    #                                       text needs its own user ruling — the
    #                                       equivalence does not generalize automatically.
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
# Hosting index (the should_host_space pattern)
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

    Two sentinels are also registrable: "field_phase" (the FIELD during-window
    hosts free-order triggers and pre-take flat autos on that event — design
    doc §4a/§4d; a "field_phase" trigger is what makes the walk push the
    PendingFieldPhase host) and "feeding" (choice-free INCOME autos only —
    "in the feeding phase, you get X food" cards fire at the FEED entry,
    before the payment decision, so their food is payable; design doc §5).
    In-feeding CONVERSIONS ride the HARVEST_CONVERSIONS seam, and "breeding"
    is not registrable — in-breeding effects ride the BREED frames' own
    machinery.
    """
    assert window_id in WINDOW_INDEX and window_id != "breeding", (
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
# - Layabout (C108): the player skips their next WHOLE harvest, feeding included —
#   and per ruling 14 (2026-07-05, following the official online implementation,
#   superseding the earlier contested ruling 2) the cancellation is TOTAL: every
#   window #1-#18 is suppressed for the skipping player, before- and after-harvest
#   boundaries included, plus their feeding and breeding frames (the sentinels need
#   skip guards when Layabout lands).
#
# Each skip card registers a PREDICATE `fn(state, idx, window_id) -> bool`
# answering "is this window suppressed for this player right now?" — the latch
# it reads lives in the card's own card_state (the state-placement rule), keyed
# by the harvest ROUND it applies to (harvest rounds are unique, so a stale
# latch from a past harvest is inert with no clearing step). The walk asks this
# for every simple window; the FEED/BREED entry points ask it with the sentinel
# ids "feeding" / "breeding" (also valid window ids) to suppress a skipper's
# payment/breeding frames. Family fast path: the registry is empty and the
# whole check is one truthiness test.
HARVEST_SKIP_CARDS: dict[str, Callable] = {}


def register_harvest_skip(card_id: str, skip_fn: Callable) -> None:
    """Register a skip card's suppression predicate (card-module import time).
    skip_fn signature: (state, player_idx, window_id) -> bool."""
    HARVEST_SKIP_CARDS[card_id] = skip_fn


def window_skipped(state, player_idx: int, window_id: str) -> bool:
    """Is `window_id` suppressed for this player this harvest (a phase/harvest
    skip)? True iff some OWNED skip card's predicate says so."""
    if not HARVEST_SKIP_CARDS:
        return False
    p = state.players[player_idx]
    return any(_owns(p, cid) and fn(state, player_idx, window_id)
               for cid, fn in HARVEST_SKIP_CARDS.items())


# ---------------------------------------------------------------------------
# Breeding-outcome autos (design doc §5 — the which-newborns payload event)
# ---------------------------------------------------------------------------
# Cards that react to WHICH newborns a player's breeding actually placed
# ("for each newborn animal you get…" — Fodder Planter; "if you get newborn
# animals of at least two types" — Slurry Spreader C71; Champion Breeder [3+])
# register here with (state, owner_idx, outcome) signatures, where `outcome`
# is the `BreedingOutcome` payload computed at `resolution._execute_breed`
# from the engine's own kept-newborn indicator. These are AUTOS — typically
# they write a round-keyed CardStore latch; the OPTIONAL follow-up choice
# (the sow grants) then surfaces as a "breeding_outcome" trigger on the still-
# open breed frame, whose eligibility reads the latch. NOT for any-source
# newborn gains (Dung Collector — deliberately out of scope, §12 handoff).
# Family fast path: empty list, one truthiness test.


BREEDING_OUTCOME_AUTOS: list = []


def register_breeding_outcome_auto(card_id, eligibility_fn, apply_fn) -> None:
    """Register a breeding-outcome consequence (card-module import time).
    eligibility_fn/apply_fn signatures: (state, owner_idx, outcome)."""
    BREEDING_OUTCOME_AUTOS.append(OccasionEntry(card_id, eligibility_fn, apply_fn))


def apply_breeding_outcome_autos(state, owner_idx: int, outcome):
    """Fire every owned, eligible breeding-outcome AUTO for one player's just-
    resolved breeding, in registration order. Called by `_execute_breed` with
    the frame still on top. A no-op when nothing is registered."""
    for e in BREEDING_OUTCOME_AUTOS:
        p = state.players[owner_idx]
        if _owns(p, e.card_id) and e.eligibility_fn(state, owner_idx, outcome):
            state = e.apply_fn(state, owner_idx, outcome)
    return state


# ---------------------------------------------------------------------------
# Feeding-requirement folds (design doc §5 — the feeding-cost fold)
# ---------------------------------------------------------------------------
# Cards that change WHAT FEEDING COSTS ("your newborns require 2 food" —
# Child's Toy; Old Miser [4]'s per-person discount) fold into the requirement
# at its single computation chokepoint, `helpers.feeding_requirement` (the
# base is 2 per adult + 1 per newborn, expressed as 2*people_total − newborns).
# Each fold is `fn(state, owner_idx, need) -> need'`, applied for its owner in
# registration order. The FOLDED requirement flows into the memoized feed
# frontier as the `food_owed` ARGUMENT (part of the cache key), so no
# card-dependent input hides from the cache — the FRONTIER_OPT footgun does
# not arise here. Family fast path: empty dict, one truthiness test.
FEEDING_REQUIREMENT_FOLDS: dict[str, Callable] = {}


def register_feeding_requirement(card_id: str, fold_fn: Callable) -> None:
    """Register a feeding-requirement fold (card-module import time).
    fold_fn signature: (state, owner_idx, need) -> int."""
    FEEDING_REQUIREMENT_FOLDS[card_id] = fold_fn


# ---------------------------------------------------------------------------
# Take-modifier fold-ins (design doc §4b; user ruling 11, 2026-07-05)
# ---------------------------------------------------------------------------
# ALL field-phase harvesting is ONE simultaneous event: a card that harvests
# extra goods from fields during the field phase ("1 additional grain from each
# of your grain fields" — Scythe Worker; "1 additional good from a number of
# fields" — Stable Manure; Scythe E73's one-field widening) does not create a
# second harvesting occasion — it FOLDS INTO the take. A full-catalog sweep
# (2026-07-05) found no sequential wording anywhere; every such card is a
# modifier of the singular event. Mechanically: the fold-ins contribute
# per-cell EXTRA units to `resolution.field_take`, whose manifest entries then
# carry the combined amounts (so occasion consumers — Grain Sieve per ruling
# 11, Slurry Spreader's emptied flags — see one event with everything in it).
#
# KNOWN, DELIBERATELY-DEFERRED limitation (user decision 2026-07-06 — ruling
# 33 in CARD_DEFERRED_PLANS.md): group encodings treat same-count fields as
# interchangeable, but Lynchet's house-adjacency reading can distinguish them
# (which field Grain Thief replaces, which cell a sow fills). The agreed
# eventual fix is a CONDITIONAL adjacency-aware group key; the user chose to
# ignore the gap for now rather than widen the decision space. A decision,
# not an oversight.
#
# Two modifier kinds:
# - **Auto fold-ins** (`variants_fn=None`): choice-free (or modeled choice-free,
#   like Scythe Worker's documented mandatory-max simplification). Applied on
#   every REAL-harvest take for their owner — the hosted CommitFieldTake and
#   the inline walk take alike. `fold_fn(state, idx, None)` returns the extra
#   units per cell ({} when nothing qualifies).
# - **Choice-bearing modifiers** (`variants_fn` given): the player picks HOW to
#   use the card (Stable Manure's which-fields count vectors). Because the
#   choice is part of the one event, it surfaces as VARIANTS OF THE TAKE
#   COMMIT — `CommitFieldTake(modifiers=((card_id, variant), ...))` — never as
#   a separate trigger (the §4b class; Grain Thief's replacement joins this
#   shape later). Owning one with a non-empty variant set is itself a reason
#   to host the during-window frame. `fold_fn(state, idx, variant)` maps the
#   chosen variant to its extra units.
#
# Scope: both implemented members are printed "in the field phase of EACH
# HARVEST" — harvest-event-scoped (ruling 12) — so fold-ins apply only to a
# real harvest's take. A card-played field phase (Bumper Crop, ruling 4) calls
# the bare `field_take` with no fold-ins.


@dataclass(frozen=True)
class TakeFold:
    """What one modifier's fold contributes to the take — the richer return
    shape (a bare dict of extras is accepted as shorthand for
    ``TakeFold(extras=d)``).

    extras  — extra units to harvest per cell, ON TOP of the base 1.
    skipped — cells REPLACED out of the take entirely (Grain Thief's "leave
              the grain on the field … instead"): the base 1 is not taken, no
              extras may target them, and the manifest gets NO entry for them
              (the field was not harvested — user ruling 2026-07-06).
    bonus   — goods from the GENERAL SUPPLY granted by the replacement
              (Grain Thief's 1 grain per replaced field). Not harvested, so
              never in the manifest.
    """
    extras: dict = None            # type: ignore[assignment]
    skipped: frozenset = frozenset()
    bonus: "Resources | None" = None

    def __post_init__(self):
        if self.extras is None:
            object.__setattr__(self, "extras", {})


@dataclass(frozen=True)
class TakeModifierEntry:
    """One registered take-modifier.

    fold_fn signature:
        (state, owner_idx, variant | None, claimed)
            -> dict[(r, c), int] | TakeFold | None
        — the modifier's contribution to the one take event (a bare dict is
        extras-only shorthand). `claimed` maps cells to units ALREADY spoken
        for by earlier modifiers in the same take (the base 1 is implicit on
        every planted cell; a REPLACED cell is entered at its full crop count,
        so later folds see zero spare there): a fold may only allocate within
        each cell's remaining spare (count − 1 − claimed), redirecting to
        another cell of its target group where one exists. Returns None when
        its printed demand cannot be fully met given the claims — the
        enumerator then drops that modifier COMBINATION as infeasible (never
        offered), so `step` can't be handed an over-harvesting action.
        Allocation order: chosen modifiers in `order` (below), then the auto
        fold-ins last (Scythe Worker degrades gracefully — a field with no
        spare simply has no "additional" grain to give).
    variants_fn signature: (state, owner_idx) -> list[str]
        — the currently-legal variant strings (empty = no legal use now), or
        None for an auto fold-in (no choice; fold_fn is called with variant
        None).
    order — allocation precedence within a combo, load-bearing for
        feasibility: 0 = REPLACE-kind (Grain Thief — removes cells from the
        take, so everyone downstream must see the skips), 1 = RIGID fixed-
        demand (Stable Manure), 2 = FLEXIBLE (Scythe). Ties keep registration
        order.
    harvest_scoped — True (default) for cards printed "of each harvest"
        (ruling 12): the fold applies only to a REAL harvest's take. False
        for unscoped wording ("each time you would harvest a grain field" —
        Grain Thief): the fold also applies to a card-driven bare field take
        (Bumper Crop's played field phase).
    """
    card_id: str
    fold_fn: Callable
    variants_fn: Callable | None = None
    order: int = 1
    harvest_scoped: bool = True


TAKE_MODIFIERS: list[TakeModifierEntry] = []


def register_take_modifier(card_id, fold_fn, *, variants_fn=None,
                           order: int = 1, harvest_scoped: bool = True) -> None:
    """Register a field-phase take-modifier (card-module import time). The
    list is kept sorted by `order` (stable — ties keep registration order),
    which fixes both combo-fold precedence and enumeration order."""
    TAKE_MODIFIERS.append(TakeModifierEntry(
        card_id, fold_fn, variants_fn, order, harvest_scoped))
    TAKE_MODIFIERS.sort(key=lambda e: e.order)


def _owns(player_state, card_id: str) -> bool:
    return (card_id in player_state.occupations
            or card_id in player_state.minor_improvements)


@dataclass(frozen=True)
class TakePlan:
    """The merged result of every fold applied to one take: the per-cell
    extras, the replaced-out cells, and the combined supply bonus. What
    `fold_chosen_modifiers` hands to `field_take`."""
    extras: dict
    skipped: frozenset
    bonus: "Resources | None"


def _as_fold(got):
    """Normalize a fold return (bare extras dict shorthand) to TakeFold."""
    return got if isinstance(got, TakeFold) else TakeFold(extras=got)


def _crop_count(state, idx, cell):
    c = state.players[idx].farmyard.grid[cell[0]][cell[1]]
    return c.grain if c.grain > 0 else c.veg


def auto_take_fold_ins(state, idx: int, claimed: dict | None = None) -> dict:
    """The merged choice-free extra takes for player `idx`'s take (Scythe
    Worker's mandatory-max grain), allocated AFTER any `claimed` units (auto
    fold-ins degrade gracefully — no spare, nothing additional to take, never
    infeasible; a REPLACED cell arrives pre-claimed at its full count, so
    nothing is ever taken from it). Empty dict — the Family fast path — when
    no auto modifier is owned."""
    extras: dict = {}
    claimed = dict(claimed) if claimed else {}
    for e in TAKE_MODIFIERS:
        if e.variants_fn is None and _owns(state.players[idx], e.card_id):
            got = e.fold_fn(state, idx, None, claimed)
            assert got is not None, (
                f"auto take fold-in {e.card_id} must degrade, not fail")
            fold = _as_fold(got)
            assert not fold.skipped and fold.bonus is None, (
                f"auto take fold-in {e.card_id} may only contribute extras")
            for cell, n in fold.extras.items():
                extras[cell] = extras.get(cell, 0) + n
                claimed[cell] = claimed.get(cell, 0) + n
    return extras


def choice_take_modifiers(state, idx: int, *, harvest: bool = True) -> list:
    """The owned choice-bearing modifiers with their currently-legal variants:
    [(card_id, [variant, ...]), ...], in fold (`order`) order. Non-empty
    forces the during-window frame (the choice must be surfaced); empty — the
    Family fast path. `harvest=False` — the card-driven bare-take path
    (Bumper Crop) — keeps only the UNSCOPED modifiers (ruling 12: an
    "of each harvest" fold never applies outside a real harvest)."""
    out = []
    for e in TAKE_MODIFIERS:
        if e.variants_fn is None or not _owns(state.players[idx], e.card_id):
            continue
        if not harvest and e.harvest_scoped:
            continue
        vs = e.variants_fn(state, idx)
        if vs:
            out.append((e.card_id, vs))
    return out


def take_modifier_combos(state, idx: int, *, harvest: bool = True) -> list:
    """Every FEASIBLE combination of choice-bearing modifier uses for one
    take, the bare `()` (use none) included — the cross-product of each owned
    modifier's variants-or-decline, feasibility-filtered through
    `fold_chosen_modifiers`. Shared by the FIELD during-frame's
    CommitFieldTake enumeration and by card-driven takes that must surface
    the unscoped modifiers' choice (Bumper Crop × Grain Thief,
    `harvest=False`)."""
    combos: list[tuple] = [()]
    for card_id, variants in choice_take_modifiers(state, idx, harvest=harvest):
        combos = [c + pair
                  for c in combos
                  for pair in ([()]                    # decline this card
                               + [((card_id, v),) for v in variants])]
    return [c for c in combos
            if fold_chosen_modifiers(state, idx, c, harvest=harvest) is not None]


def fold_chosen_modifiers(state, idx: int, modifiers, *,
                          harvest: bool = True) -> "TakePlan | None":
    """Merge the take commit's chosen (card_id, variant) pairs — in fold
    order, each allocating within what the earlier ones left — then the auto
    fold-ins last (skipped on the non-harvest path: every auto member is
    harvest-scoped), into one TakePlan. A REPLACE-kind fold's skipped cells
    are entered into the claim map at their full crop count, so no later fold
    can take anything from them. Returns None when some chosen modifier's
    demand cannot be met given the claims: the enumerator uses that to drop
    the combination as infeasible, so every offered commit is executable."""
    from agricola.resources import Resources

    extras: dict = {}
    claimed: dict = {}
    skipped: set = set()
    bonus = Resources()
    by_id = {e.card_id: e for e in TAKE_MODIFIERS}
    for card_id, variant in modifiers:
        got = by_id[card_id].fold_fn(state, idx, variant, claimed)
        if got is None:
            return None
        fold = _as_fold(got)
        for cell in fold.skipped:
            skipped.add(cell)
            claimed[cell] = _crop_count(state, idx, cell)
        if fold.bonus is not None:
            bonus = bonus + fold.bonus
        for cell, n in fold.extras.items():
            extras[cell] = extras.get(cell, 0) + n
            claimed[cell] = claimed.get(cell, 0) + n
    if harvest:
        for cell, n in auto_take_fold_ins(state, idx, claimed).items():
            extras[cell] = extras.get(cell, 0) + n
    return TakePlan(extras=extras, skipped=frozenset(skipped),
                    bonus=bonus if bonus != Resources() else None)


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
# - TRIGGERS are optional per-occasion offers (Potato Ridger's 3-veg
#   exchange, Food Merchant's per-grain buys). Right after an occasion's
#   autos fire, `apply_harvest_occasion_autos` pushes a per-player
#   `PendingHarvestOccasion` host (the occasion rides the frame) whenever the
#   owner has an eligible registered trigger — wherever the occasion was
#   emitted (the walk's inline take, a CommitFieldTake, a card-driven bare
#   take). The card's (state, idx, occasion)-shaped fns are adapted into the
#   global trigger registry (event "harvest_occasion") so the standard
#   FireTrigger dispatch / variant expansion serve them unchanged.


@dataclass(frozen=True)
class OccasionEntry:
    """One registered per-occasion effect.

    eligibility_fn signature: (state, owner_idx, occasion) -> bool
    apply_fn signature:        (state, owner_idx, occasion) -> GameState
                        or, with variants_fn (triggers only):
                               (state, owner_idx, occasion, variant) -> GameState
    variants_fn signature:     (state, owner_idx, occasion) -> list[str]

    A mandatory-and-choice-free tier of a two-tier card (Potato Ridger's
    "with 4+ vegetables, you MUST do so") is NOT a trigger — it is an
    occasion AUTO (fires with no player input; user ruling 2026-07-05). The
    optional tier's eligibility can exclude the auto-already-reacted case via
    the host frame's `autos_fired`.
    """
    card_id: str
    eligibility_fn: Callable
    apply_fn: Callable
    variants_fn: Callable | None = None


HARVEST_OCCASION_AUTOS: list[OccasionEntry] = []
HARVEST_OCCASION_TRIGGERS: list[OccasionEntry] = []


def register_harvest_occasion_auto(card_id, eligibility_fn, apply_fn) -> None:
    """Register an automatic per-occasion consequence (card-module import time)."""
    HARVEST_OCCASION_AUTOS.append(OccasionEntry(card_id, eligibility_fn, apply_fn))


def _top_occasion(state):
    """The occasion payload of the PendingHarvestOccasion host on top of the
    stack — where the adapted trigger fns run, the host is always the top
    (the enumerator/dispatch operate on the top frame)."""
    top = state.pending_stack[-1]
    return top.occasion


def register_harvest_occasion_trigger(
    card_id, eligibility_fn, apply_fn, *, variants_fn=None,
) -> None:
    """Register an optional per-occasion trigger (card-module import time).

    The card supplies (state, idx, occasion)-shaped fns; this seam adapts them
    into the GLOBAL trigger registry under the "harvest_occasion" event — the
    `PendingHarvestOccasion` host's enumerator and the generic FireTrigger
    dispatch then serve them like any other trigger, reading the occasion off
    the host frame. A variants_fn makes it a play-variant trigger (one
    FireTrigger per variant; apply_fn then takes the variant as a 4th arg)."""
    from agricola.cards.triggers import register, register_play_variant_trigger

    HARVEST_OCCASION_TRIGGERS.append(
        OccasionEntry(card_id, eligibility_fn, apply_fn, variants_fn))

    def adapted_elig(state, idx, triggers_resolved):
        top = state.pending_stack[-1]
        # Two-tier exclusivity: a card whose per-occasion AUTO fired for this
        # same occasion does not also get its optional trigger (Potato
        # Ridger's mandatory 4+ exchange precludes the optional at-3 offer —
        # "exactly 1 vegetable" per occasion; user ruling 2026-07-05: the
        # must-tier is automatic, never surfaced).
        if card_id in top.autos_fired:
            return False
        return eligibility_fn(state, idx, top.occasion)

    if variants_fn is None:
        def adapted_apply(state, idx):
            return apply_fn(state, idx, _top_occasion(state))
    else:
        def adapted_apply(state, idx, variant):
            return apply_fn(state, idx, _top_occasion(state), variant)
        register_play_variant_trigger(
            card_id, lambda state, idx: variants_fn(state, idx, _top_occasion(state)))

    register("harvest_occasion", card_id, adapted_elig, adapted_apply)


def apply_harvest_occasion_autos(state, owner_idx: int, occasion):
    """Fire every owned, eligible per-occasion AUTO for one harvest occasion,
    in registration order. Returns ``(state, fired)`` — the card ids that
    fired, which the paired `maybe_host_occasion_triggers` call below stamps
    on the host frame (two-tier cards use it to keep their optional tier from
    double-reacting to the same occasion). Called wherever an occasion is
    emitted, always paired with the host push (autos first, host second —
    split so a caller can slot its own frame between them, as the walk's
    inline take does with the exit-gated during-frame). A no-op at one list
    check when nothing is registered — the Family fast path."""
    fired: set = set()
    for e in HARVEST_OCCASION_AUTOS:
        p = state.players[owner_idx]
        if (e.card_id in p.occupations or e.card_id in p.minor_improvements) \
                and e.eligibility_fn(state, owner_idx, occasion):
            state = e.apply_fn(state, owner_idx, occasion)
            fired.add(e.card_id)
    return state, frozenset(fired)


def maybe_host_occasion_triggers(state, owner_idx: int, occasion,
                                 autos_fired: frozenset = frozenset()):
    """Push the `PendingHarvestOccasion` choice host for this occasion iff the
    owner has an eligible registered per-occasion TRIGGER (Potato Ridger's
    optional tier, Food Merchant). Returns (state, hosted). Pure push — the
    host lands on top of whatever frame emitted the occasion and resolves
    first. `autos_fired` (from the paired apply_harvest_occasion_autos call)
    rides the frame; a card in it is excluded here and by the enumerator —
    its automatic tier already reacted to this occasion. Family fast path:
    empty registry, one truthiness test."""
    if HARVEST_OCCASION_TRIGGERS:
        p = state.players[owner_idx]
        if any(_owns(p, e.card_id)
               and e.card_id not in autos_fired
               and e.eligibility_fn(state, owner_idx, occasion)
               for e in HARVEST_OCCASION_TRIGGERS):
            from agricola.pending import PendingHarvestOccasion, push
            return push(state, PendingHarvestOccasion(
                player_idx=owner_idx, occasion=occasion,
                autos_fired=autos_fired)), True
    return state, False
