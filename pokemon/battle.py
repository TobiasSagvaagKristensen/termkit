"""Battle engine: damage calculation, turn order, AI decision making."""

from __future__ import annotations

import math
import random

from models import Pokemon, MoveInstance
from type_chart import Type, effectiveness, effectiveness_message


# Struggle: used when all moves are out of PP
STRUGGLE_POWER = 50
STRUGGLE_RECOIL = 0.25


def calculate_damage(attacker: Pokemon, defender: Pokemon, move: MoveInstance) -> tuple[int, float, bool]:
    """Calculate damage for a move.

    Returns (damage, type_effectiveness_multiplier, is_stab).
    """
    if move.power == 0:
        return 0, 1.0, False

    level = attacker.level
    power = move.power

    if move.category == "physical":
        atk = attacker.attack
        dfn = defender.defense
    else:
        atk = attacker.sp_attack
        dfn = defender.sp_defense

    # Prevent division by zero
    dfn = max(dfn, 1)

    # Base damage
    base = ((2 * level / 5 + 2) * power * atk / dfn) / 50 + 2

    # STAB (Same Type Attack Bonus)
    stab = 1.0
    is_stab = False
    if move.type == attacker.species.type1 or move.type == attacker.species.type2:
        stab = 1.5
        is_stab = True

    # Type effectiveness
    type_eff = effectiveness(move.type, defender.species.type1, defender.species.type2)

    # Random factor
    rand = random.uniform(0.85, 1.0)

    damage = int(base * stab * type_eff * rand)
    return max(1, damage) if type_eff > 0 else 0, type_eff, is_stab


def check_accuracy(move: MoveInstance) -> bool:
    """Return True if the move hits."""
    if move.accuracy == 0:  # Status moves with 0 accuracy always hit
        return True
    return random.randint(1, 100) <= move.accuracy


def get_turn_order(p1: Pokemon, p2: Pokemon) -> tuple[Pokemon, Pokemon]:
    """Determine who goes first based on speed."""
    if p1.speed > p2.speed:
        return p1, p2
    elif p2.speed > p1.speed:
        return p2, p1
    else:
        return (p1, p2) if random.random() < 0.5 else (p2, p1)


def ai_choose_move(pokemon: Pokemon, opponent: Pokemon) -> int:
    """AI selects a move index. Returns index into pokemon.moves."""
    available = [(i, m) for i, m in enumerate(pokemon.moves) if m.current_pp > 0]
    if not available:
        return -1  # Will use Struggle

    scores = []
    for i, move in available:
        if move.power == 0:
            # Status moves get a low base score
            score = 10.0
        else:
            type_eff = effectiveness(move.type, opponent.species.type1, opponent.species.type2)
            stab = 1.5 if (move.type == pokemon.species.type1 or move.type == pokemon.species.type2) else 1.0
            score = move.power * type_eff * stab * (move.accuracy / 100)

        # Random jitter +-15%
        score *= random.uniform(0.85, 1.15)
        scores.append((i, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0][0]


def execute_move(attacker: Pokemon, defender: Pokemon, move_index: int) -> list[str]:
    """Execute a single move. Returns list of battle messages."""
    messages = []

    # Check for Struggle
    if move_index == -1:
        messages.append(f"{attacker.name} has no moves left!")
        messages.append(f"{attacker.name} used Struggle!")

        # Struggle damage: typeless, fixed power
        level = attacker.level
        atk = attacker.attack
        dfn = max(defender.defense, 1)
        base = ((2 * level / 5 + 2) * STRUGGLE_POWER * atk / dfn) / 50 + 2
        damage = max(1, int(base * random.uniform(0.85, 1.0)))
        defender.take_damage(damage)
        messages.append(f"{defender.name} took {damage} damage!")

        # Recoil
        recoil = max(1, int(damage * STRUGGLE_RECOIL))
        attacker.take_damage(recoil)
        messages.append(f"{attacker.name} took {recoil} recoil damage!")
        return messages

    move = attacker.moves[move_index]
    move.current_pp -= 1
    messages.append(f"{attacker.name} used {move.name}!")

    # Status moves (power == 0) - simple message for now
    if move.power == 0:
        if check_accuracy(move):
            messages.append(f"But nothing happened...")  # Simplified for v1
        else:
            messages.append(f"{attacker.name}'s attack missed!")
        return messages

    # Accuracy check
    if not check_accuracy(move):
        messages.append(f"{attacker.name}'s attack missed!")
        return messages

    # Calculate and apply damage
    damage, type_eff, is_stab = calculate_damage(attacker, defender, move)
    defender.take_damage(damage)

    if damage > 0:
        messages.append(f"{defender.name} took {damage} damage!")

    # Type effectiveness message
    eff_msg = effectiveness_message(type_eff)
    if eff_msg:
        messages.append(eff_msg)

    # Check if defender fainted
    if defender.is_fainted:
        messages.append(f"{defender.name} fainted!")

    return messages


def attempt_run(player_pokemon: Pokemon, wild_pokemon: Pokemon) -> bool:
    """Attempt to run from a wild battle. Higher speed = better chance."""
    if player_pokemon.speed >= wild_pokemon.speed:
        return True
    chance = (player_pokemon.speed / wild_pokemon.speed) * 0.8 + 0.2
    return random.random() < chance
