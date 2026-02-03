#!/bin/bash
# P1-4: Threshold Calibration from Historical Data (Session 89)
#
# Auto-calibrate validation thresholds from historical data instead of assumptions.
# Prevents false alarms by using actual data distribution.
#
# Usage: ./bin/monitoring/calibrate-threshold.sh <metric-name> [days-lookback] [dataset.table]
#
# Examples:
#   ./bin/monitoring/calibrate-threshold.sh vegas_line_coverage 30
#   ./bin/monitoring/calibrate-threshold.sh grading_coverage 14
#   ./bin/monitoring/calibrate-threshold.sh feature_completeness 30 nba_analytics.player_game_summary
#
# Prevents: Session 80 - False alarm (Vegas 90% when 44% is normal)

set -e

METRIC_NAME=$1
DAYS_LOOKBACK=${2:-30}
TABLE=${3:-""}
PROJECT="nba-props-platform"

if [ -z "$METRIC_NAME" ]; then
    echo "Usage: $0 <metric-name> [days-lookback] [dataset.table]"
    echo ""
    echo "Available metrics:"
    echo "  vegas_line_coverage       - % of players with real betting lines"
    echo "  grading_coverage          - % of predictions graded"
    echo "  feature_completeness      - % of features present in feature store"
    echo "  prediction_hit_rate       - % of predictions correct"
    echo "  bigquery_write_rate       - Records written per hour"
    echo "  custom                    - Custom metric from specified table"
    echo ""
    echo "Examples:"
    echo "  $0 vegas_line_coverage 30"
    echo "  $0 grading_coverage 14"
    echo "  $0 custom 30 nba_analytics.player_game_summary"
    exit 1
fi

echo "=============================================="
echo "P1-4: Threshold Calibration"
echo "=============================================="
echo "Metric: $METRIC_NAME"
echo "Lookback: $DAYS_LOOKBACK days"
echo "Project: $PROJECT"
echo ""

# Build query based on metric type
case "$METRIC_NAME" in
    vegas_line_coverage)
        QUERY="
        WITH daily_coverage AS (
          SELECT
            game_date,
            ROUND(100.0 * COUNTIF(current_points_line IS NOT NULL) / COUNT(*), 1) as metric_value
          FROM \`$PROJECT.nba_predictions.player_prop_predictions\`
          WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
            AND game_date < CURRENT_DATE()
            AND system_id = 'catboost_v9'
          GROUP BY game_date
        )
        SELECT
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(1)], 1) as p1,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(5)], 1) as p5,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(10)], 1) as p10,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(50)], 1) as median,
          ROUND(MIN(metric_value), 1) as min_observed,
          ROUND(MAX(metric_value), 1) as max_observed,
          COUNT(*) as sample_days
        FROM daily_coverage
        "
        METRIC_DESC="Vegas line coverage (%)"
        ;;

    grading_coverage)
        QUERY="
        WITH daily_grading AS (
          SELECT
            p.game_date,
            ROUND(100.0 * COUNT(pa.player_lookup) / COUNT(p.player_lookup), 1) as metric_value
          FROM \`$PROJECT.nba_predictions.player_prop_predictions\` p
          LEFT JOIN \`$PROJECT.nba_predictions.prediction_accuracy\` pa
            ON p.player_lookup = pa.player_lookup
            AND p.game_date = pa.game_date
            AND p.system_id = pa.system_id
          WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
            AND p.game_date < CURRENT_DATE()
            AND p.system_id = 'catboost_v9'
            AND p.line_source = 'ACTUAL_PROP'
          GROUP BY p.game_date
        )
        SELECT
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(1)], 1) as p1,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(5)], 1) as p5,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(10)], 1) as p10,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(50)], 1) as median,
          ROUND(MIN(metric_value), 1) as min_observed,
          ROUND(MAX(metric_value), 1) as max_observed,
          COUNT(*) as sample_days
        FROM daily_grading
        "
        METRIC_DESC="Grading coverage (%)"
        ;;

    feature_completeness)
        QUERY="
        WITH daily_completeness AS (
          SELECT
            game_date,
            ROUND(AVG(completeness_percentage), 1) as metric_value
          FROM \`$PROJECT.nba_precompute.ml_feature_store_v2\`
          WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
            AND game_date < CURRENT_DATE()
          GROUP BY game_date
        )
        SELECT
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(1)], 1) as p1,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(5)], 1) as p5,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(10)], 1) as p10,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(50)], 1) as median,
          ROUND(MIN(metric_value), 1) as min_observed,
          ROUND(MAX(metric_value), 1) as max_observed,
          COUNT(*) as sample_days
        FROM daily_completeness
        "
        METRIC_DESC="Feature completeness (%)"
        ;;

    prediction_hit_rate)
        QUERY="
        WITH daily_hit_rate AS (
          SELECT
            game_date,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as metric_value
          FROM \`$PROJECT.nba_predictions.prediction_accuracy\`
          WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
            AND game_date < CURRENT_DATE()
            AND system_id = 'catboost_v9'
            AND line_source = 'ACTUAL_PROP'
            AND recommendation IN ('OVER', 'UNDER')
            AND prediction_correct IS NOT NULL
          GROUP BY game_date
        )
        SELECT
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(1)], 1) as p1,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(5)], 1) as p5,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(10)], 1) as p10,
          ROUND(APPROX_QUANTILES(metric_value, 100)[OFFSET(50)], 1) as median,
          ROUND(MIN(metric_value), 1) as min_observed,
          ROUND(MAX(metric_value), 1) as max_observed,
          COUNT(*) as sample_days
        FROM daily_hit_rate
        "
        METRIC_DESC="Prediction hit rate (%)"
        ;;

    bigquery_write_rate)
        QUERY="
        WITH hourly_writes AS (
          SELECT
            DATE(processed_at) as metric_date,
            EXTRACT(HOUR FROM processed_at) as hour,
            COUNT(*) as writes_per_hour
          FROM \`$PROJECT.nba_analytics.player_game_summary\`
          WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $DAYS_LOOKBACK DAY)
          GROUP BY metric_date, hour
        )
        SELECT
          ROUND(APPROX_QUANTILES(writes_per_hour, 100)[OFFSET(1)], 0) as p1,
          ROUND(APPROX_QUANTILES(writes_per_hour, 100)[OFFSET(5)], 0) as p5,
          ROUND(APPROX_QUANTILES(writes_per_hour, 100)[OFFSET(10)], 0) as p10,
          ROUND(APPROX_QUANTILES(writes_per_hour, 100)[OFFSET(50)], 0) as median,
          ROUND(MIN(writes_per_hour), 0) as min_observed,
          ROUND(MAX(writes_per_hour), 0) as max_observed,
          COUNT(*) as sample_hours
        FROM hourly_writes
        "
        METRIC_DESC="BigQuery writes per hour"
        ;;

    custom)
        if [ -z "$TABLE" ]; then
            echo "ERROR: Custom metric requires table parameter"
            echo "Usage: $0 custom <days> <dataset.table>"
            echo "Example: $0 custom 30 nba_analytics.player_game_summary"
            exit 1
        fi

        echo "⚠️  Custom mode: You must edit this script to define the query"
        echo "   Table: $TABLE"
        echo ""
        echo "Template query structure:"
        echo "  1. Calculate daily metric_value"
        echo "  2. Calculate percentiles (p1, p5, p10, median, min, max)"
        echo "  3. Return single row with statistics"
        exit 1
        ;;

    *)
        echo "ERROR: Unknown metric: $METRIC_NAME"
        echo ""
        echo "Available metrics:"
        echo "  vegas_line_coverage, grading_coverage, feature_completeness"
        echo "  prediction_hit_rate, bigquery_write_rate, custom"
        exit 1
        ;;
esac

# Run query
echo "Querying historical data..."
RESULT=$(bq query --use_legacy_sql=false --format=csv "$QUERY" 2>&1)

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: BigQuery query failed"
    echo "$RESULT"
    exit 1
fi

# Parse result (skip header, get data row)
DATA_ROW=$(echo "$RESULT" | tail -1)

# Extract values
IFS=',' read -r P1 P5 P10 MEDIAN MIN MAX SAMPLE_SIZE <<< "$DATA_ROW"

echo ""
echo "=============================================="
echo "HISTORICAL DATA ANALYSIS"
echo "=============================================="
echo "Metric:       $METRIC_DESC"
echo "Sample size:  $SAMPLE_SIZE days/periods"
echo "Date range:   Last $DAYS_LOOKBACK days"
echo ""
echo "Distribution:"
echo "  Minimum:    $MIN"
echo "  P1:         $P1  (1st percentile - almost never below)"
echo "  P5:         $P5  (5th percentile - rare but happens)"
echo "  P10:        $P10 (10th percentile - occasional low)"
echo "  Median:     $MEDIAN (typical value)"
echo "  Maximum:    $MAX"
echo ""
echo "=============================================="
echo "RECOMMENDED THRESHOLDS"
echo "=============================================="
echo ""
echo "Conservative approach (fewer false alarms):"
echo "  🚨 CRITICAL: < $P1"
echo "  ⚠️  WARNING:  < $P5"
echo "  ✅ OK:        >= $P5"
echo ""
echo "Moderate approach (balanced):"
echo "  🚨 CRITICAL: < $P5"
echo "  ⚠️  WARNING:  < $P10"
echo "  ✅ OK:        >= $P10"
echo ""
echo "Aggressive approach (catch all issues):"
echo "  🚨 CRITICAL: < $P10"
echo "  ⚠️  WARNING:  < $MEDIAN"
echo "  ✅ OK:        >= $MEDIAN"
echo ""
echo "=============================================="
echo "INTERPRETATION"
echo "=============================================="
echo ""
echo "Choose threshold based on tolerance for:"
echo "  - False positives (alerts when actually OK)"
echo "  - False negatives (missing real issues)"
echo ""
echo "Recommendations:"
echo "  • Use Conservative for noisy metrics"
echo "  • Use Moderate for most metrics (recommended)"
echo "  • Use Aggressive for critical safety metrics"
echo ""
echo "Example for $METRIC_NAME:"

# Provide metric-specific recommendations
case "$METRIC_NAME" in
    vegas_line_coverage)
        echo "  Recommended: MODERATE approach"
        echo "  Rationale: Line coverage varies by day but should stay > $P10%"
        echo ""
        echo "  Suggested validation config:"
        echo "    CRITICAL: < $P5% (very unusual)"
        echo "    WARNING:  < $P10% (lower than normal)"
        echo "    OK:       >= $P10% (typical range)"
        ;;

    grading_coverage)
        echo "  Recommended: AGGRESSIVE approach"
        echo "  Rationale: Grading should be nearly complete daily"
        echo ""
        echo "  Suggested validation config:"
        echo "    CRITICAL: < 80% (major grading failure)"
        echo "    WARNING:  < 95% (some games not graded)"
        echo "    OK:       >= 95% (expected coverage)"
        ;;

    feature_completeness)
        echo "  Recommended: MODERATE approach"
        echo "  Rationale: Feature completeness affects model quality"
        echo ""
        echo "  Suggested validation config:"
        echo "    CRITICAL: < $P5% (too much missing data)"
        echo "    WARNING:  < $P10% (some data gaps)"
        echo "    OK:       >= $P10% (sufficient data)"
        ;;

    prediction_hit_rate)
        echo "  Recommended: CONSERVATIVE approach"
        echo "  Rationale: Hit rate varies by day, opponent, sample size"
        echo ""
        echo "  Suggested validation config:"
        echo "    CRITICAL: < $P1% (model broken)"
        echo "    WARNING:  < $P5% (unusually low performance)"
        echo "    OK:       >= $P5% (acceptable variance)"
        ;;

    bigquery_write_rate)
        echo "  Recommended: MODERATE approach"
        echo "  Rationale: Write rate should be consistent per schedule"
        echo ""
        echo "  Suggested validation config:"
        echo "    CRITICAL: < $P5 writes/hour (major failure)"
        echo "    WARNING:  < $P10 writes/hour (degraded performance)"
        echo "    OK:       >= $P10 writes/hour (normal operation)"
        ;;
esac

echo ""
echo "=============================================="
echo "NEXT STEPS"
echo "=============================================="
echo ""
echo "1. Review recommended thresholds above"
echo "2. Update validation config in /validate-daily skill"
echo "3. Update monitoring alerting thresholds"
echo "4. Document threshold rationale for future reference"
echo ""
echo "To update /validate-daily:"
echo "  Edit: shared/validation/daily_validation.py"
echo "  Or: Update skill configuration"
echo ""
echo "To save this analysis:"
echo "  $0 $METRIC_NAME $DAYS_LOOKBACK > docs/monitoring/threshold-calibration-$METRIC_NAME.txt"
echo ""
echo "✅ Threshold calibration complete"
