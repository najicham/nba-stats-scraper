#!/bin/bash
# Test Data Quality Monitoring Queries
#
# Usage:
#   ./test_queries.sh [date]
#
# Date: YYYY-MM-DD format (default: 2026-01-26 - known issue date)

set -e

TEST_DATE=${1:-2026-01-26}
PROJECT_ID="nba-props-platform"

echo "=== Testing Data Quality Queries ==="
echo "Date: $TEST_DATE"
echo "Project: $PROJECT_ID"
echo ""

# Color codes
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Test zero predictions query
echo "----------------------------------------"
echo "1. Testing Zero Predictions Query"
echo "----------------------------------------"
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:$TEST_DATE \
  --project_id=$PROJECT_ID \
  < zero_predictions.sql

echo ""
read -p "Press Enter to continue..."
echo ""

# Test low usage coverage query
echo "----------------------------------------"
echo "2. Testing Low Usage Coverage Query"
echo "----------------------------------------"
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:$TEST_DATE \
  --project_id=$PROJECT_ID \
  < low_usage_coverage.sql

echo ""
read -p "Press Enter to continue..."
echo ""

# Test duplicate detection query
echo "----------------------------------------"
echo "3. Testing Duplicate Detection Query"
echo "----------------------------------------"
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:$TEST_DATE \
  --project_id=$PROJECT_ID \
  < duplicate_detection.sql

echo ""
read -p "Press Enter to continue..."
echo ""

# Test prop lines missing query
echo "----------------------------------------"
echo "4. Testing Prop Lines Missing Query"
echo "----------------------------------------"
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:$TEST_DATE \
  --project_id=$PROJECT_ID \
  < prop_lines_missing.sql

echo ""
echo "=== Test Complete ==="
echo ""
echo "Review the results above for:"
echo "  - Query execution time (should be < 30s each)"
echo "  - Alert levels (CRITICAL, WARNING, OK)"
echo "  - Diagnostic hints and recommendations"
echo ""
echo "Next steps:"
echo "  1. If all queries work, deploy the Cloud Function"
echo "  2. Test Cloud Function with: curl [URL]?game_date=$TEST_DATE&dry_run=true"
echo "  3. Set up Cloud Scheduler for daily runs"
