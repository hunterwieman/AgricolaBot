// Game setup + the nature/reveal dealer (CPP_ENGINE_PLAN.md §8 Stage 4).
//
// A faithful port of agricola/setup.py (`setup_env`) + agricola/environment.py
// (`Environment.reveal_action`). The C++ binary uses its OWN RNG (std::mt19937_64)
// — the trace, not the seed, is the source of truth (CPP_ENGINE_PLAN.md §2.1), so
// there is no need to reproduce NumPy's PCG64 stream. What MUST match Python is
// the *structure* of the produced round-1 WORK state: it must be one Python could
// also produce (SP coin-flip + 2/3 food split + within-stage card shuffle + the
// round-1 pre-deal).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "agricola/actions.hpp"
#include "agricola/types.hpp"

namespace agricola {

// The output of setup(): the round-1 WORK GameState plus the hidden per-game
// stage-card reveal order (length 14; order[i] is round i+1's card). The order
// is the C++ analogue of the Python Environment.round_card_order — hidden info
// kept out of GameState, consulted only by the dealer.
struct SetupResult {
  GameState initial;
  std::vector<std::string> round_card_order;
};

// Build a 2-player Family game from `seed`, mirroring setup_env(seed):
//   - std::mt19937_64(seed) RNG (own stream; NOT NumPy).
//   - starting_player = rng() % 2; SP gets 2 food, the other 3.
//   - round_card_order: each stage 1..6 shuffled WITHIN the stage, concatenated.
//   - the full 25-space board (11 permanents revealed, 14 stage cards hidden).
//   - drives the round-0 PREPARATION pre-state to the round-1 WORK state exactly
//     as setup_env does (reveal node -> RevealCard(order[0]) -> WORK).
SetupResult setup(std::uint64_t seed);

// Nature policy: the true RevealCard for the round being entered. Mirrors
// Environment.reveal_action — order[state.round_number] (round_number is the
// round just completed; the reveal turns up the NEXT round's card).
Action reveal_action(const GameState& state,
                     const std::vector<std::string>& round_card_order);

}  // namespace agricola
