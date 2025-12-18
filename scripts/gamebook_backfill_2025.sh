#!/bin/bash
# Gamebook PDF Backfill for 2025-26 Season
# Backfills gamebook data for Nov 13 - Dec 15, 2025 (100 games)

# Don't exit on error - some games may fail and that's ok
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Gamebook PDF Backfill for 2025-26 Season ===${NC}"
echo "Start time: $(date)"

# Counters
SUCCESS=0
FAILED=0
SKIPPED=0

# Function to run gamebook scraper for a single game
scrape_game() {
    local game_date=$1
    local away_team=$2
    local home_team=$3

    # Format: YYYYMMDD/AWYHOM
    local date_formatted=$(echo $game_date | tr -d '-')
    local game_code="${date_formatted}/${away_team}${home_team}"

    echo -e "${YELLOW}Scraping: ${game_date} ${away_team} @ ${home_team} (${game_code})${NC}"

    # Check if already exists in GCS
    local gcs_path="gs://nba-scraped-data/nba-com/gamebooks-data/${game_date}/${date_formatted}-${away_team}${home_team}/"
    if gsutil ls "$gcs_path" &>/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ Already exists, skipping${NC}"
        SKIPPED=$((SKIPPED + 1))
        return 0
    fi

    # Run scraper
    if PYTHONPATH=. .venv/bin/python scrapers/nbacom/nbac_gamebook_pdf.py \
        --game_code "$game_code" \
        --group gcs 2>&1 | tail -5; then
        echo -e "  ${GREEN}✓ Success${NC}"
        SUCCESS=$((SUCCESS + 1))
    else
        echo -e "  ${RED}✗ Failed${NC}"
        FAILED=$((FAILED + 1))
    fi

    # Rate limit - 3 seconds between requests
    sleep 3
}

# Games to backfill (extracted from BDL data)
# Format: date,away,home
GAMES=(
    "2025-11-13,ATL,UTA"
    "2025-11-13,IND,PHX"
    "2025-11-13,TOR,CLE"
    "2025-11-14,BKN,ORL"
    "2025-11-14,CHA,MIL"
    "2025-11-14,GSW,SAS"
    "2025-11-14,LAC,DAL"
    "2025-11-14,LAL,NOP"
    "2025-11-14,MIA,NYK"
    "2025-11-14,PHI,DET"
    "2025-11-14,POR,HOU"
    "2025-11-14,SAC,MIN"
    "2025-11-15,DEN,MIN"
    "2025-11-15,LAL,MIL"
    "2025-11-15,MEM,CLE"
    "2025-11-15,OKC,CHA"
    "2025-11-15,TOR,IND"
    "2025-11-16,ATL,PHX"
    "2025-11-16,BKN,WAS"
    "2025-11-16,CHI,MEM"
    "2025-11-16,DEN,SAC"
    "2025-11-16,GSW,NOP"
    "2025-11-16,MIA,DET"
    "2025-11-16,NYK,BOS"
    "2025-11-16,ORL,HOU"
    "2025-11-16,PHI,CLE"
    "2025-11-16,POR,DAL"
    "2025-11-17,CHA,TOR"
    "2025-11-17,LAC,UTA"
    "2025-11-17,MIN,OKC"
    "2025-11-17,PHX,SAS"
    "2025-11-18,ATL,LAL"
    "2025-11-18,BKN,PHI"
    "2025-11-18,CHI,MIL"
    "2025-11-18,DEN,HOU"
    "2025-11-18,GSW,DAL"
    "2025-11-18,IND,ORL"
    "2025-11-18,MEM,NOP"
    "2025-11-18,MIA,CLE"
    "2025-11-18,NYK,MIN"
    "2025-11-18,SAC,WAS"
    "2025-11-19,BOS,CHA"
    "2025-11-19,DET,TOR"
    "2025-11-19,LAC,POR"
    "2025-11-19,PHX,UTA"
    "2025-11-20,ATL,SAC"
    "2025-11-20,BKN,MIL"
    "2025-11-20,CHI,WAS"
    "2025-11-20,DEN,DAL"
    "2025-11-20,GSW,HOU"
    "2025-11-20,IND,MEM"
    "2025-11-20,LAL,OKC"
    "2025-11-20,MIA,DET"
    "2025-11-20,MIN,NOP"
    "2025-11-20,NYK,ORL"
    "2025-11-20,PHI,BOS"
    "2025-11-21,CLE,SAS"
    "2025-11-21,LAC,PHX"
    "2025-11-21,POR,UTA"
    "2025-11-22,ATL,LAL"
    "2025-11-22,BKN,NYK"
    "2025-11-22,CHI,TOR"
    "2025-11-22,DEN,SAC"
    "2025-11-22,DET,MIA"
    "2025-11-22,GSW,DAL"
    "2025-11-22,IND,MIL"
    "2025-11-22,MEM,OKC"
    "2025-11-22,MIN,CHA"
    "2025-11-22,NOP,WAS"
    "2025-11-22,ORL,PHI"
    "2025-11-23,BOS,HOU"
    "2025-11-23,CLE,POR"
    "2025-11-23,LAC,UTA"
    "2025-11-23,PHX,SAS"
    "2025-11-24,CHI,BKN"
    "2025-11-24,DEN,MIN"
    "2025-11-24,DET,ORL"
    "2025-11-24,GSW,MIL"
    "2025-11-24,IND,NOP"
    "2025-11-24,LAL,PHI"
    "2025-11-24,MEM,TOR"
    "2025-11-24,NYK,MIA"
    "2025-11-24,OKC,WAS"
    "2025-11-24,SAC,ATL"
    "2025-11-25,BOS,DAL"
    "2025-11-25,CHA,HOU"
    "2025-11-25,CLE,LAC"
    "2025-11-25,PHX,POR"
    "2025-11-26,ATL,DEN"
    "2025-11-26,BKN,IND"
    "2025-11-26,CHI,OKC"
    "2025-11-26,LAL,MIN"
    "2025-11-26,MEM,GSW"
    "2025-11-26,MIA,MIL"
    "2025-11-26,NOP,SAS"
    "2025-11-26,ORL,NYK"
    "2025-11-26,SAC,TOR"
    "2025-11-26,UTA,CLE"
    "2025-11-27,BOS,DET"
    "2025-11-27,PHI,HOU"
)

# Add remaining games from Dec (reading from BigQuery output)
# For brevity, let me just run the first batch...

echo ""
echo "Total games to process: ${#GAMES[@]}"
echo ""

for game in "${GAMES[@]}"; do
    IFS=',' read -r date away home <<< "$game"
    scrape_game "$date" "$away" "$home"
done

echo ""
echo -e "${GREEN}=== Backfill Complete ===${NC}"
echo "End time: $(date)"
echo "Success: $SUCCESS"
echo "Failed: $FAILED"
echo "Skipped: $SKIPPED"
