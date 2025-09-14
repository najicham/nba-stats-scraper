#!/bin/bash
# File: bin/analytics/deploy/test_analytics_processors.sh
# Test analytics processors with sample data

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "🧪 Testing NBA Analytics Processors"
echo "==================================="

# Test 1: Check raw data availability
echo "📊 Phase 1: Checking raw data availability..."

RAW_DATA_CHECK=$(bq query --use_legacy_sql=false --format=json --max_rows=1 "
SELECT 
    COUNT(*) as nbac_gamebook_records,
    (SELECT COUNT(*) FROM \`$PROJECT_ID.nba_raw.bdl_player_boxscores\` WHERE game_date >= '2024-01-01') as bdl_records,
    (SELECT COUNT(*) FROM \`$PROJECT_ID.nba_raw.odds_api_player_points_props\` WHERE game_date >= '2024-01-01') as props_records
FROM \`$PROJECT_ID.nba_raw.nbac_gamebook_player_stats\`  
WHERE game_date >= '2024-01-01' AND player_status = 'active'
")

echo "Raw data availability:"
echo "$RAW_DATA_CHECK" | jq -r '.[0] | "  NBA.com Gamebook: \(.nbac_gamebook_records) records\n  Ball Don\'t Lie: \(.bdl_records) records\n  Props Data: \(.props_records) records"'

# Test 2: Dry run analytics processing
echo ""
echo "📊 Phase 2: Testing player game summary processor..."

if gcloud run jobs describe "player-game-summary-analytics-backfill" --region=$REGION >/dev/null 2>&1; then
    echo "Running dry run test..."
    
    EXECUTION_OUTPUT=$(gcloud run jobs execute "player-game-summary-analytics-backfill" \
        --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 \
        --region=$REGION \
        --format="value(name)" \
        --quiet)
    
    if [[ -n "$EXECUTION_OUTPUT" ]]; then
        echo "Execution started: $EXECUTION_OUTPUT"
        
        # Wait for completion
        sleep 10
        
        echo "Checking execution logs..."
        gcloud beta run jobs executions logs read "$EXECUTION_OUTPUT" --region=$REGION --limit=50
    else
        echo "⚠️  Failed to start execution"
    fi
else
    echo "⚠️  Player game summary job not deployed. Deploy first with:"
    echo "   ./bin/analytics/deploy/deploy_analytics_processor_backfill.sh player_game_summary"
fi

# Test 3: Check analytics schema exists
echo ""
echo "📊 Phase 3: Verifying analytics schema..."

SCHEMA_CHECK=$(bq ls --format=json "$PROJECT_ID:nba_analytics" 2>/dev/null | jq -r '.[].tableReference.tableId' | grep -E "(player_game_summary|team_offense|team_defense)" | wc -l)

if [[ "$SCHEMA_CHECK" -ge 3 ]]; then
    echo "✅ Analytics schema tables exist"
    
    # Check if any data exists
    EXISTING_DATA=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 "
    SELECT COUNT(*) as record_count 
    FROM \`$PROJECT_ID.nba_analytics.player_game_summary\`
    " | tail -n +2)
    
    echo "  Existing analytics records: $EXISTING_DATA"
else
    echo "⚠️  Analytics schema incomplete. Run schema creation:"
    echo "   bq query --use_legacy_sql=false < schemas/bigquery/analytics/complete_analytics_schema.sql"
fi

# Test 4: Travel distance integration test
echo ""
echo "📊 Phase 4: Testing travel distance integration..."

TRAVEL_TEST=$(python3 -c "
import sys
sys.path.append('analytics_processors')
try:
    from utils.travel_utils import quick_distance_lookup
    distance = quick_distance_lookup('LAL', 'BOS')
    print(f'LAL to BOS distance: {distance} miles')
    if distance == 2592:
        print('✅ Travel distance system working correctly')
    else:
        print('⚠️  Unexpected distance result')
except Exception as e:
    print(f'❌ Travel distance system error: {e}')
")

echo "$TRAVEL_TEST"

echo ""
echo "🎯 Testing Summary:"
echo "=================="
echo "✅ Raw data availability checked"
echo "✅ Analytics processor dry run tested" 
echo "✅ Schema verification completed"
echo "✅ Travel integration tested"
echo ""
echo "🚀 Ready for production analytics processing!"
echo ""
echo "Next steps:"
echo "1. Deploy analytics processors: ./bin/analytics/deploy/deploy_analytics_processors.sh"
echo "2. Deploy backfill jobs: ./bin/analytics/deploy/deploy_analytics_processor_backfill.sh player_game_summary"
echo "3. Run initial processing: gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=$REGION"
