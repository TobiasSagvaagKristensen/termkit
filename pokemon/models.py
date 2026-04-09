"""Core data models for the Pokemon game."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from type_chart import Type


@dataclass
class Species:
    id: int
    name: str
    type1: Type
    type2: Type | None
    base_hp: int
    base_attack: int
    base_defense: int
    base_sp_attack: int
    base_sp_defense: int
    base_speed: int
    catch_rate: int
    xp_yield: int
    learnable_moves: list[tuple[int, str]]  # [(level, move_id), ...]
    evolve_level: int | None
    evolve_into: int | None  # species id


@dataclass
class MoveTemplate:
    id: str
    name: str
    type: Type
    category: str  # "physical" or "special"
    power: int
    accuracy: int
    pp: int
    description: str


@dataclass
class MoveInstance:
    template: MoveTemplate
    current_pp: int

    @property
    def id(self) -> str:
        return self.template.id

    @property
    def name(self) -> str:
        return self.template.name

    @property
    def type(self) -> Type:
        return self.template.type

    @property
    def power(self) -> int:
        return self.template.power

    @property
    def accuracy(self) -> int:
        return self.template.accuracy

    @property
    def max_pp(self) -> int:
        return self.template.pp

    @property
    def category(self) -> str:
        return self.template.category


@dataclass
class Pokemon:
    species: Species
    level: int
    xp: int
    current_hp: int
    moves: list[MoveInstance]
    nickname: str | None = None
    fainted: bool = False

    @property
    def name(self) -> str:
        return self.nickname or self.species.name

    @property
    def max_hp(self) -> int:
        return calc_hp(self.species.base_hp, self.level)

    @property
    def attack(self) -> int:
        return calc_stat(self.species.base_attack, self.level)

    @property
    def defense(self) -> int:
        return calc_stat(self.species.base_defense, self.level)

    @property
    def sp_attack(self) -> int:
        return calc_stat(self.species.base_sp_attack, self.level)

    @property
    def sp_defense(self) -> int:
        return calc_stat(self.species.base_sp_defense, self.level)

    @property
    def speed(self) -> int:
        return calc_stat(self.species.base_speed, self.level)

    @property
    def xp_to_next_level(self) -> int:
        return self.level ** 3

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0 or self.fainted

    def heal(self, amount: int):
        self.current_hp = min(self.current_hp + amount, self.max_hp)
        if self.current_hp > 0:
            self.fainted = False

    def take_damage(self, amount: int):
        self.current_hp = max(0, self.current_hp - amount)
        if self.current_hp == 0:
            self.fainted = True

    def full_heal(self):
        self.current_hp = self.max_hp
        self.fainted = False
        for move in self.moves:
            move.current_pp = move.max_pp

    def gain_xp(self, amount: int) -> list[dict]:
        """Gain XP. Returns list of events (level_up, new_move, evolve)."""
        events = []
        self.xp += amount
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            old_max_hp = self.max_hp
            self.level += 1
            hp_increase = self.max_hp - old_max_hp
            self.current_hp += hp_increase
            events.append({"type": "level_up", "level": self.level})

            # Check for new moves at this level
            for learn_level, move_id in self.species.learnable_moves:
                if learn_level == self.level:
                    events.append({"type": "new_move", "move_id": move_id})

            # Check for evolution (only once — stop leveling, defer to evolution screen)
            # evolve_level == 0 means stone evolution (not auto)
            if (self.species.evolve_level is not None
                    and self.species.evolve_level > 0
                    and self.level >= self.species.evolve_level):
                events.append({
                    "type": "evolve",
                    "into": self.species.evolve_into,
                })
                break

        return events


@dataclass
class Item:
    id: str
    name: str
    category: str  # "healing", "capture", "status"
    effect: str
    value: float
    price: int
    description: str


@dataclass
class Zone:
    id: str
    name: str
    description: str
    level_min: int
    level_max: int
    encounters: list[tuple[int, float]]  # (species_id, weight)


def calc_hp(base: int, level: int) -> int:
    return math.floor((2 * base * level) / 100) + level + 10


def calc_stat(base: int, level: int) -> int:
    return math.floor((2 * base * level) / 100) + 5


def create_pokemon(species: Species, level: int,
                   move_templates: dict[str, MoveTemplate]) -> Pokemon:
    """Create a new Pokemon instance at a given level with appropriate moves."""
    # Collect all moves learnable at or below this level
    available = []
    for learn_level, move_id in sorted(species.learnable_moves, key=lambda x: x[0]):
        if learn_level <= level:
            if move_id in move_templates:
                available.append(move_id)

    # Take the last 4 (most recently learned)
    chosen_ids = available[-4:] if len(available) > 4 else available

    # Fallback: if no moves, give Tackle
    if not chosen_ids and "tackle" in move_templates:
        chosen_ids = ["tackle"]

    moves = [
        MoveInstance(template=move_templates[mid], current_pp=move_templates[mid].pp)
        for mid in chosen_ids
    ]

    hp = calc_hp(species.base_hp, level)
    return Pokemon(species=species, level=level, xp=0, current_hp=hp, moves=moves)


def create_wild_pokemon(species: Species, level_min: int, level_max: int,
                        move_templates: dict[str, MoveTemplate]) -> Pokemon:
    """Create a wild Pokemon at a random level within range."""
    level = random.randint(level_min, level_max)
    return create_pokemon(species, level, move_templates)
