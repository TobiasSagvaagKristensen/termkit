"""Pokemon type system and effectiveness chart."""

from enum import Enum


class Type(Enum):
    NORMAL = "normal"
    FIRE = "fire"
    WATER = "water"
    GRASS = "grass"
    ELECTRIC = "electric"
    ICE = "ice"
    FIGHTING = "fighting"
    POISON = "poison"
    GROUND = "ground"
    FLYING = "flying"
    PSYCHIC = "psychic"
    BUG = "bug"
    ROCK = "rock"
    GHOST = "ghost"
    DRAGON = "dragon"
    FAIRY = "fairy"


# Type effectiveness chart: (attacker, defender) -> multiplier
# Only non-1.0 entries are stored; missing pairs default to 1.0
_CHART: dict[tuple[Type, Type], float] = {}


def load_type_chart(rows: list[tuple[str, str, float]]):
    """Load type effectiveness from parsed CSV rows."""
    _CHART.clear()
    for atk, dfn, mult in rows:
        try:
            atk_type = Type(atk.strip().lower())
            dfn_type = Type(dfn.strip().lower())
            _CHART[(atk_type, dfn_type)] = mult
        except ValueError:
            continue


def effectiveness(atk_type: Type, def_type1: Type, def_type2: Type | None = None) -> float:
    """Get combined type effectiveness multiplier."""
    mult = _CHART.get((atk_type, def_type1), 1.0)
    if def_type2 is not None:
        mult *= _CHART.get((atk_type, def_type2), 1.0)
    return mult


def effectiveness_message(mult: float) -> str | None:
    """Return a battle message for the effectiveness multiplier."""
    if mult == 0:
        return "It had no effect..."
    elif mult < 1:
        return "It's not very effective..."
    elif mult > 1:
        return "It's super effective!"
    return None
