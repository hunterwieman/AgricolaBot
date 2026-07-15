"""Tests for Parvenu (occupation, E145; Ephipparius Expansion; players 3+).

Card text: "If you play this card in round 7 or before, choose clay or reed: you
immediately get a number of that building resource equal to the number you
already have in your supply."

A play-variant occupation (Petrified Wood / Roof Ballaster shape): the play
surfaces one CommitPlayOccupation per variant, the variant-aware on_play doubles
the chosen building resource. The round gate replaces the two real routes with a
single no-op in round 8+.
"""
import agricola.cards.parvenu  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import CommitPlayOccupation
from agricola.cards.parvenu import CARD_ID, _variants
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, round_number=3, res=Resources()):
    """A CARDS state at a PendingPlayOccupation with Parvenu in hand and `res`."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = dataclasses.replace(cs, round_number=round_number)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({CARD_ID}),
                     occupations=frozenset(), resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayOccupation(
        player_idx=cp, initiated_by_id="space:lessons", cost=Resources()),))
    return cs, cp


def _commits(cs):
    return [a for a in legal_actions(cs)
            if isinstance(a, CommitPlayOccupation) and a.card_id == CARD_ID]


def _commit(cs, variant):
    return next(a for a in _commits(cs) if a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_OCCUPATION_VARIANTS


# ---------------------------------------------------------------------------
# The round gate on the variant list
# ---------------------------------------------------------------------------

def test_variants_are_clay_and_reed_when_round_at_most_7():
    cs, _cp = _state(round_number=7, res=Resources(clay=2))
    assert sorted(v for v, _s in _variants(cs, cs.current_player)) == ["clay", "reed"]


def test_variants_are_noop_after_round_7():
    cs, _cp = _state(round_number=8, res=Resources(clay=2))
    assert _variants(cs, cs.current_player) == [("none", Resources())]


# ---------------------------------------------------------------------------
# The doubling
# ---------------------------------------------------------------------------

def test_choosing_clay_doubles_clay():
    cs, cp = _state(round_number=5, res=Resources(clay=3, reed=1))
    out = step(cs, _commit(cs, "clay"))
    p = out.players[cp]
    assert p.resources.clay == 6            # 3 held -> +3
    assert p.resources.reed == 1            # reed untouched
    assert CARD_ID in p.occupations         # the card was played


def test_choosing_reed_doubles_reed():
    cs, cp = _state(round_number=5, res=Resources(clay=2, reed=4))
    out = step(cs, _commit(cs, "reed"))
    p = out.players[cp]
    assert p.resources.reed == 8            # 4 held -> +4
    assert p.resources.clay == 2


def test_choosing_clay_with_none_held_grants_nothing():
    cs, cp = _state(round_number=5, res=Resources(reed=2))
    out = step(cs, _commit(cs, "clay"))
    assert out.players[cp].resources.clay == 0
    assert CARD_ID in out.players[cp].occupations


def test_round_8_play_grants_nothing():
    cs, cp = _state(round_number=8, res=Resources(clay=5, reed=5))
    (commit,) = _commits(cs)
    assert commit.variant == "none"
    out = step(cs, commit)
    p = out.players[cp]
    assert p.resources == Resources(clay=5, reed=5)   # unchanged
    assert CARD_ID in p.occupations
