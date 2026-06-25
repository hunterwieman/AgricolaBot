"""Tests for the step-3 firing infrastructure (CARD_IMPLEMENTATION_PLAN.md):

- II.1 — the automatic-effect registry (`register_auto` / `apply_auto_effects`
  / `AUTO_EFFECTS` / `_owns`): mandatory, choice-free effects applied directly
  at a hook (no FireTrigger surfaced).
- II.3 — the scoped used-set fields on PlayerState (`used_this_turn` /
  `used_this_round` / `fired_once`) and `engine._clear`, plus the canonical
  serialization (default-skip keeps the Family JSON byte-identical).

This is inert infrastructure until the hooks (a later build step) call it, so the
tests exercise the pieces directly rather than through gameplay.
"""
import pytest

from agricola.agents.base import RandomAgent, play_game
from agricola.canonical import dumps, loads
from agricola.cards import triggers
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    AutoEntry,
    apply_auto_effects,
    register_auto,
    _owns,
)
from agricola.engine import _advance_current_player, _clear, _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup, setup_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_player(state, idx, **fields):
    p = fast_replace(state.players[idx], **fields)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _own_occupation(state, idx, card_id):
    return _set_player(state, idx,
                       occupations=state.players[idx].occupations | {card_id})


@pytest.fixture
def clean_auto_effects():
    """Snapshot/restore AUTO_EFFECTS so a test's registrations don't leak."""
    saved = {ev: list(entries) for ev, entries in AUTO_EFFECTS.items()}
    try:
        yield
    finally:
        AUTO_EFFECTS.clear()
        AUTO_EFFECTS.update(saved)


def _add_food(card_id, amount, *, any_player=False):
    """An auto-effect that adds `amount` food to its owner; eligible iff played."""
    def apply(state, idx):
        p = state.players[idx]
        return _set_player(state, idx, resources=p.resources + Resources(food=amount))
    register_auto("test_event", card_id, lambda s, i: True, apply,
                  any_player=any_player)


# ---------------------------------------------------------------------------
# II.1 — _owns
# ---------------------------------------------------------------------------

def test_owns_checks_played_not_hand():
    s = setup(0)
    s = _set_player(s, 0,
                    occupations=frozenset({"occ_played"}),
                    minor_improvements=frozenset({"minor_played"}),
                    hand_occupations=frozenset({"occ_hand"}),
                    hand_minors=frozenset({"minor_hand"}))
    p = s.players[0]
    assert _owns(p, "occ_played")
    assert _owns(p, "minor_played")
    assert not _owns(p, "occ_hand")      # a HAND card cannot fire
    assert not _owns(p, "minor_hand")
    assert not _owns(p, "never_seen")


# ---------------------------------------------------------------------------
# II.1 — register_auto / AUTO_EFFECTS
# ---------------------------------------------------------------------------

def test_register_auto_populates_registry(clean_auto_effects):
    _add_food("c", 1)
    entries = AUTO_EFFECTS["test_event"]
    assert len(entries) == 1
    assert isinstance(entries[0], AutoEntry)
    assert entries[0].card_id == "c"
    assert entries[0].any_player is False


def test_auto_effects_no_op_on_unregistered_event():
    s = setup(0)
    # An event with no registrations (the Family fast path) returns state itself.
    assert apply_auto_effects(s, "no_such_event", 0) is s


# ---------------------------------------------------------------------------
# II.1 — apply_auto_effects: own-action firing
# ---------------------------------------------------------------------------

def test_apply_auto_effects_fires_for_owner(clean_auto_effects):
    _add_food("c", 2)
    s = setup(0)
    base = s.players[0].resources.food
    s = _own_occupation(s, 0, "c")
    out = apply_auto_effects(s, "test_event", 0)
    assert out.players[0].resources.food == base + 2


def test_apply_auto_effects_skips_non_owner(clean_auto_effects):
    _add_food("c", 2)
    s = setup(0)
    # Player 0 does NOT own the card -> nothing fires (state unchanged).
    out = apply_auto_effects(s, "test_event", 0)
    assert out is s


def test_apply_auto_effects_respects_eligibility(clean_auto_effects):
    def apply(state, idx):
        return _set_player(state, idx,
                           resources=state.players[idx].resources + Resources(food=5))
    register_auto("test_event", "c", lambda s, i: False, apply)  # never eligible
    s = _own_occupation(setup(0), 0, "c")
    out = apply_auto_effects(s, "test_event", 0)
    assert out is s


def test_apply_auto_effects_own_action_only_acting_player(clean_auto_effects):
    _add_food("c", 1, any_player=False)
    s = setup(0)
    s = _own_occupation(s, 0, "c")
    s = _own_occupation(s, 1, "c")
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food
    out = apply_auto_effects(s, "test_event", 0)   # acting player is 0
    assert out.players[0].resources.food == f0 + 1
    assert out.players[1].resources.food == f1      # the non-acting owner does NOT fire


# ---------------------------------------------------------------------------
# II.1 — apply_auto_effects: any_player firing (Milk Jug shape)
# ---------------------------------------------------------------------------

def test_apply_auto_effects_any_player_fires_for_each_owner(clean_auto_effects):
    _add_food("c", 1, any_player=True)
    s = setup(0)
    s = _own_occupation(s, 1, "c")     # only player 1 owns it
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food
    out = apply_auto_effects(s, "test_event", 0)   # player 0 is acting
    # Fires for the OWNER (player 1) even though player 0 is acting.
    assert out.players[1].resources.food == f1 + 1
    assert out.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# II.3 — _clear
# ---------------------------------------------------------------------------

def test_clear_empties_both_players():
    s = setup(0)
    s = _set_player(s, 0, used_this_turn=frozenset({"a"}))
    s = _set_player(s, 1, used_this_turn=frozenset({"b"}))
    out = _clear(s, "used_this_turn")
    assert out.players[0].used_this_turn == frozenset()
    assert out.players[1].used_this_turn == frozenset()


def test_clear_is_noop_when_empty():
    s = setup(0)
    # Family state: all used-sets empty -> _clear returns the SAME object (no churn).
    assert _clear(s, "used_this_turn") is s
    assert _clear(s, "used_this_round") is s
    assert _clear(s, "fired_once") is s


def test_clear_only_targets_named_field():
    s = setup(0)
    s = _set_player(s, 0, used_this_turn=frozenset({"a"}),
                    used_this_round=frozenset({"r"}))
    out = _clear(s, "used_this_turn")
    assert out.players[0].used_this_turn == frozenset()
    assert out.players[0].used_this_round == frozenset({"r"})   # untouched


# ---------------------------------------------------------------------------
# II.3 — wiring: turn boundary clears used_this_turn but not used_this_round
# ---------------------------------------------------------------------------

def test_advance_current_player_clears_per_turn_set():
    s = setup(0)
    s = _set_player(s, s.current_player,
                    used_this_turn=frozenset({"x"}),
                    used_this_round=frozenset({"y"}),
                    fired_once=frozenset({"z"}))
    out = _advance_current_player(s)
    for i in (0, 1):
        assert out.players[i].used_this_turn == frozenset()       # cleared at the turn boundary
    # per-round and per-game latches survive a turn boundary
    assert out.players[s.current_player].used_this_round == frozenset({"y"})
    assert out.players[s.current_player].fired_once == frozenset({"z"})


def test_complete_preparation_clears_per_round_and_per_turn():
    s = setup(0)
    s = _set_player(s, 0, used_this_round=frozenset({"r"}),
                    used_this_turn=frozenset({"t"}),
                    fired_once=frozenset({"g"}))
    out = _complete_preparation(s)
    for i in (0, 1):
        assert out.players[i].used_this_round == frozenset()
        assert out.players[i].used_this_turn == frozenset()
    assert out.players[0].fired_once == frozenset({"g"})           # per-game latch survives


# ---------------------------------------------------------------------------
# II.3 — canonical serialization (default-skip keeps Family JSON byte-identical)
# ---------------------------------------------------------------------------

def test_canonical_omits_empty_used_sets():
    s = setup(0)
    blob = dumps(s)
    for name in ("used_this_turn", "used_this_round", "fired_once"):
        assert name not in blob   # default-skipped -> Family JSON unchanged


def test_canonical_emits_and_roundtrips_nonempty_used_sets():
    s = setup(0)
    s = _set_player(s, 0, used_this_turn=frozenset({"abc"}))
    blob = dumps(s)
    assert "used_this_turn" in blob
    assert "abc" in blob
    restored = loads(blob)
    assert restored.players[0].used_this_turn == frozenset({"abc"})
    assert restored.players[0].used_this_round == frozenset()   # omitted -> default


def test_family_game_used_sets_stay_empty_to_terminal():
    s, env = setup_env(7)
    final, _ = play_game(s, (RandomAgent(seed=1), RandomAgent(seed=2)),
                         dealer=env.resolve)
    for i in (0, 1):
        assert final.players[i].used_this_turn == frozenset()
        assert final.players[i].used_this_round == frozenset()
        assert final.players[i].fired_once == frozenset()
