"""Tests for the "empty-pasture" capacity restriction shared by Herbal Garden (E36) and
Beaver Colony (E33): one qualifying pasture must hold no animals, so `extract_slots` drops
the smallest-capacity qualifying pasture (with sharing when both are owned)."""
import agricola.cards.herbal_garden  # noqa: F401  (registers the card)
import agricola.cards.beaver_colony  # noqa: F401  (registers the card)

from types import SimpleNamespace

from agricola.cards.capacity_mods import reserved_empty_pasture_indices
from agricola.helpers import extract_slots
from agricola.replace import fast_replace
from agricola.setup import setup

from scripts.profile_states import STATES


def _own(state, pidx, *card_ids):
    p = state.players[pidx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == pidx else state.players[i] for i in range(2)))


def _pasture(num_stables):
    return SimpleNamespace(num_stables=num_stables)


# --- The reservation fold ---------------------------------------------------

def test_fold_no_owner_no_reservation():
    s = setup(0)
    assert reserved_empty_pasture_indices(s.players[0], [_pasture(1)], [4]) == set()


def test_fold_herbal_drops_smallest_any():
    # index0 = has-stable cap 6, index1 = no-stable cap 4 -> Herbal reserves the smallest (4).
    s = _own(setup(0), 0, "herbal_garden")
    assert reserved_empty_pasture_indices(s.players[0], [_pasture(1), _pasture(0)], [6, 4]) == {1}


def test_fold_beaver_only_has_stable():
    # Beaver may only reserve a pasture-with-stable -> index0 (cap 6), not the smaller no-stable.
    s = _own(setup(0), 0, "beaver_colony")
    assert reserved_empty_pasture_indices(s.players[0], [_pasture(1), _pasture(0)], [6, 4]) == {0}


def test_fold_shared_pasture_when_both_owned():
    # Both owned: one empty pasture-with-stable satisfies BOTH (the sharing ruling) -> {0}.
    s = _own(setup(0), 0, "herbal_garden", "beaver_colony")
    assert reserved_empty_pasture_indices(s.players[0], [_pasture(1), _pasture(0)], [6, 4]) == {0}


def test_fold_beaver_no_qualifying_pasture_is_vacuous():
    # No pasture-with-stable -> Beaver imposes no restriction (user ruling).
    s = _own(setup(0), 0, "beaver_colony")
    assert reserved_empty_pasture_indices(s.players[0], [_pasture(0), _pasture(0)], [4, 6]) == set()


def test_fold_both_owned_no_stable_pasture_herbal_still_applies():
    # No pasture-with-stable: Beaver vacuous, but Herbal still reserves the smallest (any).
    s = _own(setup(0), 0, "herbal_garden", "beaver_colony")
    assert reserved_empty_pasture_indices(s.players[0], [_pasture(0), _pasture(0)], [4, 6]) == {0}


# --- Through extract_slots (a real farm with two pastures) ------------------

def test_herbal_drops_a_pasture_from_extract_slots():
    state = STATES["mid_round_6_basic"]()
    base_caps, base_flex = extract_slots(state.players[0])
    assert len(base_caps) == 2                       # two pastures
    owned = _own(state, 0, "herbal_garden")
    caps, flex = extract_slots(owned.players[0])
    assert flex == base_flex                          # house/standalone slots unchanged
    assert len(caps) == len(base_caps) - 1            # one pasture reserved empty
    assert sorted(caps) == sorted(base_caps)[1:]      # dropped the smallest
    # The opponent (no card) is unaffected.
    assert extract_slots(owned.players[1]) == extract_slots(state.players[1])


def test_beaver_drops_the_stabled_pasture():
    state = STATES["mid_round_6_basic"]()
    pastures = state.players[0].farmyard.pastures
    stabled = {i for i, p in enumerate(pastures) if p.num_stables >= 1}
    assert stabled                                    # at least one pasture-with-stable
    owned = _own(state, 0, "beaver_colony")
    caps = [p.capacity for p in pastures]
    reserved = reserved_empty_pasture_indices(owned.players[0], pastures, caps)
    assert reserved <= stabled                        # only a stabled pasture reserved
    assert len(extract_slots(owned.players[0])[0]) == len(caps) - 1


def test_family_extract_slots_unchanged():
    # No card owned -> extract_slots is byte-identical to the base (Family byte-identity).
    state = STATES["mid_round_6_basic"]()
    assert extract_slots(state.players[0]) == extract_slots(state.players[0])
    # And owning neither card leaves it untouched vs a fresh copy.
    owned_other = _own(state, 0, "drinking_trough")   # a different, additive capacity card
    assert len(extract_slots(owned_other.players[0])[0]) == 2   # no pasture dropped
