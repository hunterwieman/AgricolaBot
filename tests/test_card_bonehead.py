import agricola.cards.bonehead  # noqa: F401
"""Bonehead (occupation, deck D #118; Consul Dirigens Expansion).

Card text: "When you play this card, immediately place 6 wood on it. Immediately
after each time you play a card from your hand, including this one, you get
1 wood from this card."

User rulings 2026-07-14: (1) "immediately after" = the ordinary after-window
seam; (2) ruling 60 — the payout arrives only after the played card's FULL
effect has resolved (the deferred after-flip), pinned below with Shifting
Cultivation's granted plow; (3) "including this one" is handled inside on_play
(store <- 6 then take 1: net 5 on the card, +1 wood — one synchronous shot).

Covered: registration (subset checks); the self-payout at Bonehead's own play
through the real Lessons flow (exactly +1 wood — pins that the deferred flip
does not pay a second wood for the self-play); a later occupation play; a later
TRAVELING minor play (passed on, still counts); the ruling-60 ordering pin; pile
exhaustion (eligibility gates at 0); opponent plays never fire; hand-only inert.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    CommitPlow,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor, PendingPlow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_pending_stack,
    with_resources,
    with_space,
)
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=("bonehead", "consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall", "shifting_cultivation") + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=3):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so plays come only from what a test grants explicitly.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _edit_player(state, idx, **kwargs):
    p = fast_replace(state.players[idx], **kwargs)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_occ(state, idx, card_id):
    return _edit_player(
        state, idx,
        hand_occupations=state.players[idx].hand_occupations | {card_id})


def _give_hand_minor(state, idx, card_id):
    return _edit_player(
        state, idx, hand_minors=state.players[idx].hand_minors | {card_id})


def _own_bonehead(state, idx, pile):
    """Bonehead already in the tableau with `pile` wood in its CardStore."""
    p = state.players[idx]
    return _edit_player(
        state, idx,
        occupations=p.occupations | {"bonehead"},
        card_state=p.card_state.set("bonehead", pile))


def _play_occupation(cs, idx, card_id):
    """Drive the real Lessons -> play-occupation flow for player `idx`."""
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


def _at_play_minor(state, idx):
    return with_pending_stack(state, (PendingPlayMinor(
        player_idx=idx, initiated_by_id="space:meeting_place_cards"),))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_bonehead_registered():
    assert "bonehead" in OCCUPATIONS
    # Subset checks, never exact-set.
    assert any(e.card_id == "bonehead" and not e.any_player
               for e in AUTO_EFFECTS["after_play_occupation"])
    assert any(e.card_id == "bonehead" and not e.any_player
               for e in AUTO_EFFECTS["after_play_minor"])


# ---------------------------------------------------------------------------
# "Including this one": the self-payout at Bonehead's own play
# ---------------------------------------------------------------------------

def test_playing_bonehead_pays_itself_once():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "bonehead")
    cs = with_resources(cs, 0, food=5)          # wood 0 — clean counting
    cs = _play_occupation(cs, 0, "bonehead")
    assert "bonehead" in cs.players[0].occupations
    # Ruling 3: store <- 6 then take 1 — net 5 on the card, EXACTLY +1 wood
    # (pins that the deferred after-flip does not pay a second, doubled wood).
    assert cs.players[0].card_state.get("bonehead") == 5
    assert cs.players[0].resources.wood == 1


# ---------------------------------------------------------------------------
# Later plays from hand: occupations and (traveling) minors
# ---------------------------------------------------------------------------

def test_later_occupation_play_pays_one_wood():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "bonehead")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = with_resources(cs, 0, food=5)
    cs = _play_occupation(cs, 0, "bonehead")
    cs = step(cs, Stop())                       # pop the play-occupation host
    cs = _play_occupation(cs, 0, "consultant")
    assert cs.players[0].resources.wood == 2    # self-payout + consultant's play
    assert cs.players[0].card_state.get("bonehead") == 4


def test_traveling_minor_play_pays_one_wood():
    # Market Stall is a passing minor: played from hand (counts) then handed to
    # the opponent (irrelevant to Bonehead).
    cs = _card_state()
    cs = _own_bonehead(cs, 0, 5)
    cs = _give_hand_minor(cs, 0, "market_stall")
    cs = with_resources(cs, 0, grain=1)         # exactly the play cost; wood 0
    cs = _at_play_minor(cs, 0)
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    assert cs.players[0].resources.wood == 1
    assert cs.players[0].card_state.get("bonehead") == 4
    assert "market_stall" in cs.players[1].hand_minors   # passed on regardless


# ---------------------------------------------------------------------------
# The ruling-60 ordering pin: the wood can never fund the played card's effect
# ---------------------------------------------------------------------------

def test_wood_arrives_only_after_the_played_cards_full_effect():
    cs = _card_state()
    cs = _own_bonehead(cs, 0, 5)
    cs = _give_hand_minor(cs, 0, "shifting_cultivation")
    cs = with_resources(cs, 0, food=2)          # exactly the play cost; wood 0
    cs = _at_play_minor(cs, 0)

    cs = step(cs, sole_play_minor(cs, "shifting_cultivation"))

    # Mid-effect: the granted plow is up, the play host is unflipped, and the
    # wood has NOT arrived yet.
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    host = cs.pending_stack[-2]
    assert host.phase == "before" and host.effect_initiated
    assert cs.players[0].resources.wood == 0
    assert cs.players[0].card_state.get("bonehead") == 5

    plows = [a for a in legal_actions(cs) if isinstance(a, CommitPlow)]
    cs = step(cs, plows[0])                     # the granted plow
    cs = step(cs, Stop())                       # pop the plow; the deferred flip fires

    host = cs.pending_stack[-1]
    assert isinstance(host, PendingPlayMinor)
    assert host.phase == "after"
    assert cs.players[0].resources.wood == 1    # only now
    assert cs.players[0].card_state.get("bonehead") == 4


# ---------------------------------------------------------------------------
# Pile exhaustion: eligibility gates at zero
# ---------------------------------------------------------------------------

def test_empty_pile_pays_nothing():
    cs = _card_state()
    cs = _own_bonehead(cs, 0, 1)                # one wood left on the card
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = _give_hand_occ(cs, 0, "priest")
    cs = with_resources(cs, 0, food=5)

    cs = _play_occupation(cs, 0, "consultant")  # takes the last wood
    cs = step(cs, Stop())
    assert cs.players[0].resources.wood == 1
    assert cs.players[0].card_state.get("bonehead") == 0

    cs = _play_occupation(cs, 0, "priest")      # pile empty -> nothing more
    assert cs.players[0].resources.wood == 1
    assert cs.players[0].card_state.get("bonehead") == 0


# ---------------------------------------------------------------------------
# Scoping: own plays only; hand-only inert
# ---------------------------------------------------------------------------

def test_opponents_play_never_fires():
    cs = _card_state()
    cs = _own_bonehead(cs, 0, 5)
    cs = _give_hand_occ(cs, 1, "consultant")
    cs = with_resources(cs, 0, food=5)
    cs = with_resources(cs, 1, food=5)
    cs = _play_occupation(cs, 1, "consultant")
    assert "consultant" in cs.players[1].occupations
    assert cs.players[0].resources.wood == 0            # owner got nothing
    assert cs.players[0].card_state.get("bonehead") == 5  # pile untouched
    assert cs.players[1].resources.wood == 0            # non-owner got nothing


def test_hand_only_bonehead_is_inert():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "bonehead")      # in hand, never played
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = with_resources(cs, 0, food=5)
    cs = _play_occupation(cs, 0, "consultant")
    assert cs.players[0].resources.wood == 0
    assert cs.players[0].card_state.get("bonehead") is None   # no store either
