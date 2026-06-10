// legal_actions(state) — a faithful port of agricola/legality.py (Stage 2).
// CPP_ENGINE_PLAN.md §4 row 5, the biggest single correctness surface.
#pragma once

#include <vector>

#include "agricola/actions.hpp"
#include "agricola/types.hpp"

namespace agricola {

// All currently-legal actions, given pending and phase state. Mirrors
// legality.legal_actions: empty stack + WORK -> legal_placements; non-empty
// stack -> the top frame's enumerator; BEFORE_SCORING -> empty.
//
// Note: cards are deferred (Family-only), so FireTrigger options are never
// emitted (no player owns potter_ceramics in Family play; the trigger is
// always ineligible). The set is identical to Python over the Family-game
// reachable corpus.
std::vector<Action> legal_actions(const GameState& state);

}  // namespace agricola
