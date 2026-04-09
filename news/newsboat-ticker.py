#!/usr/bin/env python3
"""Smooth scrolling news ticker using Rich Live display."""

import os
import sqlite3
import subprocess
import sys
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

CACHE_DB = os.path.expanduser("~/.newsboat/cache.db")
CHARS_PER_SEC = 8         # text speed (characters per second)
RELOAD_INTERVAL = 300     # seconds between feed reloads
SEPARATOR = "     \u25c6     "
FPS = 60                  # render frame rate
EDGE_WIDTH = 3            # characters to fade at each edge

ORANGE_R, ORANGE_G, ORANGE_B = 255, 175, 0


def get_headlines():
    try:
        conn = sqlite3.connect(CACHE_DB)
        cur = conn.cursor()

        cur.execute(
            "SELECT strftime('%H:%M', i.pubDate, 'unixepoch', 'localtime')"
            " || '  ' || i.title || '  (' || f.title || ')'"
            " FROM rss_item i"
            " JOIN rss_feed f ON i.feedurl = f.rssurl"
            " WHERE i.pubDate >= strftime('%s', 'now', '-30 minutes')"
            " ORDER BY i.pubDate DESC"
        )
        rows = cur.fetchall()

        if not rows:
            cur.execute(
                "SELECT strftime('%H:%M', i.pubDate, 'unixepoch', 'localtime')"
                " || '  ' || i.title || '  (' || f.title || ')'"
                " FROM rss_item i"
                " JOIN rss_feed f ON i.feedurl = f.rssurl"
                " ORDER BY i.pubDate DESC LIMIT 10"
            )
            rows = cur.fetchall()

        conn.close()
        return SEPARATOR.join(r[0] for r in rows) + SEPARATOR if rows else ""
    except Exception:
        return ""


def build_ticker_line(display, progress, width):
    """Build a Rich Text object with edge fading."""
    text = Text(" ")

    left_end = min(EDGE_WIDTH, width)
    right_start = max(left_end, width - EDGE_WIDTH)

    # Left fading zone
    for i in range(left_end):
        b = max(0.0, min(1.0, (i + 1.0 - progress) / EDGE_WIDTH))
        r = int(ORANGE_R * b)
        g = int(ORANGE_G * b)
        text.append(display[i], style=f"bold rgb({r},{g},0)")

    # Middle — full brightness
    if right_start > left_end:
        text.append(display[left_end:right_start], style=f"bold rgb({ORANGE_R},{ORANGE_G},{ORANGE_B})")

    # Right fading zone
    for i in range(right_start, width):
        i_from_right = width - 1 - i
        b = max(0.0, min(1.0, (i_from_right + progress) / EDGE_WIDTH))
        r = int(ORANGE_R * b)
        g = int(ORANGE_G * b)
        text.append(display[i], style=f"bold rgb({r},{g},0)")

    text.append(" ")
    return text


def main():
    console = Console()
    char_interval = 1.0 / CHARS_PER_SEC
    frame_interval = 1.0 / FPS

    ticker_text = ""
    doubled = ""
    pos = 0
    last_reload = 0.0

    now = time.monotonic()
    next_frame = now
    next_char = now + 2.0

    with Live(console=console, refresh_per_second=FPS, screen=True, vertical_overflow="visible") as live:
        while True:
            now = time.monotonic()

            # Reload feeds periodically
            if now - last_reload >= RELOAD_INTERVAL:
                try:
                    subprocess.run(
                        ["newsboat", "-x", "reload"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except FileNotFoundError:
                    pass
                ticker_text = get_headlines()
                doubled = ticker_text + ticker_text
                pos = 0
                last_reload = now
                next_char = now + char_interval

            if not ticker_text:
                ticker_text = get_headlines()
                doubled = ticker_text + ticker_text
                next_char = now + 2.0

            if not ticker_text:
                time.sleep(1)
                continue

            text_len = len(ticker_text)
            width = console.width - 2

            # Advance character position when due
            if now >= next_char:
                pos = (pos + 1) % text_len
                next_char += char_interval
                if next_char < now:
                    next_char = now + char_interval

            # Sub-frame progress
            progress = 1.0 - max(0.0, min(1.0, (next_char - now) / char_interval))

            display = doubled[pos: pos + width]
            if len(display) < width:
                display = display.ljust(width)

            # Build ticker and position at bottom
            rows = console.height
            padding = Text("\n" * (rows - 2))
            ticker = build_ticker_line(display, progress, width)

            # Update display
            output = Text()
            output.append_text(padding)
            output.append_text(ticker)
            live.update(output)

            # Frame timing
            next_frame += frame_interval
            sleep_time = next_frame - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_frame = time.monotonic()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
