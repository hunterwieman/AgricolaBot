"""The Cards-mode forgo-the-newborn breed configs (2026-07-30).

WHY THEY EXIST. Two prunes were each justified by the availability of the
other, and together they deleted a rules-legal line:

  * `breeding_frontier`'s Pareto runs over ANIMAL counts only — food is a
    downstream proceed, excluded per Foundations' preserving-optionality rule
    ("don't cook now, you can cook later"). Every cook-for-food configuration
    is therefore dominated by not cooking, and pruned.
  * `post_breed_floors` (ruling 39) then blocks the deferred equivalent: a type
    that just bred sits at min_parents + 1, exactly its floor, so nothing of it
    is cookable for the rest of the breeding phase.

A player holding exactly min_parents of a type had neither route, so "forgo
this type's newborn and cook the animals instead" was unreachable. Slurry (C71)
-> Drill Harrow (D17) is the motivating pair: Slurry grants a Sow at
`breeding_outcome` and Drill Harrow charges 3 food on that sow's `before_sow`
window, so the fee falls INSIDE the breeding phase and cannot be pre-spent —
the plow only exists at that instant.

WHAT WAS BUILT. `bred_flags` partitions the frontier's dominance comparison by
breeding outcome, so a config that forfeits a newborn is incomparable to one
that keeps it. The retained config pins the forfeited type at `min_parents`
(user, 2026-07-30) — dominated but kept, standing in for breed-then-release —
and the post-breed raise frame reaches 0 from there because the floor does not
bind below itself. Cards mode only: the Family game has no card that charges
food anywhere in the breeding band, so withholding it there is lossless and
keeps the Family trace byte-identical for the C++ twin.
"""
import dataclasses

import agricola.cards  # noqa: F401  (registers the slot-bearing cards)

from agricola.cards.capacity_mods import sheep_min_parents
from agricola.constants import GameMode
from agricola.helpers import bred_flags, breeding_frontier, cooking_rates
from agricola.pasture import compute_pastures_from_arrays
from agricola.resources import Animals
from agricola.setup import setup
from agricola.state import Farmyard

from tests.factories import with_majors, with_phase, with_resources


def _state(*, sheep=0, boar=0, cattle=0, mode=GameMode.CARDS, cols=3,
           cards=frozenset()):
    """P0 with the given herd, a `cols`-wide pasture (ample room), a Fireplace
    (sheep/boar 2 food, cattle 3), and the given tableau."""
    state = dataclasses.replace(setup(seed=0), mode=mode, starting_player=0)
    p = dataclasses.replace(
        state.players[0],
        animals=Animals(sheep=sheep, boar=boar, cattle=cattle),
        minor_improvements=frozenset(cards), occupations=frozenset(cards))
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    for c in range(cols):
        h[0][c] = True
        h[1][c] = True
    v[0][0] = True
    v[0][cols] = True
    fy = Farmyard(
        grid=p.farmyard.grid,
        horizontal_fences=tuple(tuple(r) for r in h),
        vertical_fences=tuple(tuple(r) for r in v),
        pastures=compute_pastures_from_arrays(
            p.farmyard.grid, tuple(tuple(r) for r in h),
            tuple(tuple(r) for r in v)))
    state = dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, farmyard=fy) if i == 0 else state.players[i]
        for i in range(2)))
    state = with_majors(state, owner_by_idx={0: 0})
    return with_resources(state, 0, food=0)


def _sheep_frontier(state):
    """[(final sheep, food gained, this type kept a newborn?)], sorted."""
    p = state.players[0]
    m = sheep_min_parents(p)
    return sorted(
        (cfg.sheep, food, bred_flags(p.animals, cfg, m)[0])
        for cfg, food in breeding_frontier(state, p, cooking_rates(state, 0)[:3]))


# --- Family is untouched ----------------------------------------------------

def test_family_offers_only_the_breeding_config():
    """No card charges food in the Family breeding band, so the forfeit config
    has no consumer there; withholding it keeps the Family trace
    byte-identical for the C++ differential gates."""
    assert _sheep_frontier(_state(sheep=2, mode=GameMode.FAMILY)) == [(3, 0, True)]
    assert _sheep_frontier(_state(sheep=3, mode=GameMode.FAMILY)) == [(4, 0, True)]


# --- Cards gains exactly one extra config per breeding type -----------------

def test_cards_adds_the_forfeit_config_at_min_parents():
    # pre 2 -> breed to 3, or keep 2 and forgo the newborn (nothing cooked yet;
    # 2 is below the floor of 3, so the raise frame can still take it to 0).
    assert _sheep_frontier(_state(sheep=2)) == [(2, 0, False), (3, 0, True)]
    # pre 3 -> breed to 4, or cook 1 down to 2 and forgo the newborn.
    assert _sheep_frontier(_state(sheep=3)) == [(2, 2, False), (4, 0, True)]


def test_dollys_mother_shifts_the_forfeit_config_one_lower():
    """Dolly's Mother lowers the sheep parent threshold to 1, so leaving 1
    sheep still breeds; the not-bred config is `final = min_parents` = 1."""
    state = _state(sheep=3, cards=frozenset({"dollys_mother"}))
    assert sheep_min_parents(state.players[0]) == 1
    rows = _sheep_frontier(state)
    assert (1, 4, False) in rows
    assert not any(sheep <= 1 and bred for sheep, _f, bred in rows)


def test_forfeit_config_survives_a_strip_exceeding_the_threshold():
    """The regression cross-level equivalence CANNOT catch: both paths would
    compute the same wrong shift and agree with each other.

    Dolly's Mother sits on both sides of the comparison — it lowers the sheep
    threshold to 1 AND contributes a typed card slot — so owning it plus any
    second sheep-slot card makes the strip exceed the threshold. Under a
    uniform strip shift-back the "not-bred" config lands at the strip value,
    i.e. a BRED config wearing the wrong label. Assert the flag directly.
    """
    for cards in (frozenset({"dollys_mother", "sheep_agent"}),
                  frozenset({"dollys_mother", "sheep_agent",
                             "wildlife_reserve"})):
        state = _state(sheep=3, cards=cards)
        m = sheep_min_parents(state.players[0])
        rows = _sheep_frontier(state)
        forfeits = [r for r in rows if not r[2]]
        assert forfeits, f"{sorted(cards)}: no not-bred sheep config offered"
        assert all(sheep <= m for sheep, _f, _b in forfeits), (
            f"{sorted(cards)}: a config labelled not-bred sits above "
            f"min_parents={m} — the strip shift-back is wrong: {forfeits}")


def test_types_that_cannot_breed_get_no_extra_config():
    """Below the threshold there is no newborn to forgo, and the post-breed
    floor does not bind below itself anyway, so nothing is added."""
    assert _sheep_frontier(_state(sheep=1)) == [(1, 0, False)]
    assert _sheep_frontier(_state(sheep=0)) == [(0, 0, False)]


def _three_pastures(state):
    """Three separate 2-cell pastures (capacity 4 each) — a pasture holds one
    animal TYPE, so all three types need their own to breed simultaneously."""
    p = state.players[0]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    for row, col0 in ((0, 0), (0, 3), (2, 0)):
        for c in (col0, col0 + 1):
            h[row][c] = True
            h[row + 1][c] = True
        v[row][col0] = True
        v[row][col0 + 2] = True
    fy = Farmyard(
        grid=p.farmyard.grid,
        horizontal_fences=tuple(tuple(r) for r in h),
        vertical_fences=tuple(tuple(r) for r in v),
        pastures=compute_pastures_from_arrays(
            p.farmyard.grid, tuple(tuple(r) for r in h),
            tuple(tuple(r) for r in v)))
    return dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, farmyard=fy) if i == 0 else state.players[i]
        for i in range(2)))


def test_slurry_drill_harrow_fee_becomes_fundable():
    """The motivating pair, end to end.

    Slurry (C71) grants a Sow at `breeding_outcome`; Drill Harrow (D17)
    charges 3 food on that sow's `before_sow` window. The fee therefore falls
    INSIDE the breeding phase and cannot be pre-spent — the plow exists only at
    that instant, and only because breeding produced two newborn types.

    With 2/2/2 and room, every type breeds to exactly its floor and nothing is
    cookable, so the fee was unpayable. Forgoing the CATTLE newborn leaves the
    cattle at 2 — below the floor of 3, hence still cookable at the Cooking
    Hearth's rate of 4 — while sheep and boar still breed, so Slurry's
    two-newborn-types condition is still met.
    """
    from agricola.actions import CommitBreed
    from agricola.cards.harvest_windows import post_breed_floors, sentinel_position
    from agricola.engine import step
    from agricola.legality import _liquidatable_to
    from agricola.pending import PendingHarvestBreed, push
    from agricola.replace import fast_replace
    from agricola.resources import Resources
    from agricola.constants import Phase

    def at_breed_frame(mode):
        state = _three_pastures(_state(sheep=2, boar=2, cattle=2, mode=mode))
        state = with_majors(state, owner_by_idx={2: 0})   # CookingHearth(4c)
        state = with_phase(state, Phase.HARVEST_BREED)
        # One PAST the breeding sentinel: where the floors actually bind.
        state = fast_replace(
            state, harvest_cursor=sentinel_position("breeding", 0) + 1)
        return push(state, PendingHarvestBreed(
            player_idx=0, initiated_by_id="phase:harvest_breed"))

    pre = Animals(sheep=2, boar=2, cattle=2)

    # Family: only the all-breed config, and the fee stays unpayable.
    fam = at_breed_frame(GameMode.FAMILY)
    fam_opts = [a for a in legal_actions_breed(fam)]
    assert len(fam_opts) == 1
    fam = step(fam, fam_opts[0])
    assert post_breed_floors(fam, 0) == (3, 3, 3)
    assert not _liquidatable_to(fam, 0, fam.players[0], Resources(food=3))

    # Cards: the forgo-the-cattle-newborn config exists and funds the fee.
    state = at_breed_frame(GameMode.CARDS)
    m = sheep_min_parents(state.players[0])
    forgo_cattle = [
        a for a in legal_actions_breed(state)
        if bred_flags(pre, Animals(a.sheep, a.boar, a.cattle), m) == (True, True, False)
    ]
    assert forgo_cattle, "no config keeps both other newborns while forgoing cattle"

    state = step(state, forgo_cattle[0])
    p = state.players[0]
    assert p.animals.cattle <= 2                      # below the floor
    assert post_breed_floors(state, 0) == (3, 3, 3)   # floors ARE binding
    assert _liquidatable_to(state, 0, p, Resources(food=3)), (
        "Drill Harrow's in-breeding-phase fee must be fundable by cooking the "
        "cattle whose newborn was forgone")


def legal_actions_breed(state):
    from agricola.actions import CommitBreed
    from agricola.legality import legal_actions
    return [a for a in legal_actions(state) if isinstance(a, CommitBreed)]


def test_forfeit_configs_are_independent_per_type():
    """Three breeding types, each with its own pasture -> the subsets form a
    cross-product, so every combination of "which newborns did I keep?" is
    offered. This is why the enumeration iterates SUBSETS rather than lowering
    one type at a time: forgoing one type's newborn can also free capacity for
    another."""
    state = _three_pastures(_state(sheep=2, boar=2, cattle=2))
    p = state.players[0]
    m = sheep_min_parents(p)
    patterns = {
        bred_flags(p.animals, cfg, m)
        for cfg, _food in breeding_frontier(state, p, cooking_rates(state, 0)[:3])
    }
    assert len(patterns) == 8, f"expected all 8 breeding outcomes, got {patterns}"
