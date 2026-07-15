"""Tests for Grain Depot (minor improvement, B65; Bubulcus): "If you paid
wood/clay/stone for this card, place 1 grain on each of the next 2/3/4 round spaces.
At the start of these rounds, you get the grain." Cost 2 Wood / 2 Clay / 2 Stone;
no prereq; no VP; not passing.

An `alt_costs` + `cost_labels` card (the Canvas Sack shape): the reward — how many of
the next round spaces get 1 grain — is COUPLED to which alternative cost was paid
(wood -> 2, clay -> 3, stone -> 4). Coverage: registration; the wide enumeration
(one CommitPlayMinor per affordable alternative, tagged with its label); that the
payment is the real alternative cost; and the label-coupled schedule length via a
REAL play of each alternative.
"""
import agricola.cards.grain_depot  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_round

CARD_ID = "grain_depot"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _grain_sched(state, idx):
    return [r.grain for r in state.players[idx].future_resources]


def _play_minor_state(res, round_number=1):
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = with_round(cs, round_number)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}), resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def _variants(state):
    return {a.variant for a in _commits(state)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.alt_costs == (Cost(resources=Resources(clay=2)),
                              Cost(resources=Resources(stone=2)))
    assert spec.cost_labels == ("wood", "clay", "stone")
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is None


# ---------------------------------------------------------------------------
# Wide enumeration: one play per affordable alternative, tagged with the label
# ---------------------------------------------------------------------------

def test_all_three_alternatives_offered_wide():
    cs, _cp = _play_minor_state(Resources(wood=2, clay=2, stone=2))
    assert _variants(cs) == {"wood", "clay", "stone"}


def test_only_affordable_alternatives_offered():
    cs, _cp = _play_minor_state(Resources(clay=2, stone=2))   # no wood
    assert _variants(cs) == {"clay", "stone"}


def test_payment_is_the_real_alternative_cost():
    cs, _cp = _play_minor_state(Resources(wood=2, clay=2, stone=2))
    by_variant = {c.variant: c.payment for c in _commits(cs)}
    assert by_variant["wood"] == Resources(wood=2)
    assert by_variant["clay"] == Resources(clay=2)
    assert by_variant["stone"] == Resources(stone=2)


# ---------------------------------------------------------------------------
# The coupled reward: wood -> 2, clay -> 3, stone -> 4 next round spaces
# ---------------------------------------------------------------------------

def _play_variant_and_check(variant, res_field, n):
    R = 1
    cs, cp = _play_minor_state(Resources(**{res_field: 2}), round_number=R)
    before = _grain_sched(cs, cp)
    commit = next(c for c in _commits(cs) if c.variant == variant)
    out = step(cs, commit)
    g = _grain_sched(out, cp)
    # Rounds R+1..R+n each gain 1 grain (round M -> slot M-1); round R+n+1 does NOT.
    for rnd in range(R + 1, R + 1 + n):
        assert g[rnd - 1] == before[rnd - 1] + 1
    assert g[(R + n + 1) - 1] == before[(R + n + 1) - 1]
    assert CARD_ID in out.players[cp].minor_improvements
    return out, cp


def test_paying_wood_schedules_next_2():
    _play_variant_and_check("wood", "wood", 2)


def test_paying_clay_schedules_next_3():
    _play_variant_and_check("clay", "clay", 3)


def test_paying_stone_schedules_next_4():
    _play_variant_and_check("stone", "stone", 4)


# ---------------------------------------------------------------------------
# The scheduled grain is actually collected at the target round's start
# ---------------------------------------------------------------------------

def test_grain_collected_at_next_round_start():
    from agricola.constants import Phase
    from agricola.engine import _complete_preparation

    cs, cp = _play_minor_state(Resources(clay=2), round_number=1)   # clay -> next 3
    commit = next(c for c in _commits(cs) if c.variant == "clay")
    s = step(cs, commit)
    assert _grain_sched(s, cp)[1] == 1   # round-2 slot scheduled

    grain_before = s.players[cp].resources.grain
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    s = _complete_preparation(s)
    assert s.round_number == 2
    assert s.players[cp].resources.grain == grain_before + 1
    assert _grain_sched(s, cp)[1] == 0
