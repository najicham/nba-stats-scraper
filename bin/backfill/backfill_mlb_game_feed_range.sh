#!/bin/bash
# Backfill per-pitch MLB game feed data over a date range.
#
# Runs the scraper locally (--group test → /tmp/), uploads each date's JSON to
# GCS, then invokes the processor to write into mlb_raw.mlb_game_feed_pitches.
# Idempotent: processor does scoped DELETE per (game_date, game_pk) before insert.
#
# Usage:
#   ./bin/backfill/backfill_mlb_game_feed_range.sh 2025-03-27 2025-10-31
#   ./bin/backfill/backfill_mlb_game_feed_range.sh 2025-04-01 2025-04-03 3   # 3s sleep
#
# Args:
#   $1  START_DATE (YYYY-MM-DD)  required
#   $2  END_DATE   (YYYY-MM-DD)  required
#   $3  SLEEP_SEC  between dates  default 2

set -u

START_DATE="${1:?start date required (YYYY-MM-DD)}"
END_DATE="${2:?end date required (YYYY-MM-DD)}"
SLEEP_SEC="${3:-2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs
LOG_FILE="logs/backfill_mlb_game_feed_${START_DATE}_${END_DATE}_$(date +%Y%m%d_%H%M%S).log"

echo "=============================================="
echo "MLB Per-Pitch Game Feed Backfill"
echo "=============================================="
echo "Range: $START_DATE -> $END_DATE"
echo "Sleep between dates: ${SLEEP_SEC}s"
echo "Log: $LOG_FILE"
echo ""

# Expand date range (macOS vs GNU date compatibility not needed — Linux only)
CURRENT="$START_DATE"
TOTAL_PITCHES=0
TOTAL_DATES=0
SKIPPED_DATES=0
ERROR_DATES=0

{
  echo "Backfill started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Range: $START_DATE -> $END_DATE"
  echo ""
} >> "$LOG_FILE"

while [[ "$CURRENT" < "$END_DATE" || "$CURRENT" == "$END_DATE" ]]; do
  TOTAL_DATES=$((TOTAL_DATES + 1))
  echo "=== [$TOTAL_DATES] $CURRENT ==="

  {
    echo ""
    echo "=== [$TOTAL_DATES] $CURRENT === $(date -u +%H:%M:%SZ)"
  } >> "$LOG_FILE"

  # --- Scrape ---
  # Writes to /tmp/mlb_game_feed_daily_{date}_{ts}.json (--group test)
  SPORT=mlb PYTHONPATH=. .venv/bin/python3 \
    scrapers/mlb/mlbstatsapi/mlb_game_feed_daily.py \
    --date "$CURRENT" --group test >> "$LOG_FILE" 2>&1

  FILE=$(ls -t /tmp/mlb_game_feed_daily_${CURRENT}_*.json 2>/dev/null | head -1)
  if [[ -z "$FILE" ]]; then
    echo "  !! scraper produced no file — skipping"
    echo "  ERROR: no file for $CURRENT" >> "$LOG_FILE"
    ERROR_DATES=$((ERROR_DATES + 1))
    # Advance date and continue
    CURRENT=$(date -I -d "$CURRENT + 1 day")
    sleep "$SLEEP_SEC"
    continue
  fi

  # Parse pitch count (off-day detection)
  PITCHES=$(python3 -c "import json; print(json.load(open('$FILE')).get('total_pitches', 0))" 2>/dev/null || echo "0")
  GAMES=$(python3 -c "import json; print(json.load(open('$FILE')).get('games_processed', 0))" 2>/dev/null || echo "0")

  if [[ "$PITCHES" == "0" ]]; then
    echo "  -- off day (0 games) — skipping upload"
    echo "  off day: 0 pitches" >> "$LOG_FILE"
    SKIPPED_DATES=$((SKIPPED_DATES + 1))
    # Clean up empty file to keep /tmp tidy
    rm -f "$FILE"
    CURRENT=$(date -I -d "$CURRENT + 1 day")
    sleep "$SLEEP_SEC"
    continue
  fi

  # --- Upload to GCS ---
  TS=$(basename "$FILE" | sed "s/.*${CURRENT}_//;s/.json//")
  GCS_PATH="mlb-stats-api/game-feed-daily/${CURRENT}/${TS}.json"
  if ! gsutil -q cp "$FILE" "gs://nba-scraped-data/$GCS_PATH" 2>>"$LOG_FILE"; then
    echo "  !! GCS upload failed"
    echo "  ERROR: gsutil cp failed" >> "$LOG_FILE"
    ERROR_DATES=$((ERROR_DATES + 1))
    CURRENT=$(date -I -d "$CURRENT + 1 day")
    sleep "$SLEEP_SEC"
    continue
  fi

  # --- Process into BQ ---
  if SPORT=mlb PYTHONPATH=. .venv/bin/python3 \
      data_processors/raw/mlb/mlb_game_feed_processor.py \
      --file-path "$GCS_PATH" --date "$CURRENT" --force >> "$LOG_FILE" 2>&1; then
    echo "  ok  games=$GAMES pitches=$PITCHES"
    TOTAL_PITCHES=$((TOTAL_PITCHES + PITCHES))
    rm -f "$FILE"  # clean up once processed
  else
    echo "  !! processor failed"
    echo "  ERROR: processor non-zero exit" >> "$LOG_FILE"
    ERROR_DATES=$((ERROR_DATES + 1))
  fi

  sleep "$SLEEP_SEC"
  CURRENT=$(date -I -d "$CURRENT + 1 day")
done

echo ""
echo "=============================================="
echo "Backfill complete"
echo "=============================================="
echo "Dates processed: $TOTAL_DATES"
echo "Off-days skipped: $SKIPPED_DATES"
echo "Errors: $ERROR_DATES"
echo "Total pitches: $TOTAL_PITCHES"
echo "Log: $LOG_FILE"

{
  echo ""
  echo "Backfill ended: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Dates: $TOTAL_DATES, Off-days: $SKIPPED_DATES, Errors: $ERROR_DATES, Pitches: $TOTAL_PITCHES"
} >> "$LOG_FILE"
