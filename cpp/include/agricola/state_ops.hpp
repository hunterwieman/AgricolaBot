// Small keyed-access helpers over BoardState.action_spaces (mirrors
// state.get_space / state.with_space) + pending-stack ops (pending.push/pop/
// replace_top). Header-only inline; used by the resolution + engine ports.
#pragma once

#include <stdexcept>
#include <string>

#include "agricola/constants.hpp"
#include "agricola/types.hpp"

namespace agricola {

inline const ActionSpaceState& get_space_ref(const GameState& s,
                                             const std::string& space_id) {
  int i = space_index(space_id);
  if (i < 0) throw std::runtime_error("get_space: unknown space " + space_id);
  return s.board.action_spaces[static_cast<size_t>(i)];
}

// Return a new GameState with the named action space replaced.
inline GameState with_space(GameState s, const std::string& space_id,
                            const ActionSpaceState& new_space) {
  int i = space_index(space_id);
  if (i < 0) throw std::runtime_error("with_space: unknown space " + space_id);
  s.board.action_spaces[static_cast<size_t>(i)] = new_space;
  return s;
}

inline GameState update_player(GameState s, int ap, const PlayerState& np) {
  s.players[static_cast<size_t>(ap)] = np;
  return s;
}

// --- pending-stack ops (value-semantic; mirror pending.push/pop/replace_top) -
inline GameState push(GameState s, const PendingDecision& frame) {
  s.pending_stack.push_back(frame);
  return s;
}
inline GameState pop(GameState s) {
  s.pending_stack.pop_back();
  return s;
}
inline GameState replace_top(GameState s, const PendingDecision& new_top) {
  s.pending_stack.back() = new_top;
  return s;
}

}  // namespace agricola
