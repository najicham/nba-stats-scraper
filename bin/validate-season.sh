#!/bin/bash
# validate-season.sh — answer "is every past date of the season processed?"
#
# Runs against nba_orchestration.expected_outputs (the date-grid contract).
# Prints a compact summary the user can scan in seconds; emits CSV detail to
# /tmp/season-gaps.csv for follow-up.
#
# Usage:
#   ./bin/validate-season.sh           # NBA + MLB, default windows
#   ./bin/validate-season.sh nba       # NBA only
#   ./bin/validate-season.sh nba 2025-10-21 2026-04-13   # explicit range
#
# Pipeline-state-redesign Phase F.

set -euo pipefail

PROJECT_ID="nba-props-platform"
SPORT="${1:-all}"
START="${2:-2025-10-01}"
END="${3:-$(date +%Y-%m-%d)}"

if [ "${SPORT}" = "all" ]; then
  SPORT_FILTER=""
else
  SPORT_FILTER="AND sport = '${SPORT}'"
fi

echo "==> Season validation: sport=${SPORT} range=${START}..${END}"
echo

echo "==> 1. Coverage by phase (% COMPLETE + EMPTY_OK)"
bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=pretty \
  "SELECT
    sport,
    phase,
    COUNT(*) AS expected_total,
    COUNTIF(status IN ('COMPLETE', 'EMPTY_OK')) AS healthy,
    COUNTIF(status IN ('EXPECTED', 'RUNNING')) AS pending,
    COUNTIF(status IN ('FAILED', 'DEGRADED')) AS broken,
    ROUND(100.0 * COUNTIF(status IN ('COMPLETE', 'EMPTY_OK')) / COUNT(*), 1) AS pct_healthy
   FROM \`${PROJECT_ID}.nba_orchestration.expected_outputs\`
   WHERE game_date BETWEEN '${START}' AND '${END}' ${SPORT_FILTER}
   GROUP BY sport, phase
   ORDER BY sport, phase" 2>&1 | tail -25
echo

echo "==> 2. Top 20 oldest unresolved gaps"
bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=pretty \
  "SELECT sport, game_date, phase, output_type, status, attempts,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), expected_by, HOUR) AS hours_overdue
   FROM \`${PROJECT_ID}.nba_orchestration.expected_outputs\`
   WHERE status IN ('EXPECTED', 'FAILED', 'DEGRADED')
     AND expected_by < CURRENT_TIMESTAMP()
     AND game_date BETWEEN '${START}' AND '${END}'
     ${SPORT_FILTER}
   ORDER BY hours_overdue DESC
   LIMIT 20" 2>&1 | tail -25
echo

echo "==> 3. Dates with ZERO healthy outputs (worst hits)"
bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=pretty \
  "SELECT sport, game_date,
          COUNT(*) AS expected_total,
          COUNTIF(status IN ('COMPLETE', 'EMPTY_OK')) AS healthy
   FROM \`${PROJECT_ID}.nba_orchestration.expected_outputs\`
   WHERE game_date BETWEEN '${START}' AND '${END}'
     ${SPORT_FILTER}
   GROUP BY sport, game_date
   HAVING healthy = 0
   ORDER BY game_date DESC
   LIMIT 20" 2>&1 | tail -25
echo

echo "==> Full per-row gap detail written to: /tmp/season-gaps.csv"
bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=csv --headless \
  "SELECT sport, game_date, phase, output_type, status, attempts, last_error
   FROM \`${PROJECT_ID}.nba_orchestration.expected_outputs\`
   WHERE status NOT IN ('COMPLETE', 'EMPTY_OK')
     AND game_date BETWEEN '${START}' AND '${END}'
     ${SPORT_FILTER}
   ORDER BY game_date DESC, phase, output_type" \
   > /tmp/season-gaps.csv 2>&1

GAP_COUNT=$(($(wc -l < /tmp/season-gaps.csv) - 1))
echo "    ${GAP_COUNT} non-healthy rows. View with: head -50 /tmp/season-gaps.csv"
echo
echo "==> Done."
