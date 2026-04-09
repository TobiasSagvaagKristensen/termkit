#!/usr/bin/env python3
"""Pokemon Terminal Edition — A CLI Pokemon game."""

from __future__ import annotations

import atexit
import random
import signal
import sys
import termios
import time
import tty

from rich.console import Console
from rich.live import Live

from data import load_all
from models import Pokemon, MoveInstance, create_pokemon
from state import (
    GameState, Screen, BattleState,
    save_game, load_game, has_save,
)
from battle import (
    execute_move, ai_choose_move, get_turn_order, attempt_run,
)
from capture import attempt_catch, generate_wild_encounter
from shop import buy_item, use_healing_item, get_ball_modifier, get_shop_items
from ui import (
    read_key, render_title, render_starter_select, render_main_menu,
    render_explore, render_walking, render_encounter, render_battle,
    render_battle_result, render_team, render_shop, render_move_learn,
    render_evolution, render_message, render_catch_animation,
)

# ──────────────────────────────────────────────────────────
#  Game data (loaded once at startup)
# ──────────────────────────────────────────────────────────

MOVE_DB: dict = {}
SPECIES_DB: dict = {}
ITEM_DB: dict = {}
ZONE_DB: dict = {}
SPRITE_DB: dict = {}

STARTER_IDS = [1, 4, 7]  # Bulbasaur, Charmander, Squirtle
STARTER_LEVEL = 5

# ──────────────────────────────────────────────────────────
#  Terminal setup
# ──────────────────────────────────────────────────────────

_old_settings = None


def setup_terminal():
    global _old_settings
    if not sys.stdin.isatty():
        return
    _old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())


def restore_terminal():
    if _old_settings and sys.stdin.isatty():
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _old_settings)


def cleanup(*_):
    restore_terminal()
    sys.exit(0)


# ──────────────────────────────────────────────────────────
#  Screen handlers
# ──────────────────────────────────────────────────────────


def handle_title(state: GameState, key: str | None) -> None:
    if key == "enter":
        state.screen = Screen.STARTER_SELECT
        state.menu_selection = 0
    elif key == "l" and has_save():
        loaded = load_game(SPECIES_DB, MOVE_DB)
        if loaded:
            state.team = loaded.team
            state.inventory = loaded.inventory
            state.money = loaded.money
            state.current_zone = loaded.current_zone
            state.screen = Screen.MAIN_MENU
            state.menu_selection = 0
    elif key in ("q", "ctrl-c"):
        cleanup()


def handle_starter_select(state: GameState, key: str | None) -> None:
    if key == "up":
        state.menu_selection = (state.menu_selection - 1) % 3
    elif key == "down":
        state.menu_selection = (state.menu_selection + 1) % 3
    elif key == "enter":
        species_id = STARTER_IDS[state.menu_selection]
        starter = create_pokemon(SPECIES_DB[species_id], STARTER_LEVEL, MOVE_DB)
        state.team.append(starter)
        state.add_item("pokeball", 5)
        state.screen = Screen.MAIN_MENU
        state.menu_selection = 0


def handle_main_menu(state: GameState, key: str | None) -> None:
    options = ["explore", "team", "shop", "save", "quit"]
    if key == "up":
        state.menu_selection = (state.menu_selection - 1) % len(options)
    elif key == "down":
        state.menu_selection = (state.menu_selection + 1) % len(options)
    elif key == "enter":
        choice = options[state.menu_selection]
        if choice == "explore":
            state.screen = Screen.EXPLORE
            state.zone_selection = 0
        elif choice == "team":
            state.screen = Screen.TEAM
            state.team_selection = 0
        elif choice == "shop":
            state.screen = Screen.SHOP
            state.shop_selection = 0
        elif choice == "save":
            save_game(state)
            state.message_queue.append("Game saved!")
        elif choice == "quit":
            cleanup()
    elif key in ("q", "ctrl-c"):
        cleanup()


def handle_explore(state: GameState, key: str | None) -> None:
    zone_list = list(ZONE_DB.keys())
    if key == "up":
        state.zone_selection = (state.zone_selection - 1) % len(zone_list)
    elif key == "down":
        state.zone_selection = (state.zone_selection + 1) % len(zone_list)
    elif key == "enter":
        state.current_zone = zone_list[state.zone_selection]
        state.encounter_steps = 0
        state.steps_to_encounter = random.randint(3, 8)
        state.screen = Screen.ENCOUNTER
    elif key in ("escape", "q"):
        state.screen = Screen.MAIN_MENU
        state.menu_selection = 0


def handle_encounter_walk(state: GameState, key: str | None) -> bool:
    """Handle walking in grass. Returns True if wild encounter triggered."""
    if key == "enter":
        state.encounter_steps += 1
        if state.encounter_steps >= state.steps_to_encounter:
            return True
    elif key in ("escape", "q"):
        state.screen = Screen.EXPLORE
        state.zone_selection = 0
    return False


def start_wild_battle(state: GameState, wild: Pokemon) -> None:
    """Initialize a wild battle."""
    player = state.active_pokemon()
    if player is None:
        state.message_queue.append("All your Pokemon have fainted! Visit the shop to heal.")
        state.screen = Screen.MAIN_MENU
        return

    state.battle = BattleState(
        player_pokemon=player,
        opponent_pokemon=wild,
        is_wild=True,
        messages=[f"A wild {wild.name} appeared!"],
    )
    state.screen = Screen.BATTLE


def handle_battle(state: GameState, key: str | None, live: Live) -> None:
    """Handle battle input and logic."""
    battle = state.battle
    if battle is None:
        state.screen = Screen.MAIN_MENU
        return

    if battle.battle_over:
        if key == "enter":
            finish_battle(state, live)
        return

    # Process messages queue first
    if not battle.awaiting_input:
        return

    if battle.menu_mode == "action":
        handle_battle_action_menu(state, key, live)
    elif battle.menu_mode == "fight":
        handle_battle_fight_menu(state, key, live)
    elif battle.menu_mode == "bag":
        handle_battle_bag_menu(state, key, live)
    elif battle.menu_mode == "pokemon":
        handle_battle_pokemon_menu(state, key, live)


def handle_battle_action_menu(state: GameState, key: str | None, live: Live) -> None:
    battle = state.battle
    if key == "up" or key == "down":
        battle.selected_move = (battle.selected_move + (2 if key == "down" else -2)) % 4
    elif key == "left" or key == "right":
        row = battle.selected_move // 2
        col = 1 - (battle.selected_move % 2)
        battle.selected_move = row * 2 + col
    elif key == "enter":
        actions = ["fight", "bag", "pokemon", "run"]
        action = actions[battle.selected_move]

        if action == "fight":
            battle.menu_mode = "fight"
            battle.selected_move = 0
        elif action == "bag":
            battle.menu_mode = "bag"
            battle.selected_move = 0
        elif action == "pokemon":
            battle.menu_mode = "pokemon"
            battle.selected_move = 0
        elif action == "run":
            if battle.is_wild:
                if attempt_run(battle.player_pokemon, battle.opponent_pokemon):
                    battle.messages.append("Got away safely!")
                    state.battle = None
                    state.screen = Screen.EXPLORE
                    state.encounter_steps = 0
                    state.steps_to_encounter = random.randint(3, 8)
                else:
                    battle.messages.append("Can't escape!")
                    execute_ai_turn(state, live)
            else:
                battle.messages.append("Can't run from a trainer battle!")


def handle_battle_fight_menu(state: GameState, key: str | None, live: Live) -> None:
    battle = state.battle
    plr = battle.player_pokemon
    num_moves = len(plr.moves)

    if key == "up":
        battle.selected_move = (battle.selected_move - 1) % num_moves
    elif key == "down":
        battle.selected_move = (battle.selected_move + 1) % num_moves
    elif key == "escape":
        battle.menu_mode = "action"
        battle.selected_move = 0
    elif key == "enter":
        move_idx = battle.selected_move
        if plr.moves[move_idx].current_pp <= 0:
            battle.messages.append("No PP left for this move!")
            return

        execute_battle_turn(state, move_idx, live)


def handle_battle_bag_menu(state: GameState, key: str | None, live: Live) -> None:
    battle = state.battle
    bag_items = get_battle_bag_items(state)

    if not bag_items:
        if key:
            battle.menu_mode = "action"
            battle.selected_move = 0
        return

    if key == "up":
        battle.selected_move = (battle.selected_move - 1) % len(bag_items)
    elif key == "down":
        battle.selected_move = (battle.selected_move + 1) % len(bag_items)
    elif key == "escape":
        battle.menu_mode = "action"
        battle.selected_move = 0
    elif key == "enter":
        item, _ = bag_items[battle.selected_move]
        ball_mod = get_ball_modifier(item)

        if ball_mod is not None:
            # Capture attempt
            if not battle.is_wild:
                battle.messages.append("Can't use that in a trainer battle!")
                return
            state.remove_item(item.id)
            caught, shakes = attempt_catch(battle.opponent_pokemon, ball_mod)

            # Show catch animation
            console = live.console
            for phase in range(shakes + 2):
                panel = render_catch_animation(
                    battle.opponent_pokemon.name, shakes, caught, phase
                )
                display(live, console, panel)
                time.sleep(0.6)

            if caught:
                battle.caught = True
                battle.battle_over = True
                battle.player_won = True
                if len(state.team) < 6:
                    state.team.append(battle.opponent_pokemon)
                    battle.messages.append(f"{battle.opponent_pokemon.name} was added to your team!")
                else:
                    battle.messages.append(f"Your team is full! {battle.opponent_pokemon.name} was released.")
            else:
                battle.messages.append(f"Oh no! {battle.opponent_pokemon.name} broke free!")
                execute_ai_turn(state, live)

            battle.menu_mode = "action"
            battle.selected_move = 0

        elif item.category == "healing":
            success, msg = use_healing_item(item, battle.player_pokemon)
            battle.messages.append(msg)
            if success:
                state.remove_item(item.id)
                execute_ai_turn(state, live)
            battle.menu_mode = "action"
            battle.selected_move = 0


def handle_battle_pokemon_menu(state: GameState, key: str | None, live: Live) -> None:
    battle = state.battle
    if key == "up":
        battle.selected_move = (battle.selected_move - 1) % len(state.team)
    elif key == "down":
        battle.selected_move = (battle.selected_move + 1) % len(state.team)
    elif key == "escape":
        battle.menu_mode = "action"
        battle.selected_move = 0
    elif key == "enter":
        selected = state.team[battle.selected_move]
        if selected is battle.player_pokemon:
            battle.messages.append(f"{selected.name} is already in battle!")
        elif selected.is_fainted:
            battle.messages.append(f"{selected.name} has fainted!")
        else:
            battle.messages.append(f"Come back, {battle.player_pokemon.name}!")
            battle.messages.append(f"Go, {selected.name}!")
            battle.player_pokemon = selected
            battle.menu_mode = "action"
            battle.selected_move = 0
            execute_ai_turn(state, live)


def get_battle_bag_items(state: GameState) -> list:
    """Get items available in battle as (Item, count) pairs."""
    items = []
    for item_id, count in sorted(state.inventory.items()):
        if item_id in ITEM_DB:
            item = ITEM_DB[item_id]
            if item.category in ("capture", "healing"):
                items.append((item, count))
    return items


def execute_battle_turn(state: GameState, player_move_idx: int, live: Live) -> None:
    """Execute a full battle turn (player + AI)."""
    battle = state.battle
    plr = battle.player_pokemon
    opp = battle.opponent_pokemon

    # Determine turn order
    first, second = get_turn_order(plr, opp)

    if first is plr:
        # Player goes first
        msgs = execute_move(plr, opp, player_move_idx)
        battle.messages.extend(msgs)
        show_battle_update(state, live)

        if opp.is_fainted:
            handle_opponent_fainted(state, live)
            return

        # AI turn
        ai_move = ai_choose_move(opp, plr)
        msgs = execute_move(opp, plr, ai_move)
        battle.messages.extend(msgs)
        show_battle_update(state, live)

        if plr.is_fainted:
            handle_player_pokemon_fainted(state, live)
            return
    else:
        # AI goes first
        ai_move = ai_choose_move(opp, plr)
        msgs = execute_move(opp, plr, ai_move)
        battle.messages.extend(msgs)
        show_battle_update(state, live)

        if plr.is_fainted:
            handle_player_pokemon_fainted(state, live)
            return

        # Player turn
        msgs = execute_move(plr, opp, player_move_idx)
        battle.messages.extend(msgs)
        show_battle_update(state, live)

        if opp.is_fainted:
            handle_opponent_fainted(state, live)
            return

    battle.menu_mode = "action"
    battle.selected_move = 0
    battle.turn += 1


def execute_ai_turn(state: GameState, live: Live) -> None:
    """Execute just the AI's turn (after player used item/switched/failed to run)."""
    battle = state.battle
    if battle is None or battle.battle_over:
        return

    opp = battle.opponent_pokemon
    plr = battle.player_pokemon

    ai_move = ai_choose_move(opp, plr)
    msgs = execute_move(opp, plr, ai_move)
    battle.messages.extend(msgs)
    show_battle_update(state, live)

    if plr.is_fainted:
        handle_player_pokemon_fainted(state, live)


def show_battle_update(state: GameState, live: Live) -> None:
    """Update the display during battle and pause briefly."""
    console = live.console
    panel = render_battle(state.battle, state, ITEM_DB, SPRITE_DB)
    display(live, console, panel)
    time.sleep(0.8)


def handle_opponent_fainted(state: GameState, live: Live) -> None:
    """Handle opponent fainting: XP, money, level ups."""
    battle = state.battle
    opp = battle.opponent_pokemon
    plr = battle.player_pokemon

    # XP and money
    xp_gain = (opp.species.xp_yield * opp.level) // 5
    money_gain = opp.level * 10
    state.money += money_gain

    battle.messages.append(f"{plr.name} gained {xp_gain} XP!")
    events = plr.gain_xp(xp_gain)

    # Track which Pokemon is leveling up for move learn / evolution screens
    try:
        state.event_pokemon_idx = state.team.index(plr)
    except ValueError:
        state.event_pokemon_idx = 0

    for event in events:
        if event["type"] == "level_up":
            battle.messages.append(f"{plr.name} grew to level {event['level']}!")
        elif event["type"] == "new_move":
            move_id = event["move_id"]
            if move_id in MOVE_DB:
                state.pending_move_id = move_id
        elif event["type"] == "evolve":
            state.evolve_into_id = event["into"]

    battle.xp_events = events
    battle.battle_over = True
    battle.player_won = True
    show_battle_update(state, live)


def handle_player_pokemon_fainted(state: GameState, live: Live) -> None:
    """Handle player's Pokemon fainting."""
    battle = state.battle

    # Check if there's another Pokemon to send out
    next_pokemon = state.active_pokemon()
    if next_pokemon is None:
        battle.messages.append("All your Pokemon have fainted!")
        battle.battle_over = True
        battle.player_won = False
    else:
        battle.messages.append(f"Go, {next_pokemon.name}!")
        battle.player_pokemon = next_pokemon
        battle.menu_mode = "action"
        battle.selected_move = 0

    show_battle_update(state, live)


def finish_battle(state: GameState, live: Live) -> None:
    """Clean up after battle ends."""
    battle = state.battle

    if not battle.player_won:
        # Heal all Pokemon on loss
        for pkmn in state.team:
            pkmn.full_heal()
        state.screen = Screen.MAIN_MENU
        state.menu_selection = 0
        state.battle = None
        return

    # Check for pending move learning
    if state.pending_move_id and state.pending_move_id in MOVE_DB:
        pkmn = battle.player_pokemon
        move_template = MOVE_DB[state.pending_move_id]
        if len(pkmn.moves) < 4:
            pkmn.moves.append(MoveInstance(template=move_template, current_pp=move_template.pp))
            state.message_queue.append(f"{pkmn.name} learned {move_template.name}!")
            state.pending_move_id = None
        else:
            state.screen = Screen.MOVE_LEARN
            state.move_learn_selection = 0
            return

    # Check for pending evolution
    if state.evolve_into_id is not None:
        state.screen = Screen.EVOLVE
        return

    state.screen = Screen.EXPLORE
    state.encounter_steps = 0
    state.steps_to_encounter = random.randint(3, 8)
    state.battle = None


def handle_move_learn(state: GameState, key: str | None) -> None:
    """Handle the move learning screen."""
    pkmn = state.team[state.event_pokemon_idx]
    move_id = state.pending_move_id

    if move_id not in MOVE_DB:
        state.pending_move_id = None
        state.screen = Screen.BATTLE
        return

    max_selection = len(pkmn.moves)  # 0..3 = replace, 4 = don't learn

    if key == "up":
        state.move_learn_selection = (state.move_learn_selection - 1) % (max_selection + 1)
    elif key == "down":
        state.move_learn_selection = (state.move_learn_selection + 1) % (max_selection + 1)
    elif key == "enter":
        move_template = MOVE_DB[move_id]
        if state.move_learn_selection < len(pkmn.moves):
            old_name = pkmn.moves[state.move_learn_selection].name
            pkmn.moves[state.move_learn_selection] = MoveInstance(
                template=move_template, current_pp=move_template.pp
            )
            state.message_queue.append(f"{pkmn.name} forgot {old_name} and learned {move_template.name}!")
        else:
            state.message_queue.append(f"{pkmn.name} did not learn {move_template.name}.")

        state.pending_move_id = None

        # Check for evolution
        if state.evolve_into_id is not None:
            state.screen = Screen.EVOLVE
        else:
            state.screen = Screen.EXPLORE
            state.encounter_steps = 0
            state.steps_to_encounter = random.randint(3, 8)
            state.battle = None


def handle_evolution(state: GameState, key: str | None) -> None:
    """Handle evolution screen."""
    if key == "enter":
        pkmn = state.team[state.event_pokemon_idx]

        if state.evolve_into_id in SPECIES_DB:
            old_name = pkmn.name
            old_max = pkmn.max_hp
            pkmn.species = SPECIES_DB[state.evolve_into_id]
            new_max = pkmn.max_hp
            pkmn.current_hp = min(pkmn.current_hp + (new_max - old_max), new_max)
            state.message_queue.append(f"{old_name} evolved into {pkmn.species.name}!")

        state.evolve_into_id = None
        state.screen = Screen.EXPLORE
        state.encounter_steps = 0
        state.steps_to_encounter = random.randint(3, 8)
        state.battle = None

    elif key == "b":
        state.message_queue.append("Evolution was cancelled.")
        state.evolve_into_id = None
        state.screen = Screen.EXPLORE
        state.encounter_steps = 0
        state.steps_to_encounter = random.randint(3, 8)
        state.battle = None


def handle_team(state: GameState, key: str | None) -> None:
    """Handle team management screen."""
    if not state.team:
        if key:
            state.screen = Screen.MAIN_MENU
        return

    if key == "up":
        state.team_selection = (state.team_selection - 1) % len(state.team)
    elif key == "down":
        state.team_selection = (state.team_selection + 1) % len(state.team)
    elif key == "s" and len(state.team) > 1:
        # Swap mode: swap selected with next
        idx = state.team_selection
        next_idx = (idx + 1) % len(state.team)
        state.team[idx], state.team[next_idx] = state.team[next_idx], state.team[idx]
        state.team_selection = next_idx
    elif key in ("escape", "q"):
        state.screen = Screen.MAIN_MENU
        state.menu_selection = 0


def handle_shop(state: GameState, key: str | None) -> None:
    """Handle shop screen."""
    shop_items = get_shop_items(ITEM_DB)

    if key == "up":
        state.shop_selection = (state.shop_selection - 1) % len(shop_items)
    elif key == "down":
        state.shop_selection = (state.shop_selection + 1) % len(shop_items)
    elif key == "enter":
        item = shop_items[state.shop_selection]
        if buy_item(state, item):
            state.message_queue.append(f"Bought {item.name}!")
        else:
            state.message_queue.append("Not enough money!")
    elif key in ("escape", "q"):
        state.screen = Screen.MAIN_MENU
        state.menu_selection = 0


# ──────────────────────────────────────────────────────────
#  Main game loop
# ──────────────────────────────────────────────────────────


def display(live: Live, console: Console, panel: Panel):
    """Center a panel horizontally and vertically, then refresh."""
    from rich.align import Align
    centered = Align.center(panel, vertical="middle", height=console.height)
    live.update(centered)
    live.refresh()


def main():
    global MOVE_DB, SPECIES_DB, ITEM_DB, ZONE_DB, SPRITE_DB

    MOVE_DB, SPECIES_DB, ITEM_DB, ZONE_DB, SPRITE_DB = load_all()

    console = Console(force_terminal=True)
    state = GameState()

    setup_terminal()
    atexit.register(restore_terminal)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    wild_pokemon: Pokemon | None = None

    try:
        with Live(console=console, screen=True, auto_refresh=False) as live:
            while True:
                # read_key blocks for up to 0.05s, no separate sleep needed
                key = read_key()

                # Handle queued messages first
                if state.message_queue:
                    msg = state.message_queue[0]
                    display(live, console, render_message("Info", msg))
                    if key == "enter":
                        state.message_queue.pop(0)
                    continue

                # Dispatch based on screen
                if state.screen == Screen.TITLE:
                    display(live, console, render_title(has_save()))
                    if key:
                        handle_title(state, key)

                elif state.screen == Screen.STARTER_SELECT:
                    display(live, console, render_starter_select(state.menu_selection))
                    if key:
                        handle_starter_select(state, key)

                elif state.screen == Screen.MAIN_MENU:
                    display(live, console, render_main_menu(state))
                    if key:
                        handle_main_menu(state, key)

                elif state.screen == Screen.EXPLORE:
                    display(live, console, render_explore(state, ZONE_DB))
                    if key:
                        handle_explore(state, key)

                elif state.screen == Screen.ENCOUNTER:
                    zone = ZONE_DB[state.current_zone]
                    if wild_pokemon is None:
                        display(live, console, render_walking(zone, state.encounter_steps))
                        if key:
                            triggered = handle_encounter_walk(state, key)
                            if triggered:
                                wild_pokemon = generate_wild_encounter(
                                    zone.encounters, zone.level_min, zone.level_max,
                                    SPECIES_DB, MOVE_DB,
                                )
                                if wild_pokemon:
                                    display(live, console, render_encounter(wild_pokemon, SPRITE_DB))
                                    time.sleep(1.5)
                    else:
                        display(live, console, render_encounter(wild_pokemon, SPRITE_DB))
                        if key == "enter":
                            start_wild_battle(state, wild_pokemon)
                            wild_pokemon = None
                        elif key in ("escape", "q"):
                            wild_pokemon = None
                            state.encounter_steps = 0
                            state.steps_to_encounter = random.randint(3, 8)

                elif state.screen == Screen.BATTLE:
                    if state.battle:
                        if state.battle.battle_over:
                            xp_gain = 0
                            money_gain = 0
                            if state.battle.player_won and not state.battle.caught:
                                opp = state.battle.opponent_pokemon
                                xp_gain = (opp.species.xp_yield * opp.level) // 5
                                money_gain = opp.level * 10
                            display(live, console, render_battle_result(
                                state.battle, xp_gain, money_gain
                            ))
                        else:
                            display(live, console, render_battle(state.battle, state, ITEM_DB, SPRITE_DB))
                        if key:
                            handle_battle(state, key, live)

                elif state.screen == Screen.MOVE_LEARN:
                    if state.pending_move_id in MOVE_DB:
                        pkmn = state.team[state.event_pokemon_idx]
                        display(live, console, render_move_learn(
                            pkmn,
                            MOVE_DB[state.pending_move_id].name,
                            state.move_learn_selection,
                        ))
                    if key:
                        handle_move_learn(state, key)

                elif state.screen == Screen.EVOLVE:
                    if state.evolve_into_id in SPECIES_DB:
                        pkmn = state.team[state.event_pokemon_idx]
                        new_name = SPECIES_DB[state.evolve_into_id].name
                        display(live, console, render_evolution(pkmn, new_name))
                    if key:
                        handle_evolution(state, key)

                elif state.screen == Screen.TEAM:
                    display(live, console, render_team(state, SPRITE_DB))
                    if key:
                        handle_team(state, key)

                elif state.screen == Screen.SHOP:
                    shop_items = get_shop_items(ITEM_DB)
                    display(live, console, render_shop(state, shop_items))
                    if key:
                        handle_shop(state, key)

    except Exception:
        restore_terminal()
        raise


if __name__ == "__main__":
    main()
