#!/bin/bash
set -euo pipefail
# Morning Health Check Dashboard - Fast overview of overnight processing
# Usage: ./bin/monitoring/morning_health_check.sh [GAME_DATE]
#
# Shows health summary in < 30 seconds with clear status indicators.
# Run this every morning to quickly assess overnight processing health.

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Dates
GAME_DATE=${1:-$(TZ=America/New_York date -d "yesterday" +%Y-%m-%d)}
PROCESSING_DATE=$(TZ=America/New_York date +%Y-%m-%d)

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Morning Health Check - ${PROCESSING_DATE}${NC}"
echo -e "${BLUE}Validating data for games on: ${GAME_DATE}${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# ==============================================================================
# SECTION 1: Overnight Processing Summary
# ==============================================================================
echo -e "${BLUE}[1] OVERNIGHT PROCESSING SUMMARY${NC}"

# Single comprehensive query to get all phase data
OVERNIGHT_SUMMARY=$(bq query --use_legacy_sql=false --format=csv --quiet "
WITH game_counts AS (
  SELECT COUNT(DISTINCT game_id) as games_played
  FROM nba_analytics.player_game_summary
  WHERE game_date = DATE('${GAME_DATE}')
),
phase3_status AS (
  SELECT
    COUNT(*) as total_records,
    COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) as has_minutes,
    ROUND(COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) * 100.0 / NULLIF(COUNT(*), 0), 1) as minutes_pct,
    COUNTIF(usage_rate IS NOT NULL) as has_usage,
    ROUND(COUNTIF(usage_rate IS NOT NULL) * 100.0 / NULLIF(COUNT(*), 0), 1) as usage_pct
  FROM nba_analytics.player_game_summary
  WHERE game_date = DATE('${GAME_DATE}')
),
phase4_status AS (
  SELECT COUNT(*) as features
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = DATE('${GAME_DATE}')
),
phase5_status AS (
  SELECT COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = DATE('${GAME_DATE}')
    AND is_active = TRUE
)
SELECT
  g.games_played,
  p3.total_records as player_records,
  p3.minutes_pct,
  p3.usage_pct,
  p4.features,
  p5.predictions
FROM game_counts g, phase3_status p3, phase4_status p4, phase5_status p5
" 2>&1)

if echo "$OVERNIGHT_SUMMARY" | grep -q "Not found"; then
  echo -e "  ${RED}❌ ERROR: Could not query BigQuery tables${NC}"
  echo ""
else
  # Parse results (skip header, get data row)
  DATA_ROW=$(echo "$OVERNIGHT_SUMMARY" | tail -1)

  if [ -n "$DATA_ROW" ] && [ "$DATA_ROW" != "games_played,player_records,minutes_pct,usage_pct,features,predictions" ]; then
    GAMES=$(echo "$DATA_ROW" | cut -d',' -f1)
    PLAYER_RECORDS=$(echo "$DATA_ROW" | cut -d',' -f2)
    MINUTES_PCT=$(echo "$DATA_ROW" | cut -d',' -f3)
    USAGE_PCT=$(echo "$DATA_ROW" | cut -d',' -f4)
    FEATURES=$(echo "$DATA_ROW" | cut -d',' -f5)
    PREDICTIONS=$(echo "$DATA_ROW" | cut -d',' -f6)

    # Determine status for each metric
    if [ "${GAMES:-0}" -eq 0 ]; then
      echo -e "  ${YELLOW}ℹ️  No games played on ${GAME_DATE} (off-day)${NC}"
      echo ""
      echo -e "${GREEN}No issues - this is an off-day.${NC}"
      exit 0
    fi

    echo -e "  Games Processed: ${GREEN}${GAMES}${NC}"
    echo -e "  Player Records: ${PLAYER_RECORDS}"
    echo ""

    # Phase 3 - Analytics (check minutes and usage coverage)
    MINUTES_INT=${MINUTES_PCT%.*}
    USAGE_INT=${USAGE_PCT%.*}

    if [ "${MINUTES_INT:-0}" -ge 90 ]; then
      MINUTES_STATUS="${GREEN}✅ ${MINUTES_PCT}%${NC}"
    elif [ "${MINUTES_INT:-0}" -ge 80 ]; then
      MINUTES_STATUS="${YELLOW}⚠️  ${MINUTES_PCT}% (WARNING)${NC}"
    else
      MINUTES_STATUS="${RED}❌ ${MINUTES_PCT}% (CRITICAL)${NC}"
    fi

    if [ "${USAGE_INT:-0}" -ge 90 ]; then
      USAGE_STATUS="${GREEN}✅ ${USAGE_PCT}%${NC}"
    elif [ "${USAGE_INT:-0}" -ge 80 ]; then
      USAGE_STATUS="${YELLOW}⚠️  ${USAGE_PCT}% (WARNING)${NC}"
    else
      USAGE_STATUS="${RED}❌ ${USAGE_PCT}% (CRITICAL)${NC}"
    fi

    echo -e "  Phase 3 (Analytics):"
    echo -e "    - Minutes coverage: ${MINUTES_STATUS}"
    echo -e "    - Usage rate coverage: ${USAGE_STATUS}"

    # Phase 4 - ML Features
    if [ "${FEATURES:-0}" -gt 0 ]; then
      echo -e "  Phase 4 (Features): ${GREEN}✅ ${FEATURES} features${NC}"
    else
      echo -e "  Phase 4 (Features): ${RED}❌ No features generated${NC}"
    fi

    # Phase 5 - Predictions
    if [ "${PREDICTIONS:-0}" -gt 0 ]; then
      echo -e "  Phase 5 (Predictions): ${GREEN}✅ ${PREDICTIONS} predictions${NC}"
    else
      echo -e "  Phase 5 (Predictions): ${RED}❌ No predictions${NC}"
    fi

    echo ""
  else
    echo -e "  ${YELLOW}⚠️  Could not parse overnight summary${NC}"
    echo ""
  fi
fi

# ==============================================================================
# SECTION 2: Phase 3 Processor Completion (Must be 5/5)
# ==============================================================================
echo -e "${BLUE}[2] PHASE 3 PROCESSOR COMPLETION${NC}"

PHASE3_CHECK=$(PROCESSING_DATE="${PROCESSING_DATE}" python3 << 'EOF'
from google.cloud import firestore
import sys
import os
from datetime import datetime

EXPECTED_PROCESSORS = 5
EXPECTED_NAMES = [
    'player_game_summary',
    'team_offense_game_summary',
    'team_defense_game_summary',
    'upcoming_player_game_context',
    'upcoming_team_game_context'
]

processing_date = os.environ.get('PROCESSING_DATE', datetime.now().strftime('%Y-%m-%d'))
db = firestore.Client()
doc = db.collection('phase3_completion').document(processing_date).get()

if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]
    count = len(completed)
    triggered = data.get('_triggered', False)

    print(f"{count}/{EXPECTED_PROCESSORS}")
    print("triggered" if triggered else "not_triggered")

    # Print missing processors
    missing = set(EXPECTED_NAMES) - set(completed)
    if missing:
        print(",".join(sorted(missing)))
    else:
        print("none")

    sys.exit(0 if count == EXPECTED_PROCESSORS else 1)
else:
    print("0/5")
    print("no_record")
    print("all")
    sys.exit(1)
EOF
)

PHASE3_EXIT_CODE=$?
PROCESSOR_COUNT=$(echo "$PHASE3_CHECK" | sed -n '1p')
TRIGGER_STATUS=$(echo "$PHASE3_CHECK" | sed -n '2p')
MISSING_PROCS=$(echo "$PHASE3_CHECK" | sed -n '3p')

if [ $PHASE3_EXIT_CODE -eq 0 ]; then
  echo -e "  ${GREEN}✅ Processors: ${PROCESSOR_COUNT} complete${NC}"
  echo -e "  ${GREEN}✅ Phase 4 triggered: ${TRIGGER_STATUS}${NC}"
else
  echo -e "  ${RED}❌ Processors: ${PROCESSOR_COUNT} complete (CRITICAL)${NC}"
  echo -e "  ${RED}❌ Phase 4 triggered: ${TRIGGER_STATUS}${NC}"
  if [ "$MISSING_PROCS" != "none" ] && [ "$MISSING_PROCS" != "all" ]; then
    echo -e "  ${RED}   Missing: ${MISSING_PROCS}${NC}"
  fi
fi
echo ""

# ==============================================================================
# SECTION 3: Stuck Phase Detection
# ==============================================================================
echo -e "${BLUE}[3] STUCK PHASE DETECTION${NC}"

STUCK_PHASES=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  phase_name,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) as minutes_since_start
FROM nba_orchestration.phase_execution_log
WHERE status IN ('started', 'running')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) > 60
ORDER BY minutes_since_start DESC
LIMIT 5
" 2>&1)

if echo "$STUCK_PHASES" | grep -q "Not found"; then
  echo -e "  ${YELLOW}ℹ️  phase_execution_log table not available${NC}"
elif [ $(echo "$STUCK_PHASES" | wc -l) -le 1 ]; then
  echo -e "  ${GREEN}✅ No stuck phases detected${NC}"
else
  echo -e "  ${RED}❌ STUCK PHASES DETECTED:${NC}"
  echo "$STUCK_PHASES" | tail -n +2 | while IFS=, read -r phase_name minutes; do
    echo -e "  ${RED}   - ${phase_name}: stuck for ${minutes} minutes${NC}"
  done
fi
echo ""

# ==============================================================================
# SECTION 4: Recent Errors
# ==============================================================================
echo -e "${BLUE}[4] RECENT ERRORS (Last 2h)${NC}"

ERROR_COUNT=$(gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=10 --format="value(timestamp)" --freshness=2h 2>/dev/null | wc -l)

if [ "${ERROR_COUNT:-0}" -eq 0 ]; then
  echo -e "  ${GREEN}✅ No errors in last 2 hours${NC}"
else
  echo -e "  ${YELLOW}⚠️  ${ERROR_COUNT} errors found${NC}"
  gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
    --limit=3 --format="value(timestamp,resource.labels.service_name,textPayload)" --freshness=2h 2>/dev/null | head -6
fi
echo ""

# ==============================================================================
# SECTION 5: Data Source Health
# ==============================================================================
echo -e "${BLUE}[5] DATA SOURCE HEALTH${NC}"

# Check cross-source validation discrepancies
DISCREPANCY_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  COALESCE(SUM(CASE WHEN severity = 'major' THEN 1 ELSE 0 END), 0) as major_discrepancies,
  COALESCE(SUM(CASE WHEN severity = 'minor' THEN 1 ELSE 0 END), 0) as minor_discrepancies
FROM nba_orchestration.source_discrepancies
WHERE game_date = DATE('${GAME_DATE}')
" 2>&1)

if echo "$DISCREPANCY_COUNT" | grep -q "Not found\|Error"; then
  echo -e "  ${YELLOW}ℹ️  Source validation data not available${NC}"
else
  MAJOR_DISC=$(echo "$DISCREPANCY_COUNT" | tail -1 | cut -d',' -f1)
  MINOR_DISC=$(echo "$DISCREPANCY_COUNT" | tail -1 | cut -d',' -f2)

  if [ "${MAJOR_DISC:-0}" -eq 0 ]; then
    echo -e "  ${GREEN}✅ Cross-source validation: No major discrepancies${NC}"
  else
    echo -e "  ${YELLOW}⚠️  Cross-source validation: ${MAJOR_DISC} major, ${MINOR_DISC} minor discrepancies${NC}"
  fi
fi

# Check BDB PBP data gaps
BDB_GAPS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  COUNT(*) as gap_count,
  COUNTIF(severity = 'critical') as critical_gaps
FROM nba_orchestration.data_gaps
WHERE source = 'bigdataball_pbp'
  AND status = 'open'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
" 2>&1)

if echo "$BDB_GAPS" | grep -q "Not found\|Error"; then
  echo -e "  ${YELLOW}ℹ️  BDB PBP gap tracking not available${NC}"
else
  GAP_COUNT=$(echo "$BDB_GAPS" | tail -1 | cut -d',' -f1)
  CRITICAL_GAPS=$(echo "$BDB_GAPS" | tail -1 | cut -d',' -f2)

  if [ "${GAP_COUNT:-0}" -eq 0 ]; then
    echo -e "  ${GREEN}✅ BigDataBall PBP: All games have data${NC}"
  elif [ "${CRITICAL_GAPS:-0}" -gt 0 ]; then
    echo -e "  ${RED}❌ BigDataBall PBP: ${CRITICAL_GAPS} critical gaps (>24h missing)${NC}"
  else
    echo -e "  ${YELLOW}⚠️  BigDataBall PBP: ${GAP_COUNT} games waiting for data${NC}"
  fi
fi

# Check backup source coverage
BACKUP_COVERAGE=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  'bref' as source, COUNT(*) as records
FROM nba_raw.bref_player_boxscores
WHERE game_date = DATE('${GAME_DATE}')
UNION ALL
SELECT
  'nba_api' as source, COUNT(*) as records
FROM nba_raw.nba_api_player_boxscores
WHERE game_date = DATE('${GAME_DATE}')
" 2>&1)

if echo "$BACKUP_COVERAGE" | grep -q "Not found\|Error"; then
  echo -e "  ${YELLOW}ℹ️  Backup sources not yet scraped for ${GAME_DATE}${NC}"
else
  BREF_COUNT=$(echo "$BACKUP_COVERAGE" | grep "bref" | cut -d',' -f2)
  NBAAPI_COUNT=$(echo "$BACKUP_COVERAGE" | grep "nba_api" | cut -d',' -f2)

  if [ "${BREF_COUNT:-0}" -gt 0 ] && [ "${NBAAPI_COUNT:-0}" -gt 0 ]; then
    echo -e "  ${GREEN}✅ Backup sources: BRef (${BREF_COUNT}), NBA API (${NBAAPI_COUNT})${NC}"
  else
    echo -e "  ${YELLOW}ℹ️  Backup sources: BRef (${BREF_COUNT:-0}), NBA API (${NBAAPI_COUNT:-0})${NC}"
  fi
fi

echo ""

# ==============================================================================
# SECTION 6: Summary & Actions
# ==============================================================================
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}SUMMARY${NC}"
echo -e "${BLUE}================================================${NC}"

# Determine overall health
ISSUES=0

# Check minutes coverage
MINUTES_INT_CHECK=${MINUTES_PCT%.*}
if [ "${MINUTES_INT_CHECK:-100}" -lt 80 ]; then
  ISSUES=$((ISSUES + 1))
  echo -e "${RED}❌ CRITICAL: Minutes coverage is ${MINUTES_PCT}% (threshold: 80%)${NC}"
fi

# Check Phase 3 completion
if [ $PHASE3_EXIT_CODE -ne 0 ]; then
  ISSUES=$((ISSUES + 1))
  echo -e "${RED}❌ CRITICAL: Phase 3 incomplete (${PROCESSOR_COUNT})${NC}"
fi

# Check predictions
if [ "${PREDICTIONS:-0}" -eq 0 ] && [ "${GAMES:-0}" -gt 0 ]; then
  ISSUES=$((ISSUES + 1))
  echo -e "${RED}❌ ERROR: No predictions generated${NC}"
fi

# Check BDB critical gaps
if [ "${CRITICAL_GAPS:-0}" -gt 0 ]; then
  ISSUES=$((ISSUES + 1))
  echo -e "${RED}❌ WARNING: ${CRITICAL_GAPS} BigDataBall PBP gaps >24 hours${NC}"
fi

# Overall status
if [ $ISSUES -eq 0 ]; then
  echo -e "${GREEN}✅ All systems healthy - overnight processing completed successfully${NC}"
else
  echo -e "${RED}❌ ${ISSUES} critical issue(s) detected - immediate action required${NC}"
  echo ""
  echo -e "${YELLOW}Recommended actions:${NC}"
  echo -e "  1. Run full validation: ${BLUE}python scripts/validate_tonight_data.py --date ${GAME_DATE}${NC}"
  echo -e "  2. Check Cloud Run logs for failed processors"
  echo -e "  3. Review handoff docs: ${BLUE}docs/09-handoff/${NC}"
fi

echo -e "${BLUE}================================================${NC}"
echo "Completed at $(TZ=America/New_York date)"
