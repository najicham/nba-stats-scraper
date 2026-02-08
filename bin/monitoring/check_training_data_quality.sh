#!/bin/bash
#
# Training Data Contamination Monitor (v2)
# Session 158: Three-tier contamination reporting with per-feature breakdown
#
# Reports:
#   Tier 1: Required-feature defaults (blocks predictions)
#   Tier 2: Optional-feature defaults (vegas - expected for bench players)
#   Tier 3: Per-feature breakdown (pinpoint which features are defaulted)
#
# Usage:
#   ./bin/monitoring/check_training_data_quality.sh
#   ./bin/monitoring/check_training_data_quality.sh --train-start 2025-11-02
#   ./bin/monitoring/check_training_data_quality.sh --recent          # Last 14 days only
#
# Exit codes:
#   0 = Clean (required contamination <= threshold)
#   1 = Contaminated (required contamination > threshold)
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Defaults
TRAIN_START="2025-11-02"
RECENT_ONLY=false
PROJECT_ID="nba-props-platform"
REQUIRED_THRESHOLD=15  # Alert if > 15% required defaults

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --train-start)
            TRAIN_START="$2"
            shift 2
            ;;
        --recent)
            RECENT_ONLY=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

if [[ "$RECENT_ONLY" == "true" ]]; then
    DATE_FILTER="game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)"
    WINDOW_LABEL="Last 14 days"
else
    DATE_FILTER="game_date >= '${TRAIN_START}'"
    WINDOW_LABEL="${TRAIN_START} to today"
fi

echo -e "${CYAN}=== Training Data Quality Monitor v2 (Session 158) ===${NC}"
echo -e "Window: ${GREEN}${WINDOW_LABEL}${NC}"
echo -e "Required-feature threshold: ${YELLOW}${REQUIRED_THRESHOLD}%${NC}"
echo ""

# ── TIER 1 + 2: Required vs Optional breakdown ──
echo -e "${BOLD}${CYAN}TIER 1: Required Feature Defaults (blocks predictions)${NC}"
echo -e "${CYAN}TIER 2: Optional Feature Defaults (vegas - expected)${NC}"
echo -e "──────────────────────────────────────────────────────"

python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='${PROJECT_ID}')

query = '''
SELECT
    COUNT(*) as total,
    -- Required defaults (Tier 1 - blocks predictions)
    COUNTIF(required_default_count > 0) as req_contaminated,
    ROUND(COUNTIF(required_default_count > 0) * 100.0 / NULLIF(COUNT(*), 0), 1) as req_pct,
    ROUND(AVG(required_default_count), 2) as avg_req_defaults,
    -- All defaults (Tier 1 + 2)
    COUNTIF(default_feature_count > 0) as all_contaminated,
    ROUND(COUNTIF(default_feature_count > 0) * 100.0 / NULLIF(COUNT(*), 0), 1) as all_pct,
    ROUND(AVG(default_feature_count), 2) as avg_all_defaults,
    -- Quality ready
    COUNTIF(is_quality_ready = TRUE) as quality_ready,
    ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / NULLIF(COUNT(*), 0), 1) as ready_pct,
    -- Vegas-only defaults (Tier 2 = all - required)
    COUNTIF(default_feature_count > 0 AND required_default_count = 0) as vegas_only,
    ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM \`${PROJECT_ID}.nba_predictions.ml_feature_store_v2\`
WHERE ${DATE_FILTER}
  AND game_date < CURRENT_DATE()
  AND feature_count >= 37
'''

rows = list(client.query(query).result())
if not rows or rows[0].total == 0:
    print('No data found')
    exit(1)

r = rows[0]
vegas_pct = round(r.vegas_only * 100.0 / r.total, 1) if r.total > 0 else 0

print(f'  Total records:        {r.total:,}')
print()
print(f'  \033[1mTier 1 (Required):\033[0m')
print(f'    With req defaults:  {r.req_contaminated:,} ({r.req_pct}%)')
print(f'    Clean (no req def): {r.total - r.req_contaminated:,} ({round(100 - r.req_pct, 1)}%)')
print(f'    Avg req defaults:   {r.avg_req_defaults}')
print(f'    Quality-ready:      {r.quality_ready:,} ({r.ready_pct}%)')
print()
print(f'  \033[1mTier 2 (Vegas only):\033[0m')
print(f'    Vegas-only gaps:    {r.vegas_only:,} ({vegas_pct}%)  \033[2m← Expected for bench players\033[0m')
print()
print(f'  Avg quality score:    {r.avg_quality}')
"

echo ""

# ── Monthly Breakdown ──
echo -e "${BOLD}${CYAN}Monthly Breakdown (Required defaults only):${NC}"
echo -e "──────────────────────────────────────────────────────"

python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='${PROJECT_ID}')

query = '''
SELECT
    FORMAT_DATE('%Y-%m', game_date) as month,
    COUNT(*) as total,
    COUNTIF(required_default_count = 0) as clean,
    COUNTIF(required_default_count > 0) as req_contam,
    ROUND(COUNTIF(required_default_count > 0) * 100.0 / NULLIF(COUNT(*), 0), 1) as req_pct,
    COUNTIF(is_quality_ready = TRUE) as ready,
    ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / NULLIF(COUNT(*), 0), 1) as ready_pct
FROM \`${PROJECT_ID}.nba_predictions.ml_feature_store_v2\`
WHERE ${DATE_FILTER}
  AND game_date < CURRENT_DATE()
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1
'''

rows = list(client.query(query).result())
print(f'  {\"Month\":<10} {\"Total\":>7} {\"Clean\":>7} {\"ReqDef\":>7} {\"Req%\":>6} {\"Ready\":>7} {\"Rdy%\":>6}')
print(f'  {\"─\"*10} {\"─\"*7} {\"─\"*7} {\"─\"*7} {\"─\"*6} {\"─\"*7} {\"─\"*6}')
for r in rows:
    flag = ' !!!' if r.req_pct > 15 else (' !' if r.req_pct > 5 else '')
    print(f'  {r.month:<10} {r.total:>7,} {r.clean:>7,} {r.req_contam:>7,} {r.req_pct:>5.1f}% {r.ready:>7,} {r.ready_pct:>5.1f}%{flag}')
"

echo ""

# ── TIER 3: Per-feature breakdown ──
echo -e "${BOLD}${CYAN}TIER 3: Top Defaulted Features (pinpoints the problem):${NC}"
echo -e "──────────────────────────────────────────────────────"

python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='${PROJECT_ID}')

query = '''
WITH feature_names AS (
  SELECT 0 as idx, 'pts_avg_l5' as name, 'required' as kind UNION ALL
  SELECT 1, 'pts_avg_l10', 'required' UNION ALL
  SELECT 2, 'pts_avg_season', 'required' UNION ALL
  SELECT 3, 'pts_std_l10', 'required' UNION ALL
  SELECT 4, 'games_7d', 'required' UNION ALL
  SELECT 5, 'fatigue', 'required' UNION ALL
  SELECT 6, 'shot_zone_mismatch', 'required' UNION ALL
  SELECT 7, 'pace', 'required' UNION ALL
  SELECT 8, 'usage_spike', 'required' UNION ALL
  SELECT 9, 'home_away', 'required' UNION ALL
  SELECT 10, 'b2b', 'required' UNION ALL
  SELECT 11, 'rest_days', 'required' UNION ALL
  SELECT 12, 'season_game_num', 'required' UNION ALL
  SELECT 13, 'opp_def_rating', 'required' UNION ALL
  SELECT 14, 'opp_pace', 'required' UNION ALL
  SELECT 15, 'is_home', 'required' UNION ALL
  SELECT 16, 'is_b2b', 'required' UNION ALL
  SELECT 17, 'rest_days_exact', 'required' UNION ALL
  SELECT 18, 'pct_paint', 'required' UNION ALL
  SELECT 19, 'pct_mid_range', 'required' UNION ALL
  SELECT 20, 'pct_three', 'required' UNION ALL
  SELECT 21, 'season_progress', 'required' UNION ALL
  SELECT 22, 'team_pace', 'required' UNION ALL
  SELECT 23, 'team_off_rating', 'required' UNION ALL
  SELECT 24, 'team_win_pct', 'required' UNION ALL
  SELECT 25, 'vegas_line', 'optional' UNION ALL
  SELECT 26, 'vegas_opening', 'optional' UNION ALL
  SELECT 27, 'vegas_line_move', 'optional' UNION ALL
  SELECT 28, 'line_available', 'required' UNION ALL
  SELECT 29, 'opp_history_avg', 'required' UNION ALL
  SELECT 30, 'opp_history_games', 'required' UNION ALL
  SELECT 31, 'minutes_avg_l10', 'required' UNION ALL
  SELECT 32, 'ppm_avg_l10', 'required' UNION ALL
  SELECT 33, 'pts_trend_l5', 'required' UNION ALL
  SELECT 34, 'consistency_l10', 'required' UNION ALL
  SELECT 35, 'ceiling_l10', 'required' UNION ALL
  SELECT 36, 'floor_l10', 'required'
),
defaults AS (
  SELECT idx, COUNT(*) as cnt
  FROM \`${PROJECT_ID}.nba_predictions.ml_feature_store_v2\`,
  UNNEST(default_feature_indices) as idx
  WHERE ${DATE_FILTER}
    AND game_date < CURRENT_DATE()
    AND feature_count >= 37
  GROUP BY 1
),
total AS (
  SELECT COUNT(*) as n
  FROM \`${PROJECT_ID}.nba_predictions.ml_feature_store_v2\`
  WHERE ${DATE_FILTER}
    AND game_date < CURRENT_DATE()
    AND feature_count >= 37
)
SELECT
  d.idx,
  fn.name,
  fn.kind,
  d.cnt as default_count,
  ROUND(d.cnt * 100.0 / t.n, 1) as pct_records
FROM defaults d
JOIN feature_names fn ON d.idx = fn.idx
CROSS JOIN total t
ORDER BY d.cnt DESC
LIMIT 15
'''

rows = list(client.query(query).result())
print(f'  {\"#\":>3} {\"Feature\":<22} {\"Kind\":<10} {\"Defaults\":>9} {\"% Records\":>9}')
print(f'  {\"─\"*3} {\"─\"*22} {\"─\"*10} {\"─\"*9} {\"─\"*9}')
for r in rows:
    kind_display = '\033[2m(optional)\033[0m' if r.kind == 'optional' else '\033[1;31mREQUIRED\033[0m'
    print(f'  {r.idx:>3} {r.name:<22} {kind_display:<20} {r.default_count:>9,} {r.pct_records:>8.1f}%')
"

echo ""

# ── Threshold check ──
REQ_PCT=$(python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='${PROJECT_ID}')
query = '''
SELECT ROUND(COUNTIF(required_default_count > 0) * 100.0 / NULLIF(COUNT(*), 0), 1) as pct
FROM \`${PROJECT_ID}.nba_predictions.ml_feature_store_v2\`
WHERE ${DATE_FILTER} AND game_date < CURRENT_DATE() AND feature_count >= 37
'''
rows = list(client.query(query).result())
print(rows[0].pct if rows else 0)
")

OVER=$(python3 -c "print('yes' if float('${REQ_PCT}') > ${REQUIRED_THRESHOLD} else 'no')")

if [[ "$OVER" == "yes" ]]; then
    echo -e "${RED}ALERT: Required-feature contamination ${REQ_PCT}% exceeds ${REQUIRED_THRESHOLD}% threshold!${NC}"
    echo -e "${RED}Action: Check TIER 3 above for which features are most defaulted.${NC}"
    echo -e "${RED}Then check if the corresponding Phase 4 processor is running.${NC}"
    exit 1
else
    echo -e "${GREEN}OK: Required-feature contamination ${REQ_PCT}% is within ${REQUIRED_THRESHOLD}% threshold.${NC}"
    exit 0
fi
