#!/bin/bash
# File: bin/analytics/validation/validate_analytics_data.sh  
# Validate analytics data quality and cross-source consistency

PROJECT_ID="nba-props-platform"

echo "🔍 NBA Analytics Data Validation"
echo "================================"

# Validation 1: Player game summary data quality
echo "📊 Validating player game summary data quality..."

PLAYER_VALIDATION=$(bq query --use_legacy_sql=false --format=json --max_rows=10 "
WITH validation_metrics AS (
    SELECT 
        COUNT(*) as total_records,
        COUNT(CASE WHEN points IS NOT NULL THEN 1 END) as records_with_points,
        COUNT(CASE WHEN data_quality_tier = 'high' THEN 1 END) as high_quality_records,
        COUNT(CASE WHEN over_under_result IN ('OVER', 'UNDER') THEN 1 END) as records_with_prop_outcomes,
        COUNT(CASE WHEN travel_miles > 0 THEN 1 END) as records_with_travel,
        AVG(points) as avg_points,
        COUNT(DISTINCT game_id) as unique_games,
        COUNT(DISTINCT player_lookup) as unique_players
    FROM \`$PROJECT_ID.nba_analytics.player_game_summary\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT * FROM validation_metrics
")

echo "Player Game Summary Validation:"
echo "$PLAYER_VALIDATION" | jq -r '.[0] | "  Total Records: \(.total_records)\n  Records with Points: \(.records_with_points)\n  High Quality Records: \(.high_quality_records)\n  Prop Outcomes: \(.records_with_prop_outcomes)\n  Travel Data: \(.records_with_travel)\n  Average Points: \(.avg_points | tonumber | floor)\n  Unique Games: \(.unique_games)\n  Unique Players: \(.unique_players)"'

# Validation 2: Cross-source consistency check
echo ""
echo "🔄 Checking cross-source data consistency..."

CONSISTENCY_CHECK=$(bq query --use_legacy_sql=false --format=json --max_rows=5 "
WITH source_comparison AS (
    SELECT 
        a.game_id,
        a.player_lookup,
        a.points as analytics_points,
        b.points as bdl_points,
        a.primary_source_used,
        ABS(a.points - COALESCE(b.points, a.points)) as points_difference
    FROM \`$PROJECT_ID.nba_analytics.player_game_summary\` a
    LEFT JOIN \`$PROJECT_ID.nba_raw.bdl_player_boxscores\` b
        ON a.game_id = b.game_id AND a.player_lookup = b.player_lookup
    WHERE a.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        AND a.points IS NOT NULL
)
SELECT 
    COUNT(*) as total_comparisons,
    COUNT(CASE WHEN points_difference = 0 THEN 1 END) as exact_matches,
    COUNT(CASE WHEN points_difference <= 1 THEN 1 END) as close_matches,  
    AVG(points_difference) as avg_difference,
    MAX(points_difference) as max_difference
FROM source_comparison
")

echo "Cross-Source Consistency:"
echo "$CONSISTENCY_CHECK" | jq -r '.[0] | "  Total Comparisons: \(.total_comparisons)\n  Exact Matches: \(.exact_matches)\n  Close Matches (±1): \(.close_matches)\n  Average Difference: \(.avg_difference)\n  Max Difference: \(.max_difference)"'

# Validation 3: Prop outcome accuracy
echo ""  
echo "🎯 Validating prop outcome calculations..."

PROP_VALIDATION=$(bq query --use_legacy_sql=false --format=json --max_rows=1 "
WITH prop_validation AS (
    SELECT 
        COUNT(CASE WHEN points_line IS NOT NULL THEN 1 END) as games_with_lines,
        COUNT(CASE WHEN over_under_result = 'OVER' THEN 1 END) as overs,
        COUNT(CASE WHEN over_under_result = 'UNDER' THEN 1 END) as unders,
        -- Validate calculation logic
        COUNT(CASE 
            WHEN points > points_line AND over_under_result = 'OVER' THEN 1 
            WHEN points <= points_line AND over_under_result = 'UNDER' THEN 1
        END) as correct_calculations,
        COUNT(CASE 
            WHEN points IS NOT NULL AND points_line IS NOT NULL 
            THEN 1 
        END) as calculable_records
    FROM \`$PROJECT_ID.nba_analytics.player_game_summary\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        AND is_active = TRUE
)
SELECT 
    *,
    ROUND(correct_calculations * 100.0 / NULLIF(calculable_records, 0), 2) as calculation_accuracy_pct
FROM prop_validation
")

echo "Prop Outcome Validation:"
echo "$PROP_VALIDATION" | jq -r '.[0] | "  Games with Lines: \(.games_with_lines)\n  Over Results: \(.overs)\n  Under Results: \(.unders)\n  Calculation Accuracy: \(.calculation_accuracy_pct)%"'

# Validation 4: Team summary data consistency  
echo ""
echo "🏀 Validating team summary consistency..."

TEAM_VALIDATION=$(bq query --use_legacy_sql=false --format=json --max_rows=1 "
WITH team_consistency AS (
    SELECT 
        p.game_id,
        p.team_abbr,
        SUM(CASE WHEN p.is_active THEN p.points ELSE 0 END) as player_total_points,
        t.points_scored as team_points_scored,
        ABS(SUM(CASE WHEN p.is_active THEN p.points ELSE 0 END) - COALESCE(t.points_scored, 0)) as points_difference
    FROM \`$PROJECT_ID.nba_analytics.player_game_summary\` p
    LEFT JOIN \`$PROJECT_ID.nba_analytics.team_offense_game_summary\` t
        ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr  
    WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY p.game_id, p.team_abbr, t.points_scored
)
SELECT 
    COUNT(*) as team_games_compared,
    COUNT(CASE WHEN points_difference <= 1 THEN 1 END) as consistent_totals,
    AVG(points_difference) as avg_difference,
    MAX(points_difference) as max_difference
FROM team_consistency
WHERE team_points_scored IS NOT NULL
")

if [[ "$TEAM_VALIDATION" != "[]" ]]; then
    echo "Team Summary Consistency:"
    echo "$TEAM_VALIDATION" | jq -r '.[0] | "  Team Games Compared: \(.team_games_compared)\n  Consistent Totals: \(.consistent_totals)\n  Average Difference: \(.avg_difference)\n  Max Difference: \(.max_difference)"'
else
    echo "  ⚠️  No team summary data found - may need to run team processors"
fi

echo ""
echo "✅ Analytics data validation complete!"
echo ""
echo "🔧 If issues found, check:"
echo "  - Data quality logs: SELECT * FROM \`$PROJECT_ID.nba_processing.analytics_data_issues\` ORDER BY created_at DESC LIMIT 10"
echo "  - Processing runs: SELECT * FROM \`$PROJECT_ID.nba_processing.analytics_processor_runs\` ORDER BY run_date DESC LIMIT 5"