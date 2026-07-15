import agricola.cards.shoreforester  # noqa: F401  (registers the card — not in cards/__init__.py)

"""Tests for Shoreforester (occupation, B116; Bubulcus Expansion).

Card text: "When you play this card and each time 1 reed is placed on an empty
"Reed Bank" accumulation space in the preparation phase, you get 1 wood."

Two halves:
- on-play: +1 wood, unconditional (driven here through the REAL Lessons flow in
  card mode, mirroring tests/test_cards_occupations.py's Consultant test);
- recurring: a mandatory choice-free `register_auto` on the preparation ladder's
  `replenishment` window (post-refill). The refill adds exactly +1 reed, so
  post-refill `reed_bank.accumulated.reed == 1` is exactly "the reed was placed
  on an EMPTY bank" (see the module docstring for the equivalence caveat).

The preparation tests drive `_complete_preparation` directly (fast_replace
phase/round_number, then call it) — the same idiom as tests/test_card_nest_site.py.
The condition is about the SPACE, not who emptied it: the opponent emptying the
bank still pays the owner (that test empties the bank through a real PlaceWorker
on the Reed Bank by the non-owner).
"""

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space


CARD_ID = "shoreforester"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_reed_bank(state, reed):
    """Force the Reed Bank's accumulated reed (the pre-refill state)."""
    space = get_space(state.board, "reed_bank")
    space = fast_replace(space, accumulated=Resources(reed=reed))
    return fast_replace(state, board=with_space(state.board, "reed_bank", space))


def _prep_state(idx=0, *, reed_before):
    """A PREPARATION state (round 1 → becoming round 2) owning Shoreforester with
    the Reed Bank set to `reed_before` reed before this round's +1 refill."""
    s = _own_occ(setup(0), idx)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, reed_before)
    return s


def _card_state_with_hand(seed=5, *, hand):
    """A card-mode round-1 state with the current player's hand set
    deterministically (mirrors tests/test_cards_occupations.py)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=hand, occupations=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS


def test_registered_on_replenishment_window():
    # The recurring half is a mandatory, choice-free AUTO on the preparation
    # ladder's post-refill window — not on start_of_round, never a trigger.
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("replenishment", ()))
    assert all(e.card_id != CARD_ID for e in AUTO_EFFECTS.get("start_of_round", ()))
    assert all(e.card_id != CARD_ID
               for entries in TRIGGERS.values() for e in entries)


# ---------------------------------------------------------------------------
# On-play: +1 wood, unconditional (real Lessons flow, card mode)
# ---------------------------------------------------------------------------

def test_on_play_grants_one_wood_via_lessons():
    cs, cp = _card_state_with_hand(hand=frozenset({CARD_ID}))
    before = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    assert CommitPlayOccupation(card_id=CARD_ID) in legal_actions(cs)

    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))
    p = cs.players[cp]
    assert p.resources.wood == before + 1             # "when you play this card": +1 wood
    assert CARD_ID in p.occupations                   # moved to tableau
    assert CARD_ID not in p.hand_occupations          # removed from hand
    cs = step(cs, Stop())                             # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())                             # pop the Lessons host
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# The recurring half via the real preparation refill flow
# ---------------------------------------------------------------------------

def test_wood_when_reed_placed_on_empty_bank():
    # Bank EMPTY before refill → +1 → post-refill 1 reed → reed placed on an
    # empty bank → +1 wood.
    s = _prep_state(0, reed_before=0)
    before = s.players[0].resources.wood
    after = _complete_preparation(s)
    assert get_space(after.board, "reed_bank").accumulated.reed == 1
    assert after.players[0].resources.wood == before + 1
    # A choice-free auto pushes no frame: the ladder ran to completion.
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


def test_no_wood_when_bank_unused():
    # Bank held 1 reed before refill (nobody took it) → post-refill 2 reed →
    # the reed was placed on a NON-empty bank → nothing.
    s = _prep_state(0, reed_before=1)
    before = s.players[0].resources.wood
    after = _complete_preparation(s)
    assert get_space(after.board, "reed_bank").accumulated.reed == 2
    assert after.players[0].resources.wood == before


def test_no_wood_when_bank_well_stocked():
    # A larger stockpile → post-refill 5 reed → nothing.
    s = _prep_state(0, reed_before=4)
    before = s.players[0].resources.wood
    after = _complete_preparation(s)
    assert get_space(after.board, "reed_bank").accumulated.reed == 5
    assert after.players[0].resources.wood == before


def test_fires_again_each_time_bank_was_emptied():
    # Emptied before round 2's prep → +1 wood; emptied again before round 3's
    # prep → +1 wood again ("each time", no once-per-game latch).
    s = _prep_state(0, reed_before=0)
    before = s.players[0].resources.wood
    s = _complete_preparation(s)                      # round 2: bank 0 → 1, +1 wood
    assert s.players[0].resources.wood == before + 1
    s = _set_reed_bank(s, 0)                          # someone empties it again
    s = fast_replace(s, phase=Phase.PREPARATION)
    s = _complete_preparation(s)                      # round 3: bank 0 → 1, +1 wood
    assert s.players[0].resources.wood == before + 2


def test_intervening_stocked_prep_pays_nothing_then_rearms():
    # A preparation over a non-empty bank pays nothing; the next preparation
    # over an emptied bank pays again — the condition re-checks each round.
    s = _prep_state(0, reed_before=1)
    before = s.players[0].resources.wood
    s = _complete_preparation(s)                      # round 2: bank 1 → 2, nothing
    assert s.players[0].resources.wood == before
    s = _set_reed_bank(s, 0)
    s = fast_replace(s, phase=Phase.PREPARATION)
    s = _complete_preparation(s)                      # round 3: bank 0 → 1, +1 wood
    assert s.players[0].resources.wood == before + 1


# ---------------------------------------------------------------------------
# Whose action emptied the bank is irrelevant; only the owner is paid
# ---------------------------------------------------------------------------

def test_opponent_emptying_bank_still_pays_owner():
    # The recurring half has no "you" about who emptied the space — the
    # condition is about the Reed Bank itself. The NON-owner takes the reed
    # through a real placement (emptying the bank); at the next preparation
    # the OWNER is paid.
    s = setup(0)
    taker = s.current_player          # the non-owner, about to empty the bank
    owner = 1 - taker
    s = _own_occ(s, owner)
    assert get_space(s.board, "reed_bank").accumulated.reed == 1
    s = step(s, PlaceWorker(space="reed_bank"))       # atomic: takes all reed
    assert get_space(s.board, "reed_bank").accumulated.reed == 0

    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    w_owner = s.players[owner].resources.wood
    w_taker = s.players[taker].resources.wood
    after = _complete_preparation(s)
    assert after.players[owner].resources.wood == w_owner + 1   # owner paid
    assert after.players[taker].resources.wood == w_taker       # taker not


def test_non_owner_gets_nothing():
    # Player 1 owns it, player 0 does not: only P1 is paid on an emptied bank.
    s = _own_occ(setup(0), 1)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, 0)
    w0 = s.players[0].resources.wood
    w1 = s.players[1].resources.wood
    after = _complete_preparation(s)
    assert after.players[0].resources.wood == w0
    assert after.players[1].resources.wood == w1 + 1


def test_hand_only_card_is_inert():
    # Still in hand (never played) → no ownership → no auto fires and no
    # on-play wood, even over an emptied bank.
    s = setup(0)
    p = fast_replace(s.players[0], hand_occupations=frozenset({CARD_ID}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, 0)
    w0 = s.players[0].resources.wood
    after = _complete_preparation(s)
    assert after.players[0].resources.wood == w0
