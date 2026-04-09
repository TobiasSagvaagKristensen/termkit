#!/usr/bin/env python3
"""News newspaper display using Rich."""

import html
import os
import re
import select
import sqlite3
import subprocess
import sys
import termios
import time
import tty
import webbrowser

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

CACHE_DB = os.path.expanduser("~/.newsboat/cache.db")
RELOAD_INTERVAL = 300
ARTICLES_PER_PAGE = 10

ORANGE_R, ORANGE_G, ORANGE_B = 255, 175, 0
ORANGE = f"rgb({ORANGE_R},{ORANGE_G},{ORANGE_B})"


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_key():
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        if select.select([sys.stdin], [], [], 0.01)[0]:
            ch2 = sys.stdin.read(1)
            if ch2 == "[" and select.select([sys.stdin], [], [], 0.01)[0]:
                ch3 = sys.stdin.read(1)
                return {"A": "up", "B": "down"}.get(ch3)
        return "escape"
    elif ch in ("\r", "\n"):
        return "enter"
    elif ch == "\x03":
        return "ctrl-c"
    return ch


def get_articles(offset=0, limit=ARTICLES_PER_PAGE):
    try:
        conn = sqlite3.connect(CACHE_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT i.title, i.content, f.title,"
            " strftime('%H:%M', i.pubDate, 'unixepoch', 'localtime'),"
            " i.pubDate, i.url"
            " FROM rss_item i"
            " JOIN rss_feed f ON i.feedurl = f.rssurl"
            " ORDER BY i.pubDate DESC"
            f" LIMIT {limit} OFFSET {offset}"
        )
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def build_header(width):
    header = Text()
    header.append("NYHETER", style=f"bold {ORANGE}")
    header.append("  \u2502  ", style="dim")
    header.append(time.strftime("%A %d. %B %Y  %H:%M"), style="dim")
    return Panel(
        header,
        border_style=ORANGE,
        width=width,
        padding=(0, 1),
    )


def build_footer(width, page):
    footer = Text()
    footer.append("  w/s", style=ORANGE)
    footer.append(" navigate  ", style="dim")
    footer.append("a/d", style=ORANGE)
    footer.append(" prev/next page  ", style="dim")
    footer.append("e", style=ORANGE)
    footer.append(" first page  ", style="dim")
    footer.append("\u21b5", style=ORANGE)
    footer.append(" open in browser  ", style="dim")
    footer.append("q", style=ORANGE)
    footer.append(" quit", style="dim")
    footer.append(f"  \u2502  ", style="dim")
    footer.append(f"page {page + 1}", style="dim")
    return Panel(
        footer,
        border_style="rgb(80,80,80)",
        width=width,
        padding=(0, 1),
    )


def build_newspaper(articles, width, selected, max_height):
    if not articles:
        return Text("No articles available", style="dim")

    col_width = (width - 4) // 2
    display_count = min(ARTICLES_PER_PAGE, len(articles))

    # Each panel row is ~8 lines; figure out how many rows fit
    rows_that_fit = max(1, max_height // 8)
    selected_row = selected // 2
    total_rows = (display_count + 1) // 2

    # Scroll to keep selected visible
    scroll = max(0, min(selected_row - rows_that_fit // 2, total_rows - rows_that_fit))
    start = scroll * 2
    end = min(display_count, (scroll + rows_that_fit) * 2)

    left_items = []
    right_items = []

    for idx in range(start, end):
        title, content, source, t, _, url = articles[idx]
        ingress = strip_html(content)
        if len(ingress) > 200:
            ingress = ingress[:197] + "..."

        article = Text()
        article.append(f"{t} ", style="dim")
        article.append(f"{title}\n", style=f"bold {ORANGE}")
        if ingress:
            article.append(f"{ingress}\n", style="")
        article.append(source, style="dim italic")

        border = ORANGE if idx == selected else "rgb(80,80,80)"

        panel = Panel(
            article,
            width=col_width,
            border_style=border,
            padding=(0, 1),
        )

        if idx % 2 == 0:
            left_items.append(panel)
        else:
            right_items.append(panel)

    table = Table.grid(padding=(0, 1))
    table.add_column(width=col_width)
    table.add_column(width=col_width)

    max_rows = max(len(left_items), len(right_items))
    for i in range(max_rows):
        left = left_items[i] if i < len(left_items) else ""
        right = right_items[i] if i < len(right_items) else ""
        table.add_row(left, right)

    return table


def main():
    console = Console()
    articles = []
    last_reload = 0.0
    selected = 0
    page = 0

    old_term = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin)

    try:
        with Live(console=console, refresh_per_second=10, screen=True) as live:
            while True:
                now = time.monotonic()

                if now - last_reload >= RELOAD_INTERVAL:
                    try:
                        subprocess.run(
                            ["newsboat", "-x", "reload"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    except FileNotFoundError:
                        pass
                    page = 0
                    articles = get_articles(offset=0)
                    selected = 0
                    last_reload = now

                if not articles:
                    articles = get_articles(offset=0)

                if not articles:
                    time.sleep(1)
                    continue

                key = read_key()
                display_count = len(articles)
                if key in ("w", "up"):
                    if selected > 0:
                        selected -= 1
                    elif page > 0:
                        page -= 1
                        articles = get_articles(offset=page * ARTICLES_PER_PAGE)
                        selected = len(articles) - 1
                elif key in ("s", "down"):
                    if selected < display_count - 1:
                        selected += 1
                    else:
                        next_articles = get_articles(offset=(page + 1) * ARTICLES_PER_PAGE)
                        if next_articles:
                            page += 1
                            articles = next_articles
                            selected = 0
                elif key in ("a", "left"):
                    if page > 0:
                        page -= 1
                        articles = get_articles(offset=page * ARTICLES_PER_PAGE)
                        selected = 0
                elif key in ("d", "right"):
                    next_articles = get_articles(offset=(page + 1) * ARTICLES_PER_PAGE)
                    if next_articles:
                        page += 1
                        articles = next_articles
                        selected = 0
                elif key == "e":
                    if page != 0:
                        page = 0
                        articles = get_articles(offset=0)
                        selected = 0
                elif key == "enter":
                    if selected < len(articles):
                        url = articles[selected][5]
                        if url:
                            webbrowser.open(url)
                elif key in ("q", "ctrl-c", "escape"):
                    break

                header = build_header(console.width)
                newspaper = build_newspaper(articles, console.width, selected, console.height - 8)
                footer = build_footer(console.width, page)
                live.update(Group(header, newspaper, footer))

                time.sleep(0.05)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
