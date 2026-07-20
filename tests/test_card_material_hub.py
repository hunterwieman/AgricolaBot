import agricola.cards.material_hub  # noqa: F401  (registers the card)

"""Tests for Material Hub (minor improvement, Corbarius C81).

Card text: "Immediately place 2 of each building resource on this card. Each time
any player (including you) takes at least 5 wood, 4 clay, 3 reed, or 3 stone, you
get 1 of that building resource from this card."

An `any_player` automatic effect on `after_action_space` (reads the host frame's
`taken` sweep delta), hosting the five (2p) building accumulation spaces on either
player's use. Covers: registration; the HAVE-check prereq (reed+stone, not
debited); on-play stocking from the supply; own/opponent qualifying sweeps paying
the owner 1 from the card's stock; the sub-threshold no-fire; the native-type
filter (a foreign resource on a space counts toward no threshold); each building
type; stock exhaustion.
"""
from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    should_host_space,
)
from agricola.constants import BUILDING_RESOURCE_ACCUMULATION_SPACES
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_space

CARD_ID = "material_hub"
_FULL_STOCK = Resources(wood=2, clay=2, reed=2, stone=2)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, stock=_FULL_STOCK):
    """Give `idx` the played card with `stock` goods on it (bypassing on_play)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {CARD_ID},
        card_state=p.card_state.set(CARD_ID, stock),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _stock(state, idx) -> Resources:
    return state.players[idx].card_state.get(CARD_ID, Resources())


def _stock_space(state, space_id, res: Resources):
    """Reveal a building accumulation space and set its accumulated pile."""
    return with_space(state, space_id, revealed=True, accumulated=res)


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, Proceed (primary effect), Stop."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    # Automatic-only card -> before-phase is a singleton Proceed.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    # Spendable cost is ONLY the 1 wood + 1 clay (reed/stone are a prereq, not a cost).
    assert spec.cost == Cost(resources=Resources(wood=1, clay=1))
    assert spec.passing_left is False
    # Payout is an AFTER-window auto (reads taken).
    after_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert CARD_ID in after_ids
    # any-player hook on ALL five building accumulation spaces.
    for sid in BUILDING_RESOURCE_ACCUMULATION_SPACES:
        assert CARD_ID in ANY_PLAYER_HOOK_CARDS.get(sid, set())
    assert BUILDING_RESOURCE_ACCUMULATION_SPACES == frozenset(
        {"forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"})


# ---------------------------------------------------------------------------
# Prerequisite (HAVE-check: 1 reed + 1 stone in supply, never debited)
# ---------------------------------------------------------------------------

def test_prereq_have_check_reed_and_stone():
    spec, s = MINORS[CARD_ID], _state()
    none = fast_replace(s.players[0], resources=Resources())
    assert not prereq_met(spec, fast_replace(s, players=(none, s.players[1])), 0)
    reed_only = fast_replace(s.players[0], resources=Resources(reed=1))
    assert not prereq_met(spec, fast_replace(s, players=(reed_only, s.players[1])), 0)
    stone_only = fast_replace(s.players[0], resources=Resources(stone=1))
    assert not prereq_met(spec, fast_replace(s, players=(stone_only, s.players[1])), 0)
    both = fast_replace(s.players[0], resources=Resources(reed=1, stone=1))
    assert prereq_met(spec, fast_replace(s, players=(both, s.players[1])), 0)


def test_on_play_stocks_card_without_touching_supply():
    # on_play places 2 of each building resource on the card FROM THE SUPPLY: the
    # card's stock is set and the player's own goods are unchanged.
    s = _state()
    p0 = fast_replace(s.players[0], resources=Resources(reed=1, stone=1))  # the prereq goods
    s = fast_replace(s, players=(p0, s.players[1]))
    before = s.players[0].resources
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _stock(out, 0) == _FULL_STOCK
    assert out.players[0].resources == before          # reed/stone NOT debited; nothing spent
    assert _stock(out, 1) == Resources()               # opponent unaffected


# ---------------------------------------------------------------------------
# Own qualifying sweep pays 1 of the native type from the stock
# ---------------------------------------------------------------------------

def test_own_sweep_5_wood_pays_1_wood_from_stock():
    # Forest swept for exactly 5 wood (the "at least 5" boundary) -> +1 wood payout.
    s = _stock_space(_own(with_current_player(_state(), 0), 0), "forest",
                     Resources(wood=5))
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "forest")
    # Owner got the 5 swept wood PLUS 1 wood from the card.
    assert out.players[0].resources.wood == before_wood + 5 + 1
    # The stock's wood dropped 2 -> 1; the other types are untouched.
    assert _stock(out, 0) == Resources(wood=1, clay=2, reed=2, stone=2)


def test_four_wood_sweep_does_not_fire():
    # 4 wood < the 5-wood threshold -> no payout; stock unchanged.
    s = _stock_space(_own(with_current_player(_state(), 0), 0), "forest",
                     Resources(wood=4))
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "forest")
    assert out.players[0].resources.wood == before_wood + 4   # sweep only, no bonus
    assert _stock(out, 0) == _FULL_STOCK


def test_clay_pit_4_clay_fires():
    s = _stock_space(_own(with_current_player(_state(), 0), 0), "clay_pit",
                     Resources(clay=4))
    before_clay = s.players[0].resources.clay
    out = _play_hosted_space(s, "clay_pit")
    assert out.players[0].resources.clay == before_clay + 4 + 1
    assert _stock(out, 0) == Resources(wood=2, clay=1, reed=2, stone=2)


def test_reed_bank_3_reed_fires():
    s = _stock_space(_own(with_current_player(_state(), 0), 0), "reed_bank",
                     Resources(reed=3))
    before_reed = s.players[0].resources.reed
    out = _play_hosted_space(s, "reed_bank")
    assert out.players[0].resources.reed == before_reed + 3 + 1
    assert _stock(out, 0) == Resources(wood=2, clay=2, reed=1, stone=2)


def test_quarry_3_stone_fires():
    s = _stock_space(_own(with_current_player(_state(), 0), 0), "western_quarry",
                     Resources(stone=3))
    before_stone = s.players[0].resources.stone
    out = _play_hosted_space(s, "western_quarry")
    assert out.players[0].resources.stone == before_stone + 3 + 1
    assert _stock(out, 0) == Resources(wood=2, clay=2, reed=2, stone=1)


# ---------------------------------------------------------------------------
# any_player: an opponent's qualifying sweep pays the owner
# ---------------------------------------------------------------------------

def test_opponent_sweep_pays_owner():
    # P0 owns Material Hub; P1 (active) sweeps 6 wood from Forest.
    s = _own(with_current_player(_state(), 1), 0)
    s = _stock_space(s, "forest", Resources(wood=6))
    assert should_host_space(s, "forest", 1)     # hosted on the opponent's turn
    p0_wood = s.players[0].resources.wood
    p1_wood = s.players[1].resources.wood
    out = _play_hosted_space(s, "forest")
    # The OWNER (P0) gets +1 wood from the card; the acting player (P1) only the sweep.
    assert out.players[0].resources.wood == p0_wood + 1
    assert out.players[1].resources.wood == p1_wood + 6
    assert _stock(out, 0) == Resources(wood=1, clay=2, reed=2, stone=2)


def test_each_hub_pays_its_own_owner():
    # BOTH players own a Material Hub; P0 sweeps 6 wood -> each owner's own card
    # pays that owner 1 wood from its own stock.
    s = _own(_own(with_current_player(_state(), 0), 0), 1)
    s = _stock_space(s, "forest", Resources(wood=6))
    p0_wood = s.players[0].resources.wood
    p1_wood = s.players[1].resources.wood
    out = _play_hosted_space(s, "forest")
    assert out.players[0].resources.wood == p0_wood + 6 + 1   # sweep + own card
    assert out.players[1].resources.wood == p1_wood + 1       # own card only
    assert _stock(out, 0) == Resources(wood=1, clay=2, reed=2, stone=2)
    assert _stock(out, 1) == Resources(wood=1, clay=2, reed=2, stone=2)


# ---------------------------------------------------------------------------
# Native-type filter: a foreign resource on a space counts toward NO threshold
# ---------------------------------------------------------------------------

def test_foreign_resource_on_space_counts_toward_no_threshold():
    # Inject 3 stone onto Forest's accumulated pile alongside 3 wood. Forest's
    # native type is WOOD, so only taken.wood (=3, below 5) is checked; the foreign
    # stone (>= the 3-stone threshold) counts toward NOTHING. No payout.
    s = _stock_space(_own(with_current_player(_state(), 0), 0), "forest",
                     Resources(wood=3, stone=3))
    before = s.players[0].resources
    out = _play_hosted_space(s, "forest")
    # The player really did sweep both goods (so the foreign stone was on the pile)...
    assert out.players[0].resources.wood == before.wood + 3
    assert out.players[0].resources.stone == before.stone + 3
    # ...but Material Hub paid nothing.
    assert _stock(out, 0) == _FULL_STOCK


# ---------------------------------------------------------------------------
# Stock exhaustion: once the native type reaches 0, further takes pay nothing
# ---------------------------------------------------------------------------

def test_stock_exhaustion_pays_nothing():
    # A card whose wood stock is already 0 (other types full): a qualifying wood
    # sweep pays no wood.
    s = _own(with_current_player(_state(), 0), 0,
             stock=Resources(wood=0, clay=2, reed=2, stone=2))
    s = _stock_space(s, "forest", Resources(wood=6))
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "forest")
    assert out.players[0].resources.wood == before_wood + 6   # sweep only
    assert _stock(out, 0) == Resources(wood=0, clay=2, reed=2, stone=2)


def test_last_wood_pays_then_exhausted():
    # Stock holds exactly 1 wood: the first qualifying sweep pays it (1 -> 0), a
    # second qualifying sweep then pays nothing.
    s = _own(with_current_player(_state(), 0), 0,
             stock=Resources(wood=1, clay=2, reed=2, stone=2))
    s = _stock_space(s, "forest", Resources(wood=6))
    w0 = s.players[0].resources.wood
    out = _play_hosted_space(s, "forest")
    assert out.players[0].resources.wood == w0 + 6 + 1        # last wood paid
    assert _stock(out, 0).wood == 0
    # Re-stock the forest and sweep again (same worker-placement flow) -> no payout.
    out = _stock_space(with_current_player(out, 0), "forest", Resources(wood=6))
    w1 = out.players[0].resources.wood
    out2 = _play_hosted_space(out, "forest")
    assert out2.players[0].resources.wood == w1 + 6           # sweep only
    assert _stock(out2, 0).wood == 0


# ---------------------------------------------------------------------------
# Not owned -> space stays atomic, nobody pays
# ---------------------------------------------------------------------------

def test_not_owned_no_host_no_payout():
    s = _stock_space(with_current_player(_state(), 0), "forest", Resources(wood=6))
    p0 = s.players[0].resources
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == p0.wood + 6       # sweep only, atomic path
