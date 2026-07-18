import agricola.cards.furrows  # noqa: F401  (registers the card)
import agricola.cards.beanfield  # noqa: F401  (a veg-only card-field, for the card-field sow test)

"""Tests for Furrows (minor improvement, D3, traveling/passing).

Card text (verbatim): "You can immediately sow in exactly 1 field."
Cost: none. Passing (traveling — after the effect the card goes to the
opponent's hand).

An on-play OPTIONAL granted "Sow" action surfaced WIDE via the minor
play-variant seam (`register_play_minor_variant`): a zero-surcharge "sow"
variant offered only when a sow is possible now, and an always-present
zero-surcharge "skip". "sow" pushes `PendingSow(max_fields=1)` — "exactly 1
field" (grain + veg + cards_touched <= 1); `crops_only=False` per ruling 48
(a generic limited sow grant may target wood/stone card-fields, and reaches
crop card-fields). The card is passed to the opponent's hand at play, before
the sow resolves.
"""
from agricola.actions import CommitPlayMinor, CommitSow
from agricola.cards.card_fields import card_field_stacks, stacks_to_store
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_fields, with_pending_stack, with_resources

CARD_ID = "furrows"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _at_play_minor_frame(*, fields=(), grain=0, veg=0, wood=0, own_beanfield=False):
    """A CARDS state at a PendingPlayMinor with Furrows in the current player's
    hand, the given empty FIELD cells plowed, and the given supply. The opponent
    starts with an empty hand so a travel is unambiguous."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    if own_beanfield:
        p = fast_replace(p, minor_improvements=p.minor_improvements | {"beanfield"})
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    if fields:
        state = with_fields(state, cp, list(fields))
    state = with_resources(state, cp, grain=grain, veg=veg, wood=wood)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp,
                                 initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _variants_offered(state):
    return sorted(a.variant for a in legal_actions(state)
                  if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)


def _commit(state, variant):
    return next(a for a in legal_actions(state)
                if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()               # no cost
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.prereq is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.vps == 0                     # no printed VP
    assert spec.passing_left is True         # traveling minor
    assert CARD_ID in PLAY_MINOR_VARIANTS


# ---------------------------------------------------------------------------
# The wide variants: skip always; sow only when a sow is possible now
# ---------------------------------------------------------------------------

def test_both_variants_when_sowable():
    # An empty field + a grain in supply -> a sow is possible now.
    state, _cp = _at_play_minor_frame(fields=((0, 0),), grain=1)
    assert _variants_offered(state) == ["skip", "sow"]


def test_sow_absent_without_seed():
    # An empty field but no seed (no grain/veg) -> no sow possible -> skip only.
    state, _cp = _at_play_minor_frame(fields=((0, 0),))
    assert _variants_offered(state) == ["skip"]


def test_sow_absent_without_field():
    # A seed but no empty board field and no card-field -> no sow -> skip only.
    state, _cp = _at_play_minor_frame(grain=1)
    assert _variants_offered(state) == ["skip"]


# ---------------------------------------------------------------------------
# Playing "sow": exactly one field, and the cap forbids a 2-field commit
# ---------------------------------------------------------------------------

def test_sow_commits_exactly_one_field():
    # 2 empty fields + 2 grain in supply: without the cap a 2-field sow would be
    # legal; the max_fields=1 cap must forbid it.
    state, cp = _at_play_minor_frame(fields=((0, 0), (0, 1)), grain=2)
    out = step(state, _commit(state, "sow"))
    # on_play pushed the one-field-capped sow.
    top = out.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.max_fields == 1
    assert top.crops_only is False           # ruling 48: generic sow grant
    assert top.initiated_by_id == "card:furrows"
    # The card already traveled to the opponent before the sow.
    assert CARD_ID in out.players[1 - cp].hand_minors
    assert CARD_ID not in out.players[cp].minor_improvements

    sows = [a for a in legal_actions(out) if isinstance(a, CommitSow)]
    assert sows
    # Every offered sow plants exactly one field-unit (grain + veg == 1).
    assert all(a.grain + a.veg == 1 for a in sows)
    # A 2-field commit is NOT offered under the cap.
    assert CommitSow(grain=2, veg=0) not in sows
    assert CommitSow(grain=1, veg=1) not in sows
    # Commit the single sow: one field becomes 3 grain, one grain spent.
    sow1 = next(a for a in sows if a.grain == 1)
    resolved = step(out, sow1)
    grid = resolved.players[cp].farmyard.grid
    grain_fields = [grid[r][c] for r in range(3) for c in range(5)
                    if grid[r][c].grain == 3]
    assert len(grain_fields) == 1            # exactly one field sown
    assert resolved.players[cp].resources.grain == 1   # 2 - 1 sown


# ---------------------------------------------------------------------------
# Playing "skip": declines the sow, still passes the card
# ---------------------------------------------------------------------------

def test_skip_declines_and_still_passes():
    state, cp = _at_play_minor_frame(fields=((0, 0),), grain=1)
    out = step(state, _commit(state, "skip"))
    # No sow pushed, nothing sown, no grain spent.
    assert not any(isinstance(f, PendingSow) for f in out.pending_stack)
    grid = out.players[cp].farmyard.grid
    assert all(grid[r][c].grain == 0 for r in range(3) for c in range(5))
    assert out.players[cp].resources.grain == 1
    # Still a traveling card: it moved to the opponent's hand.
    assert CARD_ID in out.players[1 - cp].hand_minors
    assert CARD_ID not in out.players[cp].minor_improvements
    assert CARD_ID not in out.players[cp].hand_minors


# ---------------------------------------------------------------------------
# The card lands in the opponent's hand and is playable by them later
# ---------------------------------------------------------------------------

def test_travels_to_opponent_and_playable_by_them():
    state, cp = _at_play_minor_frame(fields=((0, 0),), grain=1)
    out = step(state, _commit(state, "skip"))
    opp = 1 - cp
    assert CARD_ID in out.players[opp].hand_minors
    # The opponent can now play it (no cost, no prereq): it appears among their
    # playable minors, and a real play-minor frame offers a CommitPlayMinor.
    assert CARD_ID in playable_minors(out, opp)
    opp_state = fast_replace(out, current_player=opp)
    opp_state = with_pending_stack(
        opp_state, (PendingPlayMinor(player_idx=opp,
                                     initiated_by_id="space:meeting_place_cards"),))
    variants = sorted(a.variant for a in legal_actions(opp_state)
                      if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)
    assert variants == ["skip"]              # opponent has no field/seed -> skip only


# ---------------------------------------------------------------------------
# Card-field sow under the grant (ruling 48 — a crop card-field is reachable)
# ---------------------------------------------------------------------------

def test_sow_onto_card_field_under_grant():
    # Own a Beanfield (veg-only card-field), a veg in supply, and NO board field:
    # a sow is possible only via the card-field, so "sow" is offered and the sow
    # enumerator surfaces the card sow.
    state, cp = _at_play_minor_frame(veg=1, own_beanfield=True)
    assert _variants_offered(state) == ["skip", "sow"]
    out = step(state, _commit(state, "sow"))
    assert isinstance(out.pending_stack[-1], PendingSow)
    sows = [a for a in legal_actions(out) if isinstance(a, CommitSow)]
    # The only sow bundle plants the beanfield (a card-field consumes one
    # field-unit of the cap).
    card_sow = next(a for a in sows if a.card_sows)
    assert card_sow.card_sows == (("beanfield", "veg"),)
    resolved = step(out, card_sow)
    (stack,) = card_field_stacks(resolved.players[cp], "beanfield")
    assert stack == (0, 2, 0, 0)             # 1 supply veg planted 2 on the card
    assert resolved.players[cp].resources.veg == 0
