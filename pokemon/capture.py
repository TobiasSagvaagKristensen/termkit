"""Capture mechanics and wild encounter generation."""

from __future__ import annotations

import random

from models import Pokemon, Species, MoveTemplate, create_pokemon


def calculate_catch_chance(pokemon: Pokemon, ball_modifier: float) -> float:
    """Calculate probability of catching a Pokemon (0.0 to 0.95)."""
    base_rate = pokemon.species.catch_rate / 255.0
    hp_factor = (3 * pokemon.max_hp - 2 * pokemon.current_hp) / (3 * pokemon.max_hp)
    chance = base_rate * ball_modifier * hp_factor
    return min(chance, 0.95)


def attempt_catch(pokemon: Pokemon, ball_modifier: float) -> tuple[bool, int]:
    """Attempt to catch a Pokemon.

    Returns (caught, shakes) where shakes is 0-3.
    """
    chance = calculate_catch_chance(pokemon, ball_modifier)

    # Simulate 3 shakes, each must succeed
    shakes = 0
    shake_chance = chance ** (1 / 3)  # Per-shake probability
    for _ in range(3):
        if random.random() < shake_chance:
            shakes += 1
        else:
            break

    caught = shakes == 3
    return caught, shakes


def generate_wild_encounter(
    zone_encounters: list[tuple[int, float]],
    level_min: int,
    level_max: int,
    species_db: dict[int, Species],
    move_db: dict[str, MoveTemplate],
) -> Pokemon | None:
    """Generate a random wild Pokemon from zone encounter table."""
    if not zone_encounters:
        return None

    # Weighted random selection
    total_weight = sum(w for _, w in zone_encounters)
    roll = random.uniform(0, total_weight)
    cumulative = 0.0

    selected_species_id = zone_encounters[0][0]  # fallback
    for species_id, weight in zone_encounters:
        cumulative += weight
        if roll <= cumulative:
            selected_species_id = species_id
            break

    if selected_species_id not in species_db:
        return None

    species = species_db[selected_species_id]
    level = random.randint(level_min, level_max)
    return create_pokemon(species, level, move_db)
