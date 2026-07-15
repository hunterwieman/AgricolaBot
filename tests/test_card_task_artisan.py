"""Tests for Task Artisan (occupation, A96; Artifex Expansion).

Card text: "When you play this card and each time a stone accumulation space
appears on a round space in the preparation phase, you get 1 wood and a
\"Minor Improvement\" action."

The recurring half rides the preparation ladder's `reveal` window (ruling 54,
2026-07-14 as revised): a MANDATORY +1 wood auto plus an OPTIONAL
Minor-Improvement trigger, both gated on "a quarry was revealed by THIS
round's preparation" — `revealed_round == state.round_number` (user decision
2026-07-15; at the `reveal` window the round increment has already run). The
trigger additionally requires a playable hand minor (the forced
`PendingPlayMinor` must never dead-end); the window host's Proceed is the
decline. The on-play half grants the wood outright and, when a hand minor is
playable AFTER the wood lands, pushes the generic
`PendingGrantedSubAction(("play_minor",))` choose-or-decline wrapper (the
Dwelling Plan shape).

These tests drive a REAL preparation: a state paused at the round-card reveal
(`PendingReveal` up), stepped with `RevealCard(card="western_quarry")`, letting
the ladder walk run — mirroring tests/test_reveal.py's reveal idiom and
tests/test_card_tree_farm_joiner.py's window-trigger idiom.
"""
from __future__ import annotations

import agricola.cards.task_artisan  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    RevealCard,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import STAGE_CARDS, Phase, stage_of_round
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import (
    PendingGrantedSubAction,
    PendingHarvestWindow,
    PendingPlayMinor,
    PendingReveal,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import sole_play_minor

CARD_ID = "task_artisan"

_CHOOSE_MINOR = ChooseSubAction(name="play_minor")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _give_hand_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, hand_minors=p.hand_minors | {card_id})


def _give_resources(state, idx, **kw):
    p = state.players[idx]
    return _edit_player(state, idx, resources=p.resources + Resources(**kw))


def _mark_revealed(state, card_id, round_number):
    sp = get_space(state.board, card_id)
    return fast_replace(state, board=with_space(state.board, card_id, fast_replace(
        sp, revealed=True, revealed_round=round_number)))


def _reveal_pause(state, prev_round, pinned=None):
    """Advance `state` to the reveal nature pause for entering round
    `prev_round + 1`: mark stage cards revealed for rounds 2..prev_round (any
    `pinned` {round: card_id} first, generic fillers for the rest — setup
    already revealed round 1's card), then run the preparation walk, which
    parks at the PendingReveal."""
    pinned = pinned or {}
    for r, cid in pinned.items():
        state = _mark_revealed(state, cid, r)
    for r in range(2, prev_round + 1):
        if r in pinned:
            continue
        stage = stage_of_round(r)
        cid = next(c for c in STAGE_CARDS[stage]
                   if not get_space(state.board, c).revealed)
        state = _mark_revealed(state, cid, r)
    state = fast_replace(state, phase=Phase.PREPARATION, round_number=prev_round)
    state = _advance_until_decision(state)
    assert isinstance(state.pending_stack[-1], PendingReveal)
    return state


def _quarry_reveal_owner_with_handplow():
    """Player 0 owns Task Artisan, holds Handplow (cost 1 wood) in hand with 0
    wood, paused at the round-5 reveal — a western_quarry reveal then makes the
    granted wood the very thing that affords the minor."""
    s = _own_occ(setup(0), 0)
    s = _give_hand_minor(s, 0, "handplow")
    assert s.players[0].resources.wood == 0
    return _reveal_pause(s, prev_round=4)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation_with_reveal_hooks():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID not in MINORS
    # The mandatory +1 wood is an AUTO on the `reveal` window; the optional
    # Minor-Improvement action is a TRIGGER on the same window. (Subset checks.)
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("reveal", ()))
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("reveal", ())}


# ---------------------------------------------------------------------------
# Recurring half — a quarry reveal via the REAL preparation walk
# ---------------------------------------------------------------------------

def test_quarry_reveal_pays_wood_owner_only():
    # No hand minor → the trigger is ineligible, so the walk runs straight to
    # WORK: the wood landed, no frame surfaced, and the opponent got nothing.
    s = _own_occ(setup(0), 0)
    s = _reveal_pause(s, prev_round=4)
    wood0 = s.players[0].resources.wood
    wood1 = s.players[1].resources.wood
    out = step(s, RevealCard(card="western_quarry"))
    assert out.round_number == 5
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()
    assert out.players[0].resources.wood == wood0 + 1
    assert out.players[1].resources.wood == wood1


def test_owner_seat_one_is_paid_too():
    s = _own_occ(setup(0), 1)
    s = _reveal_pause(s, prev_round=4)
    wood1 = s.players[1].resources.wood
    out = step(s, RevealCard(card="western_quarry"))
    assert out.players[1].resources.wood == wood1 + 1
    assert out.players[0].resources.wood == s.players[0].resources.wood


def test_wood_lands_before_minor_offer():
    # Handplow costs exactly the 1 wood the auto grants: the window's autos
    # fire before its trigger frames are hosted, so the granted wood makes the
    # hand minor playable and the FireTrigger surfaces.
    s = _quarry_reveal_owner_with_handplow()
    out = step(s, RevealCard(card="western_quarry"))
    assert out.players[0].resources.wood == 1          # the auto's wood
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "reveal" and top.player_idx == 0
    assert out.phase is Phase.PREPARATION              # walk paused at the window
    la = legal_actions(out)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                             # optional → declinable


def test_fire_plays_minor_end_to_end():
    s = _quarry_reveal_owner_with_handplow()
    s = step(s, RevealCard(card="western_quarry"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlayMinor)
    assert top.initiated_by_id == "card:task_artisan"
    # The forced minor offers exactly the playable hand minor — Handplow.
    assert {a.card_id for a in legal_actions(s)} == {"handplow"}
    s = step(s, sole_play_minor(s, "handplow"))
    assert "handplow" in s.players[0].minor_improvements
    assert s.players[0].resources.wood == 0            # granted wood paid the cost
    s = step(s, Stop())                                # pop the play-minor after-phase
    # Back at the window host: the trigger is spent (once per window), only
    # Proceed remains; proceeding completes the ladder to WORK.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "reveal"
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la
    s = step(s, Proceed())
    assert s.phase is Phase.WORK
    assert s.pending_stack == ()


def test_minor_action_declinable_wood_kept():
    s = _quarry_reveal_owner_with_handplow()
    s = step(s, RevealCard(card="western_quarry"))
    s = step(s, Proceed())                             # decline the minor action
    assert s.phase is Phase.WORK
    assert all(not isinstance(f, PendingPlayMinor) for f in s.pending_stack)
    assert "handplow" in s.players[0].hand_minors      # unplayed
    assert s.players[0].resources.wood == 1            # the mandatory wood stays


def test_no_frame_when_no_minor_playable():
    # A hand minor exists but is unaffordable (Market Stall costs 1 grain; the
    # player has none and the granted wood doesn't pay it) → wood only, no frame.
    s = _own_occ(setup(0), 0)
    s = _give_hand_minor(s, 0, "market_stall")
    p = s.players[0]
    s = _edit_player(s, 0, resources=fast_replace(p.resources, grain=0))
    s = _reveal_pause(s, prev_round=4)
    wood0 = s.players[0].resources.wood
    out = step(s, RevealCard(card="western_quarry"))
    assert playable_minors(out, 0) == []
    assert out.players[0].resources.wood == wood0 + 1
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


def test_non_quarry_reveal_grants_nothing():
    s = _own_occ(setup(0), 0)
    s = _give_hand_minor(s, 0, "market_stall")
    s = _give_resources(s, 0, grain=1)                 # market_stall affordable
    s = _reveal_pause(s, prev_round=4)
    wood0 = s.players[0].resources.wood
    out = step(s, RevealCard(card="basic_wish_for_children"))
    assert out.players[0].resources.wood == wood0      # no wood
    assert out.pending_stack == ()                     # no trigger frame
    assert out.phase is Phase.WORK


def test_quarry_from_earlier_round_does_not_refire():
    # western_quarry appeared in round 5 (revealed_round=5); entering round 6
    # reveals a non-quarry — revealed_round(5) < round_number(6), so nothing.
    s = _own_occ(setup(0), 0)
    s = _give_hand_minor(s, 0, "market_stall")
    s = _give_resources(s, 0, grain=1)
    s = _reveal_pause(s, prev_round=5, pinned={5: "western_quarry"})
    wood0 = s.players[0].resources.wood
    out = step(s, RevealCard(card="house_redevelopment"))
    assert out.round_number == 6
    assert out.players[0].resources.wood == wood0
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


def test_hand_only_is_inert():
    # The card sitting UNPLAYED in the hand fires nothing.
    s = setup(0)
    p = s.players[0]
    s = _edit_player(s, 0, hand_occupations=p.hand_occupations | {CARD_ID})
    s = _reveal_pause(s, prev_round=4)
    wood0 = s.players[0].resources.wood
    out = step(s, RevealCard(card="western_quarry"))
    assert out.players[0].resources.wood == wood0
    assert out.pending_stack == ()


# ---------------------------------------------------------------------------
# On-play half — +1 wood always; the optional minor via the granted wrapper
# ---------------------------------------------------------------------------

def test_on_play_grants_wood_without_minor():
    s = setup(0)
    wood0 = s.players[0].resources.wood
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == wood0 + 1
    assert out.pending_stack == ()                     # nothing playable → no wrapper


def test_on_play_offers_optional_minor_when_playable():
    s = _give_hand_minor(setup(0), 0, "market_stall")
    s = _give_resources(s, 0, grain=1)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == s.players[0].resources.wood + 1
    top = out.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("play_minor",)
    assert top.initiated_by_id == "card:task_artisan"
    la = legal_actions(out)
    assert _CHOOSE_MINOR in la
    assert Stop() in la                                # decline path


def test_on_play_wood_counts_toward_affordability():
    # Handplow (1 wood) is unaffordable before the on-play wood lands; the wood
    # is granted FIRST, so the wrapper is still offered.
    s = _give_hand_minor(setup(0), 0, "handplow")
    assert s.players[0].resources.wood == 0
    assert playable_minors(s, 0) == []
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert isinstance(out.pending_stack[-1], PendingGrantedSubAction)


def test_on_play_choose_plays_minor_then_only_stop():
    s = _give_hand_minor(setup(0), 0, "market_stall")
    s = _give_resources(s, 0, grain=1)
    s = OCCUPATIONS[CARD_ID].on_play(s, 0)
    veg0 = s.players[0].resources.veg
    grain0 = s.players[0].resources.grain
    s = step(s, _CHOOSE_MINOR)
    assert isinstance(s.pending_stack[-1], PendingPlayMinor)
    s = step(s, sole_play_minor(s, "market_stall"))
    # Market Stall: pay 1 grain, gain 1 veg; traveling — passes to the opponent.
    assert s.players[0].resources.veg == veg0 + 1
    assert s.players[0].resources.grain == grain0 - 1
    assert "market_stall" in s.players[1].hand_minors
    s = step(s, Stop())                                # pop the play-minor after-phase
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.chosen == frozenset({"play_minor"})     # taken at most once
    la = legal_actions(s)
    assert _CHOOSE_MINOR not in la
    assert Stop() in la


def test_on_play_minor_declinable():
    s = _give_hand_minor(setup(0), 0, "market_stall")
    s = _give_resources(s, 0, grain=1)
    s = OCCUPATIONS[CARD_ID].on_play(s, 0)
    wood_after_play = s.players[0].resources.wood
    s = step(s, Stop())                                # decline the granted minor
    assert all(not isinstance(f, (PendingGrantedSubAction, PendingPlayMinor))
               for f in s.pending_stack)
    assert "market_stall" in s.players[0].hand_minors  # unplayed
    assert s.players[0].resources.wood == wood_after_play  # wood already banked


# ---------------------------------------------------------------------------
# Real play-via-Lessons flow (cards mode)
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def test_played_via_lessons_grants_wood_and_minor_offer():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_occupations=frozenset({CARD_ID}),
        hand_minors=frozenset({"market_stall"}),
    )
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    cs = _give_resources(cs, cp, grain=1)              # market_stall affordable
    wood0 = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))

    assert CARD_ID in cs.players[cp].occupations
    assert cs.players[cp].resources.wood == wood0 + 1
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("play_minor",)
    assert top.initiated_by_id == "card:task_artisan"
