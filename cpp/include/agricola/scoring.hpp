// Scoring + tiebreaker — a faithful port of agricola/scoring.py (Stage 3).
// Only the integer total + tiebreaker are needed for the graduation gate (not
// the breakdown struct). CPP_ENGINE_PLAN.md §5.4: craft spend is recomputed
// independently in both, so craft spending both scores AND lowers tiebreaker.
#pragma once

#include "agricola/types.hpp"

namespace agricola {

int score(const GameState& state, int player_idx);
int tiebreaker(const GameState& state, int player_idx);

}  // namespace agricola
