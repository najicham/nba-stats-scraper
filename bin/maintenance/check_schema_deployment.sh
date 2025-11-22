#!/bin/bash
#
# Check Schema Deployment Status
# Verifies that Phase 2, 3, 4, 5 tables have required columns
#
# Usage: ./bin/maintenance/check_schema_deployment.sh

set -e

echo "================================================================================"
echo "SCHEMA DEPLOYMENT STATUS CHECK"
echo "================================================================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_phase2_tables() {
    echo "Phase 2 (Raw) - Checking for smart idempotency columns..."
    echo "---------------------------------------------------"

    # Sample Phase 2 tables to check
    tables=(
        "nba_raw.bdl_player_boxscores"
        "nba_raw.nbac_gamebook_player_stats"
        "nba_raw.odds_api_player_points_props"
        "nba_raw.bdl_injuries"
    )

    for table in "${tables[@]}"; do
        echo -n "  Checking $table... "

        # Check for processed_at column
        has_processed_at=$(bq show --schema --format=prettyjson "$table" 2>/dev/null | grep -c '"name": "processed_at"' || echo "0")

        # Check for data_hash column
        has_data_hash=$(bq show --schema --format=prettyjson "$table" 2>/dev/null | grep -c '"name": "data_hash"' || echo "0")

        if [[ "$has_processed_at" == "1" && "$has_data_hash" == "1" ]]; then
            echo -e "${GREEN}✅ Has both processed_at and data_hash${NC}"
        elif [[ "$has_processed_at" == "1" ]]; then
            echo -e "${YELLOW}⚠️  Has processed_at but MISSING data_hash${NC}"
        else
            echo -e "${RED}❌ MISSING both processed_at and data_hash${NC}"
        fi
    done
    echo ""
}

check_phase3_tables() {
    echo "Phase 3 (Analytics) - Checking for hash tracking columns..."
    echo "---------------------------------------------------"

    # Phase 3 tables to check
    tables=(
        "nba_analytics.player_game_summary"
        "nba_analytics.upcoming_player_game_context"
        "nba_analytics.team_offense_game_summary"
        "nba_analytics.team_defense_game_summary"
        "nba_analytics.upcoming_team_game_context"
    )

    for table in "${tables[@]}"; do
        echo -n "  Checking $table... "

        # Check if table exists
        table_exists=$(bq show "$table" 2>/dev/null && echo "1" || echo "0")

        if [[ "$table_exists" == "0" ]]; then
            echo -e "${RED}❌ TABLE DOES NOT EXIST${NC}"
            continue
        fi

        # Check for sample hash column (source_nbac_hash, source_bdl_hash, etc.)
        has_hash_cols=$(bq show --schema --format=prettyjson "$table" 2>/dev/null | grep -c '"name": "source_.*_hash"' || echo "0")

        if [[ "$has_hash_cols" -ge "1" ]]; then
            echo -e "${GREEN}✅ Has hash tracking columns ($has_hash_cols found)${NC}"
        else
            echo -e "${RED}❌ MISSING hash tracking columns${NC}"
        fi
    done
    echo ""
}

check_phase4_tables() {
    echo "Phase 4 (Precompute) - Checking status..."
    echo "---------------------------------------------------"

    # Phase 4 tables to check (examples)
    tables=(
        "nba_precompute.player_composite_factors"
        "nba_precompute.ml_feature_store"
    )

    for table in "${tables[@]}"; do
        echo -n "  Checking $table... "

        # Check if table exists
        table_exists=$(bq show "$table" 2>/dev/null && echo "1" || echo "0")

        if [[ "$table_exists" == "0" ]]; then
            echo -e "${YELLOW}⚠️  TABLE DOES NOT EXIST (may not be deployed yet)${NC}"
        else
            echo -e "${GREEN}✅ Table exists${NC}"
        fi
    done
    echo ""
}

check_phase5_tables() {
    echo "Phase 5 (Predictions) - Checking status..."
    echo "---------------------------------------------------"

    # Phase 5 tables to check (examples)
    tables=(
        "nba_predictions.player_predictions_final"
    )

    for table in "${tables[@]}"; do
        echo -n "  Checking $table... "

        # Check if table exists
        table_exists=$(bq show "$table" 2>/dev/null && echo "1" || echo "0")

        if [[ "$table_exists" == "0" ]]; then
            echo -e "${YELLOW}⚠️  TABLE DOES NOT EXIST (may not be deployed yet)${NC}"
        else
            echo -e "${GREEN}✅ Table exists${NC}"
        fi
    done
    echo ""
}

# Run all checks
check_phase2_tables
check_phase3_tables
check_phase4_tables
check_phase5_tables

echo "================================================================================"
echo "SUMMARY"
echo "================================================================================"
echo ""
echo "If you see any ❌ or ⚠️  above, you need to deploy schemas:"
echo ""
echo "  # Deploy Phase 2 schemas (add data_hash column)"
echo "  for f in schemas/bigquery/raw/*.sql; do"
echo "    bq query --use_legacy_sql=false < \$f"
echo "  done"
echo ""
echo "  # Deploy Phase 3 schemas (add hash tracking columns)"
echo "  for f in schemas/bigquery/analytics/*_tables.sql; do"
echo "    bq query --use_legacy_sql=false < \$f"
echo "  done"
echo ""
echo "================================================================================"
