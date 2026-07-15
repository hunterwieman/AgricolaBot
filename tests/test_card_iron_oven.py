import agricola.cards.iron_oven  # noqa: F401  (registers the card; not in __init__ yet)
# Tests for Iron Oven (minor improvement, E63; Ephipparius Expansion).
#
# Card text (verbatim): "For any "Bake Bread" action, you can convert exactly 1
# grain into 6 food. When you build this improvement, you can immediately take a
# "Bake Bread" action."  Cost 3 Stone; no prerequisite; 2 printed VP.
#
# A BAKING IMPROVEMENT (Clay/Stone Oven family). Two standing baking seams plus a
# one-shot, declinable on-build bake grant:
#   (1) register_baking_spec_extension  -> a (cap 1, rate 6) source for ANY bake
#   (2) register_bake_bread_extension   -> reachability with no major oven
#   (3) on_play pushes the generic PendingGrantedSubAction("bake_bread") wrapper
#       (the Dwelling Plan / Field Fences optional-grant pattern) — NOT a
#       play-minor variant; the shared dispatch hosts the offer / decline / bake.
#
# Coverage: registration + verbatim-text fidelity; _can_bake_bread + a real
# Grain Utilization bake at 6/grain for an oven-less owner; composition with a
# Fireplace major (oven grain first, then rate 2); the free bake on build driven
# through the real PendingGrantedSubAction wrapper (play -> ChooseSubAction
# ("bake_bread") -> PendingBakeBread -> CommitBake, and Stop = decline); and the
# "exactly 1 grain" per-action cap.
import json
from pathlib import Path

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitPlayMinor,
    PlaceWorker,
    Stop,
)
from agricola.cards.iron_oven import (
    CARD_ID,
    _baking_spec,
    _can_bake_bread_extension,
)
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS
from agricola.engine import step
from agricola.legality import (
    BAKE_BREAD_ELIGIBILITY_EXTENSIONS,
    BAKING_SPEC_EXTENSIONS,
    _can_bake_bread,
    baking_specs_for_player,
    legal_actions,
)
from agricola.pending import (
    PendingBakeBread,
    PendingGrantedSubAction,
    PendingPlayMinor,
    push,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import (
    with_current_player,
    with_majors,
    with_pending_stack,
    with_resources,
    with_space,
)

_N = 6                                 # 6 food per grain
_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Iron Oven")

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx=0):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _bake_amounts(state):
    return sorted(a.grain for a in legal_actions(state)
                  if isinstance(a, CommitBake))


def _at_play_minor_frame(hand=(CARD_ID,), **res):
    """A state at a PendingPlayMinor frame for the current player, holding
    `hand` and exactly the given resources (mirrors the Facades Carving idiom)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_resources(state, cp, **res)
    state = with_pending_stack(state, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _play_the_oven(state):
    """Play the (single, variant-less) oven at a PendingPlayMinor frame,
    returning the state at the pushed PendingGrantedSubAction wrapper."""
    plays = [a for a in legal_actions(state)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    (play,) = plays
    assert play.variant is None                    # no play-minor variant now
    return step(state, play)


# --- (1) Registration + verbatim-text fidelity ------------------------------

def test_json_row():
    assert _ROW["cost"] == "3 Stone"
    assert _ROW["vps"] == 2
    assert _ROW["prerequisites"] is None
    assert _ROW["passing_left"] is None
    assert _ROW["text"] == (
        "For any “Bake Bread” action, you can convert exactly 1 grain "
        "into 6 food. When you build this improvement, you can immediately take "
        "a “Bake Bread” action.")
    # The module docstring quotes the printed text verbatim (line-wrapped, so
    # compare whitespace-normalized).
    import agricola.cards.iron_oven as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(stone=3))   # 3 Stone
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 2                                      # printed VP
    assert not spec.passing_left
    # The two standing baking seams are live; the on-build bake is the wrapper
    # on_play pushes, so the card registers NO play-minor variant.
    assert _baking_spec in BAKING_SPEC_EXTENSIONS
    assert _can_bake_bread_extension in BAKE_BREAD_ELIGIBILITY_EXTENSIONS
    assert CARD_ID not in PLAY_MINOR_VARIANTS


def test_unowned_is_inert():
    s = setup(seed=0)
    s = with_resources(s, 0, grain=3)
    assert _baking_spec(s, 0) == []
    assert baking_specs_for_player(s, 0) == []
    assert not _can_bake_bread(s, s.players[0])


# --- (2) _can_bake_bread + a real Grain Utilization bake, oven-less ----------

def test_ovenless_owner_bakes_at_grain_utilization():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _own(s, 0)
    s = with_resources(s, 0, grain=1)
    s = with_space(s, "grain_utilization", revealed=True)

    # Ownership + grain makes a Bake Bread action reachable with NO major oven.
    assert _can_bake_bread(s, s.players[0])
    assert _baking_spec(s, 0) == [(1, _N)]

    place = PlaceWorker(space="grain_utilization")
    assert place in legal_actions(s)
    s = step(s, place)
    choose = ChooseSubAction(name="bake_bread")
    assert choose in legal_actions(s)
    s = step(s, choose)
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    assert _bake_amounts(s) == [1]                 # cap 1
    s = step(s, CommitBake(grain=1))
    r = s.players[0].resources
    assert r.grain == 0 and r.food == _N           # 1 grain -> 6 food


# --- (3) The spec composes with a major improvement -------------------------

def test_composes_with_fireplace():
    """Owner of a Fireplace (idx 0, rate 2, uncapped) AND this oven (cap 1,
    rate 6): one bake converts via both — the oven's grain first (higher rate),
    the rest at 2. The Fireplace's uncapped source lifts the per-action cap to
    the grain supply."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _own(s, 0)
    s = with_majors(s, owner_by_idx={0: 0})        # Fireplace
    s = with_resources(s, 0, grain=2)
    s = push(s, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization"))

    assert _bake_amounts(s) == [1, 2]              # cap lifted by the Fireplace

    one = step(s, CommitBake(grain=1))
    assert one.players[0].resources.food == _N     # oven (rate 6) fires first

    two = step(s, CommitBake(grain=2))
    r = two.players[0].resources
    assert r.grain == 0 and r.food == _N + 2       # 6 (oven) + 2 (Fireplace)


# --- (4) The free bake on build (the PendingGrantedSubAction wrapper) --------

def test_build_grant_offers_bake_only_with_grain():
    """The oven's on_play pushes the PendingGrantedSubAction("bake_bread")
    wrapper AFTER the oven is owned, so eligibility is exact: with grain it
    offers the bake + Stop; with no grain only Stop (decline)."""
    state, _cp = _at_play_minor_frame(stone=3, grain=1)
    state = _play_the_oven(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("bake_bread",)
    assert top.initiated_by_id == "card:iron_oven"
    assert legal_actions(state) == [ChooseSubAction(name="bake_bread"), Stop()]

    state, _cp = _at_play_minor_frame(stone=3, grain=0)
    state = _play_the_oven(state)
    assert isinstance(state.pending_stack[-1], PendingGrantedSubAction)
    assert legal_actions(state) == [Stop()]        # 0 grain -> decline only


def test_build_bake_pushes_bake_and_converts():
    """Play the oven, then choose the granted "bake_bread": a real
    PendingBakeBread is pushed carrying the card's provenance, and CommitBake
    converts exactly 1 grain -> 6 food at this oven's rate."""
    state, cp = _at_play_minor_frame(stone=3, grain=2)
    state = _play_the_oven(state)

    p = state.players[cp]
    assert CARD_ID in p.minor_improvements and CARD_ID not in p.hand_minors
    assert p.resources.stone == 0                  # 3-stone cost paid
    assert isinstance(state.pending_stack[-1], PendingGrantedSubAction)

    state = step(state, ChooseSubAction(name="bake_bread"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBakeBread)
    assert top.initiated_by_id == "card:iron_oven" and top.player_idx == cp
    assert _bake_amounts(state) == [1]             # cap 1 (even with 2 grain)

    state = step(state, CommitBake(grain=1))
    r = state.players[cp].resources
    assert r.grain == 1 and r.food == _N           # 1 of the 2 grain -> 6 food


def test_build_decline_plays_without_baking():
    """Stop at the wrapper declines the grant: the oven is played, nothing is
    baked, and no bake frame remains on the stack."""
    state, cp = _at_play_minor_frame(stone=3, grain=2)
    state = _play_the_oven(state)
    assert isinstance(state.pending_stack[-1], PendingGrantedSubAction)
    state = step(state, Stop())
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.grain == 2 and p.resources.food == 0   # nothing baked
    assert not any(isinstance(f, PendingBakeBread) for f in state.pending_stack)


# --- (5) The "exactly 1 grain" per-action cap -------------------------------

def test_exactly_one_grain_cap():
    """Owning ONLY the oven, the per-action cap is 1 grain regardless of supply
    (max_grain = min(supply, cap 1)); it never converts more than 1."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _own(s, 0)
    s = with_resources(s, 0, grain=5)
    s = push(s, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization"))
    assert _bake_amounts(s) == [1]                 # only 1 grain, never more
    s = step(s, CommitBake(grain=1))
    r = s.players[0].resources
    assert r.grain == 4 and r.food == _N           # exactly 1 grain -> 6 food
