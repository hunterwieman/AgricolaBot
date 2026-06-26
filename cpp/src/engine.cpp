// step(state, action) -> GameState + the phase machine — a faithful port of
// agricola/engine.py (Stage 3). step applies the action, alternates the player
// (only in WORK with an empty stack), then walks system transitions. It does
// NOT validate legality and does NOT auto-resolve singletons. The __debug__
// non-negative assertion in Python is a no-op for output, so it is omitted.
#include "agricola/engine.hpp"

#include <algorithm>
#include <stdexcept>

#include "agricola/constants.hpp"
#include "agricola/resolution.hpp"
#include "agricola/state_ops.hpp"

namespace agricola {
namespace {

// player_idx of the top pending frame (for the commit dispatcher).
int top_player_idx(const GameState& s) {
  return std::visit(
      [](const auto& f) -> int { return f.player_idx.value(); },
      s.pending_stack.back());
}

// ---------------------------------------------------------------------------
// Commit dispatch (mirrors COMMIT_SUBACTION_HANDLERS: expected-top + effect +
// auto_pop). auto_pop=true pops the sub-action pending after the effect.
// ---------------------------------------------------------------------------
GameState apply_commit(const GameState& state, const Action& action) {
  int pidx = top_player_idx(state);
  if (auto* a = std::get_if<CommitSow>(&action))
    return execute_sow(state, pidx, *a);  // auto_pop=false (pivots to after-phase)
  if (auto* a = std::get_if<CommitBake>(&action))
    return execute_bake(state, pidx, *a);  // auto_pop=false (pivots to after-phase)
  if (auto* a = std::get_if<CommitPlow>(&action))
    return execute_plow(state, pidx, *a);  // auto_pop=false (pivots to after-phase)
  if (auto* a = std::get_if<CommitBuildStable>(&action))
    return execute_build_stable(state, pidx, *a);  // auto_pop=false
  if (auto* a = std::get_if<CommitBuildRoom>(&action))
    return execute_build_room(state, pidx, *a);  // auto_pop=false
  if (auto* a = std::get_if<CommitRenovate>(&action))
    return execute_renovate(state, pidx, *a);  // auto_pop=false (pivots to after-phase)
  if (auto* a = std::get_if<CommitAccommodate>(&action))
    return execute_accommodate(state, pidx, *a);  // auto_pop=false (pivots to after-phase)
  if (auto* a = std::get_if<CommitBuildMajor>(&action))
    return execute_build_major(state, pidx, *a);  // auto_pop=false
  if (auto* a = std::get_if<CommitBuildPasture>(&action))
    return execute_build_pasture(state, pidx, *a);  // auto_pop=false
  if (auto* a = std::get_if<CommitHarvestConversion>(&action))
    return execute_harvest_conversion(state, pidx, *a);  // auto_pop=false
  if (auto* a = std::get_if<CommitConvert>(&action))
    return execute_convert(state, pidx, *a);  // auto_pop=false
  if (auto* a = std::get_if<CommitBreed>(&action))
    return execute_breed(state, pidx, *a);  // auto_pop=false
  throw std::runtime_error("apply_commit: not a commit action");
}

bool is_commit_action(const Action& action) {
  return std::holds_alternative<CommitSow>(action) ||
         std::holds_alternative<CommitBake>(action) ||
         std::holds_alternative<CommitPlow>(action) ||
         std::holds_alternative<CommitBuildStable>(action) ||
         std::holds_alternative<CommitBuildRoom>(action) ||
         std::holds_alternative<CommitRenovate>(action) ||
         std::holds_alternative<CommitAccommodate>(action) ||
         std::holds_alternative<CommitBuildMajor>(action) ||
         std::holds_alternative<CommitBuildPasture>(action) ||
         std::holds_alternative<CommitHarvestConversion>(action) ||
         std::holds_alternative<CommitConvert>(action) ||
         std::holds_alternative<CommitBreed>(action);
}

// ---------------------------------------------------------------------------
// PlaceWorker.
// ---------------------------------------------------------------------------
GameState apply_place_worker(const GameState& state, const PlaceWorker& a) {
  GameState s = apply_worker_placement(state, a.space);
  if (is_atomic_space(a.space)) return resolve_atomic(s, a.space);
  if (is_nonatomic_space(a.space)) return initiate_nonatomic(s, a.space);
  throw std::runtime_error("No handler registered for space " + a.space);
}

// ---------------------------------------------------------------------------
// RevealCard: set the named stage card revealed, pop the PendingReveal frame.
// ---------------------------------------------------------------------------
GameState apply_reveal_card(const GameState& state, const RevealCard& a) {
  ActionSpaceState ns = get_space_ref(state, a.card);
  ns.revealed = true;
  GameState s = with_space(state, a.card, ns);
  return pop(s);
}

GameState apply_action(const GameState& state, const Action& action) {
  if (auto* a = std::get_if<PlaceWorker>(&action))
    return apply_place_worker(state, *a);
  if (auto* a = std::get_if<ChooseSubAction>(&action))
    return choose_subaction(state, *a);
  if (is_commit_action(action)) return apply_commit(state, action);
  if (std::holds_alternative<FireTrigger>(action))
    throw std::runtime_error("FireTrigger not supported (Family-only)");
  if (std::holds_alternative<Stop>(action)) return pop(state);
  if (auto* a = std::get_if<RevealCard>(&action))
    return apply_reveal_card(state, *a);
  throw std::runtime_error("apply_action: unknown action");
}

// ---------------------------------------------------------------------------
// Active-player alternation: rotate to the next player who has workers.
// ---------------------------------------------------------------------------
GameState advance_current_player(const GameState& state) {
  int n = 2;
  for (int offset = 1; offset < n; ++offset) {
    int cand = (state.current_player + offset) % n;
    if (state.players[static_cast<size_t>(cand)].people_home > 0) {
      GameState s = state;
      s.current_player = cand;
      return s;
    }
  }
  return state;
}

// ---------------------------------------------------------------------------
// Phase resolvers.
// ---------------------------------------------------------------------------
int count_revealed_stage_cards(const GameState& s) {
  int n = 0;
  for (int stage = 1; stage <= 6; ++stage)
    for (const auto& card_id : STAGE_CARDS[static_cast<size_t>(stage)])
      if (get_space_ref(s, card_id).revealed) ++n;
  return n;
}

GameState resolve_return_home(const GameState& state) {
  GameState s = state;
  // 1. Reset every action space's worker tuple.
  for (auto& sp : s.board.action_spaces) sp.workers = {0, 0};
  // 2. Return all people home.
  for (auto& p : s.players) p.people_home = p.people_total;
  // 3. Next phase: harvest round -> HARVEST_FIELD, else PREPARATION.
  if (is_harvest_round(s.round_number))
    s.phase = Phase::HARVEST_FIELD;
  else
    s.phase = Phase::PREPARATION;
  return s;
}

GameState complete_preparation(const GameState& state) {
  GameState s = state;
  int new_round = s.round_number + 1;
  // 1. Refill every revealed accumulation space.
  for (int i = 0; i < static_cast<int>(s.board.action_spaces.size()); ++i) {
    ActionSpaceState& sp = s.board.action_spaces[static_cast<size_t>(i)];
    if (!sp.revealed) continue;
    const std::string& id = SPACE_IDS[static_cast<size_t>(i)];
    if (id == "forest")
      sp.accumulated = sp.accumulated + Resources{3, 0, 0, 0, 0, 0, 0};
    else if (id == "clay_pit")
      sp.accumulated = sp.accumulated + Resources{0, 1, 0, 0, 0, 0, 0};
    else if (id == "reed_bank")
      sp.accumulated = sp.accumulated + Resources{0, 0, 1, 0, 0, 0, 0};
    else if (id == "western_quarry" || id == "eastern_quarry")
      sp.accumulated = sp.accumulated + Resources{0, 0, 0, 1, 0, 0, 0};
    else if (id == "fishing" || id == "meeting_place")
      sp.accumulated_amount += 1;  // food
    else if (id == "sheep_market" || id == "pig_market" ||
             id == "cattle_market")
      sp.accumulated_amount += 1;  // animal
  }
  // 2. Per-player: distribute future_resources[new_round-1], clear newborns.
  int idx = new_round - 1;
  for (auto& p : s.players) {
    p.resources = p.resources + p.future_resources[static_cast<size_t>(idx)];
    p.future_resources[static_cast<size_t>(idx)] = Resources{};
    p.newborns = 0;
  }
  // 3. Transition to WORK with starting_player active.
  s.round_number = new_round;
  s.phase = Phase::WORK;
  s.current_player = s.starting_player;
  return s;
}

GameState initiate_harvest_feed(const GameState& state) {
  GameState s = state;
  int sp = s.starting_player;
  int order[2] = {(sp + 1) % 2, sp};
  for (int idx : order) {
    PendingHarvestFeed frame;
    frame.player_idx = idx;
    frame.initiated_by_id = "phase:harvest_feed";
    s = push(s, frame);
  }
  return s;
}

GameState initiate_harvest_breed(const GameState& state) {
  GameState s = state;
  int sp = s.starting_player;
  int order[2] = {(sp + 1) % 2, sp};
  for (int idx : order) {
    PendingHarvestBreed frame;
    frame.player_idx = idx;
    frame.initiated_by_id = "phase:harvest_breed";
    s = push(s, frame);
  }
  return s;
}

GameState resolve_harvest_field(const GameState& state) {
  GameState s = state;
  for (auto& p : s.players) {
    int grain_gain = 0, veg_gain = 0;
    for (int r = 0; r < kRows; ++r)
      for (int c = 0; c < kCols; ++c) {
        Cell& cell = p.farmyard.grid[static_cast<size_t>(r)][static_cast<size_t>(c)];
        if (cell.cell_type == CellType::FIELD) {
          if (cell.grain > 0) {
            ++grain_gain;
            cell.grain -= 1;
          } else if (cell.veg > 0) {
            ++veg_gain;
            cell.veg -= 1;
          }
        }
      }
    p.resources = p.resources + Resources{0, 0, 0, 0, 0, grain_gain, veg_gain};
    p.harvest_conversions_used.clear();
  }
  s = initiate_harvest_feed(s);
  s.phase = Phase::HARVEST_FEED;
  return s;
}

// ---------------------------------------------------------------------------
// _advance_until_decision: walk system transitions until the next decision /
// terminal. Idempotent.
// ---------------------------------------------------------------------------
GameState advance_until_decision(GameState s) {
  while (true) {
    if (!s.pending_stack.empty()) return s;

    if (s.phase == Phase::PREPARATION) {
      if (count_revealed_stage_cards(s) == s.round_number)
        s = push(s, PendingReveal{});
      else
        s = complete_preparation(s);
      continue;
    }

    if (s.phase == Phase::WORK) {
      bool all_empty = true;
      for (const auto& p : s.players)
        if (p.people_home != 0) all_empty = false;
      if (all_empty) {
        s.phase = Phase::RETURN_HOME;
        continue;
      }
      return s;
    }

    if (s.phase == Phase::RETURN_HOME) {
      s = resolve_return_home(s);
      continue;
    }

    if (s.phase == Phase::HARVEST_FIELD) {
      s = resolve_harvest_field(s);
      continue;
    }

    if (s.phase == Phase::HARVEST_FEED) {
      s = initiate_harvest_breed(s);
      s.phase = Phase::HARVEST_BREED;
      continue;
    }

    if (s.phase == Phase::HARVEST_BREED) {
      if (s.round_number >= NUM_ROUNDS)
        s.phase = Phase::BEFORE_SCORING;
      else
        s.phase = Phase::PREPARATION;
      continue;
    }

    if (s.phase == Phase::BEFORE_SCORING) return s;

    throw std::runtime_error("Unexpected phase in advance loop");
  }
}

}  // namespace

GameState step(const GameState& state_in, const Action& action) {
  if (state_in.phase == Phase::BEFORE_SCORING)
    throw std::runtime_error("step called on a terminated game");

  // 1. Apply the action.
  GameState state = apply_action(state_in, action);

  // 2. Alternation point: only in WORK with an empty stack.
  if (state.phase == Phase::WORK && state.pending_stack.empty())
    state = advance_current_player(state);

  // 3. Walk system transitions.
  state = advance_until_decision(state);

  return state;
}

}  // namespace agricola
