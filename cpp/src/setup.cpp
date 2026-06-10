#include "agricola/setup.hpp"

#include <algorithm>
#include <random>

#include "agricola/constants.hpp"
#include "agricola/engine.hpp"
#include "agricola/state_ops.hpp"

namespace agricola {

namespace {

// Mirror setup.py::_make_round_card_order: for each stage 1..6, take that
// stage's cards in canonical within-stage order, shuffle WITHIN the stage, and
// concatenate. (Never shuffle across stages.) STAGE_CARDS[0] is the unused
// placeholder; iterate 1..6.
std::vector<std::string> make_round_card_order(std::mt19937_64& rng) {
  std::vector<std::string> order;
  for (int stage = 1; stage <= 6; ++stage) {
    std::vector<std::string> cards = STAGE_CARDS[static_cast<size_t>(stage)];
    std::shuffle(cards.begin(), cards.end(), rng);
    for (auto& c : cards) order.push_back(std::move(c));
  }
  return order;
}

// Mirror setup.py::_make_action_spaces: all 25 spaces start with empty
// accumulation and workers (0,0); permanents revealed=true, stage cards
// revealed=false. Indexed by the canonical SPACE_IDS order. The round-1 reveal's
// _complete_preparation loads round-1 goods (handled by step, not here).
std::vector<ActionSpaceState> make_action_spaces() {
  std::vector<ActionSpaceState> spaces;
  spaces.reserve(SPACE_IDS.size());
  // Permanents are the first 11 SPACE_IDS entries (PERMANENT_ACTION_SPACES);
  // every stage-card id lives in some STAGE_CARDS bucket. Rather than re-derive
  // the permanent set, mark a space revealed iff it is NOT a stage card.
  auto is_stage_card = [](const std::string& id) {
    for (int stage = 1; stage <= 6; ++stage)
      for (const auto& c : STAGE_CARDS[static_cast<size_t>(stage)])
        if (c == id) return true;
    return false;
  };
  for (const auto& sid : SPACE_IDS) {
    ActionSpaceState a;
    a.workers = {0, 0};
    a.accumulated = Resources{};
    a.accumulated_amount = 0;
    a.revealed = !is_stage_card(sid);
    spaces.push_back(a);
  }
  return spaces;
}

// Mirror setup.py::_make_farmyard: starting rooms at (1,0) and (2,0); no fences.
// (pastures stays empty — no enclosed cells with zero fences.)
Farmyard make_farmyard() {
  Farmyard f;  // grid all EMPTY, all fences false, pastures empty
  f.grid[1][0].cell_type = CellType::ROOM;
  f.grid[2][0].cell_type = CellType::ROOM;
  return f;
}

// Mirror setup.py::_make_player.
PlayerState make_player(int food) {
  PlayerState p;
  p.resources = Resources{};
  p.resources.food = food;
  p.animals = Animals{};
  p.farmyard = make_farmyard();
  p.house_material = HouseMaterial::WOOD;
  p.people_total = 2;
  p.people_home = 2;
  p.newborns = 0;
  p.begging_markers = 0;
  p.future_resources = std::vector<Resources>(NUM_ROUNDS, Resources{});  // 14 empty
  p.minor_improvements = {};
  p.occupations = {};
  p.harvest_conversions_used = {};
  return p;
}

}  // namespace

SetupResult setup(std::uint64_t seed) {
  std::mt19937_64 rng(seed);

  // Starting player + food (SP gets 2, the other 3) — setup.py order matches:
  // draw SP first, then build the order. (Our RNG stream differs from NumPy's,
  // which is fine; only the resulting structure must be Python-reachable.)
  int starting_player = static_cast<int>(rng() % 2);
  std::array<int, 2> food_for{3, 3};
  food_for[static_cast<size_t>(starting_player)] = 2;

  std::array<PlayerState, 2> players{
      make_player(food_for[0]),
      make_player(food_for[1]),
  };

  std::vector<std::string> round_card_order = make_round_card_order(rng);

  BoardState board;
  board.action_spaces = make_action_spaces();
  board.major_improvement_owners =
      std::vector<std::optional<int>>(NUM_MAJOR_IMPROVEMENTS, std::nullopt);

  // Pre-round-1 state: round_number=0, PREPARATION, empty stack, nothing
  // revealed (setup.py `pre`).
  GameState pre;
  pre.round_number = 0;
  pre.phase = Phase::PREPARATION;
  pre.current_player = starting_player;
  pre.starting_player = starting_player;
  pre.players = players;
  pre.board = board;
  pre.pending_stack = {};

  // Deal round 1 exactly as setup_env does. advance_until_decision on a round-0
  // PREPARATION empty-stack state pushes a PendingReveal (count_revealed==0==
  // round_number), then step with the true round-1 RevealCard completes
  // preparation -> round-1 WORK. advance_until_decision is engine-internal, so
  // we reproduce its single relevant step here (push the reveal frame) and let
  // step() do the rest — step() ends by calling advance_until_decision itself.
  GameState reveal_node = push(pre, PendingReveal{});
  GameState initial = step(reveal_node, RevealCard{round_card_order[0]});

  return SetupResult{initial, round_card_order};
}

Action reveal_action(const GameState& state,
                     const std::vector<std::string>& round_card_order) {
  // Mirror Environment.reveal_action: order[round_number] (round_number is the
  // round just completed; the reveal turns up the NEXT round's card). At game
  // start round_number==0 -> round 1's card order[0].
  return RevealCard{round_card_order[static_cast<size_t>(state.round_number)]};
}

}  // namespace agricola
