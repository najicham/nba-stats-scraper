#!/bin/bash
# bin/monitoring/test_resilience_components.sh
#
# Test all resilience monitoring components locally
#
# Usage:
#   ./bin/monitoring/test_resilience_components.sh

set -e

PROJECT_ID="nba-props-platform"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

cd "$REPO_ROOT"

echo "=== Testing Resilience Monitoring Components ==="
echo ""

# Test 1: Deployment Drift Alerter
echo "1. Testing Deployment Drift Alerter..."
echo "   (This may send a Slack alert if drift is detected)"
echo ""

python bin/monitoring/deployment_drift_alerter.py
DRIFT_EXIT_CODE=$?

if [ $DRIFT_EXIT_CODE -eq 0 ]; then
    echo "   ✅ No deployment drift detected"
elif [ $DRIFT_EXIT_CODE -eq 1 ]; then
    echo "   ⚠️  Deployment drift detected (check #deployment-alerts)"
else
    echo "   ❌ Error running drift alerter (exit code: $DRIFT_EXIT_CODE)"
    exit 1
fi

echo ""

# Test 2: Pipeline Canary Queries
echo "2. Testing Pipeline Canary Queries..."
echo "   (This may send a Slack alert if canaries fail)"
echo ""

python bin/monitoring/pipeline_canary_queries.py
CANARY_EXIT_CODE=$?

if [ $CANARY_EXIT_CODE -eq 0 ]; then
    echo "   ✅ All canary queries passed"
elif [ $CANARY_EXIT_CODE -eq 1 ]; then
    echo "   ⚠️  Canary failures detected (check #canary-alerts)"
else
    echo "   ❌ Error running canary queries (exit code: $CANARY_EXIT_CODE)"
    exit 1
fi

echo ""

# Test 3: Phase 2 Quality Gate
echo "3. Testing Phase 2 Quality Gate..."
echo ""

python -c "
from datetime import date, timedelta
from google.cloud import bigquery
from shared.validation.phase2_quality_gate import Phase2QualityGate

try:
    client = bigquery.Client(project='$PROJECT_ID')
    gate = Phase2QualityGate(client, '$PROJECT_ID')

    # Test yesterday's data
    test_date = date.today() - timedelta(days=1)
    result = gate.check_raw_data_quality(test_date)

    print(f'   Status: {result.status.value}')
    print(f'   Quality Score: {result.quality_score:.2f}')
    print(f'   Message: {result.message}')

    if result.quality_issues:
        print('   Issues:')
        for issue in result.quality_issues:
            print(f'     - {issue}')

    if result.can_proceed:
        print('   ✅ Quality gate would allow processing')
    else:
        print('   ❌ Quality gate would block processing')

except Exception as e:
    print(f'   ❌ Error: {e}')
    import sys
    sys.exit(1)
"

echo ""
echo "=== Test Summary ==="
echo ""
echo "✅ All components tested successfully"
echo ""
echo "Next Steps:"
echo "1. Review Slack alerts in #deployment-alerts and #canary-alerts"
echo "2. Deploy to production: ./bin/monitoring/setup_deployment_drift_scheduler.sh"
echo "3. Deploy canaries: ./bin/monitoring/setup_pipeline_canary_scheduler.sh"
echo "4. Monitor for 24-48 hours to establish baseline"
