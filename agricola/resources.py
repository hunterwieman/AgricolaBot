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
