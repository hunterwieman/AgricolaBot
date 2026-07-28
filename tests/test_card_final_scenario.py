"""Final Scenario (B23) — the owner uses the still-unrevealed Farm
Redevelopment space (the banked use-while-unrevealed design: nothing is
mutated, the round-14 reveal is ordinary, the grant scopes to the owner and
composes with the space's own carryability + occupancy)."""
from __future__ import annotations

import agricola.cards  # noqa: F401

from agricola.actions import ChooseSubAction, CommitRenovate, PlaceWorker
from agricola.cards.worker_moves import relocation_destinations
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_house, with_resources, \
    with_space

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))
CARD_ID = "final_scenario"


def _edit(state, idx, **ch):
    p = fast_replace(state.players[idx], **ch)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fs_state(owner=0):
    s, _env = setup_env(11, card_pool=POOL)
    s = with_current_player(s, 0)
    for i in (0, 1):
        s = _edit(s, i, hand_occupations=frozenset(), hand_minors=frozenset())
        s = with_resources(s, i, reed=1, clay=2)       # both could renovate
    p = s.players[owner]
    return _edit(s, owner, minor_improvements=p.minor_improvements | {CARD_ID})


def _fr_placements(state):
    return [a for a in legal_actions(state)
            if isinstance(a, PlaceWorker) and a.space == "farm_redevelopment"]


def test_owner_may_use_the_unrevealed_space_and_nobody_else():
    s = _fs_state(owner=0)
    assert not get_space(s.board, "farm_redevelopment").revealed
    assert _fr_placements(s)                           # the owner: widened
    assert _fr_placements(with_current_player(s, 1)) == []   # the opponent: not
    s2 = _fs_state(owner=1)                            # unowned by the current
    assert _fr_placements(s2) == []


def test_carryability_still_gates():
    s = with_house(_fs_state(), 0, HouseMaterial.STONE)
    assert _fr_placements(s) == []                     # nothing to renovate


def test_the_use_is_the_ordinary_farm_redevelopment_action():
    s = _fs_state()
    s = step(s, _fr_placements(s)[0])
    assert not get_space(s.board, "farm_redevelopment").revealed   # untouched
    s = step(s, ChooseSubAction(name="renovate"))
    commits = [a for a in legal_actions(s) if isinstance(a, CommitRenovate)]
    s = step(s, commits[0])
    assert s.players[0].house_material == HouseMaterial.CLAY
    assert get_space(s.board, "farm_redevelopment").workers[0] == 1


def test_occupied_blocks_even_the_owner():
    s = with_space(_fs_state(), "farm_redevelopment", workers=(1, 0))
    assert _fr_placements(s) == []


def test_relocation_destinations_include_it_for_the_owner_only():
    s = _fs_state(owner=0)
    assert "farm_redevelopment" in relocation_destinations(s, 0)
    assert "farm_redevelopment" not in relocation_destinations(s, 1)


def test_after_the_ordinary_reveal_both_players_use_it():
    s = _fs_state(owner=0)
    sp = get_space(s.board, "farm_redevelopment")
    s = with_space(s, "farm_redevelopment", revealed=True)
    assert _fr_placements(s)
    assert _fr_placements(with_current_player(s, 1))   # normal space now
    del sp
