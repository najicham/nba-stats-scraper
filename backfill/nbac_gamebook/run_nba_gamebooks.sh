#!/bin/bash

# Save as: bin/backfill/run_nba_gamebooks.sh
# NBA Gamebook PDF Scraper Runner
# Usage:
#   ./run_nba_gamebooks.sh --game_code "20240410/MEMCLE"
#   ./run_nba_gamebooks.sh --date "2024-04-10"
#   ./run_nba_gamebooks.sh --start_date "2024-04-01" --end_date "2024-04-30"
#   ./run_nba_gamebooks.sh --season "2023-24" --team "MEM"

set -e

# Default values
GAME_CODE=""
DATE=""
START_DATE=""
END_DATE=""
SEASON=""
TEAM=""
DRY_RUN=false
GROUP="prod"
PARALLEL_JOBS=3
SCHEDULE_FILE="data/nba_schedule.json"  # Your Phase 1 schedule data

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --game_code)
            GAME_CODE="$2"
            shift 2
            ;;
        --date)
            DATE="$2"
            shift 2
            ;;
        --start_date)
            START_DATE="$2"
            shift 2
            ;;
        --end_date)
            END_DATE="$2"
            shift 2
            ;;
        --season)
            SEASON="$2"
            shift 2
            ;;
        --team)
            TEAM="$2"
            shift 2
            ;;
        --group)
            GROUP="$2"
            shift 2
            ;;
        --dry_run)
            DRY_RUN=true
            shift
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --schedule_file)
            SCHEDULE_FILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "NBA Gamebook PDF Scraper Runner"
            echo ""
            echo "Usage:"
            echo "  $0 --game_code YYYYMMDD/AWAYTEAMHOMETEAM"
            echo "  $0 --date YYYY-MM-DD"
            echo "  $0 --start_date YYYY-MM-DD --end_date YYYY-MM-DD"
            echo "  $0 --season YYYY-YY [--team TEAM]"
            echo ""
            echo "Options:"
            echo "  --game_code     Single game (e.g., 20240410/MEMCLE)"
            echo "  --date          All games on specific date"
            echo "  --start_date    Start of date range"
            echo "  --end_date      End of date range"
            echo "  --season        NBA season (e.g., 2023-24)"
            echo "  --team          Filter by team (3-letter code)"
            echo "  --group         Export group (default: prod)"
            echo "  --dry_run       Show what would be run without executing"
            echo "  --parallel      Number of parallel jobs (default: 3)"
            echo "  --schedule_file Path to schedule JSON file"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Function to get game codes from schedule data
get_game_codes() {
    local filter_args=""
    
    if [[ -n "$DATE" ]]; then
        filter_args="--date $DATE"
    elif [[ -n "$START_DATE" && -n "$END_DATE" ]]; then
        filter_args="--start_date $START_DATE --end_date $END_DATE"
    elif [[ -n "$SEASON" ]]; then
        filter_args="--season $SEASON"
        if [[ -n "$TEAM" ]]; then
            filter_args="$filter_args --team $TEAM"
        fi
    fi
    
    # Use the separate Python helper script  
    python3 scripts/query_schedule.py --schedule_file "$SCHEDULE_FILE" $filter_args
}
import json
import sys
from datetime import datetime

def load_schedule(filename):
    with open('$SCHEDULE_FILE', 'r') as f:
        return json.load(f)

def filter_games(games, date=None, start_date=None, end_date=None, season=None, team=None):
    filtered = []
    
    for game in games:
        game_date = game.get('date', '')
        away_team = game.get('away_team', '')
        home_team = game.get('home_team', '')
        game_season = game.get('season', '')
        
        # Date filtering
        if date and game_date != date:
            continue
        if start_date and game_date < start_date:
            continue
        if end_date and game_date > end_date:
            continue
        if season and season not in game_season:
            continue
        if team and team not in [away_team, home_team]:
            continue
            
        filtered.append(game)
    
    return filtered

try:
    schedule = load_schedule('$SCHEDULE_FILE')
    
    # Apply filters based on arguments
    filtered_games = schedule
    if '$DATE':
        filtered_games = filter_games(filtered_games, date='$DATE')
    elif '$START_DATE' and '$END_DATE':
        filtered_games = filter_games(filtered_games, start_date='$START_DATE', end_date='$END_DATE')
    elif '$SEASON':
        filtered_games = filter_games(filtered_games, season='$SEASON', team='$TEAM' if '$TEAM' else None)
    
    # Output game codes
    for game in filtered_games:
        print(game.get('game_code', ''))
        
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
"
}

# Function to run single scraper
run_scraper() {
    local game_code="$1"
    local job_id=$((RANDOM % 10000))
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting $game_code (job $job_id)"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "DRY RUN: Would execute: python -m scrapers.nbacom.nbac_gamebook_pdf --group $GROUP --game_code \"$game_code\""
        return 0
    fi
    
    # Run the scraper
    if python -m scrapers.nbacom.nbac_gamebook_pdf --group "$GROUP" --game_code "$game_code"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Completed $game_code (job $job_id)"
        return 0
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Failed $game_code (job $job_id)"
        return 1
    fi
}

# Main execution
main() {
    echo "NBA Gamebook PDF Scraper Runner"
    echo "==============================="
    
    # Validate inputs
    if [[ -z "$GAME_CODE" && -z "$DATE" && -z "$START_DATE" && -z "$SEASON" ]]; then
        echo "Error: Must specify --game_code, --date, --start_date/--end_date, or --season"
        exit 1
    fi
    
    if [[ -n "$START_DATE" && -z "$END_DATE" ]] || [[ -z "$START_DATE" && -n "$END_DATE" ]]; then
        echo "Error: Both --start_date and --end_date must be specified together"
        exit 1
    fi
    
    # Check if schedule file exists
    if [[ ! -f "$SCHEDULE_FILE" ]]; then
        echo "Error: Schedule file not found: $SCHEDULE_FILE"
        echo "Make sure you've run Phase 1 (schedule collection) first"
        exit 1
    fi
    
    # Get list of game codes to process
    if [[ -n "$GAME_CODE" ]]; then
        # Single game
        game_codes=("$GAME_CODE")
    else
        # Multiple games from schedule
        echo "Loading games from schedule..."
        mapfile -t game_codes < <(get_game_codes)
        
        if [[ ${#game_codes[@]} -eq 0 ]]; then
            echo "No games found matching criteria"
            exit 1
        fi
    fi
    
    echo "Found ${#game_codes[@]} games to process"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "DRY RUN MODE - showing first 10 games:"
        for i in "${!game_codes[@]}"; do
            if [[ $i -lt 10 ]]; then
                echo "  $((i+1)). ${game_codes[i]}"
            fi
        done
        [[ ${#game_codes[@]} -gt 10 ]] && echo "  ... and $((${#game_codes[@]} - 10)) more"
        exit 0
    fi
    
    # Process games
    echo "Starting scraper with $PARALLEL_JOBS parallel jobs..."
    
    # Export function for parallel execution
    export -f run_scraper
    export GROUP DRY_RUN
    
    # Use GNU parallel if available, otherwise run sequentially
    if command -v parallel >/dev/null 2>&1; then
        printf '%s\n' "${game_codes[@]}" | parallel -j "$PARALLEL_JOBS" run_scraper {}
    else
        echo "GNU parallel not found, running sequentially..."
        for game_code in "${game_codes[@]}"; do
            run_scraper "$game_code"
        done
    fi
    
    echo "All games completed!"
}

# Run main function
main "$@"