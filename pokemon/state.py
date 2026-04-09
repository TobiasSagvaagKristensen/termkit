"""Game state management, screen transitions, and save/load."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum, auto

from models import Pokemon, MoveInstance, Item

SAVE_PATH = os.path.expanduser("~/.pokemon-save.json")
SAVE_VERSION = 1


class Screen(Enum):
    TITLE = auto()
    STARTER_SELECT = auto()
    MAIN_MENU = auto()
    EXPLORE = auto()
    ENCOUNTER = auto()
    BATTLE = auto()
    BATTLE_WON = auto()
    BATTLE_LOST = auto()
    CATCH_ATTEMPT = auto()
    TEAM = auto()
    SHOP = auto()
    MOVE_LEARN = auto()
    EVOLVE = auto()


@dataclass
class BattleState:
    player_pokemon: Pokemon
    opponent_pokemon: Pokemon
    is_wild: bool
    messages: list[str] = field(default_factory=list)
    turn: int = 0
    player_action: str | None = None  # "fight", "bag", "pokemon", "run"
    selected_move: int = 0
    menu_mode: str = "action"  # "action", "fight", "bag", "pokemon"
    battle_over: bool = False
    player_won: bool = False
    caught: bool = False
    xp_events: list[dict] = field(default_factory=list)
    awaiting_input: bool = True


@dataclass
class GameState:
    screen: Screen = Screen.TITLE
    team: list[Pokemon] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=dict)
    money: int = 3000
    current_zone: str = "route_1"
    battle: BattleState | None = None

    # UI state
    menu_selection: int = 0
    zone_selection: int = 0
    team_selection: int = 0
    shop_selection: int = 0
    encounter_steps: int = 0
    steps_to_encounter: int = 0
    message_queue: list[str] = field(default_factory=list)

    # Move learning / evolution state
    pending_move_id: str | None = None
    move_learn_selection: int = 0
    evolve_into_id: int | None = None
    event_pokemon_idx: int = 0  # index into team of the Pokemon that leveled up

    def active_pokemon(self) -> Pokemon | None:
        """Get first non-fainted Pokemon."""
        for p in self.team:
            if not p.is_fainted:
                return p
        return None

    def all_fainted(self) -> bool:
        return all(p.is_fainted for p in self.team)

    def add_item(self, item_id: str, count: int = 1):
        self.inventory[item_id] = self.inventory.get(item_id, 0) + count

    def remove_item(self, item_id: str) -> bool:
        if self.inventory.get(item_id, 0) > 0:
            self.inventory[item_id] -= 1
            if self.inventory[item_id] == 0:
                del self.inventory[item_id]
            return True
        return False

    def item_count(self, item_id: str) -> int:
        return self.inventory.get(item_id, 0)


def save_game(state: GameState) -> bool:
    """Save game state to JSON file."""
    try:
        data = {
            "version": SAVE_VERSION,
            "money": state.money,
            "current_zone": state.current_zone,
            "inventory": dict(state.inventory),
            "team": [],
        }
        for pkmn in state.team:
            data["team"].append({
                "species_id": pkmn.species.id,
                "nickname": pkmn.nickname,
                "level": pkmn.level,
                "xp": pkmn.xp,
                "current_hp": pkmn.current_hp,
                "fainted": pkmn.fainted,
                "moves": [
                    {"id": m.template.id, "pp": m.current_pp}
                    for m in pkmn.moves
                ],
            })
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except (OSError, TypeError):
        return False


def load_game(species_db: dict, move_db: dict) -> GameState | None:
    """Load game state from JSON file. Returns None if no save exists."""
    if not os.path.exists(SAVE_PATH):
        return None
    try:
        with open(SAVE_PATH, encoding="utf-8") as f:
            data = json.load(f)

        state = GameState(
            screen=Screen.MAIN_MENU,
            money=data["money"],
            current_zone=data.get("current_zone", "route_1"),
            inventory=data.get("inventory", {}),
        )

        for pkmn_data in data["team"]:
            sp = species_db[pkmn_data["species_id"]]
            moves = []
            for m in pkmn_data["moves"]:
                if m["id"] in move_db:
                    moves.append(MoveInstance(
                        template=move_db[m["id"]],
                        current_pp=m["pp"],
                    ))
            from models import calc_hp
            pkmn = Pokemon(
                species=sp,
                level=pkmn_data["level"],
                xp=pkmn_data["xp"],
                current_hp=pkmn_data["current_hp"],
                moves=moves,
                nickname=pkmn_data.get("nickname"),
                fainted=pkmn_data.get("fainted", False),
            )
            state.team.append(pkmn)

        return state
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def has_save() -> bool:
    return os.path.exists(SAVE_PATH)
