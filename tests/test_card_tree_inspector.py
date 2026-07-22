"""Tests for Tree Inspector (occupation, D116; Dulcinaria Expansion).

Card text (verbatim): "This card is a "1 Wood" accumulation space for you
only. Each time the newly revealed action space card is a "Quarry"
accumulation space, you must discard all wood from this card."

User ruling 74 (2026-07-21): card-as-action-space approved; Tree Inspector
accumulates +1 wood at the preparation refill (the `replenishment` window),
and the mandatory quarry-reveal discard rides the `reveal` window, which
PRECEDES the refill on the preparation ladder (rungs 3 vs 7 — the user's
stated ordering), so a quarry round starts with exactly the fresh 1 wood.
"Quarry" is the collective name rule (Western/Eastern Quarry — the stone
accumulation spaces, Heart of Stone's reading of the identical event). Using
the space sweeps ALL its accumulated wood to the owner's supply; an EMPTY
card is not placeable (the engine's empty-accumulation-space prune, mirrored);
"for you only" — the opponent is never offered the placement.
"""
import agricola.cards.tree_inspector  # noqa: F401  -- registers the card (not in cards/__init__ yet)

from agricola.actions import PlaceWorker, Proceed, RevealCard, Stop
from agricola.cards.card_spaces import CARD_ACTION_SPACES, card_space_occupied
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.tree_inspector import CARD_ID
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase, STAGE_CARDS, stage_of_round
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingReveal
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import get_space, with_space
from tests.factories import with_current_player

# ---------------------------------------------------------------------------
# Helpers (the reveal-driving idiom of tests/test_card_heart_of_stone.py)
# ---------------------------------------------------------------------------


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _stock(state, idx, wood):
    p = state.players[idx]
    return _edit_player(state, idx, card_state=p.card_state.set(CARD_ID, wood))


def _card_wood(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _mark_revealed(state, card_id, round_number):
    sp = get_space(state.board, card_id)
    return fast_replace(state, board=with_space(state.board, card_id, fast_replace(
        sp, revealed=True, revealed_round=round_number)))


def _reveal_pause(state, prev_round, pinned=None):
    """Advance to the reveal nature pause for entering round prev_round + 1:
    mark stage cards revealed for rounds 2..prev_round (any `pinned`
    {round: card_id} first, generic fillers for the rest — setup already
    revealed round 1's card), then run the preparation walk, which parks at
    the PendingReveal (the revealed-count == round_number invariant needs
    exactly one mark per round)."""
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


def _placements(actions):
    return [a for a in actions
            if isinstance(a, PlaceWorker) and a.space == f"card:{CARD_ID}"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in CARD_ACTION_SPACES
    # +1 wood at the replenishment window — an AUTO (mechanical accumulation).
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("replenishment", ())}
    # The quarry discard — "you must": a mandatory AUTO on the `reveal`
    # window, never an optional trigger.
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("reveal", ())}
    assert CARD_ID not in {e.card_id for e in TRIGGERS.get("reveal", ())}


# ---------------------------------------------------------------------------
# Accumulation: +1 wood at each preparation refill
# ---------------------------------------------------------------------------

def test_accumulates_one_wood_per_preparation():
    s = _own(setup(0), 0)
    s = _reveal_pause(s, prev_round=4)
    # A NON-quarry stage-2 reveal: the discard never fires, the refill adds 1.
    s = step(s, RevealCard(card="house_redevelopment"))
    assert s.phase is Phase.WORK and s.round_number == 5
    assert _card_wood(s, 0) == 1


def test_accumulation_stacks_across_rounds():
    s = _stock(_own(setup(0), 0), 0, 2)          # two earlier refills banked
    s = _reveal_pause(s, prev_round=4)
    s = step(s, RevealCard(card="house_redevelopment"))
    assert _card_wood(s, 0) == 3


def test_unowned_card_never_accumulates():
    s = setup(0)                                  # nobody owns Tree Inspector
    s = _reveal_pause(s, prev_round=4)
    s = step(s, RevealCard(card="house_redevelopment"))
    assert _card_wood(s, 0) == 0 and _card_wood(s, 1) == 0


# ---------------------------------------------------------------------------
# The quarry discard: mandatory, and BEFORE the refill (rungs 3 vs 7)
# ---------------------------------------------------------------------------

def test_quarry_reveal_discards_before_the_refill():
    """A western-quarry reveal with 3 wood banked: the `reveal`-window discard
    (rung 3) clears the stack, THEN the refill lands (+1 at rung 8) — so the
    round starts with exactly 1 wood, never 0 (discard after refill) and
    never 4 (no discard)."""
    s = _stock(_own(setup(0), 0), 0, 3)
    p0_res_before = s.players[0].resources
    s = _reveal_pause(s, prev_round=4)
    s = step(s, RevealCard(card="western_quarry"))
    assert s.phase is Phase.WORK and s.round_number == 5
    assert _card_wood(s, 0) == 1
    # Discarded wood goes to the general supply, never the player.
    assert s.players[0].resources == p0_res_before


def test_eastern_quarry_also_discards():
    # eastern_quarry is a stage-4 card: reveal it entering round 10.
    s = _stock(_own(setup(0), 0), 0, 5)
    s = _reveal_pause(s, prev_round=9)
    s = step(s, RevealCard(card="eastern_quarry"))
    assert s.round_number == 10
    assert _card_wood(s, 0) == 1


def test_earlier_quarry_does_not_refire():
    # A quarry revealed in an EARLIER round never re-triggers the discard.
    s = _stock(_own(setup(0), 0), 0, 2)
    s = _reveal_pause(s, prev_round=5,
                      pinned={5: "western_quarry"})   # revealed back in round 5
    s = step(s, RevealCard(card="basic_wish_for_children"))
    assert s.round_number == 6
    assert _card_wood(s, 0) == 3                  # 2 banked + this refill


# ---------------------------------------------------------------------------
# The action space: sweep-to-supply on use; empty not placeable; owner-only
# ---------------------------------------------------------------------------

def test_use_sweeps_all_wood_to_supply():
    s = _stock(_own(setup(0), 0), 0, 3)
    s = with_current_player(s, 0)
    ps = _placements(legal_actions(s))
    assert ps == [PlaceWorker(space=f"card:{CARD_ID}")]
    assert ps[0].picks is None                    # a plain, non-wide placement
    wood_before = s.players[0].resources.wood
    s = step(s, ps[0])
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace)
    assert top.space_id == f"card:{CARD_ID}"
    s = step(s, Proceed())
    assert s.players[0].resources.wood == wood_before + 3
    assert _card_wood(s, 0) == 0                  # the whole stack was taken
    s = step(s, Stop())
    assert not s.pending_stack
    assert card_space_occupied(s.players[0], CARD_ID)   # used this round


def test_empty_card_not_placeable():
    s = _own(setup(0), 0)
    s = with_current_player(s, 0)
    assert _placements(legal_actions(s)) == []


def test_for_you_only():
    s = _stock(_own(setup(0), 0), 0, 2)
    s = with_current_player(s, 1)                 # opponent to move
    assert _placements(legal_actions(s)) == []
