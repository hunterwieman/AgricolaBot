"""Tests for Merchant (occupation, C96).

Card text: "Immediately after each time you take a 'Major or Minor Improvement'
or 'Minor Improvement' action, you can pay 1 food to take the action a second
time."

User rulings (2026-07-14):
  1. House Redevelopment's optional improvement step COUNTS (the action, not
     the action space).
  2. "Immediately after" = the ordinary after-window seam on the action's host.
  3. No chaining: Merchant may not fire again off its own granted action.
"""
import agricola.cards.merchant  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction, FireTrigger, PlaceWorker, Proceed, Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import sole_build_major, sole_play_minor, sole_renovate

_POOL = CardPool(
    occupations=("merchant",) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id="merchant")


def _merchant_offered(state) -> bool:
    return any(isinstance(a, FireTrigger) and a.card_id == "merchant"
               for a in legal_actions(state))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "merchant" in OCCUPATIONS
    cards = {e.card_id for e in TRIGGERS.get("after_major_minor_improvement", ())}
    assert "merchant" in cards
    entry = next(e for e in TRIGGERS["after_major_minor_improvement"]
                 if e.card_id == "merchant")
    assert not entry.mandatory   # "you can pay" — optional


# ---------------------------------------------------------------------------
# State helper — mirrors tests/test_card_small_trader.py
# ---------------------------------------------------------------------------

def _state(space_id, *, seed=5, occ=(), hand_occ=(), minors=(), res=None):
    """Card-mode state: `space_id` revealed + free, current player given the
    played occupations / hand cards / resources. Opponent's hand is emptied
    so it can never play (keeps the flow deterministic)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, space_id), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, space_id, sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     hand_occupations=frozenset(hand_occ),
                     hand_minors=frozenset(minors),
                     resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# POSITIVE: major, then pay 1 food for a second major (end to end)
# ---------------------------------------------------------------------------

def test_second_major_at_major_improvement():
    cs, cp = _state("major_improvement", occ=("merchant",),
                    res=Resources(clay=5, food=1))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))   # Fireplace (2 clay)
    cs = step(cs, Stop())                    # pop build-major -> MMI flips to after

    assert _merchant_offered(cs)
    cs = step(cs, _FIRE)                     # pay 1 food, granted composite pushed
    assert cs.players[cp].resources.food == 0
    top = cs.pending_stack[-1]
    assert type(top).PENDING_ID == "major_minor_improvement"
    assert top.initiated_by_id == "card:merchant"

    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 1))   # second Fireplace (3 clay)
    cs = step(cs, Stop())                    # pop build-major -> granted MMI flips

    # Ruling 3: no chaining off the granted action.
    assert not _merchant_offered(cs)
    cs = step(cs, Stop())                    # pop the granted composite

    # Back at the original host's after phase: once per action-take (latched).
    assert not _merchant_offered(cs)
    owners = cs.board.major_improvement_owners
    assert owners[0] == cp and owners[1] == cp
    assert cs.players[cp].resources.clay == 0


# ---------------------------------------------------------------------------
# POSITIVE: minor, then pay 1 food for a second minor (end to end)
# ---------------------------------------------------------------------------

def test_second_minor_at_major_improvement():
    cs, cp = _state("major_improvement", occ=("merchant",),
                    minors=("market_stall", "corn_scoop"),
                    res=Resources(grain=1, wood=1, food=1))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())                    # pop play-minor -> MMI flips to after

    assert _merchant_offered(cs)
    cs = step(cs, _FIRE)
    assert cs.players[cp].resources.food == 0

    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "corn_scoop"))
    cs = step(cs, Stop())                    # pop play-minor -> granted MMI flips

    assert not _merchant_offered(cs)         # ruling 3
    assert cs.players[cp].resources.veg == 1               # market_stall ran
    assert "corn_scoop" in cs.players[cp].minor_improvements


# ---------------------------------------------------------------------------
# The composite's CHILD minor must not itself offer Merchant on after_play_minor
# — Merchant fires once, at the composite's own after (else it double-offers).
# ---------------------------------------------------------------------------

def test_composite_child_minor_does_not_offer_merchant():
    cs, cp = _state("major_improvement", occ=("merchant",),
                    minors=("market_stall", "corn_scoop"),
                    res=Resources(grain=1, wood=1, food=1))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    # The child play-minor is in its after-phase now; it is a composite child
    # (initiated_by_id "major_minor_improvement"), so Merchant is NOT offered here.
    assert not _merchant_offered(cs)
    cs = step(cs, Stop())                    # pop child -> composite flips to after
    assert _merchant_offered(cs)             # NOW Merchant is offered, exactly once


# ---------------------------------------------------------------------------
# POSITIVE: a bare "Minor Improvement" action (Meeting Place) chains Merchant —
# reachable at 2 players (2026-07-15); a second bare minor is offered.
# ---------------------------------------------------------------------------

def test_second_minor_at_meeting_place():
    cs, cp = _state("meeting_place", occ=("merchant",),
                    minors=("market_stall", "corn_scoop"),
                    res=Resources(grain=1, wood=1, food=1))
    cs = step(cs, PlaceWorker(space="meeting_place"))     # become SP (no food, Cards)
    cs = step(cs, ChooseSubAction(name="play_minor"))     # the "Minor Improvement" action
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    # The bare play-minor's OWN after-phase offers Merchant (no composite here).
    assert _merchant_offered(cs)
    cs = step(cs, _FIRE)
    assert cs.players[cp].resources.food == 0
    # Merchant pushed a fresh bare PendingPlayMinor -> CommitPlayMinor directly
    # (no ChooseSubAction — it is already the play-minor host).
    cs = step(cs, sole_play_minor(cs, "corn_scoop"))
    assert not _merchant_offered(cs)                     # ruling 3 (card:merchant)
    assert cs.players[cp].resources.veg == 1             # market_stall ran
    assert "corn_scoop" in cs.players[cp].minor_improvements


# ---------------------------------------------------------------------------
# The clause-2 provenance guard, unit level: a card-granted bare minor chains
# Merchant (user 2026-07-15), but a composite child / a Merchant self-grant do not.
# ---------------------------------------------------------------------------

def test_bare_minor_eligibility_uses_the_action_flag():
    """Merchant's bare clause chains a frame iff it IS the named "Minor
    Improvement" action (`minor_improvement_action=True`) — never a "play a minor"
    effect (Scholar/Beneficiary, flag False) nor the composite's child minor (flag
    False) — with the sole extra guard being no self-chain (ruling 3). This is the
    flag-based replacement for the old provenance blocklist, which wrongly chained
    Scholar (user ruling 2026-07-15)."""
    from agricola.cards.merchant import _eligible_bare_minor
    from agricola.pending import PendingPlayMinor
    from tests.factories import with_pending_stack

    cs, cp = _state("major_improvement", occ=("merchant",),
                    minors=("market_stall",), res=Resources(food=1, grain=1))

    def _at(iby, is_action):
        s = with_pending_stack(cs, (PendingPlayMinor(
            player_idx=cp, initiated_by_id=iby,
            minor_improvement_action=is_action, phase="after"),))
        return _eligible_bare_minor(s, cp, frozenset())

    # The named action chains, wherever granted from...
    assert _at("card:task_artisan", True)      # a card grant of the action
    assert _at("meeting_place", True)          # Meeting Place's bare minor
    # ...but a "play a minor" effect (flag False) never does — the Scholar fix:
    assert not _at("card:scholar", False)      # Scholar plays a minor, not the action
    assert not _at("card:beneficiary", False)  # Beneficiary likewise
    assert not _at("major_minor_improvement", False)  # a composite child
    # ...and Merchant never chains off its OWN grant, though that IS the action:
    assert not _at("card:merchant", True)      # ruling 3, no self-chain


# ---------------------------------------------------------------------------
# POSITIVE: House Redevelopment's improvement step counts (ruling 1)
# ---------------------------------------------------------------------------

def test_offered_after_house_redevelopment_improvement():
    cs, cp = _state("house_redevelopment", occ=("merchant",),
                    res=Resources(clay=7, reed=1, food=1))

    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, sole_renovate(cs))         # wood -> clay: 2 clay + 1 reed
    cs = step(cs, Stop())                    # pop renovate after-phase
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))   # Fireplace (2 clay)
    cs = step(cs, Stop())                    # pop build-major -> MMI flips to after

    assert _merchant_offered(cs)             # ruling 1: the action, not the space
    cs = step(cs, _FIRE)
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 1))   # second Fireplace (3 clay)
    cs = step(cs, Stop())

    assert cs.players[cp].resources.food == 0
    owners = cs.board.major_improvement_owners
    assert owners[0] == cp and owners[1] == cp


def test_house_redevelopment_renovate_only_no_window():
    # Improvement step declined -> the composite host is never pushed, so no
    # Merchant window anywhere in the turn.
    cs, cp = _state("house_redevelopment", occ=("merchant",),
                    res=Resources(clay=2, reed=1, food=1))

    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, sole_renovate(cs))
    cs = step(cs, Stop())                    # pop renovate after-phase
    assert not _merchant_offered(cs)
    cs = step(cs, Proceed())                 # decline the improvement step
    assert not _merchant_offered(cs)         # space host after-phase: no window


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_at_zero_food():
    cs, cp = _state("major_improvement", occ=("merchant",),
                    res=Resources(clay=2, food=0))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))
    cs = step(cs, Stop())

    assert not _merchant_offered(cs)


def test_not_offered_when_nothing_buildable_or_playable():
    # Plenty of food, but after building the only affordable major there is
    # no second affordable major and no hand minor -> a granted host would be
    # dead, so no offer. (Joinery, not a Fireplace — owning a Fireplace would
    # make a Cooking Hearth buildable by returning it.)
    cs, cp = _state("major_improvement", occ=("merchant",),
                    res=Resources(wood=2, stone=2, food=5))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 7))   # Joinery: spends the wood + stone
    cs = step(cs, Stop())

    assert not _merchant_offered(cs)


def test_not_offered_when_payment_strands_the_only_minor():
    # The post-payment check: 1 food in supply and the sole remaining playable
    # card is a 1-food minor (Cob). Paying Merchant's fee would leave the
    # granted host with no legal child -> not offered. (The first minor is
    # Corn Scoop, not Market Stall — Market Stall's granted vegetable could be
    # liquidated to cover Cob's food cost.)
    cs, cp = _state("major_improvement", occ=("merchant",),
                    minors=("corn_scoop", "cob"),
                    res=Resources(wood=1, food=1))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "corn_scoop"))   # pays the wood
    cs = step(cs, Stop())

    # food=1 makes Cob look playable, but post-debit food=0 does not.
    assert not _merchant_offered(cs)


def test_hand_only_is_inert():
    # Merchant in hand (not played) never fires.
    cs, cp = _state("major_improvement", hand_occ=("merchant",),
                    res=Resources(clay=5, food=1))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))
    cs = step(cs, Stop())

    assert not _merchant_offered(cs)


# ---------------------------------------------------------------------------
# Optionality: declinable
# ---------------------------------------------------------------------------

def test_declinable():
    cs, cp = _state("major_improvement", occ=("merchant",),
                    res=Resources(clay=5, food=1))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))
    cs = step(cs, Stop())

    assert _merchant_offered(cs)
    assert any(isinstance(a, Stop) for a in legal_actions(cs))
    cs = step(cs, Stop())                    # decline: pop the host instead

    assert cs.players[cp].resources.food == 1   # nothing was paid
    owners = cs.board.major_improvement_owners
    assert owners[0] == cp and owners[1] is None
