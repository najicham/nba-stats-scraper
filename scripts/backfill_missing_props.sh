#!/bin/bash
# ============================================================================
# File: scripts/backfill_missing_props.sh
# ============================================================================
# Odds API Props - Local Backfill Script
# ============================================================================
# Purpose: Backfill missing playoff props data locally
# Usage: ./backfill_missing_props.sh [--phase PHASE] [--dry-run]
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PHASE="${1:-all}"  # all, 2024-25, 2023-24, 2022-23
DRY_RUN="${2:-false}"

# Scraper service URL (required for scraper phase)
SCRAPER_SERVICE_URL="${SCRAPER_SERVICE_URL:-https://nba-scraper-service-YOUR_ID.us-west2.run.app}"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Odds API Props - Missing Data Backfill${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# ============================================================================
# Phase 1A: 2024-25 Playoffs (DEN vs LAC First Round)
# ============================================================================
if [[ "$PHASE" == "all" || "$PHASE" == "2024-25" ]]; then
  echo -e "${GREEN}Phase 1A: 2024-25 Playoffs (DEN vs LAC)${NC}"
  echo "Priority: 🔴 CRITICAL"
  echo "Games: 7 games from April-May 2025"
  echo ""
  
  DATES_2025="2025-04-19,2025-04-21,2025-04-24,2025-04-26,2025-04-29,2025-05-01,2025-05-03"
  
  if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo -e "${YELLOW}[DRY RUN] Would scrape props for dates: ${DATES_2025}${NC}"
    ./bin/run_backfill.sh scrapers/odds_api_props \
      --dates="${DATES_2025}" \
      --dry-run
  else
    echo -e "${GREEN}Step 1: Scraping props from Odds API...${NC}"
    ./bin/run_backfill.sh scrapers/odds_api_props \
      --dates="${DATES_2025}"
    
    echo ""
    echo -e "${GREEN}Step 2: Processing scraped files to BigQuery...${NC}"
    ./bin/run_backfill.sh raw/odds_api_props \
      --dates="${DATES_2025}"
    
    echo ""
    echo -e "${GREEN}✅ Phase 1A Complete!${NC}"
    echo "Run validation query to verify:"
    echo "  bq query --use_legacy_sql=false @validation/queries/raw/odds_api_props/verify_playoff_completeness.sql"
  fi
  
  echo ""
fi

# ============================================================================
# Phase 1B: 2023-24 Playoffs (PHX-MIN + LAC-DAL)
# ============================================================================
if [[ "$PHASE" == "all" || "$PHASE" == "2023-24" ]]; then
  echo -e "${GREEN}Phase 1B: 2023-24 Playoffs${NC}"
  echo "Priority: 🔴 HIGH"
  echo ""
  
  # PHX vs MIN (4 games)
  echo "  Series 1: PHX vs MIN (4 games)"
  DATES_PHX_MIN="2024-04-20,2024-04-23,2024-04-26,2024-04-28"
  
  # LAC vs DAL (6 games)  
  echo "  Series 2: LAC vs DAL (6 games)"
  DATES_LAC_DAL="2024-04-21,2024-04-23,2024-04-26,2024-04-28,2024-05-01,2024-05-03"
  
  # Combined dates (some overlap)
  DATES_2024="2024-04-20,2024-04-21,2024-04-23,2024-04-26,2024-04-28,2024-05-01,2024-05-03"
  
  if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo -e "${YELLOW}[DRY RUN] Would scrape props for dates: ${DATES_2024}${NC}"
    ./bin/run_backfill.sh scrapers/odds_api_props \
      --dates="${DATES_2024}" \
      --dry-run
  else
    echo -e "${GREEN}Step 1: Scraping props from Odds API...${NC}"
    ./bin/run_backfill.sh scrapers/odds_api_props \
      --dates="${DATES_2024}"
    
    echo ""
    echo -e "${GREEN}Step 2: Processing scraped files to BigQuery...${NC}"
    ./bin/run_backfill.sh raw/odds_api_props \
      --dates="${DATES_2024}"
    
    echo ""
    echo -e "${GREEN}✅ Phase 1B Complete!${NC}"
    echo "Run validation query to verify:"
    echo "  bq query --use_legacy_sql=false @validation/queries/raw/odds_api_props/verify_playoff_completeness.sql"
  fi
  
  echo ""
fi

# ============================================================================
# Phase 2: 2022-23 Playoffs (Optional - if API has data)
# ============================================================================
if [[ "$PHASE" == "all" || "$PHASE" == "2022-23" ]]; then
  echo -e "${YELLOW}Phase 2: 2022-23 Playoffs (OPTIONAL)${NC}"
  echo "Priority: 🟡 MEDIUM"
  echo "Note: Older data - may not be available in Odds API"
  echo ""
  
  # Play-In + Conference Semifinals
  DATES_2023="2023-04-11,2023-04-12,2023-04-14,2023-04-29,2023-04-30,2023-05-01,2023-05-02,2023-05-05,2023-05-07,2023-05-09,2023-05-11"
  
  if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo -e "${YELLOW}[DRY RUN] Would attempt to scrape props for dates: ${DATES_2023}${NC}"
    echo -e "${YELLOW}Testing with first 3 dates only...${NC}"
    ./bin/run_backfill.sh scrapers/odds_api_props \
      --dates="2023-04-11,2023-04-12,2023-04-14" \
      --dry-run
  else
    echo -e "${YELLOW}Testing API availability with first 3 dates...${NC}"
    ./bin/run_backfill.sh scrapers/odds_api_props \
      --dates="2023-04-11,2023-04-12,2023-04-14"
    
    echo ""
    read -p "Did the test succeed? Continue with remaining dates? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      echo -e "${GREEN}Step 1: Scraping remaining dates...${NC}"
      ./bin/run_backfill.sh scrapers/odds_api_props \
        --dates="2023-04-29,2023-04-30,2023-05-01,2023-05-02,2023-05-05,2023-05-07,2023-05-09,2023-05-11"
      
      echo ""
      echo -e "${GREEN}Step 2: Processing all scraped files to BigQuery...${NC}"
      ./bin/run_backfill.sh raw/odds_api_props \
        --dates="${DATES_2023}"
      
      echo ""
      echo -e "${GREEN}✅ Phase 2 Complete!${NC}"
    else
      echo -e "${YELLOW}Skipped remaining dates for 2022-23 season${NC}"
    fi
  fi
  
  echo ""
fi

# ============================================================================
# Summary and Next Steps
# ============================================================================
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Backfill Summary${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  echo -e "${YELLOW}DRY RUN COMPLETE - No data was processed${NC}"
  echo ""
  echo "To run for real:"
  echo "  ./backfill_missing_props.sh [all|2024-25|2023-24|2022-23]"
else
  echo -e "${GREEN}Backfill complete!${NC}"
  echo ""
  echo "Next steps:"
  echo ""
  echo "1. Validate playoff coverage:"
  echo "   bq query --use_legacy_sql=false < validation/queries/raw/odds_api_props/verify_playoff_completeness.sql"
  echo ""
  echo "2. Check for any remaining gaps:"
  echo "   bq query --use_legacy_sql=false < validation/queries/raw/odds_api_props/find_missing_games.sql"
  echo ""
  echo "3. Verify specific teams (PHX, LAC, DAL):"
  echo "   bq query --use_legacy_sql=false \\"
  echo "     'SELECT game_date, home_team_abbr, away_team_abbr, COUNT(DISTINCT player_name) as players"
  echo "      FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`"
  echo "      WHERE (home_team_abbr IN (\"PHX\",\"LAC\",\"DAL\") OR away_team_abbr IN (\"PHX\",\"LAC\",\"DAL\"))"
  echo "        AND game_date >= \"2024-04-20\""
  echo "      GROUP BY game_date, home_team_abbr, away_team_abbr"
  echo "      ORDER BY game_date'"
fi

echo ""
echo -e "${BLUE}================================================${NC}"

# ============================================================================
# Usage Examples
# ============================================================================
: <<'USAGE'

Usage Examples:

1. Dry run to see what would be processed:
   ./backfill_missing_props.sh all --dry-run
   ./backfill_missing_props.sh 2024-25 --dry-run

2. Backfill specific phase:
   ./backfill_missing_props.sh 2024-25
   ./backfill_missing_props.sh 2023-24
   ./backfill_missing_props.sh 2022-23

3. Backfill everything:
   ./backfill_missing_props.sh all

4. Just test 2022-23 (oldest data):
   ./backfill_missing_props.sh 2022-23 --dry-run

USAGE
