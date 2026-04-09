# News Terminal Scripts

Terminal-based news display using [newsboat](https://newsboat.org/) RSS feeds and [Rich](https://github.com/Textualize/rich) for rendering.

## Scripts

| Script | Description |
|---|---|
| `newsboat-newspaper.py` | Full-screen newspaper layout with two-column article panels. Navigate with keyboard, open articles in browser. |
| `newsboat-ticker.py` | Smooth scrolling headline ticker at the bottom of the terminal (Python/Rich version). |
| `newsboat-ticker.sh` | Lightweight scrolling headline ticker (bash version, no Python dependency). |

## Prerequisites

- **newsboat** - RSS feed reader
- **Python 3** - for the Python scripts
- **sqlite3** CLI - for the bash ticker script (usually pre-installed)

### Install newsboat

```bash
# macOS
brew install newsboat

# Debian/Ubuntu
sudo apt install newsboat
```

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure RSS feeds

Copy the `urls` file to newsboat's config directory:

```bash
mkdir -p ~/.newsboat
cp urls ~/.newsboat/urls
```

Or add your own feeds to `~/.newsboat/urls` (one URL per line).

### 3. Initial feed sync

Run an initial reload so newsboat populates its cache:

```bash
newsboat -x reload
```

## Usage

```bash
# Newspaper view
python3 newsboat-newspaper.py

# Ticker (Python)
python3 newsboat-ticker.py

# Ticker (bash)
./newsboat-ticker.sh
```

### Newspaper controls

| Key | Action |
|---|---|
| `w` / `s` | Navigate up / down |
| `a` / `d` | Previous / next page |
| `e` | Jump to first page |
| `Enter` | Open article in browser |
| `q` | Quit |

## How it works

All scripts read from newsboat's SQLite cache at `~/.newsboat/cache.db`. Feeds are automatically reloaded every 5 minutes. The ticker shows headlines from the last 30 minutes, falling back to the 10 most recent if none are that fresh.
