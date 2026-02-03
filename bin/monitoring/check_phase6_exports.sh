#!/bin/bash
# check_phase6_exports.sh - Monitor Phase 6 export health
# Session 91: Ensures public API files are fresh and valid
#
# Usage: ./bin/monitoring/check_phase6_exports.sh [--date YYYY-MM-DD]
#
# Returns exit code 0 if healthy, 1 if issues found

# Parse arguments
TARGET_DATE=""
if [[ "$1" == "--date" ]]; then
    TARGET_DATE="$2"
else
    TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
fi

echo "=== Phase 6 Export Health Check ==="
echo "Checking exports for: $TARGET_DATE"
echo ""

ERRORS=0

# Check picks file
echo "1. Picks Export"
if gsutil -q stat "gs://nba-props-platform-api/v1/picks/${TARGET_DATE}.json" 2>/dev/null; then
    echo "   ✅ /picks/${TARGET_DATE}.json exists"
else
    echo "   🔴 /picks/${TARGET_DATE}.json MISSING"
    ERRORS=$((ERRORS + 1))
fi

# Check signals file
echo "2. Signals Export"
if gsutil -q stat "gs://nba-props-platform-api/v1/signals/${TARGET_DATE}.json" 2>/dev/null; then
    echo "   ✅ /signals/${TARGET_DATE}.json exists"
else
    echo "   🔴 /signals/${TARGET_DATE}.json MISSING"
    ERRORS=$((ERRORS + 1))
fi

# Check performance file
echo "3. Performance Export"
if gsutil -q stat "gs://nba-props-platform-api/v1/subsets/performance.json" 2>/dev/null; then
    echo "   ✅ /subsets/performance.json exists"
else
    echo "   🔴 /subsets/performance.json MISSING"
    ERRORS=$((ERRORS + 1))
fi

# Check definitions file
echo "4. Definitions Export"
if gsutil -q stat "gs://nba-props-platform-api/v1/systems/subsets.json" 2>/dev/null; then
    echo "   ✅ /systems/subsets.json exists"
else
    echo "   🔴 /systems/subsets.json MISSING"
    ERRORS=$((ERRORS + 1))
fi

# Summary
echo ""
echo "=== Summary ==="
if [[ $ERRORS -eq 0 ]]; then
    echo "✅ All Phase 6 exports healthy"
    exit 0
else
    echo "🔴 ${ERRORS} issue(s) found"
    echo ""
    echo "Troubleshooting:"
    echo "1. Check orchestrator: gcloud functions logs read phase5-to-phase6 --region=us-west2 --limit=20"
    echo "2. Manual export: PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date ${TARGET_DATE} --only subset-picks,daily-signals"
    exit 1
fi
