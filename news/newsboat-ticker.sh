#!/bin/bash
# newsboat-ticker.sh — scrolling news ticker at the bottom of the terminal

CACHE_DB="${HOME}/.newsboat/cache.db"
SCROLL_SPEED=0.1        # seconds per character (lower = faster)
RELOAD_INTERVAL=300     # reload feeds every N seconds
SEPARATOR="     ◆     "
first_frame=true

get_headlines() {
  local result=""
  while IFS= read -r line; do
    result+="${line}${SEPARATOR}"
  done < <(sqlite3 "$CACHE_DB" \
    "SELECT strftime('%H:%M', i.pubDate, 'unixepoch', 'localtime') || '  ' || i.title || '  (' || f.title || ')'
     FROM rss_item i
     JOIN rss_feed f ON i.feedurl = f.rssurl
     WHERE i.pubDate >= strftime('%s', 'now', '-30 minutes')
     ORDER BY i.pubDate DESC;" 2>/dev/null)

  # Fallback to latest 10 if nothing in the last 30 minutes
  if [[ -z "$result" ]]; then
    while IFS= read -r line; do
      result+="${line}${SEPARATOR}"
    done < <(sqlite3 "$CACHE_DB" \
      "SELECT strftime('%H:%M', i.pubDate, 'unixepoch', 'localtime') || '  ' || i.title || '  (' || f.title || ')'
       FROM rss_item i
       JOIN rss_feed f ON i.feedurl = f.rssurl
       ORDER BY i.pubDate DESC LIMIT 10;" 2>/dev/null)
  fi

  echo "$result"
}
# Save terminal state and hide cursor
tput smcup
tput civis

# Cache terminal dimensions, update on resize
cols=$(tput cols)
rows=$(tput lines)
update_dims() { cols=$(tput cols); rows=$(tput lines); }
trap 'update_dims' WINCH
trap 'tput rmcup; tput cnorm; exit' INT TERM EXIT

last_reload=0
ticker_text=""
doubled=""
pos=0

while true; do
  now=$SECONDS

  # Reload feeds and refresh headlines periodically
  if (( now - last_reload >= RELOAD_INTERVAL )); then
    newsboat -x reload &>/dev/null
    ticker_text=$(get_headlines)
    ticker_text="${ticker_text}${SEPARATOR}"
    doubled="${ticker_text}${ticker_text}"
    pos=0
    last_reload=$now
  fi

  # Initial load if empty
  if [[ -z "$ticker_text" ]]; then
    ticker_text=$(get_headlines)
    ticker_text="${ticker_text}${SEPARATOR}"
    doubled="${ticker_text}${ticker_text}"
  fi

  len=${#ticker_text}
  width=$(( cols - 2 ))

  # Slice from pre-doubled string (no branching needed)
  printf '\e[%d;0H\e[K\e[%d;0H\e[K\e[38;5;214m\e[1m %-*s \e[0m' \
    $(( rows - 1 )) "$rows" "$width" "${doubled:pos:width}"
  pos=$(( (pos + 1) % len ))
  if $first_frame; then
    sleep 2
    first_frame=false
  else
    sleep "$SCROLL_SPEED"
  fi
done