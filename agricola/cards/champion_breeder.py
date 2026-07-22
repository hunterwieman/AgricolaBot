"""Champion Breeder (occupation, E133; Ephipparius Expansion; players 3+).

Card text (verbatim): "Each time you place 2 or 3+ newborn animals on your farm
during the breeding phase of the harvest, you get 1 or 2 bonus points,
respectively."
Clarification (verbatim): "You must be able to accommodate each newborn in order to
get it."

Each harvest's breeding is a separate "each time": if the owner PLACES exactly 2
newborns that breeding they bank 1 point; 3 or more banks 2 points; 0 or 1 banks
nothing. Points accumulate across the game's six harvests and are read at scoring.

- **The counting seam.** `register_breeding_outcome_auto` fires at `CommitBreed`
  with the `BreedingOutcome` payload — the newborns actually PLACED (0/1 per type,
  so 0..3 total in the 2-player game). The printed accommodation clarification is
  inherent in the payload: an unaccommodated newborn is never placed, so it never
  appears in `outcome.total` (the `fodder_planter.py` / `slurry.py`
  precedent). Eligibility is `outcome.total >= 2` (fewer than 2 earns nothing).

- **Banking, round-keyed.** The apply accumulates into a
  `(last_scored_round, banked_points)` CardStore tuple, guarded by the harvest round
  so a re-entry of the same breeding never double-counts (harvest rounds are unique;
  the auto fires once per breeding, so the guard is defensive). Points this breeding:
  `1` for exactly 2 placed, `2` for 3+.

Category 1/2 hybrid (recurring breeding reaction + banked scoring). The CardStore
tuple is empty in the Family game -> byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_breeding_outcome_auto
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "champion_breeder"


def _entry(state: GameState, idx: int) -> tuple[int, int]:
    """This owner's (last_scored_round, banked_points), default (0, 0). Round 0 is
    never a real round, so the default never matches a live harvest round."""
    return state.players[idx].card_state.get(CARD_ID, (0, 0))


def _outcome_eligible(state: GameState, idx: int, outcome) -> bool:
    # Only 2+ placed newborns earn a bonus (1 for exactly 2, 2 for 3+).
    return outcome.total >= 2


def _bank(state: GameState, idx: int, outcome) -> GameState:
    last_round, banked = _entry(state, idx)
    if last_round == state.round_number:
        return state                      # already banked this harvest's breeding
    points = 1 if outcome.total == 2 else 2     # total >= 3 -> 2
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, (state.round_number, banked + points))
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return _entry(state, idx)[1]


# Pure recurring occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_breeding_outcome_auto(CARD_ID, _outcome_eligible, _bank)
register_scoring(CARD_ID, _score)
