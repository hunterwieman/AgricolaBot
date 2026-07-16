"""Tests for Pig Breeder (occupation, A165; Artifex Expansion; players 4+).

Card text: "When you play this card, you immediately get 1 wild boar. Your wild
boar breed at the end of round 12 (if there is room for the new wild boar)."

The round-12 breed is a real make-room decision, offered WIDE: a boar-only
breeding frontier (analogous to `helpers.breeding_frontier`) surfaced as one
FireTrigger per config via `register_play_variant_trigger` on `end_of_round`.
These tests exercise the frontier directly (its correctness is the risk) plus the
registration/wiring and the guards.
"""
import agricola.cards.pig_breeder  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.pig_breeder import CARD_ID, _frontier, _legal_variants, _apply, _on_play
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, Farmyard
from tests.factories import with_majors, with_pending_stack

_POOL = CardPool(occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
                 minors=tuple(f"m{i}" for i in range(20)))
_H = tuple(tuple([False] * 5) for _ in range(4))
_V = tuple(tuple([False] * 6) for _ in range(3))
_COOKING_HEARTH = 2   # major index; rates sheep->2, boar->3, cattle->4


def _farm(pastures=(), stable_cells=()):
    grid = [[Cell(cell_type=CellType.EMPTY) for _ in range(5)] for _ in range(3)]
    for (r, c) in stable_cells:
        grid[r][c] = Cell(cell_type=CellType.STABLE)
    return Farmyard(grid=tuple(tuple(row) for row in grid),
                    horizontal_fences=_H, vertical_fences=_V, pastures=pastures)


def _state(*, pastures=(), stable_cells=(), animals=Animals(), cooker=False,
           round_number=12, own=True):
    cs, _ = setup_env(5, card_pool=_POOL)
    p = fast_replace(cs.players[0], farmyard=_farm(pastures, stable_cells),
                     animals=animals, resources=Resources(),   # clear setup food
                     occupations=frozenset({CARD_ID}) if own else frozenset())
    cs = fast_replace(cs, round_number=round_number, players=(p, cs.players[1]))
    if cooker:
        cs = with_majors(cs, owner_by_idx={_COOKING_HEARTH: 0})   # Cooking Hearth -> player 0
    return cs


# --- registration -----------------------------------------------------------

def test_registered_wide_on_end_of_round():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_VARIANT_TRIGGERS                       # surfaced wide
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("end_of_round", ()))


def test_on_play_grants_one_boar():
    cs = _state(animals=Animals(boar=1))
    out = _on_play(cs, 0)
    assert out.players[0].animals.boar == 2


# --- guards -----------------------------------------------------------------

def test_no_breed_below_two_boar():
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                animals=Animals(boar=1))
    assert _frontier(cs, 0) == []
    assert _legal_variants(cs, 0) == []


def test_not_offered_off_round_12():
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                animals=Animals(boar=2), round_number=11)
    assert _legal_variants(cs, 0) == []          # frontier gated to round 12


# --- the frontier ------------------------------------------------------------

def test_simple_fit_one_config():
    # 1x1 boar pasture (cap 2) + house flex 1 = 3 boar capacity; 2 boar -> breed to 3.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                animals=Animals(boar=2))
    fr = _frontier(cs, 0)
    assert fr == [(Animals(sheep=0, boar=3, cattle=0), 0)]
    out = _apply(cs, 0, "0")
    assert out.players[0].animals == Animals(boar=3)


def test_needs_room_single_removal_cooks_for_food():
    # boar pasture full (2 boar) + house flex holding 1 sheep; the 3rd boar needs the
    # flex slot, so the sheep must go. With a Cooking Hearth the removed sheep -> 2 food.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                animals=Animals(sheep=1, boar=2), cooker=True)
    fr = _frontier(cs, 0)
    assert fr == [(Animals(sheep=0, boar=3, cattle=0), 2)]   # sheep cooked -> 2 food
    out = _apply(cs, 0, "0")
    assert out.players[0].animals == Animals(boar=3)
    assert out.players[0].resources.food == 2


def test_wide_two_removal_choices_no_gratuitous_cook():
    # boar pasture (2 boar) + 2 flex slots (house pet + 1 standalone stable) holding
    # 1 sheep + 1 cattle. The 3rd boar needs a flex slot -> remove EITHER the sheep OR
    # the cattle (two Pareto-incomparable configs, offered WIDE). Removing BOTH is
    # dominated and must NOT appear.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                stable_cells=((2, 4),),
                animals=Animals(sheep=1, boar=2, cattle=1), cooker=True)
    fr = _frontier(cs, 0)
    assert len(fr) == 2                                        # wide
    assert _legal_variants(cs, 0) == ["0", "1"]
    # sorted by (sheep, cattle): keep-cattle (cook sheep->2 food) then keep-sheep (cook cattle->4)
    assert fr[0] == (Animals(sheep=0, boar=3, cattle=1), 2)
    assert fr[1] == (Animals(sheep=1, boar=3, cattle=0), 4)
    # firing variant 1 keeps the sheep, cooks the cattle for 4 food
    out = _apply(cs, 0, "1")
    assert out.players[0].animals == Animals(sheep=1, boar=3, cattle=0)
    assert out.players[0].resources.food == 4


def test_cook_a_boar_to_make_room_free_food():
    # 3 boar, capacity exactly 3 (1x1 boar pasture cap 2 + house flex 1). Keeping all
    # 4 is infeasible, so the only breed is to cook 1 boar (-> 2 parents) and breed
    # back to 3: same boar count, FREE food. (The bF==b+1 model wrongly returned [].)
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                animals=Animals(boar=3), cooker=True)
    fr = _frontier(cs, 0)
    assert fr == [(Animals(boar=3), 3)]          # cook 1 boar -> 3 food (Cooking Hearth boar rate)
    out = _apply(cs, 0, "0")
    assert out.players[0].animals == Animals(boar=3)
    assert out.players[0].resources.food == 3


def test_three_branches_capped_at_three():
    # 3 boar (1x1 pasture cap 2 + 1 flex) + 1 sheep + 1 cattle, flex=3 (house pet + 2
    # standalone stables). Keeping all 4 boar plus both others won't fit; the boar slot
    # is freed by reducing exactly ONE type -> exactly three Pareto branches.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                stable_cells=((2, 3), (2, 4)),
                animals=Animals(sheep=1, boar=3, cattle=1), cooker=True)
    fr = _frontier(cs, 0)
    assert len(fr) == 3                           # capped at three: one branch per type
    assert fr == [
        (Animals(sheep=0, boar=4, cattle=1), 2),  # remove the sheep (cook -> 2 food)
        (Animals(sheep=1, boar=3, cattle=1), 3),  # cook a boar, keep both others (free food)
        (Animals(sheep=1, boar=4, cattle=0), 4),  # remove the cattle (cook -> 4 food)
    ]


def test_cook_a_boar_dropped_without_cooker():
    # Same three-branch geometry but NO cooking improvement: the cook-a-boar config
    # (1,3,1) would leave the animals unchanged at 0 food = identical to declining, so
    # it is dropped (Proceed covers it). Only the two real trades (a boar for a sheep
    # or a cattle) remain.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                stable_cells=((2, 3), (2, 4)),
                animals=Animals(sheep=1, boar=3, cattle=1), cooker=False)
    fr = _frontier(cs, 0)
    assert fr == [
        (Animals(sheep=0, boar=4, cattle=1), 0),  # remove the sheep (released, 0 food)
        (Animals(sheep=1, boar=4, cattle=0), 0),  # remove the cattle (released, 0 food)
    ]                                              # cook-a-boar (1,3,1) dropped


def test_not_offered_when_only_breed_makes_no_food():
    # 3 boar, capacity exactly 3, NO cooker: the only breed is cook-a-boar with 0 food
    # (identical to declining) -> dropped -> nothing to offer -> card not hosted.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                animals=Animals(boar=3), cooker=False)
    assert _frontier(cs, 0) == []
    assert _legal_variants(cs, 0) == []


def _at_end_of_round_window(cs, idx=0):
    return with_pending_stack(cs, (PendingHarvestWindow(
        window_id="end_of_round", player_idx=idx),))


def test_offered_wide_with_proceed_at_the_window():
    # At the end_of_round window the three configs are offered wide (one FireTrigger
    # each) alongside Proceed, which implicitly declines the breed.
    cs = _state(pastures=(Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),),
                stable_cells=((2, 3), (2, 4)),
                animals=Animals(sheep=1, boar=3, cattle=1), cooker=True)
    cs = _at_end_of_round_window(cs, 0)
    la = legal_actions(cs)
    fires = [a for a in la if isinstance(a, FireTrigger) and a.card_id == CARD_ID]
    assert {a.variant for a in fires} == {"0", "1", "2"}   # wide: one per config
    assert Proceed() in la                                  # decline
    # Firing option "0" removes the sheep -> (0,4,1) + 2 food.
    out = step(cs, FireTrigger(card_id=CARD_ID, variant="0"))
    assert out.players[0].animals == Animals(sheep=0, boar=4, cattle=1)
    assert out.players[0].resources.food == 2
    # Proceed declines: animals unchanged, no food, no boar bred.
    out2 = step(cs, Proceed())
    assert out2.players[0].animals == Animals(sheep=1, boar=3, cattle=1)
    assert out2.players[0].resources.food == 0
