from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Resources:
    wood:  int = 0
    clay:  int = 0
    reed:  int = 0
    stone: int = 0
    food:  int = 0
    grain: int = 0
    veg:   int = 0

    def __add__(self, other: Resources) -> Resources:
        """Return a new Resources with all fields summed. Does not mutate either operand."""
        return Resources(
            wood  = self.wood  + other.wood,
            clay  = self.clay  + other.clay,
            reed  = self.reed  + other.reed,
            stone = self.stone + other.stone,
            food  = self.food  + other.food,
            grain = self.grain + other.grain,
            veg   = self.veg   + other.veg,
        )

    def __sub__(self, other: Resources) -> Resources:
        """Return a new Resources with all fields differenced. Does not mutate either operand.

        Negative result components are allowed (mirrors __add__'s behavior with
        negative inputs). Use for pure-subtraction cost-debit sites; mixed
        subtract-and-add operations stay in single-Resources form with
        negative components.
        """
        return Resources(
            wood  = self.wood  - other.wood,
            clay  = self.clay  - other.clay,
            reed  = self.reed  - other.reed,
            stone = self.stone - other.stone,
            food  = self.food  - other.food,
            grain = self.grain - other.grain,
            veg   = self.veg   - other.veg,
        )

    def __bool__(self) -> bool:
        """Return True if any field is nonzero."""
        return bool(self.wood or self.clay or self.reed or self.stone
                    or self.food or self.grain or self.veg)


@dataclass(frozen=True)
class Animals:
    sheep:  int = 0
    boar:   int = 0
    cattle: int = 0

    def __add__(self, other: Animals) -> Animals:
        """Return a new Animals with all fields summed. Does not mutate either operand."""
        return Animals(
            sheep  = self.sheep  + other.sheep,
            boar   = self.boar   + other.boar,
            cattle = self.cattle + other.cattle,
        )

    def __sub__(self, other: Animals) -> Animals:
        """Return a new Animals with all fields differenced (negatives allowed)."""
        return Animals(
            sheep  = self.sheep  - other.sheep,
            boar   = self.boar   - other.boar,
            cattle = self.cattle - other.cattle,
        )


@dataclass(frozen=True)
class Cost:
    """A payable card cost. `resources` already covers building resources, food,
    AND crops (grain/veg); `animals` is the only thing it adds and is empty for
    almost every card. Pay via `p.resources - cost.resources` /
    `p.animals - cost.animals`. (Computed/state-dependent costs — e.g. Bottles'
    "1 clay + 1 food per person" — are handled per-card, not by this static
    shape.) See CARD_IMPLEMENTATION_PLAN.md II.4."""
    resources: Resources = Resources()
    animals:   Animals   = Animals()
