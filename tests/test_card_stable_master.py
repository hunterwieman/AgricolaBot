import agricola.cards.stable_master  # noqa: F401
"""Stable Master (occupation, C89): optional on-play 1-wood stable build (the
WIDE play-variant shape, ruling 17's mechanism) + ONE unfenced stable upgraded
to a 3-capacity single-type bin (ruling 74's flagged plan — the
register_flexible_to_bin seam).

Card text (verbatim): "When you play this card, you can immediately build
exactly 1 stable for 1 wood. Exactly one of your unfenced stables can hold up
to 3 animals of one type."
"""
import agricola.cards.shepherds_whistle  # noqa: F401  (the interplay check)
import agricola.cards.working_gloves  # noqa: F401  (the pair-gate stranding case)
import agricola.cards.carpenters_apprentice  # noqa: F401  (the discount-eligibility case)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    CommitPlayOccupation,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.capacity_mods import FLEX_TO_BIN_CARDS
from agricola.cards.shepherds_whistle import _stable_is_free
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import accommodates, extract_slots, stables_built
from agricola.legality import legal_actions
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_phase

SM = "stable_master"

_POOL = CardPool(
    occupations=(SM,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _card_state(seed=5, *, wood=1):
    """A card-mode round-1 WORK state: Stable Master in the current player's
    hand, wood set explicitly."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    cs = _edit_player(cs, cp,
                      hand_occupations=frozenset({SM}),
                      resources=fast_replace(cs.players[cp].resources, wood=wood))
    return cs, cp


def _at_play_host(cs):
    """Walk a real Lessons placement to the PendingPlayOccupation host."""
    cs = step(cs, PlaceWorker(space="lessons"))
    return step(cs, ChooseSubAction(name="play_occupation"))


def _sm_plays(cs):
    return [a for a in legal_actions(cs)
            if isinstance(a, CommitPlayOccupation) and a.card_id == SM]


def _own_sm(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {SM})


def _stable_at(state, idx, cells):
    return with_grid(state, idx,
                     {rc: Cell(cell_type=CellType.STABLE) for rc in cells})


def _fence_cell(state, idx, r, c):
    """Enclose cell (r, c) with 4 fences and recompute the pasture cache."""
    fy = state.players[idx].farmyard
    hf = [list(row) for row in fy.horizontal_fences]
    vf = [list(row) for row in fy.vertical_fences]
    hf[r][c] = hf[r + 1][c] = True
    vf[r][c] = vf[r][c + 1] = True
    hf = tuple(tuple(row) for row in hf)
    vf = tuple(tuple(row) for row in vf)
    fy = fast_replace(fy, horizontal_fences=hf, vertical_fences=vf,
                      pastures=compute_pastures_from_arrays(fy.grid, hf, vf))
    return _edit_player(state, idx, farmyard=fy)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_stable_master_registered():
    assert SM in OCCUPATIONS
    assert SM in PLAY_OCCUPATION_VARIANTS
    bins = {cid: fn for cid, fn in FLEX_TO_BIN_CARDS}
    assert SM in bins
    assert bins[SM](None) == 3          # 3 unconditionally; the fold gates


# ---------------------------------------------------------------------------
# The wide on-play build (clause 1) — real Lessons placement in CARDS mode
# ---------------------------------------------------------------------------

def test_play_offers_build_and_decline_when_wood_and_cell_exist():
    cs, _cp = _card_state(wood=1)
    cs = _at_play_host(cs)
    assert sorted(a.variant for a in _sm_plays(cs)) == ["build", "decline_build"]


def test_build_variant_builds_one_stable_for_exactly_one_wood():
    cs, cp = _card_state(wood=1)
    cs = _at_play_host(cs)
    cs = step(cs, CommitPlayOccupation(card_id=SM, variant="build"))
    assert SM in cs.players[cp].occupations
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    assert top.initiated_by_id == "card:stable_master"
    assert top.cost == Resources(wood=1)
    assert top.max_builds == 1
    assert top.build_stables_action is False   # card effect, not the named action

    commits = [a for a in legal_actions(cs) if isinstance(a, CommitBuildStable)]
    assert commits                              # cells on offer
    w0 = cs.players[cp].resources.wood
    b0 = stables_built(cs.players[cp].farmyard)
    cs = step(cs, commits[0])
    assert cs.players[cp].resources.wood == w0 - 1        # exactly 1 wood
    assert stables_built(cs.players[cp].farmyard) == b0 + 1

    # max_builds=1 saturates: only Proceed remains; the turn then unwinds.
    assert legal_actions(cs) == [Proceed()]
    cs = step(cs, Proceed())
    cs = step(cs, Stop())               # pop the build frame's after-phase
    cs = step(cs, Stop())               # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())               # pop the Lessons host
    assert cs.pending_stack == ()
    assert stables_built(cs.players[cp].farmyard) == b0 + 1   # exactly one


def test_decline_variant_plays_with_no_build():
    cs, cp = _card_state(wood=1)
    cs = _at_play_host(cs)
    w0 = cs.players[cp].resources.wood
    b0 = stables_built(cs.players[cp].farmyard)
    cs = step(cs, CommitPlayOccupation(card_id=SM, variant="decline_build"))
    assert SM in cs.players[cp].occupations
    assert not isinstance(cs.pending_stack[-1], PendingBuildStables)
    assert cs.players[cp].resources.wood == w0
    assert stables_built(cs.players[cp].farmyard) == b0


def test_no_wood_offers_decline_only():
    cs, _cp = _card_state(wood=0)
    cs = _at_play_host(cs)
    assert [a.variant for a in _sm_plays(cs)] == ["decline_build"]


def test_no_legal_cell_offers_decline_only():
    cs, cp = _card_state(wood=1)
    # Fill every EMPTY cell with a field: no legal stable cell remains.
    grid = cs.players[cp].farmyard.grid
    fills = {(r, c): Cell(cell_type=CellType.FIELD)
             for r in range(3) for c in range(5)
             if grid[r][c].cell_type == CellType.EMPTY}
    cs = with_grid(cs, cp, fills)
    cs = _at_play_host(cs)
    assert [a.variant for a in _sm_plays(cs)] == ["decline_build"]


# ---------------------------------------------------------------------------
# The (payment × variant) stranding pair-gate (user ruling 75, 2026-07-21):
# "a wide display of (payment × build/no-build) pairs — the build variant is
# offered only with payments that leave the build doable; the decline variant
# with every payment."
# ---------------------------------------------------------------------------

def _gloves_state():
    """Stable Master in hand, Working Gloves played, a filler occupation owned
    (so the Lessons cost is 1 food), EXACTLY 1 wood + 1 food: the payment
    frontier is {1 food, 1 wood} (Working Gloves' substitution), and the wood
    payment would consume the very wood the build variant's granted 1-wood
    build needs."""
    cs, cp = _card_state(wood=1)
    p = cs.players[cp]
    cs = _edit_player(
        cs, cp,
        occupations=p.occupations | {"o0"},               # 2nd occupation -> 1-food cost
        minor_improvements=p.minor_improvements | {"working_gloves"},
        resources=fast_replace(p.resources, wood=1, food=1))
    return cs, cp


def test_working_gloves_wood_payment_withholds_the_build_pair():
    cs, _cp = _gloves_state()
    cs = _at_play_host(cs)
    plays = _sm_plays(cs)
    wood_pay, food_pay = Resources(wood=1), Resources(food=1)
    # The wood payment strands the granted build -> only the decline pair.
    assert CommitPlayOccupation(
        card_id=SM, variant="build", payment=wood_pay) not in plays
    assert CommitPlayOccupation(
        card_id=SM, variant="decline_build", payment=wood_pay) in plays
    # The food payment leaves the wood intact -> both pairs.
    assert CommitPlayOccupation(
        card_id=SM, variant="build", payment=food_pay) in plays
    assert CommitPlayOccupation(
        card_id=SM, variant="decline_build", payment=food_pay) in plays


def test_working_gloves_no_reachable_sequence_locks():
    """Exhaustive DFS from the play host over EVERY reachable line until the
    turn unwinds: no reachable state may have zero legal actions (the hard
    lock the pair-gate exists to prevent)."""
    cs, _cp = _gloves_state()
    cs = _at_play_host(cs)
    seen = set()
    frontier = [cs]
    while frontier:
        s = frontier.pop()
        if not s.pending_stack or s in seen:
            continue                      # turn unwound / already explored
        seen.add(s)
        acts = legal_actions(s)
        assert acts, f"dead state (zero legal actions) at {s.pending_stack[-1]}"
        frontier.extend(step(s, a) for a in acts)
    assert seen                           # the walk actually explored the turn


def test_broke_player_with_apprentice_discount_is_offered_the_build():
    """The pair-gate routes through the cost-modifier chokepoint: a 0-wood
    player with 2 stables built and Carpenter's Apprentice (3rd stable costs
    1 wood less -> the 1-wood granted build is FREE) must still be offered
    the build pair — post-debit doability, not a raw wood check."""
    cs, cp = _card_state(wood=0)
    p = cs.players[cp]
    cs = _edit_player(cs, cp,
                      occupations=p.occupations | {"carpenters_apprentice"})
    cs = _stable_at(cs, cp, [(2, 3), (2, 4)])
    assert stables_built(cs.players[cp].farmyard) == 2
    cs = _at_play_host(cs)
    assert sorted(a.variant for a in _sm_plays(cs)) == ["build", "decline_build"]


# ---------------------------------------------------------------------------
# The capacity upgrade (clause 2) — extract_slots math
# ---------------------------------------------------------------------------

def test_one_standalone_stable_becomes_a_three_bin():
    state = _stable_at(setup(0), 0, [(0, 4)])
    p = state.players[0]
    # Without the card: 1 standalone stable + the house pet = 2 flexible.
    assert extract_slots(state, p) == ([], 2)
    # With the card: the stable's slot becomes a 3-cap single-type bin.
    state = _own_sm(state, 0)
    p = state.players[0]
    assert extract_slots(state, p) == ([3], 1)


def test_bin_accommodation_is_single_type():
    state = _own_sm(_stable_at(setup(0), 0, [(0, 4)]), 0)
    p = state.players[0]
    # 3 sheep in the bin + anything in the pet slot fits...
    assert accommodates(state, p, 3, 1, 0)
    # ...but the bin holds ONE type: 2 sheep + 2 boar has no assignment
    # (bin takes one type's 2, the other type's 2 overflow the 1 pet slot).
    assert not accommodates(state, p, 2, 2, 0)
    # Without the card neither holding fits (2 flexible slots, 4 animals) —
    # the card is what admits 3 sheep + 1 boar.
    base = _stable_at(setup(0), 0, [(0, 4)])
    assert not accommodates(base, base.players[0], 3, 1, 0)


def test_no_standalone_stable_no_transformation():
    state = _own_sm(setup(0), 0)        # card owned, no stable built
    p = state.players[0]
    assert extract_slots(state, p) == ([], 1)   # pet only, no bin


def test_fenced_stable_alone_does_not_qualify():
    # A stable INSIDE a pasture is not unfenced: it doubles the pasture
    # (capacity 4) and the card adds no bin and converts no flexible slot.
    state = _own_sm(_stable_at(setup(0), 0, [(0, 4)]), 0)
    state = _fence_cell(state, 0, 0, 4)
    p = state.players[0]
    assert extract_slots(state, p) == ([4], 1)


# ---------------------------------------------------------------------------
# Shepherd's Whistle interplay (the ruling-74 flagged check)
# ---------------------------------------------------------------------------

def test_whistle_bin_floats_to_an_occupied_stable():
    """Two unfenced stables, 3 sheep + 1 boar. Without Stable Master the
    animals don't even fit the reduced farm (2 flexible); with it the blanked
    stable leaves 1 standalone -> the bin re-derives on the REMAINING stable
    (3 sheep in the bin, boar in the pet slot) — the freed stable is a plain
    one, matching the physical optimum under free rearrangement."""
    base = _stable_at(setup(0), 0, [(0, 4), (0, 3)])
    base = _edit_player(base, 0, animals=Animals(sheep=3, boar=1))
    assert not _stable_is_free(base, 0)
    withcard = _own_sm(base, 0)
    assert _stable_is_free(withcard, 0)


def test_whistle_bin_dies_with_the_only_stable():
    """Exactly 1 unfenced stable (the bin) holding 2 sheep: the full farm
    accommodates them (bin 2/3 + pet free), but freeing the only stable
    removes the bin with it — the Whistle correctly finds no free stable."""
    state = _own_sm(_stable_at(setup(0), 0, [(0, 4)]), 0)
    state = _edit_player(state, 0, animals=Animals(sheep=2))
    assert accommodates(state, state.players[0], 2, 0, 0)
    assert not _stable_is_free(state, 0)


def test_whistle_auto_sheep_composes_with_the_bin():
    """End-to-end: Whistle + Stable Master, 2 stables, 3 sheep. The reduced
    farm (1 standalone -> the bin) holds all 3 sheep, so a stable is free and
    the start_of_breeding auto grants the sheep; the pair then breeds (room
    remains: bin 3 + 2 flexible)."""
    state = with_phase(setup(0), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=10))
    state = _own_sm(state, 0)
    p = state.players[0]
    state = _edit_player(state, 0,
                         minor_improvements=p.minor_improvements
                         | {"shepherds_whistle"})
    state = _stable_at(state, 0, [(0, 4), (0, 3)])
    state = _edit_player(state, 0, animals=Animals(sheep=3))
    assert _stable_is_free(state, 0)

    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        acts = legal_actions(state)
        best = max(acts, key=lambda a: getattr(a, "sheep", 0))
        state = step(state, best)
    # 3 held + 1 granted + 1 newborn = 5 (3 in the bin + 2 flexible slots).
    assert state.players[0].animals.sheep == 5
