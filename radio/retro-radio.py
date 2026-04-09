#!/usr/bin/env python3.12
"""Norsk Radio — Terminalbasert radiospiller for norske stasjoner."""

import atexit
import csv
import json
import os
import random
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import termios
import tty

# ──────────────────────────────────────────────────────────
#  Stations (loaded from stations.csv)
# ──────────────────────────────────────────────────────────

def load_stations():
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stations.csv")
    stations = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] != "name":
                stations.append((row[0].strip(), row[1].strip()))
    return stations

STATIONS = load_stations()

# ──────────────────────────────────────────────────────────
#  True-color ANSI (1960s vinyl palette)
# ──────────────────────────────────────────────────────────

RST  = "\033[0m"
BOLD = "\033[1m"

def _c(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"

CREAM  = _c(253, 246, 227)
AMBER  = _c(218, 165, 32)
GOLD   = _c(255, 200, 80)
RUST   = _c(183, 65, 14)
BROWN  = _c(160, 110, 60)
OLIVE  = _c(140, 155, 60)
DIM    = _c(100, 75, 55)
FRAME  = _c(150, 115, 70)
BG_SEL = "\033[48;2;50;35;25m"

_STRIP = re.compile(r"\033\[[^m]*m")

def _vlen(s):
    return len(_STRIP.sub("", s))

def _pad(s, w):
    return s + " " * max(0, w - _vlen(s))

TITLE_TEXT = "N O R S K    R A D I O"
TITLE_W   = len(TITLE_TEXT) + 4  # inner width of title badge

# ──────────────────────────────────────────────────────────
#  Fuzzy search
# ──────────────────────────────────────────────────────────

def fuzzy_match(query, text):
    q, t = query.lower(), text.lower()
    qi, score, prev = 0, 0, -2
    for ti, ch in enumerate(t):
        if qi < len(q) and ch == q[qi]:
            score += 1
            if ti == prev + 1:
                score += 3
            if ti == 0 or t[ti - 1] in " -_":
                score += 2
            prev = ti
            qi += 1
    if qi < len(q):
        return False, 0
    return True, score + max(0, 30 - len(t))

search   = ""
filtered = list(range(len(STATIONS)))
cur      = 0
scroll   = 0

def refilter():
    global filtered, cur, scroll
    if not search:
        filtered = list(range(len(STATIONS)))
    else:
        results = []
        for i, (name, _) in enumerate(STATIONS):
            ok, sc = fuzzy_match(search, name)
            if ok:
                results.append((sc, i))
        results.sort(key=lambda x: -x[0])
        filtered = [i for _, i in results]
        cur = 0
    if filtered:
        cur = min(cur, len(filtered) - 1)
    else:
        cur = 0
    scroll = 0

# ──────────────────────────────────────────────────────────
#  Player state
# ──────────────────────────────────────────────────────────

proc       = None
now        = None
now_title  = ""     # ICY stream title (artist — song)
now_vu     = ""     # VU dots — generated once per station change
player     = None
_done      = False
_ipc_path  = os.path.join(tempfile.gettempdir(), f"norsk-radio-{os.getpid()}.sock")
_tick       = 0       # incremented each draw, drives the marquee

_FADE1 = _c(60, 45, 32)   # near-invisible
_FADE2 = _c(80, 60, 42)   # slightly visible

def _marquee(text, width):
    """Scroll text with faded edges for smooth appearance."""
    if len(text) <= width:
        return f"{DIM}{text}{RST}"
    sep = "   \u00b7   "  # " · " gap between loops
    padded = text + sep + text
    cycle = len(text) + len(sep)
    offset = _tick % cycle
    visible = padded[offset:offset + width]
    # Fade edges: 2 chars on each side dim → very dim
    parts = []
    for i, ch in enumerate(visible):
        if i == 0 or i == width - 1:
            parts.append(f"{_FADE1}{ch}")
        elif i == 1 or i == width - 2:
            parts.append(f"{_FADE2}{ch}")
        else:
            parts.append(f"{DIM}{ch}")
    return "".join(parts) + RST

def find_player():
    for name in ("mpv", "ffplay"):
        if shutil.which(name):
            return name
    return None

def stop():
    global proc, now, now_title, now_vu
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc = None
    now = None
    now_title = ""
    now_vu = ""
    try:
        os.unlink(_ipc_path)
    except OSError:
        pass

def play(idx):
    global proc, now, now_title, now_vu
    stop()
    now_title = ""
    now_vu = " ".join(random.choice("\u25cf\u25cb") for _ in range(8))
    url = STATIONS[idx][1]
    if player == "mpv":
        cmd = [player, "--no-video", "--really-quiet",
               f"--input-ipc-server={_ipc_path}", url]
    else:
        cmd = [player, "-nodisp", "-loglevel", "quiet", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    now = idx

def get_media_title():
    """Query mpv IPC socket for the current stream title."""
    global now_title
    if player != "mpv" or not os.path.exists(_ipc_path):
        return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.1)
        s.connect(_ipc_path)
        cmd = json.dumps({"command": ["get_property", "media-title"]}) + "\n"
        s.sendall(cmd.encode())
        data = s.recv(4096).decode("utf-8", errors="replace")
        s.close()
        for line in data.strip().split("\n"):
            try:
                resp = json.loads(line)
                if "data" in resp and isinstance(resp["data"], str):
                    title = resp["data"]
                    # Filter out URLs, filenames, and stream IDs
                    if (title and title != STATIONS[now][1]
                            and not title.startswith("http")
                            and "/" not in title
                            and " " in title  # real titles have spaces
                            and "_mp3" not in title.lower()
                            and "_aac" not in title.lower()
                            and "_mh" not in title.lower()
                            and not title.endswith((".mp3", ".aac", ".ogg"))):
                        now_title = title
                    return
            except (json.JSONDecodeError, TypeError):
                continue
    except (OSError, ConnectionRefusedError, TimeoutError):
        pass

def check():
    global proc, now, now_title
    if proc is not None and proc.poll() is not None:
        proc = None
        now = None
        now_title = ""
    elif now is not None:
        get_media_title()

# ──────────────────────────────────────────────────────────
#  Terminal
# ──────────────────────────────────────────────────────────

_old_termios = None

def enter_raw():
    global _old_termios
    fd = sys.stdin.fileno()
    _old_termios = termios.tcgetattr(fd)
    tty.setcbreak(fd)

def restore_term():
    if _old_termios is not None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _old_termios)

def enter_alt():
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()

def leave_alt():
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()

def cleanup():
    global _done
    if _done:
        return
    _done = True
    stop()
    restore_term()
    leave_alt()

def getkey():
    # Wait up to 0.2s for input — allows smooth marquee scrolling
    if not select.select([sys.stdin], [], [], 0.2)[0]:
        return None  # timeout, no key pressed
    ch = sys.stdin.read(1)
    if ch == "\033":
        ch2 = sys.stdin.read(1)
        if ch2 == "[":
            ch3 = sys.stdin.read(1)
            if ch3 == "A":
                return "up"
            if ch3 == "B":
                return "down"
            return None
        return "esc"
    return ch

# ──────────────────────────────────────────────────────────
#  UI
# ──────────────────────────────────────────────────────────

VIS = 8   # stations visible at a time

# ── Speaker grille ──
SPKR_COL = _c(120, 90, 60)
# Braille rows for the speaker body (20 chars each, centered in frame)
_S_TOP = f"  \u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4\u28e4  "  # ⣤ rounded top
_S_MID = f" \u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff "   # ⣿ full fill
_S_BOT = f"  \u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b\u281b  "  # ⠛ rounded bottom
_S_VW  = len(_S_MID)  # 24 — visual width of braille content

# Speaker frame adds ┌─┐ │ └─┘ around braille (SPKR_VW = _S_VW + 2)
SPKR_VW = _S_VW + 2  # 26
_SPKR_PAD = "    "  # left margin inside outer ║

def _spkr_frame_top():
    return f"{_SPKR_PAD}{FRAME}\u250c{'\u2500' * _S_VW}\u2510{RST}"

def _spkr_frame_bot():
    return f"{_SPKR_PAD}{FRAME}\u2514{'\u2500' * _S_VW}\u2518{RST}"

def _spkr_row(braille):
    return f"{_SPKR_PAD}{FRAME}\u2502{RST}{SPKR_COL}{braille}{RST}{FRAME}\u2502{RST}"

# Full speaker visual width including padding: _SPKR_PAD(4) + │(1) + braille(24) + │(1) = 30
SPKR_FULL = len(_SPKR_PAD) + SPKR_VW  # 30

# ── Layout ──
GAP     = 4
W       = 84                           # inner width between ║ chars
RIGHT_W = W - SPKR_FULL - GAP         # 50
H_LINE  = "\u2550" * W

def draw():
    global scroll
    check()

    term_cols, term_rows = shutil.get_terminal_size()
    m = " " * max(0, (term_cols - W - 2) // 2)
    f = FRAME
    global _tick
    _tick += 1
    has_playing = now is not None
    has_search = bool(search)

    # Centered cursor scrolling
    total = len(filtered)
    if total <= VIS:
        scroll = 0
    else:
        half = VIS // 2
        if cur <= half:
            scroll = 0
        elif cur >= total - (VIS - half):
            scroll = total - VIS
        else:
            scroll = cur - half
    vis_start = scroll
    vis_end = min(scroll + VIS, total)

    vu = now_vu if has_playing else ""
    gap_s = " " * GAP
    box_w = RIGHT_W - 8  # inner width for sub-boxes

    # Helper: compose a full row — ║ left+gap+right ║
    def row(left, rt=""):
        content = f"{left}{gap_s}{rt}"
        return f"{m}{f}\u2551{RST}{_pad(content, W)}{f}\u2551{RST}"

    # ── Build rows as (speaker_str, right_str) pairs ──
    lines = []
    blank_sp = " " * SPKR_FULL
    spkr_top = _spkr_frame_top()
    spkr_mid = _spkr_row(_S_MID)
    spkr_r_top = _spkr_row(_S_TOP)
    spkr_r_bot = _spkr_row(_S_BOT)
    spkr_bot = _spkr_frame_bot()

    # Title block — embossed badge
    badge_top = f"    {f}\u2554{'\u2550' * TITLE_W}\u2557{RST}"
    badge_mid = f"    {f}\u2551{RST}  {AMBER}{BOLD}{TITLE_TEXT}{RST}  {f}\u2551{RST}"
    badge_bot = f"    {f}\u255a{'\u2550' * TITLE_W}\u255d{RST}"
    lines.append((blank_sp,   ""))
    lines.append((spkr_top,   badge_top))
    lines.append((spkr_r_top, badge_mid))
    lines.append((spkr_mid,   badge_bot))
    lines.append((spkr_mid,   ""))

    # Now playing (always 5 rows: top border, station, track, VU, bottom border)
    np_box_top = f"    {f}\u2554{'\u2550' * box_w}\u2557{RST}"
    np_box_bot = f"    {f}\u255a{'\u2550' * box_w}\u255d{RST}"
    if has_playing:
        eye = f"{OLIVE}(\u25c9){RST}"
        np_str = f"  {AMBER}\u266a  {CREAM}{STATIONS[now][0]}{RST}"
        if now_title:
            trk = f"  {_marquee(now_title, box_w - 4)}"
        else:
            trk = ""
        vu_str = f"  {BROWN}{vu}{RST}    {eye}"
        lines.append((spkr_mid, np_box_top))
        lines.append((spkr_mid, f"    {f}\u2551{RST}{_pad(np_str, box_w)}{f}\u2551{RST}"))
        lines.append((spkr_mid, f"    {f}\u2551{RST}{_pad(trk, box_w)}{f}\u2551{RST}"))
        lines.append((spkr_mid, f"    {f}\u2551{RST}{_pad(vu_str, box_w)}{f}\u2551{RST}"))
        lines.append((spkr_mid, np_box_bot))
    else:
        idle = f"  {DIM}\u266a  Velg en stasjon ...{RST}"
        lines.append((spkr_mid, np_box_top))
        lines.append((spkr_mid, f"    {f}\u2551{RST}{_pad(idle, box_w)}{f}\u2551{RST}"))
        lines.append((spkr_mid, f"    {f}\u2551{RST}{' ' * box_w}{f}\u2551{RST}"))
        lines.append((spkr_mid, f"    {f}\u2551{RST}{' ' * box_w}{f}\u2551{RST}"))
        lines.append((spkr_mid, np_box_bot))

    # Separator
    sep_line = f"    {DIM}{'\u2500' * (box_w + 2)}{RST}"
    lines.append((spkr_mid, sep_line))

    # Search bar
    if has_search:
        hits = f"{DIM}{len(filtered)} treff{RST}"
        srch = f"    {DIM}/{RST} {CREAM}{search}{DIM}\u2588{RST}"
        srch_gap = max(1, RIGHT_W - 4 - _vlen(srch) - _vlen(hits))
        lines.append((spkr_mid, f"{srch}{' ' * srch_gap}{hits}"))

    # Station list
    lines.append((spkr_mid, f"    {f}\u250c{'\u2500' * box_w}\u2510{RST}"))
    if not filtered:
        lines.append((spkr_mid, f"    {f}\u2502{RST}{_pad(f'  {DIM}Ingen treff ...{RST}', box_w)}{f}\u2502{RST}"))
        for _ in range(VIS - 1):
            lines.append((spkr_mid, f"    {f}\u2502{RST}{' ' * box_w}{f}\u2502{RST}"))
    else:
        vc = vis_end - vis_start
        for vi in range(VIS):
            if vi >= vc:
                lines.append((spkr_mid, f"    {f}\u2502{RST}{' ' * box_w}{f}\u2502{RST}"))
            else:
                fi = vis_start + vi
                si = filtered[fi]
                name = STATIONS[si][0]
                is_playing = (now is not None and si == now)
                if fi == cur and is_playing:
                    ln = f"{AMBER}\u266a\u00bb{RST} {BOLD}{CREAM}{name}{RST}"
                elif fi == cur:
                    ln = f"  {AMBER}\u00bb{RST} {BOLD}{CREAM}{name}{RST}"
                elif is_playing:
                    ln = f"  {AMBER}\u266a{RST} {DIM}{name}{RST}"
                else:
                    ln = f"    {DIM}{name}{RST}"
                lines.append((spkr_mid, f"    {f}\u2502{RST}{_pad(ln, box_w)}{f}\u2502{RST}"))
    lines.append((spkr_mid, f"    {f}\u2514{'\u2500' * box_w}\u2518{RST}"))

    lines.append((spkr_mid, ""))

    # Controls
    if has_search:
        ctrl = (f"  {DIM}[{RST}{AMBER}\u2191\u2193{RST}{DIM}]{RST} {BROWN}Velg{RST}"
                f" {DIM}\u00b7{RST} "
                f"{DIM}[{RST}{AMBER}\u23ce{RST}{DIM}]{RST} {BROWN}Spill{RST}"
                f" {DIM}\u00b7{RST} "
                f"{DIM}[{RST}{AMBER}esc{RST}{DIM}]{RST} {BROWN}Nullstill{RST}")
    else:
        ctrl = (f"  {DIM}[{RST}{AMBER}\u2191\u2193{RST}{DIM}]{RST} {BROWN}Velg{RST}"
                f" {DIM}\u00b7{RST} "
                f"{DIM}[{RST}{AMBER}\u23ce{RST}{DIM}]{RST} {BROWN}Spill{RST}"
                f" {DIM}\u00b7{RST} "
                f"{DIM}[{RST}{AMBER}s{RST}{DIM}]{RST} {BROWN}Stopp{RST}"
                f" {DIM}\u00b7{RST} "
                f"{DIM}[{RST}{AMBER}q{RST}{DIM}]{RST} {BROWN}Avslutt{RST}")
    lines.append((spkr_r_bot, ctrl))
    lines.append((spkr_bot,  ""))
    lines.append((blank_sp,  ""))

    # ── Compose output ──
    box_h = len(lines) + 2
    v_pad = max(0, (term_rows - box_h) // 2)
    b = [""] * v_pad

    b.append(f"{m}{f}\u2554{H_LINE}\u2557{RST}")
    for sp, rt in lines:
        b.append(row(sp, rt))
    b.append(f"{m}{f}\u255a{H_LINE}\u255d{RST}")

    sys.stdout.write("\033[H\033[J" + "\n".join(b) + "\n")
    sys.stdout.flush()

# ──────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────

def on_signal(sig, frame):
    cleanup()
    print(f"\n  {DIM}Ha det!{RST}\n")
    sys.exit(0)

def main():
    global player, search, cur

    player = find_player()
    if not player:
        print(f"\n  {RUST}Feil:{RST} Finner verken {CREAM}mpv{RST} eller {CREAM}ffplay{RST}!")
        print(f"  Installer med: {AMBER}brew install mpv{RST}\n")
        sys.exit(1)

    enter_alt()
    enter_raw()
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, on_signal)

    while True:
        draw()
        key = getkey()

        if search:
            if key == "esc":
                search = ""
                refilter()
            elif key in ("\x7f", "\x08"):
                search = search[:-1]
                refilter()
            elif key == "up":
                if filtered:
                    cur = (cur - 1) % len(filtered)
            elif key == "down":
                if filtered:
                    cur = (cur + 1) % len(filtered)
            elif key in ("\r", "\n"):
                if filtered:
                    si = filtered[cur]
                    play(si)
                    search = ""
                    refilter()
                    cur = si
            elif key is not None and len(key) == 1 and key.isprintable():
                search += key
                refilter()
        else:
            if key in ("q", "esc"):
                break
            elif key == "s":
                stop()
            elif key == "up":
                cur = (cur - 1) % len(filtered)
            elif key == "down":
                cur = (cur + 1) % len(filtered)
            elif key in ("\r", "\n"):
                if filtered:
                    play(filtered[cur])
            elif key is not None and len(key) == 1 and key.isprintable():
                search += key
                refilter()

    cleanup()
    print(f"\n  {DIM}Ha det!{RST}\n")

if __name__ == "__main__":
    main()
