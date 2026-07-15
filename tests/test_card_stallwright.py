import agricola.cards.stallwright  # noqa: F401  (registers the card)
"""Stallwright (occupation, E89; Ephipparius Expansion; players 1+).

Card text: "After you play your 2nd, 3rd, 5th, and 7th occupation (including this
one), you can build 1 stable at no cost."

User confirmation (2026-07-14): optional ("you can"), and only offered while the
player has stable pieces left in supply.

An OPTIONAL trigger on `after_play_occupation` keyed to the lifetime occupation
count (at the after window the just-played occupation — including Stallwright
itself — is already in the tableau, so `len(p.occupations)` is the 1-based
ordinal). Firing pushes a FREE PendingBuildStables capped at 1. These tests drive
the real Lessons -> play-occupation flow (no direct frame pokes).
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import stables_in_supply
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_space

# Clean filler occupations: no-op on_play, no hook/trigger/auto — playing them
# changes only the lifetime occupation count.
_FILLERS = (
    "bricklayer",
    "carpenter",
    "clay_plasterer",
    "conservator",
    "frame_builder",
    "master_bricklayer",
)

_POOL = CardPool(
    occupations=("stallwright",) + _FILLERS + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id="stallwright")


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so plays come only from what a test grants. Ample food:
    # Lessons plays cost 1 food each after the first, and a shortfall would detour
    # through PendingFoodPayment (an unrelated mechanic).
    p0 = fast_replace(
        cs.players[0],
        hand_occupations=frozenset(),
        hand_minors=frozenset(),
        resources=fast_replace(cs.players[0].resources, food=10),
    )
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _edit_player(state, idx, **fields):
    p = fast_replace(state.players[idx], **fields)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, hand_occupations=p.hand_occupations | {card_id})


def _play_occupation(cs, idx, card_id):
    """Drive the real Lessons -> play-occupation flow for player `idx`.

    Stops short of popping the play-occupation host's after-phase, so the caller
    can inspect any after-phase FireTriggers.
    """
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


def _play_and_finish(cs, idx, card_id):
    """Play an occupation and pop both the after-phase and the Lessons host."""
    cs = _play_occupation(cs, idx, card_id)
    cs = step(cs, Stop())   # pop the play-occupation host's after-phase
    cs = step(cs, Stop())   # pop the Lessons host frame
    return cs


def _at_ordinal(cs, n, *, next_card=None):
    """Player 0 owns Stallwright with `n - 1` occupations total in the tableau
    (Stallwright among them), and holds `next_card` (default a filler) in hand —
    so the next play is the nth lifetime occupation."""
    fillers = tuple(f"x{i}" for i in range(n - 2))
    cs = _edit_player(cs, 0, occupations=frozenset({"stallwright", *fillers}))
    return _give_hand_occ(cs, 0, next_card or _FILLERS[0])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_stallwright_registered():
    assert "stallwright" in OCCUPATIONS
    trig_ids = {e.card_id for e in TRIGGERS.get("after_play_occupation", ())}
    assert "stallwright" in trig_ids
    entry = next(e for e in TRIGGERS["after_play_occupation"]
                 if e.card_id == "stallwright")
    assert entry.mandatory is False   # "you can" — an ordinary optional trigger


# ---------------------------------------------------------------------------
# "(including this one)": Stallwright played AS the 2nd occupation qualifies,
# and the granted stable is FREE
# ---------------------------------------------------------------------------

def test_stallwright_as_second_occupation_offers_free_stable():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, _FILLERS[0])
    cs = _play_and_finish(cs, 0, _FILLERS[0])          # 1st occupation
    cs = _give_hand_occ(cs, 0, "stallwright")

    supply0 = stables_in_supply(cs.players[0])
    cs = _play_occupation(cs, 0, "stallwright")        # 2nd — including this one
    wood0 = cs.players[0].resources.wood
    acts = legal_actions(cs)
    assert _FIRE in acts
    assert Stop() in acts                              # declinable alongside

    # Fire -> the free PendingBuildStables primitive is pushed.
    cs = step(cs, _FIRE)
    assert type(cs.pending_stack[-1]).__name__ == "PendingBuildStables"
    top = cs.pending_stack[-1]
    assert top.cost == type(top.cost)()                # zero cost
    assert top.max_builds == 1
    stable_commit = next(a for a in legal_actions(cs)
                         if isinstance(a, CommitBuildStable))
    cs = step(cs, stable_commit)

    assert stables_in_supply(cs.players[0]) == supply0 - 1   # one stable built
    assert cs.players[0].resources.wood == wood0             # at no cost
    # Capped at 1: no second stable commit is offered.
    assert not any(isinstance(a, CommitBuildStable) for a in legal_actions(cs))

    # Pop the stable host; back in the play host's after-phase the trigger is
    # spent (triggers_resolved) — not re-offered within the same play.
    cs = step(cs, Proceed())
    cs = step(cs, Stop())
    assert _FIRE not in legal_actions(cs)
    # Finish the turn cleanly.
    cs = step(cs, Stop())
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_first_occupation_offers_nothing():
    # Stallwright played as the 1st occupation: ordinal 1 is not in {2,3,5,7}.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "stallwright")
    cs = _play_occupation(cs, 0, "stallwright")
    assert _FIRE not in legal_actions(cs)


def test_second_occupation_after_stallwright_first_offers():
    # Stallwright 1st (no offer), then a filler 2nd -> the offer appears.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "stallwright")
    cs = _play_and_finish(cs, 0, "stallwright")        # 1st
    cs = _give_hand_occ(cs, 0, _FILLERS[0])
    cs = _play_occupation(cs, 0, _FILLERS[0])          # 2nd
    assert _FIRE in legal_actions(cs)


# ---------------------------------------------------------------------------
# Ordinal boundaries: 2, 3, 5, 7 qualify; 4, 6, 8 do not
# ---------------------------------------------------------------------------

def test_ordinals_offer_exactly_2_3_5_7():
    for n, offered in ((2, True), (3, True), (4, False), (5, True),
                       (6, False), (7, True), (8, False)):
        cs = _card_state()
        cs = _at_ordinal(cs, n)
        cs = _play_occupation(cs, 0, _FILLERS[0])      # the nth lifetime play
        assert len(cs.players[0].occupations) == n
        assert (_FIRE in legal_actions(cs)) is offered, f"ordinal {n}"


# ---------------------------------------------------------------------------
# Supply / cell gates (never offer a dead-end)
# ---------------------------------------------------------------------------

def _set_cells(state, idx, cell_type, count=None):
    """Set EMPTY farmyard cells (all, or the first `count`) to `cell_type`."""
    p = state.players[idx]
    changed = 0
    new_rows = []
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            if cell.cell_type == CellType.EMPTY and (count is None or changed < count):
                cell = fast_replace(cell, cell_type=cell_type)
                changed += 1
            new_row.append(cell)
        new_rows.append(tuple(new_row))
    fy = fast_replace(p.farmyard, grid=tuple(new_rows))
    return _edit_player(state, idx, farmyard=fy)


def test_no_offer_with_no_stable_in_supply():
    # All 4 stable pieces already built -> supply 0 -> no offer at ordinal 2.
    cs = _card_state()
    cs = _at_ordinal(cs, 2)
    cs = _set_cells(cs, 0, CellType.STABLE, count=4)
    assert stables_in_supply(cs.players[0]) == 0
    cs = _play_occupation(cs, 0, _FILLERS[0])
    assert _FIRE not in legal_actions(cs)


def test_no_offer_with_no_legal_cell():
    # Every empty farmyard cell filled (fields) -> no legal stable cell -> no offer.
    cs = _card_state()
    cs = _at_ordinal(cs, 2)
    cs = _set_cells(cs, 0, CellType.FIELD)
    assert stables_in_supply(cs.players[0]) == 4       # supply untouched
    cs = _play_occupation(cs, 0, _FILLERS[0])
    assert _FIRE not in legal_actions(cs)


# ---------------------------------------------------------------------------
# Optionality: declinable, and a declined ordinal is gone forever
# ---------------------------------------------------------------------------

def test_declinable_and_declined_ordinal_never_returns():
    cs = _card_state()
    cs = _at_ordinal(cs, 2)
    supply0 = stables_in_supply(cs.players[0])

    cs = _play_occupation(cs, 0, _FILLERS[0])          # 2nd occupation
    assert _FIRE in legal_actions(cs)
    cs = step(cs, Stop())                              # decline (don't fire)
    cs = step(cs, Stop())                              # pop the Lessons host
    assert cs.pending_stack == ()
    assert stables_in_supply(cs.players[0]) == supply0   # nothing built

    # The count only moves forward: the 3rd play offers its OWN ordinal (3 is
    # in the set)...
    cs = _give_hand_occ(cs, 0, _FILLERS[1])
    cs = _play_occupation(cs, 0, _FILLERS[1])          # 3rd occupation
    assert _FIRE in legal_actions(cs)
    cs = step(cs, Stop())
    cs = step(cs, Stop())

    # ...and after declining that too, the 4th play offers nothing — the
    # declined ordinals 2 and 3 are not recoverable.
    cs = _give_hand_occ(cs, 0, _FILLERS[2])
    cs = _play_occupation(cs, 0, _FILLERS[2])          # 4th occupation
    assert _FIRE not in legal_actions(cs)


# ---------------------------------------------------------------------------
# Scoping: owner + own-plays only; a hand card is inert
# ---------------------------------------------------------------------------

def test_opponent_plays_offer_nothing():
    # Player 0 owns Stallwright; player 1 plays their 2nd occupation -> no offer
    # on player 1's play host (and player 0 gets nothing).
    cs = _card_state()
    cs = _edit_player(cs, 0, occupations=frozenset({"stallwright", "x0"}))
    cs = _edit_player(cs, 1, occupations=frozenset({"y0"}))
    cs = _give_hand_occ(cs, 1, _FILLERS[0])
    supply0_p0 = stables_in_supply(cs.players[0])
    cs = _play_occupation(cs, 1, _FILLERS[0])          # p1's 2nd occupation
    assert _FIRE not in legal_actions(cs)
    cs = step(cs, Stop())
    cs = step(cs, Stop())
    assert stables_in_supply(cs.players[0]) == supply0_p0


def test_hand_only_is_inert():
    # Stallwright still in hand (not played): playing the 2nd occupation offers
    # nothing.
    cs = _card_state()
    cs = _edit_player(cs, 0, occupations=frozenset({"x0"}))
    cs = _give_hand_occ(cs, 0, "stallwright")          # in hand, NOT in tableau
    cs = _give_hand_occ(cs, 0, _FILLERS[0])
    cs = _play_occupation(cs, 0, _FILLERS[0])          # 2nd occupation
    assert _FIRE not in legal_actions(cs)
