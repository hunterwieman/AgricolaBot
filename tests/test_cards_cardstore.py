"""Tests for the per-card state store infrastructure (CARD_IMPLEMENTATION_PLAN.md
II.7): the CardStore sparse hashable side-map, its get/set helpers, hashing /
canonical round-trip, and the Family-game byte-identity guarantee (an empty
card_state is omitted from the canonical JSON → no C++ change).
"""
from agricola import canonical
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import CardStore


# ---------------------------------------------------------------------------
# CardStore get / set
# ---------------------------------------------------------------------------

def test_empty_store_get_default():
    cs = CardStore()
    assert cs.items == ()
    assert cs.get("tutor") is None
    assert cs.get("tutor", 7) == 7


def test_set_then_get():
    cs = CardStore().set("tutor", 3)
    assert cs.get("tutor") == 3
    assert cs.get("other", 0) == 0


def test_set_replaces_existing_value():
    cs = CardStore().set("tutor", 3).set("tutor", 5)
    assert cs.get("tutor") == 5
    # Exactly one entry for the card (old value dropped).
    assert sum(1 for k, _ in cs.items if k == "tutor") == 1


def test_set_is_immutable():
    cs = CardStore()
    cs2 = cs.set("a", 1)
    assert cs.items == ()          # original untouched
    assert cs2.get("a") == 1


def test_items_kept_sorted_for_canonical_form():
    cs = CardStore().set("zebra", 1).set("apple", 2).set("mango", 3)
    keys = [k for k, _ in cs.items]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Hashing — same contents → equal & same hash (transposition-table requirement)
# ---------------------------------------------------------------------------

def test_equal_stores_hash_equal_regardless_of_insertion_order():
    a = CardStore().set("x", 1).set("y", 2)
    b = CardStore().set("y", 2).set("x", 1)
    assert a == b
    assert hash(a) == hash(b)


def test_different_stores_not_equal():
    a = CardStore().set("x", 1)
    b = CardStore().set("x", 2)
    assert a != b


# ---------------------------------------------------------------------------
# Canonical serialization — round-trip + Family byte-identity
# ---------------------------------------------------------------------------

def test_family_state_omits_empty_card_state():
    # The default-empty card_state must NOT appear in the Family JSON, so the C++
    # Family-only engine is untouched (byte-identical).
    s = setup(7)
    js = canonical.dumps(s)
    assert "card_state" not in js
    assert "CardStore" not in js
    # Round-trips back to an equal, equally-hashing state.
    s2 = canonical.loads(js)
    assert s2 == s
    assert hash(s2) == hash(s)


def test_populated_card_state_round_trips():
    s = setup(7)
    p = fast_replace(s.players[0], card_state=CardStore().set("tutor", 2).set("big_country", 5))
    s = fast_replace(s, players=(p, s.players[1]))
    js = canonical.dumps(s)
    assert "card_state" in js        # now it IS emitted (card state present)
    s2 = canonical.loads(js)
    assert s2 == s
    assert hash(s2) == hash(s)
    assert s2.players[0].card_state.get("tutor") == 2
    assert s2.players[0].card_state.get("big_country") == 5


def test_card_state_in_player_hash():
    s = setup(7)
    p0 = s.players[0]
    p1 = fast_replace(p0, card_state=CardStore().set("tutor", 1))
    assert hash(p0) != hash(p1)
    assert p0 != p1
