"""Terminal UI rendering using Rich library."""

from __future__ import annotations

import os
import select
import sys
import time

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

from type_chart import Type
from models import Pokemon, MoveInstance, Item, Zone
from state import GameState, Screen, BattleState

# ──────────────────────────────────────────────────────────
#  Color palette (Game Boy inspired)
# ──────────────────────────────────────────────────────────

GREEN = "rgb(80,200,120)"
YELLOW = "rgb(255,203,5)"
RED = "rgb(255,80,80)"
BLUE = "rgb(100,150,255)"
DIM = "rgb(120,120,120)"
BORDER = "rgb(60,60,90)"
WHITE = "bright_white"
CREAM = "rgb(253,246,227)"

TYPE_COLORS = {
    Type.NORMAL: "white on rgb(168,168,120)",
    Type.FIRE: "white on rgb(240,128,48)",
    Type.WATER: "white on rgb(104,144,240)",
    Type.GRASS: "white on rgb(120,200,80)",
    Type.ELECTRIC: "black on rgb(248,208,48)",
    Type.ICE: "black on rgb(152,216,216)",
    Type.FIGHTING: "white on rgb(192,48,40)",
    Type.POISON: "white on rgb(160,64,160)",
    Type.GROUND: "black on rgb(224,192,104)",
    Type.FLYING: "white on rgb(168,144,240)",
    Type.PSYCHIC: "white on rgb(248,88,136)",
    Type.BUG: "white on rgb(168,184,32)",
    Type.ROCK: "white on rgb(184,160,56)",
    Type.GHOST: "white on rgb(112,88,152)",
    Type.DRAGON: "white on rgb(112,56,248)",
    Type.FAIRY: "white on rgb(238,153,172)",
}

POKEBALL_ART = r"""
        ████████████
      ██            ██
    ██   ██████████   ██
   ██  ██          ██  ██
  ██  ██            ██  ██
  ██  ██     ████   ██  ██
  ████████████  ████████████
  ██  ██     ████   ██  ██
  ██  ██            ██  ██
   ██  ██          ██  ██
    ██   ██████████   ██
      ██            ██
        ████████████
"""

# ──────────────────────────────────────────────────────────
#  Input handling
# ──────────────────────────────────────────────────────────


_stdin_fd = None

def _raw_read(n: int = 1) -> bytes:
    """Read bytes directly from stdin fd, bypassing Python buffering."""
    import os
    global _stdin_fd
    if _stdin_fd is None:
        _stdin_fd = sys.stdin.fileno()
    return os.read(_stdin_fd, n)


def read_key(timeout: float = 0.03):
    """Read a key from stdin with timeout. Returns None if no key pressed."""
    if not sys.stdin.isatty():
        time.sleep(timeout)
        return None
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return None
    ch = _raw_read(1)
    if ch == b"\x1b":
        # Escape sequences arrive in a burst — short timeout is fine
        if select.select([sys.stdin], [], [], 0.005)[0]:
            ch2 = _raw_read(1)
            if ch2 == b"[" and select.select([sys.stdin], [], [], 0.005)[0]:
                ch3 = _raw_read(1)
                # Drain any trailing bytes from longer sequences
                while select.select([sys.stdin], [], [], 0.002)[0]:
                    _raw_read(1)
                return {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}.get(ch3)
            # Drain remaining escape sequence bytes
            while select.select([sys.stdin], [], [], 0.002)[0]:
                _raw_read(1)
        return "escape"
    elif ch in (b"\r", b"\n"):
        return "enter"
    elif ch == b"\x03":
        return "ctrl-c"
    elif ch == b"\x7f":
        return "backspace"
    return ch.decode("utf-8", errors="ignore").lower() or None


# ──────────────────────────────────────────────────────────
#  UI components
# ──────────────────────────────────────────────────────────


def build_pokemon_sprite(species_id: int, sprite_db: dict[int, str],
                         width: int = 24, height: int = 12):
    """Render a Pokemon sprite as colored half-block characters."""
    path = sprite_db.get(species_id)
    if not path or not os.path.exists(path):
        return Text("")

    try:
        from rich_pixels import Pixels
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        return Pixels.from_image(img, resize=(width, height))
    except Exception:
        return Text("")


def build_hp_bar(current: int, max_val: int, width: int = 20) -> Text:
    """Build a colored HP bar."""
    if max_val == 0:
        ratio = 0
    else:
        ratio = current / max_val

    filled = int(ratio * width)
    empty = width - filled

    if ratio > 0.5:
        color = GREEN
    elif ratio > 0.2:
        color = YELLOW
    else:
        color = RED

    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * empty, style=DIM)
    bar.append(f" {current}/{max_val}", style=WHITE)
    return bar


def build_type_badge(ptype: Type) -> Text:
    """Build a colored type badge."""
    style = TYPE_COLORS.get(ptype, "white on grey50")
    return Text(f" {ptype.value.upper()} ", style=f"bold {style}")


def build_type_badges(type1: Type, type2: Type | None) -> Text:
    """Build type badges for a Pokemon."""
    badges = Text()
    badges.append_text(build_type_badge(type1))
    if type2:
        badges.append(" ")
        badges.append_text(build_type_badge(type2))
    return badges


# ──────────────────────────────────────────────────────────
#  Screens
# ──────────────────────────────────────────────────────────


def render_title(has_save: bool) -> Panel:
    """Render the title screen."""
    content = Text()
    for line in POKEBALL_ART.strip().split("\n"):
        content.append(line + "\n", style=f"bold {RED}")
    content.append("\n")
    content.append("  P O K E M O N", style=f"bold {YELLOW}")
    content.append("\n")
    content.append("  Terminal Edition", style=f"italic {GREEN}")
    content.append("\n\n")
    content.append("  [ENTER]  New Game\n", style=WHITE)
    if has_save:
        content.append("  [L]      Load Game\n", style=WHITE)
    content.append("  [Q]      Quit\n", style=DIM)

    return Panel(
        Align.center(content),
        border_style=BORDER,
        title="[bold]Welcome[/bold]",
        padding=(1, 2),
    )


def render_starter_select(selection: int) -> Panel:
    """Render the starter selection screen."""
    starters = [
        ("Bulbasaur", Type.GRASS, Type.POISON, "The seed Pokemon. A gentle creature that carries a plant bulb on its back."),
        ("Charmander", Type.FIRE, None, "The lizard Pokemon. The flame on its tail shows its life force."),
        ("Squirtle", Type.WATER, None, "The tiny turtle Pokemon. It shelters itself in its shell when in danger."),
    ]

    content = Text()
    content.append("Professor Oak: Choose your partner!\n\n", style=f"bold {WHITE}")

    for i, (name, t1, t2, desc) in enumerate(starters):
        if i == selection:
            content.append(f"  > ", style=f"bold {YELLOW}")
            content.append(f"{name} ", style=f"bold {WHITE}")
        else:
            content.append(f"    {name} ", style=DIM)
        content.append_text(build_type_badge(t1))
        if t2:
            content.append(" ")
            content.append_text(build_type_badge(t2))
        content.append("\n")
        if i == selection:
            content.append(f"      {desc}\n", style=f"italic {CREAM}")
        content.append("\n")

    content.append("\n  [UP/DOWN] Select  [ENTER] Confirm", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title="[bold]Choose Your Starter[/bold]",
        padding=(1, 2),
    )


def render_main_menu(state: GameState) -> Panel:
    """Render the main menu."""
    options = ["Explore", "Team", "Shop", "Save", "Quit"]
    icons = ["🌿", "⚔", "🛒", "💾", "🚪"]

    content = Text()
    content.append(f"  Trainer  |  ${state.money}", style=f"bold {YELLOW}")
    content.append(f"  |  Team: {len(state.team)}/6\n\n", style=WHITE)

    for i, (opt, icon) in enumerate(zip(options, icons)):
        if i == state.menu_selection:
            content.append(f"  > {icon} {opt}\n", style=f"bold {WHITE}")
        else:
            content.append(f"    {icon} {opt}\n", style=DIM)

    content.append(f"\n  [UP/DOWN] Select  [ENTER] Confirm", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title="[bold]Main Menu[/bold]",
        padding=(1, 2),
    )


def render_explore(state: GameState, zones: dict[str, Zone]) -> Panel:
    """Render zone selection for exploration."""
    zone_list = list(zones.values())

    content = Text()
    content.append("  Where would you like to explore?\n\n", style=f"bold {WHITE}")

    for i, zone in enumerate(zone_list):
        if i == state.zone_selection:
            content.append(f"  > ", style=f"bold {YELLOW}")
            content.append(f"{zone.name}", style=f"bold {WHITE}")
            content.append(f"  Lv.{zone.level_min}-{zone.level_max}\n", style=GREEN)
            content.append(f"      {zone.description}\n", style=f"italic {CREAM}")
        else:
            content.append(f"    {zone.name}", style=DIM)
            content.append(f"  Lv.{zone.level_min}-{zone.level_max}\n", style=DIM)

    content.append(f"\n  [UP/DOWN] Select  [ENTER] Go  [ESC] Back", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title="[bold]Explore[/bold]",
        padding=(1, 2),
    )


def render_walking(zone: Zone, steps: int) -> Panel:
    """Render the walking/exploration animation."""
    # Grass animation
    grass_chars = [".", ",", ";", "'", "`"]
    line1 = ""
    line2 = ""
    line3 = ""
    for j in range(40):
        idx = (steps + j) % len(grass_chars)
        line1 += grass_chars[idx]
        line2 += grass_chars[(idx + 2) % len(grass_chars)]
        line3 += grass_chars[(idx + 4) % len(grass_chars)]

    content = Text()
    content.append(f"  {zone.name}\n\n", style=f"bold {WHITE}")
    content.append(f"  {line1}\n", style=GREEN)
    content.append(f"  {line2}\n", style=GREEN)
    content.append(f"  {line3}\n\n", style=GREEN)
    content.append(f"  Walking through the grass...\n", style=f"italic {CREAM}")
    content.append(f"\n  [ENTER] Step  [ESC] Leave", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title=f"[bold]{zone.name}[/bold]",
        padding=(1, 2),
    )


def render_encounter(wild_pokemon: Pokemon, sprite_db: dict[int, str] | None = None) -> Panel:
    """Render wild Pokemon encounter screen."""
    content = Text()
    header = Text()
    header.append(f"\n  A wild ", style=WHITE)
    header.append(f"{wild_pokemon.name}", style=f"bold {YELLOW}")
    header.append(f" appeared!\n", style=WHITE)

    info = Text()
    info.append(f"  Lv.{wild_pokemon.level}  ", style=WHITE)
    info.append_text(build_type_badges(wild_pokemon.species.type1, wild_pokemon.species.type2))
    info.append("\n  HP: ", style=WHITE)
    info.append_text(build_hp_bar(wild_pokemon.current_hp, wild_pokemon.max_hp))
    info.append("\n\n")
    info.append(f"  [ENTER] Fight  [ESC] Run", style=DIM)

    parts = [header]
    if sprite_db:
        sprite = build_pokemon_sprite(wild_pokemon.species.id, sprite_db, width=72, height=36)
        if sprite:
            parts.append(sprite)
    parts.append(info)

    return Panel(
        Group(*parts),
        border_style=f"bold {YELLOW}",
        title="[bold]Wild Encounter![/bold]",
        padding=(1, 2),
    )


def render_battle(battle: BattleState, state: GameState, item_db: dict[str, Item] | None = None, sprite_db: dict[int, str] | None = None) -> Panel:
    """Render the battle screen."""
    opp = battle.opponent_pokemon
    plr = battle.player_pokemon

    # Opponent info
    opp_info = Text()
    opp_info.append(f"  {opp.name}", style=f"bold {WHITE}")
    opp_info.append(f"  Lv.{opp.level}  ", style=DIM)
    opp_info.append_text(build_type_badges(opp.species.type1, opp.species.type2))
    opp_info.append("\n  HP: ")
    opp_info.append_text(build_hp_bar(opp.current_hp, opp.max_hp))

    # Player info
    plr_info = Text()
    plr_info.append(f"  {plr.name}", style=f"bold {WHITE}")
    plr_info.append(f"  Lv.{plr.level}  ", style=DIM)
    plr_info.append_text(build_type_badges(plr.species.type1, plr.species.type2))
    plr_info.append("\n  HP: ")
    plr_info.append_text(build_hp_bar(plr.current_hp, plr.max_hp))

    # Messages
    msg_text = Text()
    display_msgs = battle.messages[-4:] if battle.messages else []
    for msg in display_msgs:
        msg_text.append(f"  {msg}\n", style=CREAM)

    # Action menu
    menu_text = Text()
    if battle.menu_mode == "action":
        actions = ["Fight", "Bag", "Pokemon", "Run"]
        for i, act in enumerate(actions):
            if i == battle.selected_move:
                menu_text.append(f"  > {act}", style=f"bold {WHITE}")
            else:
                menu_text.append(f"    {act}", style=DIM)
            if i % 2 == 0:
                menu_text.append("    ")
            else:
                menu_text.append("\n")

    elif battle.menu_mode == "fight":
        for i, move in enumerate(plr.moves):
            if i == battle.selected_move:
                menu_text.append(f"  > ", style=f"bold {YELLOW}")
                menu_text.append(f"{move.name} ", style=f"bold {WHITE}")
                menu_text.append_text(build_type_badge(move.type))
                menu_text.append(f"  PP:{move.current_pp}/{move.max_pp}", style=DIM)
            else:
                pp_style = DIM if move.current_pp > 0 else RED
                menu_text.append(f"    {move.name}", style=DIM)
                menu_text.append(f"  PP:{move.current_pp}/{move.max_pp}", style=pp_style)
            menu_text.append("\n")
        menu_text.append(f"\n  [ESC] Back", style=DIM)

    elif battle.menu_mode == "bag":
        capture_items = []
        healing_items = []
        for item_id, count in sorted(state.inventory.items()):
            if item_db and item_id in item_db:
                item = item_db[item_id]
                if item.category == "capture":
                    capture_items.append((item, count))
                elif item.category == "healing":
                    healing_items.append((item, count))

        all_items = capture_items + healing_items
        if not all_items:
            menu_text.append(f"  No items!\n", style=DIM)
        else:
            for i, (item, count) in enumerate(all_items):
                if i == battle.selected_move:
                    menu_text.append(f"  > {item.name} x{count}\n", style=f"bold {WHITE}")
                else:
                    menu_text.append(f"    {item.name} x{count}\n", style=DIM)
        menu_text.append(f"\n  [ESC] Back", style=DIM)

    elif battle.menu_mode == "pokemon":
        for i, pkmn in enumerate(state.team):
            if pkmn is plr:
                marker = " (active)"
            elif pkmn.is_fainted:
                marker = " (fainted)"
            else:
                marker = ""
            if i == battle.selected_move:
                menu_text.append(f"  > {pkmn.name} Lv.{pkmn.level}", style=f"bold {WHITE}")
                menu_text.append(f"  HP:{pkmn.current_hp}/{pkmn.max_hp}{marker}\n",
                               style=RED if pkmn.is_fainted else GREEN)
            else:
                menu_text.append(f"    {pkmn.name} Lv.{pkmn.level}", style=DIM)
                menu_text.append(f"  HP:{pkmn.current_hp}/{pkmn.max_hp}{marker}\n",
                               style=RED if pkmn.is_fainted else DIM)
        menu_text.append(f"\n  [ESC] Back", style=DIM)

    # Compose using Group for mixed Text/Pixels renderables
    group_parts = []

    # Opponent sprite + info
    if sprite_db:
        opp_sprite = build_pokemon_sprite(opp.species.id, sprite_db, width=72, height=36)
        if opp_sprite:
            group_parts.append(opp_sprite)
    opp_section = Text()
    opp_section.append("─── Opponent ───\n", style=BORDER)
    opp_section.append_text(opp_info)
    opp_section.append("\n")
    group_parts.append(opp_section)

    # Player sprite + info
    if sprite_db:
        plr_sprite = build_pokemon_sprite(plr.species.id, sprite_db, width=72, height=36)
        if plr_sprite:
            group_parts.append(plr_sprite)
    plr_section = Text()
    plr_section.append("─── Your Pokemon ───\n", style=BORDER)
    plr_section.append_text(plr_info)
    plr_section.append("\n")
    group_parts.append(plr_section)

    # Messages
    if display_msgs:
        group_parts.append(msg_text)

    # Action menu
    action_section = Text()
    action_section.append("─── Actions ───\n", style=BORDER)
    action_section.append_text(menu_text)
    group_parts.append(action_section)

    wild_label = "Wild " if battle.is_wild else ""
    return Panel(
        Group(*group_parts),
        border_style=BORDER,
        title=f"[bold]Battle vs {wild_label}{opp.name}[/bold]",
        padding=(1, 2),
    )


def render_battle_result(battle: BattleState, xp_gained: int = 0, money_gained: int = 0) -> Panel:
    """Render battle result (win/loss/catch)."""
    content = Text()

    if battle.caught:
        content.append(f"\n  Gotcha!\n", style=f"bold {YELLOW}")
        content.append(f"  {battle.opponent_pokemon.name} was caught!\n\n", style=WHITE)
    elif battle.player_won:
        content.append(f"\n  You won!\n", style=f"bold {GREEN}")
        if xp_gained > 0:
            content.append(f"  Gained {xp_gained} XP\n", style=WHITE)
        if money_gained > 0:
            content.append(f"  Earned ${money_gained}\n", style=YELLOW)
    else:
        content.append(f"\n  You lost...\n", style=f"bold {RED}")
        content.append(f"  Your Pokemon have been healed.\n", style=WHITE)

    content.append(f"\n\n  [ENTER] Continue", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title="[bold]Battle Over[/bold]",
        padding=(1, 2),
    )


def render_team(state: GameState, sprite_db: dict[int, str] | None = None) -> Panel:
    """Render the team management screen."""
    content = Text()
    content.append(f"  Your Team ({len(state.team)}/6)\n\n", style=f"bold {WHITE}")

    for i, pkmn in enumerate(state.team):
        if i == state.team_selection:
            content.append(f"  > ", style=f"bold {YELLOW}")
            content.append(f"{pkmn.name}", style=f"bold {WHITE}")
        else:
            content.append(f"    {pkmn.name}", style=DIM)

        content.append(f"  Lv.{pkmn.level}  ", style=DIM if i != state.team_selection else WHITE)
        content.append_text(build_type_badges(pkmn.species.type1, pkmn.species.type2))
        content.append("\n")

        content.append(f"      HP: ", style=DIM if i != state.team_selection else WHITE)
        content.append_text(build_hp_bar(pkmn.current_hp, pkmn.max_hp))
        content.append("\n")

        if i == state.team_selection:
            content.append(f"      ATK:{pkmn.attack} DEF:{pkmn.defense} ", style=CREAM)
            content.append(f"SpATK:{pkmn.sp_attack} SpDEF:{pkmn.sp_defense} SPD:{pkmn.speed}\n", style=CREAM)
            content.append(f"      XP: {pkmn.xp}/{pkmn.xp_to_next_level}\n", style=DIM)
            content.append(f"      Moves: ", style=CREAM)
            for j, move in enumerate(pkmn.moves):
                content.append_text(build_type_badge(move.type))
                content.append(f" {move.name} ", style=WHITE)
                content.append(f"({move.current_pp}/{move.max_pp})", style=DIM)
                if j < len(pkmn.moves) - 1:
                    content.append("  ")
            content.append("\n")

        if pkmn.is_fainted:
            content.append(f"      [FAINTED]\n", style=RED)
        content.append("\n")

    content.append(f"\n  [UP/DOWN] Select  [S] Swap  [ESC] Back", style=DIM)

    # Build group with optional sprite preview
    group_parts = [content]
    if sprite_db and state.team:
        selected = state.team[state.team_selection]
        sprite = build_pokemon_sprite(selected.species.id, sprite_db, width=72, height=36)
        if sprite:
            preview_label = Text()
            preview_label.append("\n─── Preview ───\n", style=BORDER)
            group_parts.append(preview_label)
            group_parts.append(sprite)

    return Panel(
        Group(*group_parts),
        border_style=BORDER,
        title="[bold]Team[/bold]",
        padding=(1, 2),
    )


def render_shop(state: GameState, items: list[Item]) -> Panel:
    """Render the shop screen."""
    content = Text()
    content.append(f"  Welcome to the Poke Mart!\n", style=f"bold {WHITE}")
    content.append(f"  Your money: ", style=WHITE)
    content.append(f"${state.money}\n\n", style=f"bold {YELLOW}")

    for i, item in enumerate(items):
        owned = state.item_count(item.id)
        if i == state.shop_selection:
            content.append(f"  > ", style=f"bold {YELLOW}")
            content.append(f"{item.name}", style=f"bold {WHITE}")
            content.append(f"  ${item.price}", style=GREEN)
            if owned > 0:
                content.append(f"  (owned: {owned})", style=DIM)
            content.append(f"\n")
            content.append(f"      {item.description}\n", style=f"italic {CREAM}")
        else:
            content.append(f"    {item.name}", style=DIM)
            content.append(f"  ${item.price}", style=DIM)
            if owned > 0:
                content.append(f"  (owned: {owned})", style=DIM)
            content.append(f"\n")

    content.append(f"\n  [UP/DOWN] Select  [ENTER] Buy  [ESC] Back", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title="[bold]Poke Mart[/bold]",
        padding=(1, 2),
    )


def render_move_learn(pokemon: Pokemon, new_move_name: str, selection: int) -> Panel:
    """Render the move learning screen when a Pokemon tries to learn a new move."""
    content = Text()
    content.append(f"  {pokemon.name} wants to learn {new_move_name}!\n", style=f"bold {WHITE}")
    content.append(f"  But {pokemon.name} already knows 4 moves.\n\n", style=CREAM)
    content.append(f"  Choose a move to forget:\n\n", style=WHITE)

    for i, move in enumerate(pokemon.moves):
        if i == selection:
            content.append(f"  > {move.name} ", style=f"bold {WHITE}")
            content.append_text(build_type_badge(move.type))
            content.append(f"  Pow:{move.power} Acc:{move.accuracy} PP:{move.max_pp}\n", style=CREAM)
        else:
            content.append(f"    {move.name} ", style=DIM)
            content.append_text(build_type_badge(move.type))
            content.append(f"\n")

    # Option to not learn
    if selection == len(pokemon.moves):
        content.append(f"\n  > Don't learn {new_move_name}\n", style=f"bold {WHITE}")
    else:
        content.append(f"\n    Don't learn {new_move_name}\n", style=DIM)

    content.append(f"\n  [UP/DOWN] Select  [ENTER] Confirm", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title="[bold]New Move![/bold]",
        padding=(1, 2),
    )


def render_evolution(pokemon: Pokemon, new_species_name: str) -> Panel:
    """Render evolution screen."""
    content = Text()
    content.append(f"\n  What? {pokemon.name} is evolving!\n\n", style=f"bold {WHITE}")
    content.append(f"  {pokemon.name}  -->  ", style=YELLOW)
    content.append(f"{new_species_name}\n\n", style=f"bold {GREEN}")
    content.append(f"  [ENTER] Continue  [B] Cancel", style=DIM)

    return Panel(
        content,
        border_style=f"bold {YELLOW}",
        title="[bold]Evolution![/bold]",
        padding=(1, 2),
    )


def render_message(title: str, message: str) -> Panel:
    """Render a simple message panel."""
    content = Text()
    content.append(f"\n  {message}\n\n", style=WHITE)
    content.append(f"  [ENTER] Continue", style=DIM)

    return Panel(
        content,
        border_style=BORDER,
        title=f"[bold]{title}[/bold]",
        padding=(1, 2),
    )


def render_catch_animation(pokemon_name: str, shakes: int, caught: bool, phase: int) -> Panel:
    """Render the catch attempt animation."""
    content = Text()
    content.append(f"\n  You threw a Poke Ball!\n\n", style=WHITE)

    ball_frames = ["  ●", "   ●", "  ●", " ●"]
    for i in range(min(phase, 3)):
        if i < shakes or (i == shakes - 1 and not caught and phase > shakes):
            content.append(f"  {ball_frames[i % len(ball_frames)]}  ... shake!\n", style=YELLOW)
        elif i < phase:
            content.append(f"  {ball_frames[i % len(ball_frames)]}  ... broke free!\n", style=RED)

    if phase > shakes and not caught:
        content.append(f"\n  Oh no! {pokemon_name} broke free!\n", style=RED)
    elif phase > 3 and caught:
        content.append(f"\n  Gotcha! {pokemon_name} was caught!\n", style=f"bold {GREEN}")

    content.append(f"\n  [ENTER] Continue", style=DIM)

    return Panel(
        content,
        border_style=f"bold {YELLOW}",
        title="[bold]Catch![/bold]",
        padding=(1, 2),
    )
