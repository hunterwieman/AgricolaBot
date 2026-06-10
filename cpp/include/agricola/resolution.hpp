// Resolution handlers consumed by engine.cpp — port of agricola/resolution.py.
#pragma once

#include <string>

#include "agricola/actions.hpp"
#include "agricola/types.hpp"

namespace agricola {

// Resources arithmetic (mirrors Python __add__/__sub__; no clamping).
Resources operator+(const Resources& a, const Resources& b);
Resources operator-(const Resources& a, const Resources& b);

// Cross-cutting: place one worker + decrement people_home.
GameState apply_worker_placement(const GameState& state,
                                 const std::string& space_id);

// Atomic / non-atomic space dispatch.
bool is_atomic_space(const std::string& id);
bool is_nonatomic_space(const std::string& id);
GameState resolve_atomic(const GameState& state, const std::string& space_id);
GameState initiate_nonatomic(const GameState& state, const std::string& id);

// ChooseSubAction dispatch (on the top pending's variant).
GameState choose_subaction(const GameState& state, const ChooseSubAction& act);

// _execute_* effect functions (called by the engine's commit dispatcher).
GameState execute_sow(const GameState&, int, const CommitSow&);
GameState execute_bake(const GameState&, int, const CommitBake&);
GameState execute_plow(const GameState&, int, const CommitPlow&);
GameState execute_build_stable(const GameState&, int, const CommitBuildStable&);
GameState execute_build_room(const GameState&, int, const CommitBuildRoom&);
GameState execute_renovate(const GameState&, int, const CommitRenovate&);
GameState execute_build_major(const GameState&, int, const CommitBuildMajor&);
GameState execute_build_pasture(const GameState&, int,
                                const CommitBuildPasture&);
GameState execute_accommodate(const GameState&, int, const CommitAccommodate&);
GameState execute_harvest_conversion(const GameState&, int,
                                     const CommitHarvestConversion&);
GameState execute_convert(const GameState&, int, const CommitConvert&);
GameState execute_breed(const GameState&, int, const CommitBreed&);

}  // namespace agricola
