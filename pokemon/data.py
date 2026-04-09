"""Load game data from CSV files."""

import csv
import os

from type_chart import Type, load_type_chart
from models import Species, MoveTemplate, Item, Zone

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _csv_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def _read_csv(filename: str) -> list[dict]:
    with open(_csv_path(filename), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_types():
    """Load type effectiveness chart from CSV."""
    rows = []
    for row in _read_csv("types.csv"):
        rows.append((row["attacker"], row["defender"], float(row["multiplier"])))
    load_type_chart(rows)


def load_moves() -> dict[str, MoveTemplate]:
    """Load all move templates, keyed by id."""
    moves = {}
    for row in _read_csv("moves.csv"):
        moves[row["id"]] = MoveTemplate(
            id=row["id"],
            name=row["name"],
            type=Type(row["type"].strip().lower()),
            category=row["category"].strip().lower(),
            power=int(row["power"]),
            accuracy=int(row["accuracy"]),
            pp=int(row["pp"]),
            description=row["description"],
        )
    return moves


def load_species() -> dict[int, Species]:
    """Load all species, keyed by id."""
    species = {}
    for row in _read_csv("species.csv"):
        sid = int(row["id"])
        type2 = Type(row["type2"].strip().lower()) if row["type2"].strip() else None

        # Parse learnable moves: "tackle:1|vine_whip:7"
        learnable = []
        if row["learnable_moves"].strip():
            for entry in row["learnable_moves"].split("|"):
                parts = entry.strip().split(":")
                if len(parts) == 2:
                    move_id, level = parts[0].strip(), int(parts[1].strip())
                    learnable.append((level, move_id))

        evolve_level = int(row["evolve_level"]) if row["evolve_level"].strip() else None
        evolve_into = int(row["evolve_into"]) if row["evolve_into"].strip() else None

        species[sid] = Species(
            id=sid,
            name=row["name"].strip(),
            type1=Type(row["type1"].strip().lower()),
            type2=type2,
            base_hp=int(row["hp"]),
            base_attack=int(row["attack"]),
            base_defense=int(row["defense"]),
            base_sp_attack=int(row["sp_attack"]),
            base_sp_defense=int(row["sp_defense"]),
            base_speed=int(row["speed"]),
            catch_rate=int(row["catch_rate"]),
            xp_yield=int(row["xp_yield"]),
            learnable_moves=learnable,
            evolve_level=evolve_level,
            evolve_into=evolve_into,
        )
    return species


def load_items() -> dict[str, Item]:
    """Load all items, keyed by id."""
    items = {}
    for row in _read_csv("items.csv"):
        items[row["id"]] = Item(
            id=row["id"],
            name=row["name"],
            category=row["category"].strip().lower(),
            effect=row["effect"].strip().lower(),
            value=float(row["value"]),
            price=int(row["price"]),
            description=row["description"],
        )
    return items


def load_zones() -> dict[str, Zone]:
    """Load all zones, keyed by id."""
    zones = {}
    for row in _read_csv("zones.csv"):
        encounters = []
        if row["encounters"].strip():
            for entry in row["encounters"].split("|"):
                parts = entry.strip().split(":")
                if len(parts) == 2:
                    species_id, weight = int(parts[0].strip()), float(parts[1].strip())
                    encounters.append((species_id, weight))

        zones[row["id"]] = Zone(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            level_min=int(row["level_min"]),
            level_max=int(row["level_max"]),
            encounters=encounters,
        )
    return zones


def load_art() -> dict[int, str]:
    """Load ASCII art for Pokemon, keyed by species id."""
    art_dir = os.path.join(DATA_DIR, "art")
    art = {}
    if not os.path.isdir(art_dir):
        return art
    for filename in os.listdir(art_dir):
        if filename.endswith(".txt"):
            try:
                species_id = int(filename[:-4])
                with open(os.path.join(art_dir, filename), encoding="utf-8") as f:
                    art[species_id] = f.read().rstrip("\n")
            except (ValueError, OSError):
                continue
    return art


def load_all() -> tuple[dict[str, MoveTemplate], dict[int, Species],
                         dict[str, Item], dict[str, Zone], dict[int, str]]:
    """Load all game data. Call once at startup."""
    load_types()
    moves = load_moves()
    species = load_species()
    items = load_items()
    zones = load_zones()
    art = load_art()
    return moves, species, items, zones, art
