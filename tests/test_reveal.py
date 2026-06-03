"""Tests for the hidden-information refactor: round-card reveals as nature
steps, the Environment dealer, evaluator averaging, and MCTS chance nodes.
See HIDDEN_INFO_DESIGN.md.
"""
import dataclasses

import pytest

from agricola.actions import RevealCard
from agricola.agents.base import decider_of
from agricola.agents.heuristic import HubrisHeuristicV3, _basic_wish_revealed_round
from agricola.agents.mcts import MCTSAgent, MCTSSearch
from agricola.constants import STAGE_CARDS, Phase, stage_of_round
from agricola.engine import _advance_until_decision, _count_revealed_stage_cards, step
from agricola.legality import legal_actions
from agricola.pending import PendingReveal
from agricola.setup import setup, setup_env
from agricola.state import get_space
from tests.factories import with_people, with_space
from tests.test_utils import filter_implemented


def _reveal_node(seed=0):
    """A round-2 reveal nature node: round-1 WORK with both players out of
    workers, advanced to the round boundary (parks at the reveal)."""
    state = setup(seed=seed)
    state = with_people(state, 0, home=0)
    state = with_people(state, 1, home=0)
    rev = _advance_until_decision(state)
    assert decider_of(rev) is None and isinstance(rev.pending_stack[-1], PendingReveal)
    return rev


# --------------------------------------------------------------------------
# Setup / round-1 pre-deal
# --------------------------------------------------------------------------

def test_setup_env_returns_round1_work():
    state, env = setup_env(seed=0)
    assert state.phase == Phase.WORK
    assert state.round_number == 1
    assert state.current_player == state.starting_player
    assert _count_revealed_stage_cards(state) == 1   # round-1 card dealt
    assert len(env.round_card_order) == 14


def test_setup_is_setup_env_state():
    assert setup(seed=5) == setup_env(seed=5)[0]


def test_round1_accumulation_filled():
    """The round-1 reveal's _complete_preparation loads round-1 goods —
    permanents AND a round-1 accumulation stage card (the old bug)."""
    state, _ = setup_env(seed=0)
    assert get_space(state.board, "forest").accumulated.wood == 3   # permanent, 1 round
    # Whatever stage card was dealt at round 1: if it's an accumulation space it
    # has its round-1 goods, not 0.
    for cards in STAGE_CARDS.values():
        for sid in cards:
            sp = get_space(state.board, sid)
            if sp.revealed and sid == "sheep_market":
                assert sp.accumulated_amount == 1


# --------------------------------------------------------------------------
# count == round_number invariant + stage_of_round
# --------------------------------------------------------------------------

def test_count_invariant_holds_at_every_work_state():
    state, env = setup_env(seed=3)
    n_work = 0
    while state.phase != Phase.BEFORE_SCORING:
        if state.phase == Phase.WORK:
            n_work += 1
            assert _count_revealed_stage_cards(state) == state.round_number
        d = decider_of(state)
        action = env.resolve(state) if d is None else legal_actions(state)[0]
        state = step(state, action)
    assert n_work > 10


def test_stage_of_round():
    assert [stage_of_round(r) for r in range(1, 15)] == \
        [1, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 5, 6]


# --------------------------------------------------------------------------
# The dealer / enumerator
# --------------------------------------------------------------------------

def test_dealer_card_always_a_candidate():
    """env.reveal_action always returns one of the enumerator's candidates."""
    state, env = setup_env(seed=7)
    while state.phase != Phase.BEFORE_SCORING:
        if decider_of(state) is None:
            candidates = legal_actions(state)
            assert env.resolve(state) in candidates
            assert all(isinstance(c, RevealCard) for c in candidates)
        d = decider_of(state)
        action = env.resolve(state) if d is None else legal_actions(state)[0]
        state = step(state, action)


def test_reveal_candidates_are_unrevealed_current_stage_cards():
    rev = _reveal_node(seed=0)            # entering round 2
    cards = {a.card for a in legal_actions(rev)}
    expected = {c for c in STAGE_CARDS[1] if not get_space(rev.board, c).revealed}
    assert cards == expected
    assert len(cards) == 3               # round 2 reveal: 3 stage-1 cards left


# --------------------------------------------------------------------------
# Memorylessness / DAG recombination
# --------------------------------------------------------------------------

def test_same_revealed_set_recombines_regardless_of_order():
    base = setup(seed=0)
    a = with_space(with_space(base, "fencing", revealed=True),
                   "grain_utilization", revealed=True)
    b = with_space(with_space(base, "grain_utilization", revealed=True),
                   "fencing", revealed=True)
    assert a == b
    assert hash(a) == hash(b)


# --------------------------------------------------------------------------
# Heuristic de-cheat
# --------------------------------------------------------------------------

def test_basic_wish_expected_round():
    s = setup(seed=0)                    # round 1, basic_wish (stage 2) unrevealed
    assert not get_space(s.board, "basic_wish_for_children").revealed
    assert _basic_wish_revealed_round(s) == 6.0
    assert _basic_wish_revealed_round(dataclasses.replace(s, round_number=5)) == 6.5
    assert _basic_wish_revealed_round(dataclasses.replace(s, round_number=6)) == 7.0
    s6 = with_space(dataclasses.replace(s, round_number=6),
                    "basic_wish_for_children", revealed=True)
    assert _basic_wish_revealed_round(s6) == 6   # revealed → current round


# --------------------------------------------------------------------------
# Evaluator averaging over reveal outcomes
# --------------------------------------------------------------------------

def test_eval_averages_over_reveal_outcomes():
    agent = HubrisHeuristicV3(seed=0, lookahead="action")
    rev = _reveal_node(seed=0)
    got = agent._eval(rev, 0)
    outs = filter_implemented(agent.legal_actions_fn(rev))
    assert len(outs) >= 2
    expected = sum(agent._eval(step(rev, a), 0) for a in outs) / len(outs)
    assert got == pytest.approx(expected)


# --------------------------------------------------------------------------
# MCTS chance nodes
# --------------------------------------------------------------------------

def test_mcts_reveal_node_is_chance_node():
    search = MCTSSearch(rng_seed=0)
    node = search.find_or_create_node(_reveal_node(seed=0))
    assert node.is_chance
    assert node.decider == 0             # P0 value-frame label, not a real player


def test_chance_route_round_robin_covers_all_outcomes():
    search = MCTSSearch(rng_seed=0)
    agent = MCTSAgent(search, sims_per_move=1, rng_seed=0)
    node = search.find_or_create_node(_reveal_node(seed=0))
    node._compute_legal_actions()
    k = len(node._legal_actions)
    routed = [agent._chance_route(node) for _ in range(k)]
    assert set(routed) == set(node._legal_actions)        # first k routes cover all
    assert sum(node.chance_counts.values()) == k


def test_mcts_no_leak_independent_of_hidden_order():
    """No-leak: the MCTS search/agent take NO Environment — they branch on reveal
    candidates derived purely from public state (the enumerator). So a decision is
    a function of (public state, seed) only; the hidden future order cannot reach
    the search. We exercise it by driving the same real game under two DIFFERENT
    hidden futures that agree on round 1, and checking P0's round-1 MCTS decisions
    are identical (they search across the round-1→2 boundary internally)."""
    from agricola.environment import Environment

    _s, env_a = setup_env(seed=0)
    o = env_a.round_card_order
    # A different hidden future that still deals the same round-1 card (o[0]) and
    # keeps each stage's cards within their stage (reverse within stage segments).
    o_b = (o[:1] + o[1:4][::-1] + o[4:7][::-1] + o[7:9][::-1]
           + o[9:11][::-1] + o[11:13][::-1] + o[13:14])
    env_b = Environment(round_card_order=tuple(o_b))
    assert o_b[0] == o[0] and tuple(o_b) != o   # same round 1, different future

    def p0_round1_actions(dealer):
        state, _ = setup_env(seed=0)            # identical public round-1 start
        p0 = MCTSAgent(MCTSSearch(rng_seed=0), sims_per_move=12, rng_seed=0)
        p1 = HubrisHeuristicV3(seed=1)
        acts = []
        while state.phase != Phase.BEFORE_SCORING and state.round_number == 1:
            d = decider_of(state)
            if d is None:
                action = dealer(state)
            else:
                action = (p0, p1)[d](state)
                if d == 0:
                    acts.append(action)
            state = step(state, action)
        return acts

    assert p0_round1_actions(env_a.resolve) == p0_round1_actions(env_b.resolve)


def test_mcts_creates_chance_node_when_search_crosses_boundary():
    state = setup(seed=0)
    state = with_people(state, 0, total=2, home=1)        # 1 worker each → round
    state = with_people(state, 1, total=2, home=1)        # ends after 2 placements
    search = MCTSSearch(rng_seed=0)
    agent = MCTSAgent(search, sims_per_move=40, rng_seed=0)
    agent(state)
    chance_nodes = [n for n in search.transpositions.values() if n.is_chance]
    assert chance_nodes, "search did not create a chance node across the boundary"
    # A chance node's children are post-reveal decision nodes — never a chance node.
    for cn in chance_nodes:
        for child in cn.children.values():
            assert not child.is_chance
