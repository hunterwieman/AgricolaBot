"""Tests for Plant Fertilizer (minor C8, Corbarius Expansion; traveling).

Card text: "In each field with exactly 1 good, you can immediately place 1
additional good of the same type." Cost: none. Prerequisite: none. VPs: 0.
TRAVELING (passing) card.

Effect = automatic on-play one-shot. THE THRESHOLD is "exactly 1 good": a FIELD
holding grain == 1 (xor) veg == 1 → that crop goes to 2; everything else (empty,
>1 token, freshly sown 3-grain / 2-veg, two-crop) is skipped. It is passing
(passing_left=True), so after the effect it circulates to the opponent.

Card-fields (rulings 45/47, 2026-07-12): a card-field is a field, qualifying at
CARD level (total goods across stacks == exactly 1, any good incl. wood/stone);
a qualifying MULTI-STACK card with an empty stack surfaces the printed same-or-
different-stack placement as CommitPlayMinor variants (ruling 24, 2026-07-06 —
the PLAY_MINOR_VARIANTS seam); no-choice states keep the single variant-less
commit.
"""
import agricola.cards.plant_fertilizer  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.card_fields import card_field_stacks, stacks_to_store
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "plant_fertilizer"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _with_grid(state, idx, overrides):
    """Replace specific (r, c) cells in player idx's farmyard grid."""
    grid = state.players[idx].farmyard.grid
    new_grid = tuple(
        tuple(overrides.get((r, c), grid[r][c]) for c in range(5)) for r in range(3)
    )
    fy = fast_replace(state.players[idx].farmyard, grid=new_grid)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _field_crops(player):
    """List of (grain, veg) for every FIELD cell, in grid order."""
    return [
        (cell.grain, cell.veg)
        for row in player.farmyard.grid
        for cell in row
        if cell.cell_type is CellType.FIELD
    ]


def _own_minors(state, idx, card_ids):
    """Put the named (card-field) minors in player idx's tableau."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_stacks(state, idx, cid, stacks):
    """Set a card-field's per-stack (grain, veg, wood, stone) contents."""
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _at_play_minor(state):
    """The active player holding only Plant Fertilizer in hand, paused at
    PendingPlayMinor (the established factory pattern — test_cards_minors.py).
    Returns (state, active_player_idx)."""
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(
        state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_pending_stack(
        state,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),),
    )
    return state, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()              # no cost
    assert spec.vps == 0                    # no printed VPs
    assert spec.prereq is None              # no prerequisite
    assert spec.passing_left is True        # traveling card
    assert spec.on_play is not None


# ---------------------------------------------------------------------------
# Effect: the "exactly 1 good" threshold (direct on_play)
# ---------------------------------------------------------------------------

def test_single_token_fields_each_get_one_more():
    """A 1-grain field → 2 grain; a 1-veg field → 2 veg."""
    s = _card_state()
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=1),
    })
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sorted(_field_crops(out.players[0])) == sorted([(2, 0), (0, 2)])


def test_skips_fields_with_more_than_one_token():
    """Freshly-sown fields (3 grain / 2 veg) hold >1 good → NOT eligible."""
    s = _card_state()
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),  # sown grain → skip
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),    # sown veg → skip
        (0, 2): Cell(cell_type=CellType.FIELD, grain=2),  # 2 grain → skip
    })
    out = MINORS[CARD_ID].on_play(s, 0)
    # Nothing changed: identity returned (no-op grant).
    assert out is s
    assert sorted(_field_crops(out.players[0])) == sorted([(3, 0), (0, 2), (2, 0)])


def test_skips_empty_and_two_crop_fields():
    s = _card_state()
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),          # single → +1
        (0, 1): Cell(cell_type=CellType.FIELD),                   # empty → skip
        (0, 2): Cell(cell_type=CellType.FIELD, grain=1, veg=1),   # two crops → skip
    })
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sorted(_field_crops(out.players[0])) == sorted([(2, 0), (0, 0), (1, 1)])


def test_no_fields_is_a_noop_grant():
    """Playing it with zero planted fields is a harmless identity no-op."""
    s = _card_state()
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out is s
    assert _field_crops(out.players[0]) == []


def test_only_fields_are_touched():
    """A non-FIELD cell that happens to be empty is never given crops, and the
    crop edit does not bleed into player.resources."""
    s = _card_state()
    s = _with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    res_before = s.players[0].resources
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _field_crops(out.players[0]) == [(2, 0)]
    # No FIELD-cell crop leaked into player resources (grain/veg unchanged there).
    assert out.players[0].resources.grain == res_before.grain
    assert out.players[0].resources.veg == res_before.veg


# ---------------------------------------------------------------------------
# Scoping: only the playing player's fields
# ---------------------------------------------------------------------------

def test_only_acting_player_fields_change():
    s = _card_state()
    s = _with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    s = _with_grid(s, 1, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _field_crops(out.players[0]) == [(2, 0)]   # player 0 fertilized
    assert _field_crops(out.players[1]) == [(1, 0)]   # opponent untouched


# ---------------------------------------------------------------------------
# Real play flow: through CommitPlayMinor, and the passing circulation
# ---------------------------------------------------------------------------

def test_real_play_flow_applies_effect_and_passes_to_opponent():
    """Play the card via the minor-play machinery: the effect fires, and being a
    traveling card it leaves the player's tableau and lands in the opponent's hand.
    """
    s = _card_state()
    cp = s.current_player
    # Give the active player the card in hand and a single-token grain field.
    p = fast_replace(s.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(s.players[1 - cp], hand_minors=frozenset())
    s = fast_replace(s, players=tuple(p if i == cp else opp for i in range(2)))
    s = _with_grid(s, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    # Drive PendingPlayMinor directly (the established factory pattern for the
    # minor-play machinery — test_cards_minors.py).
    s = with_pending_stack(
        s,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),),
    )

    out = step(s, sole_play_minor(s, CARD_ID))

    # Effect applied to the active player's field.
    assert (2, 0) in _field_crops(out.players[cp])
    # Passing card: it is NOT kept in the player's tableau...
    assert CARD_ID not in out.players[cp].minor_improvements
    # ...and circulates to the opponent's hand.
    assert CARD_ID in out.players[1 - cp].hand_minors


# ---------------------------------------------------------------------------
# Card-fields (rulings 45/47, 2026-07-12): a card-field IS a field
# ---------------------------------------------------------------------------

def test_beanfield_with_one_veg_gains_one():
    """Ruling 45: a Beanfield harvested down to its last vegetable is a field
    with exactly 1 good — it gains a second (the pre-extension code ignored
    card-fields entirely)."""
    s = _own_minors(_card_state(), 0, ["beanfield"])
    s = _set_stacks(s, 0, "beanfield", ((0, 1, 0, 0),))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert card_field_stacks(out.players[0], "beanfield") == ((0, 2, 0, 0),)


def test_card_field_with_two_goods_gains_nothing():
    """A freshly-sown Beanfield (2 veg) holds >1 good → skipped (identity)."""
    s = _own_minors(_card_state(), 0, ["beanfield"])
    s = _set_stacks(s, 0, "beanfield", ((0, 2, 0, 0),))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out is s


def test_unplanted_card_field_gains_nothing():
    """An empty (never-sown / harvested-out) card-field holds 0 goods → skipped."""
    s = _own_minors(_card_state(), 0, ["beanfield"])
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out is s


def test_wood_field_split_total_two_gains_nothing():
    """Ruling 47: qualification is at CARD level ("considered 1 field"). A Wood
    Field with 1 wood on EACH stack holds 2 goods total → not "exactly 1 good",
    even though each stack alone holds 1."""
    s = _own_minors(_card_state(), 0, ["wood_field"])
    s = _set_stacks(s, 0, "wood_field", ((0, 0, 1, 0), (0, 0, 1, 0)))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out is s


def test_wood_field_one_wood_offers_same_and_new_variants():
    """The printed clarification: exactly 1 wood on the Wood Field → the play
    surfaces two CommitPlayMinor variants; "same" stacks the second wood on the
    occupied stack (one 2-wood stack), "new" opens a second 1-wood stack."""
    s, cp = _at_play_minor(_card_state())
    s = _own_minors(s, cp, ["wood_field"])
    s = _set_stacks(s, cp, "wood_field", ((0, 0, 1, 0), (0, 0, 0, 0)))

    commits = [a for a in legal_actions(s)
               if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert sorted(a.variant for a in commits) == [
        "wood_field:new", "wood_field:same"]
    by_variant = {a.variant: a for a in commits}

    out_same = step(s, by_variant["wood_field:same"])
    assert card_field_stacks(out_same.players[cp], "wood_field") == (
        (0, 0, 2, 0), (0, 0, 0, 0))
    out_new = step(s, by_variant["wood_field:new"])
    assert card_field_stacks(out_new.players[cp], "wood_field") == (
        (0, 0, 1, 0), (0, 0, 1, 0))
    # Still a traveling card on both routes: passed to the opponent.
    assert CARD_ID in out_same.players[1 - cp].hand_minors
    assert CARD_ID in out_new.players[1 - cp].hand_minors


def test_no_choice_state_keeps_single_variantless_commit():
    """With no qualifying MULTI-STACK card (here a single-stack Beanfield that
    itself qualifies) the play stays exactly ONE commit with variant=None — the
    pre-extension action shape — and the beanfield is fertilized automatically."""
    s, cp = _at_play_minor(_card_state())
    s = _own_minors(s, cp, ["beanfield"])
    s = _set_stacks(s, cp, "beanfield", ((0, 1, 0, 0),))

    commits = [a for a in legal_actions(s)
               if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert len(commits) == 1
    assert commits[0].variant is None

    out = step(s, commits[0])
    assert card_field_stacks(out.players[cp], "beanfield") == ((0, 2, 0, 0),)


def test_rock_garden_same_and_new():
    """Rock Garden analog (3 stacks, stone): the same/new fork; "new" opens a
    second 1-stone stack (stacks carry no identity, so ONE "new" route exists,
    not one per empty stack)."""
    s = _own_minors(_card_state(), 0, ["rock_garden"])
    s = _set_stacks(
        s, 0, "rock_garden", ((0, 0, 0, 1), (0, 0, 0, 0), (0, 0, 0, 0)))

    variants = PLAY_MINOR_VARIANTS[CARD_ID](s, 0)
    assert [v for v, _ in variants] == ["rock_garden:same", "rock_garden:new"]
    assert all(sur == Resources() for _, sur in variants)   # zero surcharge

    out = MINORS[CARD_ID].on_play(s, 0, "rock_garden:same")
    assert card_field_stacks(out.players[0], "rock_garden") == (
        (0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 0))
    out = MINORS[CARD_ID].on_play(s, 0, "rock_garden:new")
    assert card_field_stacks(out.players[0], "rock_garden") == (
        (0, 0, 0, 1), (0, 0, 0, 1), (0, 0, 0, 0))


def test_two_choice_cards_product_variants_and_shared_placements():
    """Wood Field (1 wood) + Rock Garden (1 stone) → the 2x2 product of
    per-card placements, '|'-joined in sorted card-id order; the grid and
    single-stack (Beanfield) placements ride identically in every route."""
    s = _card_state()
    s = _with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    s = _own_minors(s, 0, ["beanfield", "rock_garden", "wood_field"])
    s = _set_stacks(s, 0, "beanfield", ((0, 1, 0, 0),))
    s = _set_stacks(s, 0, "wood_field", ((0, 0, 1, 0), (0, 0, 0, 0)))
    s = _set_stacks(
        s, 0, "rock_garden", ((0, 0, 0, 1), (0, 0, 0, 0), (0, 0, 0, 0)))

    assert [v for v, _ in PLAY_MINOR_VARIANTS[CARD_ID](s, 0)] == [
        "rock_garden:same|wood_field:same",
        "rock_garden:same|wood_field:new",
        "rock_garden:new|wood_field:same",
        "rock_garden:new|wood_field:new",
    ]

    out = MINORS[CARD_ID].on_play(s, 0, "rock_garden:new|wood_field:same")
    assert _field_crops(out.players[0]) == [(2, 0)]                    # grid
    assert card_field_stacks(out.players[0], "beanfield") == ((0, 2, 0, 0),)
    assert card_field_stacks(out.players[0], "wood_field") == (
        (0, 0, 2, 0), (0, 0, 0, 0))
    assert card_field_stacks(out.players[0], "rock_garden") == (
        (0, 0, 0, 1), (0, 0, 0, 1), (0, 0, 0, 0))
