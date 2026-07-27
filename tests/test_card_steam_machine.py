"""Tests for Steam Machine (minor improvement, C25; Consul Dirigens Expansion).

Card text: "Each work phase, if the last action space you use is an accumulation
space, you can immediately afterward take a 'Bake Bread' action."
Cost: 2 Wood. No prerequisite. VPs: 1. Not passing.

Shape: an OPTIONAL `after_action_space` FireTrigger that grants a Bake Bread action,
gated on BOTH (a) this being the player's LAST worker placement of the work phase
(`people_home == 0` at the after-phase) and (b) the space being a goods-accumulating
space — the 6 atomic building/food spaces (atomic-hosted via the card's hook) plus the
3 animal markets (non-atomic, self-hosting). `meeting_place` is in
`constants.ACCUMULATION_SPACES` but is EXCLUDED here: in the card game it gives no goods,
so it is not functioning as an accumulation space. Firing pushes the PendingBakeBread
primitive; declining is not firing (the host's Stop exits without baking).
"""
from __future__ import annotations

import agricola.cards.steam_machine  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitBake,
    CommitCardChoice,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.telegram import (
    TAKE as TELEGRAM_TAKE,
    _OPTIONS as TELEGRAM_OPTIONS,
)
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.cards.turn_offers import has_outstanding_offer
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingBakeBread, PendingCardChoice
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import (
    with_animals,
    with_majors,
    with_minors,
    with_people,
    with_resources,
)

CARD_ID = "steam_machine"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(seed=7, *, home0=1, can_bake=True):
    """A card-mode state where P0 owns Steam Machine, has `home0` workers at home
    (so home0 placements remain), and — when `can_bake` — owns a Fireplace + grain so
    `_can_bake_bread` is true. P1 is given 2 home workers so the work phase does not
    end when P0 places its last worker."""
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    s = with_minors(s, 0, frozenset({CARD_ID}))
    if can_bake:
        s = with_majors(s, owner_by_idx={0: 0})        # Fireplace (index 0)
        s = with_resources(s, 0, grain=2, wood=0, food=0)
    else:
        s = with_resources(s, 0, grain=0, wood=0, food=0)
    s = with_people(s, 0, total=2, home=home0)
    s = with_people(s, 1, total=2, home=2)
    return s, 0


def _reveal_empty(state, space_id, **extra):
    sp = fast_replace(get_space(state.board, space_id),
                      revealed=True, workers=(0, 0), **extra)
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _place_atomic_to_after(state, space_id):
    """Place P0 on an atomic accumulation space and Proceed past its pickup so its
    host frame is in the after-phase (where this trigger is surfaced)."""
    state = _reveal_empty(state, space_id)
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                     # pickup, flip to after-phase
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_steam_machine_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.prereq is None
    assert spec.vps == 1
    assert not spec.passing_left
    # Optional after_action_space trigger.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    # Hosts ONLY the 6 atomic accumulation spaces; the 3 markets self-host.
    expected_hooked = {
        "forest", "clay_pit", "reed_bank",
        "western_quarry", "eastern_quarry", "fishing",
    }
    for sp in expected_hooked:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(sp, set()), sp
    # Markets are NOT hooked (they self-host).
    for sp in ("sheep_market", "pig_market", "cattle_market"):
        assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get(sp, set()), sp
    # meeting_place is NOT hooked (no goods in the card game → not an accumulation space).
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("meeting_place", set())


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_offered_on_last_placement_atomic_accumulation():
    s, cp = _base_state(home0=1)               # this placement is the last (home -> 0)
    s = _place_atomic_to_after(s, "forest")
    assert s.players[cp].people_home == 0      # last placement signal
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_fire_grants_bake_bread():
    s, cp = _base_state(home0=1)
    s = _place_atomic_to_after(s, "forest")
    grain0 = s.players[cp].resources.grain
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The granted, optional Bake Bread primitive is now on the stack.
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    assert bakes
    s = step(s, bakes[-1])                      # bake all grain
    # Fireplace bakes grain at 2 food / grain.
    assert s.players[cp].resources.grain == 0
    assert s.players[cp].resources.food == grain0 * 2
    # The bake leaf flips to its after-phase (only Stop remains).
    assert legal_actions(s) == [Stop()]


def test_offered_on_market_last_placement():
    # The 3 animal markets are accumulation spaces too; they self-host (non-atomic)
    # and still surface the after_action_space trigger — no hook needed.
    from agricola.actions import CommitAccommodate

    s, cp = _base_state(home0=1)
    s = _reveal_empty(s, "sheep_market", accumulated_amount=2)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.pending_stack[-1].phase == "before"
    acc = [a for a in legal_actions(s) if isinstance(a, CommitAccommodate)]
    s = step(s, acc[0])                         # flip the market host to after-phase
    assert s.pending_stack[-1].phase == "after"
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_not_last_placement():
    # Two workers at home → after placing one, people_home == 1 (not the last).
    s, cp = _base_state(home0=2)
    s = _place_atomic_to_after(s, "forest")
    assert s.players[cp].people_home == 1
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert legal_actions(s) == [Stop()]        # the host exits with no bake granted


def test_not_offered_on_meeting_place():
    # meeting_place is in constants.ACCUMULATION_SPACES but gives no goods in the card
    # game, so it is NOT an accumulation space for Steam Machine.
    s, cp = _base_state(home0=1)
    s = _reveal_empty(s, "meeting_place")
    s = step(s, PlaceWorker(space="meeting_place"))
    s = step(s, Proceed())                      # become SP, decline minor, flip to after
    assert s.pending_stack[-1].phase == "after"
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_when_cannot_bake():
    # Last placement on an accumulation space, but no baker / no grain → the grant
    # would be a dead-end, so it is not offered.
    s, cp = _base_state(home0=1, can_bake=False)
    s = _place_atomic_to_after(s, "forest")
    assert s.players[cp].people_home == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_card():
    # Without owning the card, the atomic space is not hosted → resolves immediately,
    # no host frame, no trigger anywhere.
    s, cp = _base_state(home0=1)
    s = with_minors(s, cp, frozenset())         # un-own the card
    s = _reveal_empty(s, "forest")
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                   # resolved atomically


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _base_state(home0=1)
    food0 = s.players[cp].resources.food
    grain0 = s.players[cp].resources.grain
    s = _place_atomic_to_after(s, "forest")
    la = legal_actions(s)
    # Both firing AND declining (the host's Stop) are available — optionality lives at
    # the FireTrigger.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                          # decline → host exits, work done
    assert not s.pending_stack
    # No bread baked: grain/food unchanged (Forest gave wood only).
    assert s.players[cp].resources.grain == grain0
    assert s.players[cp].resources.food == food0


# ---------------------------------------------------------------------------
# Scoping — once per use, and not on a non-accumulation atomic space
# ---------------------------------------------------------------------------

def test_fires_once_per_use():
    s, cp = _base_state(home0=1)
    s = _place_atomic_to_after(s, "forest")
    s = step(s, FireTrigger(card_id=CARD_ID))
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    s = step(s, bakes[0])                        # bake
    s = step(s, Stop())                          # pop PendingBakeBread (after-phase)
    # Back at the Forest host's after-phase; already fired → not re-offered.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_on_non_accumulation_space():
    # grain_seeds is an atomic space but NOT an accumulation space → not hooked, so it
    # resolves atomically (no host) and never offers the trigger.
    s, cp = _base_state(home0=1)
    s = _reveal_empty(s, "grain_seeds")
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not s.pending_stack                   # not hosted → atomic resolution


# ---------------------------------------------------------------------------
# The last-use commitment (ruled, the Telegram-arc principle): firing asserts
# "this was my last use of the work phase", implicitly declining every optional
# loaner offer for the round — while never deleting the other order (decline the
# bake, take the loaner, fire on the loaner's own accumulation placement).
# ---------------------------------------------------------------------------

def _with_telegram_live(s):
    """P0 additionally owns Telegram with its loaner round == the current round and a
    meeple in supply — an offer that is outstanding-but-unanswerable while P0 still
    has a family worker at home (its predicate waits for people_home == 0)."""
    import agricola.cards.telegram  # noqa: F401  (registers the offer)
    p = s.players[0]
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {"telegram"},
                     card_state=p.card_state.set("telegram", s.round_number))
    s = fast_replace(s, players=(p, s.players[1]))
    return with_people(s, 0, total=2, home=1, supply=1)


def test_fire_forecloses_an_outstanding_telegram_offer():
    s, cp = _base_state(home0=1)
    s = _with_telegram_live(s)
    s = with_people(s, 1, total=2, home=0)       # opponent already fully placed
    s = _place_atomic_to_after(s, "forest")
    assert has_outstanding_offer(s, 0)           # the offer is live at the fire instant
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].last_use_committed
    assert not has_outstanding_offer(s, 0)       # implicitly declined for the round
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    s = step(s, bakes[0])
    s = step(s, Stop())                          # pop the bake leaf
    s = step(s, Stop())                          # pop the host — turn ends
    # No loaner turn is owed: the work phase ends with no PendingCardChoice, and the
    # returning-home reset clears the latch so it never outlives its round.
    assert s.phase is not Phase.WORK
    assert not any(isinstance(f, PendingCardChoice) for f in s.pending_stack)
    assert not s.players[0].last_use_committed


def test_declining_the_bake_keeps_the_telegram_offer_live():
    s, cp = _base_state(home0=1)
    s = _with_telegram_live(s)
    s = with_people(s, 1, total=2, home=0)
    s = _place_atomic_to_after(s, "forest")
    s = step(s, Stop())                          # decline the bake; turn ends
    # The boundary walk now owes P0 the loaner decision instead of ending the phase.
    assert s.phase is Phase.WORK
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.initiated_by_id == "card:telegram"


def test_decline_then_take_loaner_then_fire_on_the_loaner_placement():
    # The other order stays fully playable: decline the bake at the family worker's
    # placement, accept the loaner, and the loaner's own accumulation placement is now
    # the true last use — the bake is offered THERE (people_home routing makes the
    # accepted-loaner path exact; only unanswered offers need the latch).
    s, cp = _base_state(home0=1)
    s = _with_telegram_live(s)
    s = with_people(s, 1, total=2, home=0)
    s = _place_atomic_to_after(s, "forest")
    s = step(s, Stop())                          # decline the bake
    assert isinstance(s.pending_stack[-1], PendingCardChoice)
    s = step(s, CommitCardChoice(index=TELEGRAM_OPTIONS.index(TELEGRAM_TAKE)))
    assert s.players[0].people_home == 1         # the loaner waits at home
    s = _place_atomic_to_after(s, "clay_pit")    # place it — the phase's true last use
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingBakeBread)


def test_not_offered_once_a_last_use_is_already_committed():
    # The once-per-phase defense for relocation effects (Straw Hat's end-of-work move
    # creates a second people_home == 0 use): a committed last use makes any later
    # use's "last" claim false, so the bake cannot be offered twice.
    s, cp = _base_state(home0=1)
    p = s.players[0]
    s = fast_replace(s, players=(
        fast_replace(p, last_use_committed=True), s.players[1]))
    s = _place_atomic_to_after(s, "forest")
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def _with_delayed_wayfarer_live(s):
    """P0 additionally owns Delayed Wayfarer played THIS round, with a supply meeple.
    Its offer arises only at the all-players-placed boundary — later than the fire
    instant when the opponent still has a worker at home."""
    import agricola.cards.delayed_wayfarer  # noqa: F401  (registers the offer)
    p = s.players[0]
    p = fast_replace(p,
                     occupations=p.occupations | {"delayed_wayfarer"},
                     card_state=p.card_state.set("delayed_wayfarer", s.round_number))
    s = fast_replace(s, players=(p, s.players[1]))
    s = with_people(s, 0, total=2, home=1, supply=1)
    return with_people(s, 1, total=2, home=1)    # opponent still to place


def test_fire_forecloses_delayed_wayfarers_later_arising_offer():
    # The reason the fix is a latch and not a decline-what's-outstanding call: at the
    # fire instant Delayed Wayfarer's offer does not exist yet (the opponent has not
    # placed), so there is nothing to decline — the latch suppresses it when it would
    # arise at the boundary.
    s, cp = _base_state(home0=1)
    s = _with_delayed_wayfarer_live(s)
    s = _place_atomic_to_after(s, "forest")
    assert not has_outstanding_offer(s, 0)       # not yet: opponent still has a worker
    s = step(s, FireTrigger(card_id=CARD_ID))
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    s = step(s, bakes[0])
    s = step(s, Stop())
    s = step(s, Stop())                          # P0's turn ends
    s = step(s, PlaceWorker(space="day_laborer"))   # opponent's last placement
    # All placed: the boundary would now surface the offer — the latch suppresses it.
    assert s.phase is not Phase.WORK
    assert not any(isinstance(f, PendingCardChoice) for f in s.pending_stack)


def test_no_fire_leaves_delayed_wayfarer_offer_to_arise():
    s, cp = _base_state(home0=1)
    s = _with_delayed_wayfarer_live(s)
    s = _place_atomic_to_after(s, "forest")
    s = step(s, Stop())                          # decline the bake; P0's turn ends
    s = step(s, PlaceWorker(space="day_laborer"))   # opponent's last placement
    # The boundary now owes P0 the one-shot loaner decision.
    assert s.phase is Phase.WORK
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.initiated_by_id == "card:delayed_wayfarer"


# ---------------------------------------------------------------------------
# Sheep Inspector shares the last placement's after-window: its return creates
# a later placement (home workers must be placed), so a committed last use
# forecloses it — while returning FIRST blocks the bake via people_home. Both
# orders exist before the choice; each fire forecloses the other.
# ---------------------------------------------------------------------------

def _with_sheep_inspector_armed(s):
    """P0 additionally owns Sheep Inspector with its costs on hand (1 farm sheep,
    2 food) and one OTHER placed person (a day_laborer marker) as a return
    target — so the return trigger and the bake share the last placement's
    after-window."""
    import agricola.cards.sheep_inspector  # noqa: F401  (registers the card)
    p = s.players[0]
    s = fast_replace(s, players=(
        fast_replace(p, occupations=p.occupations | {"sheep_inspector"}),
        s.players[1]))
    s = with_animals(s, 0, sheep=1)
    s = with_resources(s, 0, grain=2, food=2)
    sp = fast_replace(get_space(s.board, "day_laborer"), workers=(1, 0))
    return fast_replace(s, board=with_space(s.board, "day_laborer", sp))


def test_fired_bake_forecloses_sheep_inspectors_same_window_return():
    s, cp = _base_state(home0=1)
    s = _with_sheep_inspector_armed(s)
    s = _place_atomic_to_after(s, "forest")
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert FireTrigger(card_id="sheep_inspector", variant="day_laborer") in la
    s = step(s, FireTrigger(card_id=CARD_ID))          # commit this use as last
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    s = step(s, bakes[0])
    s = step(s, Stop())                                # pop the bake leaf
    # Back at the forest after-window: the return is foreclosed — a returned
    # worker would have to be re-placed, contradicting the committed last use.
    assert not any(isinstance(a, FireTrigger) and a.card_id == "sheep_inspector"
                   for a in legal_actions(s))


def test_return_first_blocks_the_bake_by_people_home():
    s, cp = _base_state(home0=1)
    s = _with_sheep_inspector_armed(s)
    s = _place_atomic_to_after(s, "forest")
    s = step(s, FireTrigger(card_id="sheep_inspector", variant="day_laborer"))
    # The return came first: this placement is no longer the phase's last, so
    # the bake is correctly off the menu by the people_home gate alone.
    assert s.players[0].people_home == 1
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))
