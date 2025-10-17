#!/bin/bash
# =============================================================================
# File: scripts/quick_start_props_backfill.sh
# =============================================================================
# Quick Start: Odds API Props Backfill
# =============================================================================
# Purpose: One-command solution to identify, backfill, and validate props data
# Usage: ./quick_start_props_backfill.sh
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}Odds API Props - Quick Start Backfill${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

# =============================================================================
# Step 1: Identify Missing Data
# =============================================================================
echo -e "${GREEN}STEP 1: Identifying Missing Data${NC}"
echo "Running validation queries..."
echo ""

# Save baseline
echo "📊 Generating gap analysis report..."
./scripts/validate-odds-props gaps > baseline_gaps_$(date +%Y%m%d_%H%M%S).txt
echo "   Saved to: baseline_gaps_*.txt"

echo ""
echo "📊 Checking playoff completeness..."
./scripts/validate-odds-props playoffs > baseline_playoffs_$(date +%Y%m%d_%H%M%S).txt
echo "   Saved to: baseline_playoffs_*.txt"

echo ""
echo "📊 Finding missing games..."
./scripts/validate-odds-props missing --csv
echo "   Saved to: validation_props_find_missing_games_*.csv"

echo ""
echo -e "${YELLOW}Review the output above. Key things to check:${NC}"
echo "  - Which teams show ❌ or ⚠️ status?"
echo "  - How many games are missing?"
echo "  - Are the missing games from 2023-24 or 2024-25?"
echo ""

read -p "Press Enter to continue with backfill or Ctrl+C to abort..."
echo ""

# =============================================================================
# Step 2: Run Backfill
# =============================================================================
echo -e "${GREEN}STEP 2: Running Backfill${NC}"
echo ""

# Ask which phase to run
echo "Which phase do you want to backfill?"
echo "  1) 2023-24 Playoffs only (PHX, LAC - ~10 games) [RECOMMENDED]"
echo "  2) 2024-25 Playoffs only (DEN vs LAC - ~7 games)"
echo "  3) Both 2023-24 and 2024-25 (all critical playoffs)"
echo "  4) Include 2022-23 (older data, may not be available)"
echo ""
read -p "Enter choice (1-4) [default: 1]: " choice
choice=${choice:-1}

case $choice in
  1)
    echo "Running 2023-24 playoff backfill..."
    ./scripts/backfill_missing_props.sh 2023-24
    ;;
  2)
    echo "Running 2024-25 playoff backfill..."
    ./scripts/backfill_missing_props.sh 2024-25
    ;;
  3)
    echo "Running 2023-24 playoff backfill..."
    ./scripts/backfill_missing_props.sh 2023-24
    echo ""
    echo "Running 2024-25 playoff backfill..."
    ./scripts/backfill_missing_props.sh 2024-25
    ;;
  4)
    echo "Running all phases (2022-23, 2023-24, 2024-25)..."
    ./scripts/backfill_missing_props.sh all
    ;;
  *)
    echo -e "${RED}Invalid choice. Running 2023-24 by default.${NC}"
    ./scripts/backfill_missing_props.sh 2023-24
    ;;
esac

echo ""
echo -e "${GREEN}✅ Backfill Complete!${NC}"
echo ""

# =============================================================================
# Step 3: Validate Results
# =============================================================================
echo -e "${GREEN}STEP 3: Validating Results${NC}"
echo ""

echo "Running post-backfill validation..."
echo ""

# Quick team check
echo "📊 Checking critical teams (PHX, LAC, DAL)..."
bq query --use_legacy_sql=false '
SELECT 
  game_date,
  CONCAT(away_team_abbr, " @ ", home_team_abbr) as matchup,
  COUNT(DISTINCT player_name) as players,
  COUNT(DISTINCT bookmaker) as bookmakers
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN "2024-04-20" AND "2024-05-03"
  AND (home_team_abbr IN ("PHX","LAC","DAL") 
   OR away_team_abbr IN ("PHX","LAC","DAL"))
GROUP BY game_date, matchup
ORDER BY game_date' | head -30

echo ""

# Re-run playoff check
echo "📊 Re-running playoff completeness check..."
./scripts/validate-odds-props playoffs > results_playoffs_$(date +%Y%m%d_%H%M%S).txt
cat results_playoffs_*.txt | tail -20
echo "   Full results saved to: results_playoffs_*.txt"

echo ""

# Comprehensive validation
echo "📊 Running comprehensive validation..."
bq query --use_legacy_sql=false < validate_backfill_results.sql > results_comprehensive_$(date +%Y%m%d_%H%M%S).txt 2>&1
echo "   Full results saved to: results_comprehensive_*.txt"

echo ""

# Check for issues
echo "📊 Checking for data quality issues..."
./scripts/validate-odds-props low-coverage | grep "🔴" || echo "   ✅ No critical low-coverage games found"

echo ""

# =============================================================================
# Step 4: Summary
# =============================================================================
echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}Backfill Summary${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

echo "📁 Generated Files:"
ls -lht baseline_*.txt results_*.txt validation_props_*.csv 2>/dev/null | head -10
echo ""

echo "📊 Before/After Comparison:"
echo "   Baseline:"
grep "2023-24.*Playoffs" baseline_playoffs_*.txt 2>/dev/null | head -1 || echo "   (check baseline_playoffs_*.txt)"
echo ""
echo "   After Backfill:"
grep "2023-24.*Playoffs" results_playoffs_*.txt 2>/dev/null | head -1 || echo "   (check results_playoffs_*.txt)"
echo ""

echo -e "${GREEN}✅ Quick Start Complete!${NC}"
echo ""
echo "Next Steps:"
echo "  1. Review results files for detailed metrics"
echo "  2. Check for any ⚠️ or ❌ status in playoffs"
echo "  3. If issues found, check troubleshooting guide"
echo "  4. Set up daily monitoring: ./scripts/validate-odds-props yesterday"
echo ""
echo "Documentation:"
echo "  - Complete workflow: COMPLETE_PROPS_BACKFILL_WORKFLOW.md"
echo "  - Troubleshooting: See workflow guide"
echo "  - CLI help: ./scripts/validate-odds-props --help"
echo ""
echo -e "${BLUE}======================================================${NC}"

# =============================================================================
# Optional: Archive results
# =============================================================================
read -p "Archive results to backfill_results_$(date +%Y%m%d)/ ? (y/n) [default: y]: " archive
archive=${archive:-y}

if [[ $archive =~ ^[Yy]$ ]]; then
  ARCHIVE_DIR="backfill_results_$(date +%Y%m%d)"
  mkdir -p "$ARCHIVE_DIR"
  mv baseline_*.txt results_*.txt validation_props_*.csv "$ARCHIVE_DIR/" 2>/dev/null || true
  echo ""
  echo -e "${GREEN}✅ Results archived to: $ARCHIVE_DIR/${NC}"
  echo ""
fi

echo "Done! 🎉"