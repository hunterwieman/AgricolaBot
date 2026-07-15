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
// Commit dispatch (mirrors COMMIT_SUBACTION_HANDLERS: expected-top + effect).
// The dispatcher never pops — each effect owns its own stack manipulation (pivot
// to the after-phase, push a wrapper, or replace_top for multi-shot); the trailing
// Stop pops the host. (The Python side once had a per-entry auto_pop flag; it was
// always false and has been removed — see SUBACTION_HOOK_REFACTOR.md.)
// ---------------------------------------------------------------------------
GameState apply_commit(const GameState& state, const Action& action) {
  int pidx = top_player_idx(state);
  if (auto* a = std::get_if<CommitSow>(&action))
    return execute_sow(state, pidx, *a);  // pivots to after-phase
  if (auto* a = std::get_if<CommitBake>(&action))
    return execute_bake(state, pidx, *a);  // pivots to after-phase
  if (auto* a = std::get_if<CommitPlow>(&action))
    return execute_plow(state, pidx, *a);  // pivots to after-phase
  if (auto* a = std::get_if<CommitBuildStable>(&action))
    return execute_build_stable(state, pidx, *a);  // multi-shot: replace_top; Proceed flips, Stop pops
  if (auto* a = std::get_if<CommitBuildRoom>(&action))
    return execute_build_room(state, pidx, *a);  // multi-shot: replace_top; Proceed flips, Stop pops
  if (auto* a = std::get_if<CommitRenovate>(&action))
    return execute_renovate(state, pidx, *a);  // pivots to after-phase
  if (auto* a = std::get_if<CommitAccommodate>(&action))
    return execute_accommodate(state, pidx, *a);  // pivots to after-phase
  if (auto* a = std::get_if<CommitBuildMajor>(&action))
    return execute_build_major(state, pidx, *a);  // pop or push oven wrapper
  if (auto* a = std::get_if<CommitBuildPasture>(&action))
    return execute_build_pasture(state, pidx, *a);  // multi-shot: replace_top; Stop pops
  if (auto* a = std::get_if<CommitHarvestConversion>(&action))
    return execute_harvest_conversion(state, pidx, *a);  // stays on top; Stop pops
  if (auto* a = std::get_if<CommitConvert>(&action))
    return execute_convert(state, pidx, *a);  // stays on top; Stop pops
  if (auto* a = std::get_if<CommitBreed>(&action))
    return execute_breed(state, pidx, *a);  // stays on top; Stop pops
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
  // The revealed card belongs to the round being entered (the increment has
  // not happened yet) — mirrors Python's _apply_reveal_card.
  ns.revealed_round = state.round_number + 1;
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
  if (std::holds_alternative<Stop>(action)) return pop(state);  // pure pop (§11)
  if (std::holds_alternative<Proceed>(action)) {
    // Proceed-host work-complete boundary (SPACE_HOST_REFACTOR.md §4.3/§11): the
    // sub-actions already ran in the before-phase, so Proceed just flips the host
    // to its after-phase (firing after_action_space autos — a Family no-op). C++
    // Family never produces the atomic PendingActionSpace host (card-only), so no
    // primary effect runs here. The trailing Stop pops.
    PendingDecision nt = state.pending_stack.back();
    std::visit([](auto& f) {
      if constexpr (requires { f.phase; }) { f.phase = "after"; }
    }, nt);
    return replace_top(state, nt);
  }
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

// One player's FEED/BREED band pass (ruling 40 — whole-phase-per-player): the
// banded walk pushes ONE payment/breeding frame per pass, starting player
// first, instead of both players' frames at once. Feeding-income autos are
// cards-only, so a Family pass is just the frame push.
GameState push_harvest_feed_frame(const GameState& state, int idx) {
  PendingHarvestFeed frame;
  frame.player_idx = idx;
  frame.initiated_by_id = "phase:harvest_feed";
  return push(state, frame);
}

GameState push_harvest_breed_frame(const GameState& state, int idx) {
  PendingHarvestBreed frame;
  frame.player_idx = idx;
  frame.initiated_by_id = "phase:harvest_breed";
  return push(state, frame);
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
  // Banded FEED entry (ruling 40): only the starting player's payment frame;
  // the other player's follows when this one pops (advance_until_decision
  // dispatches on the cursor).
  s.phase = Phase::HARVEST_FEED;
  s = push_harvest_feed_frame(s, s.starting_player);
  s.harvest_cursor = CURSOR_AFTER_FEEDING_PASS0;
  return s;
}

// ---------------------------------------------------------------------------
// _advance_until_decision: walk system transitions until the next decision /
// terminal. Idempotent.
// ---------------------------------------------------------------------------
// A Delegating space host (SPACE_HOST_REFACTOR.md §5) — PendingSubActionSpace or
// PendingMajorMinorImprovement — auto-advances to its after-phase once its single
// mandatory sub-action has completed. The two helpers below recognize that frame
// type and read its work-complete signal (subaction_complete is a real field on
// PendingSubActionSpace, a derived property on PendingMajorMinorImprovement).
bool is_delegating(const PendingDecision& top) {
  return std::holds_alternative<PendingSubActionSpace>(top) ||
         std::holds_alternative<PendingMajorMinorImprovement>(top);
}
bool delegating_subaction_complete(const PendingDecision& top) {
  if (auto* sas = std::get_if<PendingSubActionSpace>(&top))
    return sas->subaction_complete;
  if (auto* mm = std::get_if<PendingMajorMinorImprovement>(&top))
    return mm->subaction_complete();
  return false;
}
std::string delegating_phase(const PendingDecision& top) {
  if (auto* sas = std::get_if<PendingSubActionSpace>(&top)) return sas->phase;
  if (auto* mm = std::get_if<PendingMajorMinorImprovement>(&top)) return mm->phase;
  return "";
}

GameState advance_until_decision(GameState s) {
  while (true) {
    // Case 1: a pending frame is active — decision awaits the agent, UNLESS the
    // top host's work just completed, in which case flip it to its after-phase
    // (firing after_<event> autos — a Family no-op) before returning. Two
    // work-complete signals share the one flip rule (mirroring Python):
    //   - a Delegating space host whose single mandatory sub-action just popped
    //     (SPACE_HOST_REFACTOR.md §5), and
    //   - a commit-terminated host whose executor marked `effect_initiated`
    //     (the DEFERRED after-flip, user ruling 2026-07-14 — the Family-reachable
    //     case is the ovens' free-bake wrapper over PendingBuildMajor).
    // The flip makes phase=="after" and clears the mark, so the guard is False
    // next iteration — idempotent.
    if (!s.pending_stack.empty()) {
      const PendingDecision& top = s.pending_stack.back();
      bool work_complete =
          (is_delegating(top) && delegating_subaction_complete(top) &&
           delegating_phase(top) == "before") ||
          std::visit(
              [](const auto& f) {
                if constexpr (requires { f.effect_initiated; f.phase; })
                  return f.effect_initiated && f.phase == "before";
                else
                  return false;
              },
              top);
      if (work_complete) {
        PendingDecision nt = top;
        std::visit([](auto& f) {
          if constexpr (requires { f.phase; }) { f.phase = "after"; }
          if constexpr (requires { f.effect_initiated; }) { f.effect_initiated = false; }
        }, nt);
        s = replace_top(s, nt);
        continue;
      }
      return s;
    }

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

    if (s.phase == Phase::HARVEST_FEED || s.phase == Phase::HARVEST_BREED) {
      // Banded FEED/BREED walk (ruling 40): an empty stack here means the
      // current band pass's frame just popped; the cursor says where the walk
      // resumes. In the cardless Family game every window between frames is a
      // no-op, so the walk is this fixed state machine over the cursor
      // anchors (constants.hpp). A nullopt cursor is a LEGACY hand-built bare
      // FEED/BREED state (both players' frames pushed at once, e.g. by the
      // Python compat initiators): both passes are done, so it resumes past
      // the band — mirroring Python's legacy None-cursor derivation.
      int sp = s.starting_player;
      int cur = s.harvest_cursor
                    ? *s.harvest_cursor
                    : (s.phase == Phase::HARVEST_FEED
                           ? CURSOR_AFTER_FEEDING_PASS1
                           : CURSOR_AFTER_BREEDING_PASS1);
      s.harvest_cursor = std::nullopt;
      if (cur == CURSOR_AFTER_FEEDING_PASS0) {
        // SP paid -> the other player's FEED pass.
        s = push_harvest_feed_frame(s, (sp + 1) % 2);
        s.harvest_cursor = CURSOR_AFTER_FEEDING_PASS1;
      } else if (cur == CURSOR_AFTER_FEEDING_PASS1) {
        // FEED band done -> BREED band, SP's pass first.
        s.phase = Phase::HARVEST_BREED;
        s = push_harvest_breed_frame(s, sp);
        s.harvest_cursor = CURSOR_AFTER_BREEDING_PASS0;
      } else if (cur == CURSOR_AFTER_BREEDING_PASS0) {
        // SP bred -> the other player's BREED pass.
        s = push_harvest_breed_frame(s, (sp + 1) % 2);
        s.harvest_cursor = CURSOR_AFTER_BREEDING_PASS1;
      } else if (cur == CURSOR_AFTER_BREEDING_PASS1) {
        // The walk is done: the harvest is over.
        if (s.round_number >= NUM_ROUNDS)
          s.phase = Phase::BEFORE_SCORING;
        else
          s.phase = Phase::PREPARATION;
      } else {
        throw std::runtime_error("unexpected harvest_cursor in advance loop");
      }
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
