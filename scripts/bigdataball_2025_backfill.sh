#!/bin/bash
# BigDataBall 2025-26 Season Backfill Script - SIMPLIFIED
# Downloads all play-by-play data from BigDataBall Google Drive

export PYTHONPATH=/home/naji/code/nba-stats-scraper
export BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH=/home/naji/code/nba-stats-scraper/keys/bigdataball-service-account.json

LOG_FILE="/tmp/bigdataball_2025_backfill.log"
echo "Starting BigDataBall 2025-26 backfill at $(date)" > $LOG_FILE

# Date range: 2025-10-21 to 2025-12-16
START_DATE="2025-10-21"
END_DATE="2025-12-16"

total_games=0
failed_games=0

current_date="$START_DATE"
while [[ "$current_date" < "$END_DATE" ]] || [[ "$current_date" == "$END_DATE" ]]; do
    echo "" >> $LOG_FILE
    echo "=== Processing $current_date ===" >> $LOG_FILE
    echo "Processing $current_date..."

    # Discover games for this date
    .venv/bin/python scrapers/bigdataball/bigdataball_discovery.py --date=$current_date 2>/dev/null

    # Extract game IDs
    game_ids=$(.venv/bin/python -c "
import json
try:
    with open('/tmp/bigdataball_discovery_${current_date}.json', 'r') as f:
        data = json.load(f)
        games = data.get('results', {}).get('games', [])
        if not games:
            games = data.get('games', [])
        for g in games:
            gid = g.get('game_id', '')
            if gid:
                print(gid)
except:
    pass
" 2>/dev/null)

    if [ -z "$game_ids" ]; then
        echo "No games found for $current_date" >> $LOG_FILE
    else
        for game_id in $game_ids; do
            echo "  Downloading $game_id..." >> $LOG_FILE

            if .venv/bin/python scrapers/bigdataball/bigdataball_pbp.py --game_id=$game_id --group=prod 2>/dev/null; then
                echo "    SUCCESS: $game_id" >> $LOG_FILE
                total_games=$((total_games + 1))
            else
                echo "    FAILED: $game_id" >> $LOG_FILE
                failed_games=$((failed_games + 1))
            fi

            # Rate limit
            sleep 2
        done
    fi

    # Move to next day
    current_date=$(date -d "$current_date + 1 day" +%Y-%m-%d)
done

echo "" >> $LOG_FILE
echo "========================================" >> $LOG_FILE
echo "BACKFILL COMPLETE" >> $LOG_FILE
echo "Total games downloaded: $total_games" >> $LOG_FILE
echo "Failed games: $failed_games" >> $LOG_FILE
echo "Finished at $(date)" >> $LOG_FILE

echo "DONE! Total: $total_games, Failed: $failed_games"
