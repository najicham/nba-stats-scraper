#!/bin/bash
#
# Phase 3 Completion Health Check
#
# Created: 2026-02-04 (Session 116)
# Purpose: Daily check for Phase 3 orchestration issues
#
# Checks:
# 1. Firestore completion accuracy
# 2. Duplicate record detection
# 3. Scraper timing verification
#
# Usage:
#   ./bin/monitoring/phase3_health_check.sh
#   ./bin/monitoring/phase3_health_check.sh --verbose
#
# Exit codes:
#   0 - All checks passed
#   1 - Issues found (see output)
#   2 - Script error

# Don't exit on error - we want to run all checks
set +e

VERBOSE=false
if [[ "$1" == "--verbose" ]]; then
    VERBOSE=true
fi

echo "================================================================================"
echo "Phase 3 Completion Health Check"
echo "Date: $(date)"
echo "================================================================================"

# Check yesterday's completion
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
EXIT_CODE=0

# ============================================================================
# Check 1: Firestore Completion Accuracy
# ============================================================================
echo ""
echo "=== Check 1: Firestore Completion Accuracy ==="

python3 << EOF
import sys
from google.cloud import firestore

db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase3_completion').document('$YESTERDAY').get()

if not doc.exists:
    print(f'⚠️  No completion document for $YESTERDAY')
    print('   This may be normal if no games were played')
    sys.exit(0)

data = doc.to_dict()
actual = len([k for k in data.keys() if not k.startswith('_')])
stored = data.get('_completed_count', 0)
triggered = data.get('_triggered', False)

# Check for issues
issues = []
if actual != stored:
    issues.append(f'COUNT MISMATCH (actual:{actual} stored:{stored})')
if actual >= 5 and not triggered:
    issues.append(f'NOT TRIGGERED')

if issues:
    status = '❌ FAIL'
    print(f'{status} - {", ".join(issues)}')
    print(f'  Processors: {actual}/5')
    print(f'  Count: {stored}')
    print(f'  Triggered: {triggered}')
    print(f'')
    print(f'  Action: Run reconciliation')
    print(f'  python bin/maintenance/reconcile_phase3_completion.py --days 1 --fix')
    sys.exit(1)
else:
    status = '✅ OK'
    print(f'{status}')
    print(f'  Processors: {actual}/5')
    print(f'  Count: {stored}')
    print(f'  Triggered: {triggered}')
EOF

if [[ $? -ne 0 ]]; then
    EXIT_CODE=1
fi

# ============================================================================
# Check 2: Duplicate Detection
# ============================================================================
echo ""
echo "=== Check 2: Duplicate Record Detection ==="

DUPLICATES=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as duplicate_count
FROM (
  SELECT game_date, player_lookup, game_id, COUNT(*) as cnt
  FROM nba_analytics.player_game_summary
  WHERE game_date = DATE('$YESTERDAY')
  GROUP BY 1, 2, 3
  HAVING cnt > 1
)
" 2>&1 | tail -1)

if [[ "$DUPLICATES" == "0" ]]; then
    echo "✅ OK - No duplicates found"
elif [[ "$DUPLICATES" =~ ^[0-9]+$ ]]; then
    echo "❌ FAIL - Found $DUPLICATES duplicate player records"
    echo ""
    echo "  Action: Run deduplication"
    echo "  See docs/02-operations/runbooks/phase3-completion-tracking-reliability.md"
    EXIT_CODE=1
else
    echo "⚠️  Could not check duplicates (query error)"
    if [[ "$VERBOSE" == "true" ]]; then
        echo "$DUPLICATES"
    fi
fi

# ============================================================================
# Check 3: Scraper Timing
# ============================================================================
echo ""
echo "=== Check 3: Scraper Timing ==="

# Check if table exists first
TABLE_EXISTS=$(bq show --format=json nba-props-platform:nba_orchestration.scraper_run_history 2>&1)

if echo "$TABLE_EXISTS" | grep -q "Not found"; then
    echo "ℹ️  INFO - scraper_run_history table not found (expected for some deployments)"
else
    LATE_SCRAPERS=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT
      scraper_name,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MIN(started_at)) as first_run,
      TIMESTAMP_DIFF(MIN(started_at), TIMESTAMP('$YESTERDAY 06:00:00'), HOUR) as hours_late
    FROM nba_orchestration.scraper_run_history
    WHERE DATE(started_at) = CURRENT_DATE()
      AND scraper_name LIKE '%gamebook%'
    GROUP BY scraper_name
    HAVING hours_late > 4
    " 2>&1)

    if echo "$LATE_SCRAPERS" | grep -q "scraper_name"; then
        # Has header, means there are late scrapers
        LATE_COUNT=$(echo "$LATE_SCRAPERS" | tail -n +2 | wc -l)
        echo "⚠️  WARNING - $LATE_COUNT scraper(s) ran >4 hours late"
        if [[ "$VERBOSE" == "true" ]]; then
            echo "$LATE_SCRAPERS"
        fi
    else
        echo "✅ OK - All scrapers ran on time"
    fi
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "================================================================================"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "✅ All checks passed"
else
    echo "❌ Issues found - see above for details"
fi
echo "================================================================================"
echo ""

exit $EXIT_CODE
