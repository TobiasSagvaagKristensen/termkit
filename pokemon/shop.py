"""Shop system: buying items, using items on Pokemon."""

from __future__ import annotations

from models import Pokemon, Item
from state import GameState


def buy_item(state: GameState, item: Item, quantity: int = 1) -> bool:
    """Buy an item. Returns True if purchase succeeded."""
    total_cost = item.price * quantity
    if state.money < total_cost:
        return False
    state.money -= total_cost
    state.add_item(item.id, quantity)
    return True


def use_healing_item(item: Item, pokemon: Pokemon) -> tuple[bool, str]:
    """Use a healing item on a Pokemon. Returns (success, message)."""
    if item.effect == "hp":
        if pokemon.is_fainted:
            return False, f"{pokemon.name} is fainted! Use a Revive instead."
        if pokemon.current_hp >= pokemon.max_hp:
            return False, f"{pokemon.name} is already at full HP!"
        amount = int(item.value)
        pokemon.heal(amount)
        return True, f"{pokemon.name} recovered {amount} HP!"

    elif item.effect == "revive":
        if not pokemon.is_fainted:
            return False, f"{pokemon.name} isn't fainted!"
        restore = int(pokemon.max_hp * item.value)
        pokemon.current_hp = restore
        pokemon.fainted = False
        return True, f"{pokemon.name} was revived with {restore} HP!"

    return False, "Can't use that item here."


def get_ball_modifier(item: Item) -> float | None:
    """Get catch rate modifier for a ball item. None if not a ball."""
    if item.category == "capture":
        return item.value
    return None


# Items available in the shop (all items are always available)
def get_shop_items(item_db: dict[str, Item]) -> list[Item]:
    """Get list of items available for purchase."""
    return sorted(item_db.values(), key=lambda i: (i.category, i.price))
