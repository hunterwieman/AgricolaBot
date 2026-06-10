// step(state, action) -> GameState — the transition function. A faithful port
// of agricola/engine.py + resolution.py (CPP_ENGINE_PLAN.md §4 row 7, Stage 3).
//
// Pure: applies the action, performs player alternation (only in WORK with an
// empty pending stack), then walks system transitions to the next decision /
// terminal. Does NOT validate legality and does NOT auto-resolve singletons.
#pragma once

#include "agricola/actions.hpp"
#include "agricola/types.hpp"

namespace agricola {

GameState step(const GameState& state, const Action& action);

}  // namespace agricola
