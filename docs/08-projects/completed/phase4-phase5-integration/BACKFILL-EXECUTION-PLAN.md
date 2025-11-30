# Backfill Execution Plan - Complete Strategy & Procedures

**Created:** 2025-11-28 9:15 PM PST
**Last Updated:** 2025-11-28 9:15 PM PST
**Purpose:** Comprehensive backfill execution strategy with scripts and procedures

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Strategy Overview](#strategy-overview)
3. [Phase 1-2: Historical Scrapers & Raw Data](#phase-1-2-historical)
4. [Phase 3: Historical Analytics](#phase-3-historical)
5. [Phase 4: Historical Precompute](#phase-4-historical)
6. [Phase 5: Current Season with Predictions](#phase-5-current-season)
7. [Verification Procedures](#verification-procedures)
8. [Monitoring & Progress Tracking](#monitoring)
9. [Troubleshooting](#troubleshooting)
10. [Timeline & Resource Planning](#timeline)

---

## Executive Summary

### Backfill Goals

1. **Load 4 historical seasons** (2020-21, 2021-22, 2022-23, 2023-24) into Phases 1-4
2. **Skip Phase 5 for historical data** (no predictions for old games)
3. **Load current season** (2024-25) through ALL 5 phases (including predictions)
4. **Validate completeness** at each step
5. **Optimize for speed** with parallelization

### Key Decisions

**What Auto-Triggers During Backfill:**
- ✅ Phase 1 → Phase 2 (automatic via Pub/Sub)
- ❌ Phase 2 → Phase 3 (MANUAL trigger needed)
- ❌ Phase 3 → Phase 4 (MANUAL trigger needed)
- ❌ Phase 4 → Phase 5 (MANUAL trigger needed)

**Why:** `skip_downstream_trigger=true` flag prevents automatic cascading

**Execution Order:**
1. Phase 1-2 for all historical dates (2-3 days)
2. Phase 3 for all historical dates (4-6 hours)
3. Phase 4 for all historical dates (4-6 hours)
4. Phases 1-5 for current season (2-3 hours)

**Total Timeline:** ~3-4 days wall-clock time

---

## Strategy Overview

### Why This Order?

**Option A: Sequential by Phase (CHOSEN)**
```
Complete ALL of Phases 1-2 for all dates
  ↓
Then ALL of Phase 3 for all dates
  ↓
Then ALL of Phase 4 for all dates
  ↓
Then Phases 1-5 for current season
```

**Advantages:**
- ✅ Clear progress tracking (100% Phase 1-2 done, now starting Phase 3)
- ✅ Easier debugging (all raw data available before analytics)
- ✅ Can optimize parallelization per phase
- ✅ Can test Phase 3 with complete Phase 2 data
- ✅ Phase 3 processors have all dependencies ready

**Alternative (NOT CHOSEN): Scraper-by-Scraper**
```
Complete scraper 1 for all dates → phases 1-4
  ↓
Complete scraper 2 for all dates → phases 1-4
  ↓
etc.
```

**Why rejected:**
- ❌ Phase 3 can't start until ALL scrapers done anyway
- ❌ No benefit to completing one scraper first
- ❌ More complex orchestration
- ❌ Harder to parallelize

---

### Parallelization Strategy

**Phase 1-2 (Scraper Execution):**
- Multiple dates simultaneously (10 at a time)
- Multiple scrapers simultaneously (21 scrapers)
- Total: 10 dates × 21 scrapers = 210 concurrent operations
- Cloud Run scales to handle this

**Phase 3 (Analytics):**
- Multiple dates simultaneously (20 at a time)
- Each date runs 5 analytics processors
- Total: 20 dates × 5 processors = 100 concurrent operations

**Phase 4 (Precompute):**
- Multiple dates simultaneously (10 at a time)
- Each date runs 5 precompute processors with internal orchestration
- Total: 10 dates × 5 processors = 50 concurrent operations

**Phase 5 (Current Season):**
- One date at a time (sequential)
- Full pipeline validation for each date
- No rush - validating system works

---

## Phase 1-2: Historical Scrapers & Raw Data {#phase-1-2-historical}

### Overview

**Goal:** Load 4 seasons of raw data from NBA.com APIs into BigQuery raw tables

**Scope:**
- Seasons: 2020-21, 2021-22, 2022-23, 2023-24
- ~500 total game dates
- 21 scrapers per date
- ~10,500 total scraper runs

**Expected Duration:** 2-3 days

---

### Script: backfill_historical_phases1_2.sh

```bash
#!/bin/bash
# bin/backfill/backfill_historical_phases1_2.sh
#
# Backfill Phases 1-2 (scrapers + raw processing) for historical seasons
#
# Usage:
#   ./bin/backfill/backfill_historical_phases1_2.sh
#
# Environment Variables:
#   PARALLEL_DATES: Number of dates to process simultaneously (default: 10)
#   DRY_RUN: If set, only print commands without executing

set -euo pipefail

# Configuration
SCRAPER_URL="${SCRAPER_URL:-https://nba-phase1-scrapers-756957797294.us-west2.run.app}"
PARALLEL_DATES="${PARALLEL_DATES:-10}"
DRY_RUN="${DRY_RUN:-false}"
PROJECT_ID="nba-props-platform"

# List of all scrapers
SCRAPERS=(
  "bdl_games"
  "bdl_player_boxscores"
  "bdl_team_boxscores"
  "nbac_game_summary"
  "nbac_team_boxscore"
  "nbac_player_boxscore"
  "nbac_play_by_play"
  "nbap_player_traditional"
  "nbap_team_traditional"
  "nbap_player_advanced"
  "nbap_team_advanced"
  "nbap_player_misc"
  "nbap_team_misc"
  "nbap_player_scoring"
  "nbap_team_scoring"
  "nbap_player_usage"
  "nbap_team_usage"
  "nbap_player_defense"
  "nbap_team_defense"
  "nbap_tracking_player"
  "nbap_tracking_team"
)

SEASONS=("2020-21" "2021-22" "2022-23" "2023-24")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

# Get all game dates for a season
get_game_dates_for_season() {
  local season=$1

  bq query \
    --use_legacy_sql=false \
    --format=csv \
    --max_rows=1000 \
    "
    SELECT DISTINCT game_date
    FROM \`${PROJECT_ID}.nba_reference.nba_schedule\`
    WHERE season = '${season}'
    ORDER BY game_date
    " | tail -n +2
}

# Trigger a single scraper for a date
trigger_scraper() {
  local scraper=$1
  local game_date=$2
  local skip_downstream=$3

  local payload=$(cat <<EOF
{
  "scraper": "${scraper}",
  "game_date": "${game_date}",
  "skip_downstream_trigger": ${skip_downstream},
  "backfill_mode": true,
  "backfill_reason": "historical_data_load"
}
EOF
)

  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: Would trigger ${scraper} for ${game_date}"
    return 0
  fi

  curl -X POST "${SCRAPER_URL}/scrape" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    -s -o /dev/null -w "%{http_code}" 2>&1
}

# Wait for Phase 2 to process a batch
wait_for_phase2_batch() {
  local game_date=$1
  local max_wait_seconds=600  # 10 minutes
  local check_interval=30
  local elapsed=0

  log_info "Waiting for Phase 2 to process ${game_date}..."

  while [ $elapsed -lt $max_wait_seconds ]; do
    # Check how many Phase 2 processors completed for this date
    local completed=$(bq query \
      --use_legacy_sql=false \
      --format=csv \
      "
      SELECT COUNT(DISTINCT processor_name)
      FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
      WHERE data_date = '${game_date}'
        AND phase = 'phase_2_raw'
        AND status IN ('success', 'partial')
      " | tail -n 1)

    if [ "$completed" -ge 18 ]; then  # At least 18/21 (85%)
      log_info "✅ Phase 2 complete for ${game_date} (${completed}/21 processors)"
      return 0
    fi

    sleep $check_interval
    elapsed=$((elapsed + check_interval))
  done

  log_warn "⚠️  Phase 2 incomplete for ${game_date} after ${max_wait_seconds}s (${completed}/21)"
  return 1
}

# Main execution
main() {
  log_info "========================================="
  log_info "Backfill Historical Phases 1-2"
  log_info "========================================="
  log_info "Seasons: ${SEASONS[*]}"
  log_info "Parallel dates: ${PARALLEL_DATES}"
  log_info "Scrapers per date: ${#SCRAPERS[@]}"
  log_info "Dry run: ${DRY_RUN}"
  log_info ""

  # Process each season
  for season in "${SEASONS[@]}"; do
    log_info "========================================="
    log_info "Processing Season: ${season}"
    log_info "========================================="

    # Get all game dates for this season
    log_info "Fetching game dates for ${season}..."
    mapfile -t game_dates < <(get_game_dates_for_season "$season")

    log_info "Found ${#game_dates[@]} game dates for ${season}"

    # Process dates in batches
    local total_dates=${#game_dates[@]}
    local batch_num=1

    for ((i=0; i<total_dates; i+=PARALLEL_DATES)); do
      # Get batch of dates
      local batch_end=$((i + PARALLEL_DATES))
      if [ $batch_end -gt $total_dates ]; then
        batch_end=$total_dates
      fi

      local batch_dates=("${game_dates[@]:$i:$PARALLEL_DATES}")
      local batch_size=${#batch_dates[@]}

      log_info ""
      log_info "--- Batch ${batch_num} (${i}/${total_dates}) ---"
      log_info "Dates: ${batch_dates[0]} to ${batch_dates[-1]}"
      log_info "Processing ${batch_size} dates in parallel..."

      # For each date in batch, trigger all scrapers
      for date in "${batch_dates[@]}"; do
        log_info "Triggering scrapers for ${date}..."

        # Trigger all scrapers for this date in parallel
        for scraper in "${SCRAPERS[@]}"; do
          {
            http_code=$(trigger_scraper "$scraper" "$date" true)

            if [ "$http_code" = "200" ] || [ "$http_code" = "202" ]; then
              echo "  ✅ ${scraper}"
            else
              echo "  ❌ ${scraper} (HTTP ${http_code})"
            fi
          } &
        done
      done

      # Wait for all scrapers in this batch to complete
      log_info "Waiting for batch scrapers to complete..."
      wait

      # Give Phase 2 time to process
      log_info "Allowing Phase 2 to process batch..."
      sleep 120

      # Verify Phase 2 completion for each date in batch
      for date in "${batch_dates[@]}"; do
        wait_for_phase2_batch "$date" || log_warn "Phase 2 incomplete for ${date}"
      done

      log_info "✅ Batch ${batch_num} complete"
      batch_num=$((batch_num + 1))
    done

    log_info "✅ Season ${season} complete (Phases 1-2)"
  done

  log_info ""
  log_info "========================================="
  log_info "Backfill Complete: Phases 1-2"
  log_info "========================================="
  log_info "Run verification: ./bin/backfill/verify_phase1_2.sh"
}

# Run main
main "$@"
```

---

### Execution

```bash
# Standard execution
./bin/backfill/backfill_historical_phases1_2.sh

# Custom parallelism
PARALLEL_DATES=20 ./bin/backfill/backfill_historical_phases1_2.sh

# Dry run (see what would happen)
DRY_RUN=true ./bin/backfill/backfill_historical_phases1_2.sh

# With monitoring
./bin/backfill/backfill_historical_phases1_2.sh 2>&1 | tee backfill_phase1_2.log
```

---

### Verification Script

```bash
#!/bin/bash
# bin/backfill/verify_phase1_2.sh
#
# Verify Phase 1-2 backfill completeness

set -euo pipefail

PROJECT_ID="nba-props-platform"

echo "========================================="
echo "Phase 1-2 Verification"
echo "========================================="
echo ""

# Check raw table coverage by season
echo "Raw Table Coverage by Season:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  season,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as total_rows
FROM \`${PROJECT_ID}.nba_raw.bdl_games\`
WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
GROUP BY season
ORDER BY season
"

echo ""
echo "Player Boxscore Coverage:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  season,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(*) as total_player_games
FROM \`${PROJECT_ID}.nba_raw.nbac_player_boxscore\`
WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
GROUP BY season
ORDER BY season
"

echo ""
echo "Processor Run History:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  COUNT(DISTINCT data_date) as dates_processed,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
  SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) as partial
FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
WHERE phase = 'phase_2_raw'
  AND data_date >= '2020-10-01'
  AND data_date <= '2024-06-30'
GROUP BY processor_name
ORDER BY processor_name
"

echo ""
echo "Missing Dates Check:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
WITH expected_dates AS (
  SELECT DISTINCT game_date, season
  FROM \`${PROJECT_ID}.nba_reference.nba_schedule\`
  WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
),
actual_dates AS (
  SELECT DISTINCT game_date
  FROM \`${PROJECT_ID}.nba_raw.bdl_games\`
  WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
)
SELECT
  e.season,
  COUNT(*) as missing_dates
FROM expected_dates e
LEFT JOIN actual_dates a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
GROUP BY e.season
ORDER BY e.season
"

echo ""
echo "========================================="
echo "Verification Complete"
echo "========================================="
```

---

## Phase 3: Historical Analytics {#phase-3-historical}

### Overview

**Goal:** Generate analytics aggregations for all historical game dates

**Scope:**
- ~500 game dates across 4 seasons
- 5 analytics processors per date
- ~2,500 total processor runs

**Expected Duration:** 4-6 hours (with parallelism)

**Key Difference from Phase 1-2:**
- Phase 2 auto-triggered from Phase 1 via Pub/Sub
- Phase 3 MUST be manually triggered (skip_downstream_trigger=true in Phase 2)

---

### Script: backfill_phase3.sh

```bash
#!/bin/bash
# bin/backfill/backfill_phase3.sh
#
# Backfill Phase 3 (analytics) for all historical dates
#
# Usage:
#   ./bin/backfill/backfill_phase3.sh

set -euo pipefail

# Configuration
PHASE3_URL="${PHASE3_URL:-https://nba-phase3-analytics-processors-756957797294.us-west2.run.app}"
PARALLEL_DATES="${PARALLEL_DATES:-20}"
DRY_RUN="${DRY_RUN:-false}"
PROJECT_ID="nba-props-platform"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get all game dates that have Phase 2 data
get_all_historical_dates() {
  bq query \
    --use_legacy_sql=false \
    --format=csv \
    --max_rows=1000 \
    "
    SELECT DISTINCT game_date
    FROM \`${PROJECT_ID}.nba_raw.bdl_games\`
    WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
    ORDER BY game_date
    " | tail -n +2
}

# Trigger Phase 3 for a date
trigger_phase3() {
  local analysis_date=$1
  local skip_downstream=$2

  local payload=$(cat <<EOF
{
  "analysis_date": "${analysis_date}",
  "skip_downstream_trigger": ${skip_downstream},
  "backfill_mode": true,
  "backfill_reason": "historical_analytics_load"
}
EOF
)

  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: Would trigger Phase 3 for ${analysis_date}"
    return 0
  fi

  local http_code=$(curl -X POST "${PHASE3_URL}/process" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    -s -o /dev/null -w "%{http_code}" 2>&1)

  echo "$http_code"
}

# Check Phase 3 completion for a date
check_phase3_complete() {
  local analysis_date=$1

  local completed=$(bq query \
    --use_legacy_sql=false \
    --format=csv \
    "
    SELECT COUNT(DISTINCT processor_name)
    FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
    WHERE data_date = '${analysis_date}'
      AND phase = 'phase_3_analytics'
      AND status = 'success'
    " | tail -n 1)

  echo "$completed"
}

# Wait for Phase 3 completion for multiple dates
wait_for_phase3_batch() {
  local -n dates_ref=$1
  local max_wait_seconds=1200  # 20 minutes
  local check_interval=60
  local elapsed=0

  log_info "Waiting for Phase 3 batch to complete..."

  while [ $elapsed -lt $max_wait_seconds ]; do
    local all_complete=true

    for date in "${dates_ref[@]}"; do
      local completed=$(check_phase3_complete "$date")

      if [ "$completed" -lt 5 ]; then
        all_complete=false
      fi
    done

    if [ "$all_complete" = true ]; then
      log_info "✅ All dates in batch complete"
      return 0
    fi

    sleep $check_interval
    elapsed=$((elapsed + check_interval))
  done

  # Report incomplete dates
  log_warn "⚠️  Timeout waiting for batch. Checking individual dates..."
  for date in "${dates_ref[@]}"; do
    local completed=$(check_phase3_complete "$date")
    if [ "$completed" -lt 5 ]; then
      log_warn "  Incomplete: ${date} (${completed}/5 processors)"
    else
      log_info "  ✅ Complete: ${date}"
    fi
  done

  return 1
}

# Main execution
main() {
  log_info "========================================="
  log_info "Backfill Phase 3 (Analytics)"
  log_info "========================================="
  log_info "Parallel dates: ${PARALLEL_DATES}"
  log_info "Dry run: ${DRY_RUN}"
  log_info ""

  # Get all dates that have Phase 2 data
  log_info "Fetching historical game dates with Phase 2 data..."
  mapfile -t all_dates < <(get_all_historical_dates)

  log_info "Found ${#all_dates[@]} dates to process"
  log_info ""

  # Process in batches
  local total_dates=${#all_dates[@]}
  local batch_num=1

  for ((i=0; i<total_dates; i+=PARALLEL_DATES)); do
    local batch_end=$((i + PARALLEL_DATES))
    if [ $batch_end -gt $total_dates ]; then
      batch_end=$total_dates
    fi

    local batch_dates=("${all_dates[@]:$i:$PARALLEL_DATES}")
    local batch_size=${#batch_dates[@]}

    log_info "--- Batch ${batch_num} (${i}/${total_dates}) ---"
    log_info "Dates: ${batch_dates[0]} to ${batch_dates[-1]}"
    log_info "Processing ${batch_size} dates in parallel..."

    # Trigger Phase 3 for each date in batch (parallel)
    for date in "${batch_dates[@]}"; do
      {
        http_code=$(trigger_phase3 "$date" true)

        if [ "$http_code" = "200" ] || [ "$http_code" = "202" ]; then
          echo "  ✅ ${date}"
        else
          echo "  ❌ ${date} (HTTP ${http_code})"
        fi
      } &
    done

    # Wait for all triggers to complete
    wait

    # Wait for all Phase 3 processors to complete
    wait_for_phase3_batch batch_dates || log_warn "Some dates incomplete in batch ${batch_num}"

    log_info "✅ Batch ${batch_num} complete"
    log_info ""
    batch_num=$((batch_num + 1))
  done

  log_info "========================================="
  log_info "Backfill Complete: Phase 3"
  log_info "========================================="
  log_info "Run verification: ./bin/backfill/verify_phase3.sh"
}

main "$@"
```

---

### Verification Script

```bash
#!/bin/bash
# bin/backfill/verify_phase3.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"

echo "========================================="
echo "Phase 3 Verification"
echo "========================================="
echo ""

echo "Analytics Coverage by Season:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  season,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_player_games
FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
GROUP BY season
ORDER BY season
"

echo ""
echo "Phase 3 Processor Runs:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  COUNT(DISTINCT data_date) as dates_processed,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
WHERE phase = 'phase_3_analytics'
  AND data_date >= '2020-10-01'
  AND data_date <= '2024-06-30'
GROUP BY processor_name
ORDER BY processor_name
"

echo ""
echo "Missing Dates (Phase 3 vs Phase 2):"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
WITH phase2_dates AS (
  SELECT DISTINCT game_date
  FROM \`${PROJECT_ID}.nba_raw.bdl_games\`
  WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
),
phase3_dates AS (
  SELECT DISTINCT game_date
  FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
)
SELECT COUNT(*) as missing_dates
FROM phase2_dates p2
LEFT JOIN phase3_dates p3 ON p2.game_date = p3.game_date
WHERE p3.game_date IS NULL
"
```

---

## Phase 4: Historical Precompute {#phase-4-historical}

### Overview

**Goal:** Generate ML features for all historical players

**Scope:**
- ~500 game dates
- 5 precompute processors per date (with 3-level dependencies)
- Final output: ml_feature_store_v2 table with all historical features

**Expected Duration:** 4-6 hours (with parallelism)

**Key Considerations:**
- Phase 4 has internal orchestrator managing Level 1 → Level 2 → Level 3
- We just trigger Phase 4, orchestrator handles dependencies
- Heavier processing than Phase 3 (more computation per player)

---

### Script: backfill_phase4.sh

```bash
#!/bin/bash
# bin/backfill/backfill_phase4.sh
#
# Backfill Phase 4 (precompute) for all historical dates

set -euo pipefail

# Configuration
PHASE4_URL="${PHASE4_URL:-https://nba-phase4-precompute-processors-756957797294.us-west2.run.app}"
PARALLEL_DATES="${PARALLEL_DATES:-10}"  # Lower than Phase 3 (heavier processing)
DRY_RUN="${DRY_RUN:-false}"
PROJECT_ID="nba-props-platform"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get all dates with Phase 3 data
get_all_phase3_dates() {
  bq query \
    --use_legacy_sql=false \
    --format=csv \
    --max_rows=1000 \
    "
    SELECT DISTINCT game_date
    FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
    WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
    ORDER BY game_date
    " | tail -n +2
}

# Trigger Phase 4 for a date
trigger_phase4() {
  local analysis_date=$1
  local skip_downstream=$2

  local payload=$(cat <<EOF
{
  "analysis_date": "${analysis_date}",
  "skip_downstream_trigger": ${skip_downstream},
  "backfill_mode": true,
  "backfill_reason": "historical_features_load"
}
EOF
)

  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: Would trigger Phase 4 for ${analysis_date}"
    return 0
  fi

  local http_code=$(curl -X POST "${PHASE4_URL}/process-date" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    -s -o /dev/null -w "%{http_code}" 2>&1)

  echo "$http_code"
}

# Check Phase 4 completion for a date
check_phase4_complete() {
  local analysis_date=$1

  # Check if ml_feature_store_v2 has data for this date
  local player_count=$(bq query \
    --use_legacy_sql=false \
    --format=csv \
    "
    SELECT COUNT(DISTINCT player_lookup)
    FROM \`${PROJECT_ID}.nba_precompute.ml_feature_store_v2\`
    WHERE game_date = '${analysis_date}'
    " | tail -n 1)

  echo "$player_count"
}

# Check if all 5 Phase 4 processors completed
check_all_processors_complete() {
  local analysis_date=$1

  local completed=$(bq query \
    --use_legacy_sql=false \
    --format=csv \
    "
    SELECT COUNT(DISTINCT processor_name)
    FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
    WHERE data_date = '${analysis_date}'
      AND phase = 'phase_4_precompute'
      AND status = 'success'
    " | tail -n 1)

  echo "$completed"
}

# Wait for Phase 4 completion
wait_for_phase4_batch() {
  local -n dates_ref=$1
  local max_wait_seconds=2400  # 40 minutes (Phase 4 is slower)
  local check_interval=120
  local elapsed=0

  log_info "Waiting for Phase 4 batch to complete..."

  while [ $elapsed -lt $max_wait_seconds ]; do
    local all_complete=true

    for date in "${dates_ref[@]}"; do
      local player_count=$(check_phase4_complete "$date")

      if [ "$player_count" -lt 50 ]; then  # At least 50 players
        all_complete=false
      fi
    done

    if [ "$all_complete" = true ]; then
      log_info "✅ All dates in batch complete"
      return 0
    fi

    sleep $check_interval
    elapsed=$((elapsed + check_interval))
  done

  # Report incomplete dates
  log_warn "⚠️  Timeout waiting for batch. Checking individual dates..."
  for date in "${dates_ref[@]}"; do
    local player_count=$(check_phase4_complete "$date")
    local processors=$(check_all_processors_complete "$date")

    if [ "$player_count" -lt 50 ]; then
      log_warn "  Incomplete: ${date} (${player_count} players, ${processors}/5 processors)"
    else
      log_info "  ✅ Complete: ${date} (${player_count} players)"
    fi
  done

  return 1
}

# Main execution
main() {
  log_info "========================================="
  log_info "Backfill Phase 4 (Precompute)"
  log_info "========================================="
  log_info "Parallel dates: ${PARALLEL_DATES}"
  log_info "Dry run: ${DRY_RUN}"
  log_info ""

  # Get all dates with Phase 3 data
  log_info "Fetching dates with Phase 3 data..."
  mapfile -t all_dates < <(get_all_phase3_dates)

  log_info "Found ${#all_dates[@]} dates to process"
  log_info ""

  # Process in batches
  local total_dates=${#all_dates[@]}
  local batch_num=1

  for ((i=0; i<total_dates; i+=PARALLEL_DATES)); do
    local batch_end=$((i + PARALLEL_DATES))
    if [ $batch_end -gt $total_dates ]; then
      batch_end=$total_dates
    fi

    local batch_dates=("${all_dates[@]:$i:$PARALLEL_DATES}")
    local batch_size=${#batch_dates[@]}

    log_info "--- Batch ${batch_num} (${i}/${total_dates}) ---"
    log_info "Dates: ${batch_dates[0]} to ${batch_dates[-1]}"
    log_info "Processing ${batch_size} dates in parallel..."

    # Trigger Phase 4 for each date (parallel)
    for date in "${batch_dates[@]}"; do
      {
        http_code=$(trigger_phase4 "$date" true)

        if [ "$http_code" = "200" ] || [ "$http_code" = "202" ]; then
          echo "  ✅ ${date}"
        else
          echo "  ❌ ${date} (HTTP ${http_code})"
        fi
      } &
    done

    wait

    # Wait for Phase 4 to complete
    wait_for_phase4_batch batch_dates || log_warn "Some dates incomplete in batch ${batch_num}"

    log_info "✅ Batch ${batch_num} complete"
    log_info ""
    batch_num=$((batch_num + 1))
  done

  log_info "========================================="
  log_info "Backfill Complete: Phase 4"
  log_info "========================================="
  log_info "Run verification: ./bin/backfill/verify_phase4.sh"
}

main "$@"
```

---

### Verification Script

```bash
#!/bin/bash
# bin/backfill/verify_phase4.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"

echo "========================================="
echo "Phase 4 Verification"
echo "========================================="
echo ""

echo "ML Feature Store Coverage:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  DATE_TRUNC(game_date, YEAR) as year,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_rows
FROM \`${PROJECT_ID}.nba_precompute.ml_feature_store_v2\`
WHERE game_date >= '2020-10-01'
  AND game_date <= '2024-06-30'
GROUP BY year
ORDER BY year
"

echo ""
echo "Phase 4 Processor Runs:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  COUNT(DISTINCT data_date) as dates_processed,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
WHERE phase = 'phase_4_precompute'
  AND data_date >= '2020-10-01'
  AND data_date <= '2024-06-30'
GROUP BY processor_name
ORDER BY processor_name
"

echo ""
echo "Feature Completeness Check:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
WITH phase3_players AS (
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as phase3_players
  FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
  WHERE game_date >= '2020-10-01'
    AND game_date <= '2024-06-30'
  GROUP BY game_date
),
phase4_players AS (
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as phase4_players
  FROM \`${PROJECT_ID}.nba_precompute.ml_feature_store_v2\`
  WHERE game_date >= '2020-10-01'
    AND game_date <= '2024-06-30'
  GROUP BY game_date
)
SELECT
  COUNT(*) as total_dates,
  AVG(phase4_players / phase3_players) as avg_coverage_pct,
  MIN(phase4_players / phase3_players) as min_coverage_pct,
  SUM(CASE WHEN phase4_players / phase3_players < 0.90 THEN 1 ELSE 0 END) as dates_below_90pct
FROM phase3_players p3
LEFT JOIN phase4_players p4 USING (game_date)
"
```

---

## Phase 5: Current Season with Predictions {#phase-5-current-season}

### Overview

**Goal:** Load current season (2024-25) through ALL 5 phases including predictions

**Scope:**
- Season opener (Oct 22, 2024) to yesterday
- ~50-70 game dates (depends on when you run this)
- Full pipeline validation (Phases 1→2→3→4→5)
- NO skip_downstream_trigger (let it cascade)

**Expected Duration:** 2-3 hours

**Key Differences:**
- Process dates sequentially (not parallel) to validate pipeline
- Full cascade enabled (skip_downstream_trigger=false)
- Wait for Phase 5 predictions to complete before next date
- This is the production validation run

---

### Script: backfill_current_season.sh

```bash
#!/bin/bash
# bin/backfill/backfill_current_season.sh
#
# Backfill current season (2024-25) through ALL phases including predictions

set -euo pipefail

# Configuration
SCRAPER_URL="${SCRAPER_URL:-https://nba-phase1-scrapers-756957797294.us-west2.run.app}"
COORDINATOR_URL="${COORDINATOR_URL:-https://prediction-coordinator-756957797294.us-west2.run.app}"
DRY_RUN="${DRY_RUN:-false}"
PROJECT_ID="nba-props-platform"
SEASON="2024-25"

# Scrapers
SCRAPERS=(
  "bdl_games"
  "bdl_player_boxscores"
  "nbac_team_boxscore"
  "nbac_player_boxscore"
  # ... (all 21 scrapers)
)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Get current season dates
get_current_season_dates() {
  local start_date="2024-10-22"
  local end_date=$(date -d "yesterday" +%Y-%m-%d)

  bq query \
    --use_legacy_sql=false \
    --format=csv \
    --max_rows=200 \
    "
    SELECT DISTINCT game_date
    FROM \`${PROJECT_ID}.nba_reference.nba_schedule\`
    WHERE season = '${SEASON}'
      AND game_date >= '${start_date}'
      AND game_date <= '${end_date}'
    ORDER BY game_date
    " | tail -n +2
}

# Trigger scrapers for a date (full cascade)
trigger_scrapers_for_date() {
  local game_date=$1

  log_step "Triggering scrapers for ${game_date}..."

  for scraper in "${SCRAPERS[@]}"; do
    {
      local payload=$(cat <<EOF
{
  "scraper": "${scraper}",
  "game_date": "${game_date}",
  "skip_downstream_trigger": false
}
EOF
)

      if [ "$DRY_RUN" = "false" ]; then
        http_code=$(curl -X POST "${SCRAPER_URL}/scrape" \
          -H "Content-Type: application/json" \
          -d "${payload}" \
          -s -o /dev/null -w "%{http_code}")

        if [ "$http_code" = "200" ] || [ "$http_code" = "202" ]; then
          echo "  ✅ ${scraper}"
        else
          echo "  ❌ ${scraper} (HTTP ${http_code})"
        fi
      else
        echo "  DRY RUN: ${scraper}"
      fi
    } &
  done

  wait
  log_info "All scrapers triggered for ${game_date}"
}

# Wait for full pipeline to complete
wait_for_pipeline_complete() {
  local game_date=$1
  local max_wait=3600  # 1 hour
  local check_interval=60
  local elapsed=0

  log_step "Waiting for full pipeline to complete for ${game_date}..."

  while [ $elapsed -lt $max_wait ]; do
    # Check Phase 5 predictions
    local pred_count=$(bq query \
      --use_legacy_sql=false \
      --format=csv \
      "
      SELECT COUNT(DISTINCT player_lookup)
      FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
      WHERE game_date = '${game_date}'
      " | tail -n 1)

    if [ "$pred_count" -ge 100 ]; then  # At least 100 predictions
      log_info "✅ Pipeline complete for ${game_date}: ${pred_count} predictions"
      return 0
    fi

    # Show progress
    local phase2=$(bq query --use_legacy_sql=false --format=csv \
      "SELECT COUNT(*) FROM nba_reference.processor_run_history
       WHERE data_date='${game_date}' AND phase='phase_2_raw' AND status='success'" \
      | tail -n 1)

    local phase3=$(bq query --use_legacy_sql=false --format=csv \
      "SELECT COUNT(*) FROM nba_reference.processor_run_history
       WHERE data_date='${game_date}' AND phase='phase_3_analytics' AND status='success'" \
      | tail -n 1)

    local phase4=$(bq query --use_legacy_sql=false --format=csv \
      "SELECT COUNT(*) FROM nba_reference.processor_run_history
       WHERE data_date='${game_date}' AND phase='phase_4_precompute' AND status='success'" \
      | tail -n 1)

    log_info "Progress: Phase2=${phase2}/21, Phase3=${phase3}/5, Phase4=${phase4}/5, Predictions=${pred_count}"

    sleep $check_interval
    elapsed=$((elapsed + check_interval))
  done

  log_warn "⚠️  Timeout waiting for pipeline completion"
  return 1
}

# Verify predictions quality
verify_predictions() {
  local game_date=$1

  log_step "Verifying predictions for ${game_date}..."

  bq query --use_legacy_sql=false --format=pretty "
  SELECT
    COUNT(DISTINCT player_lookup) as players,
    COUNT(*) as total_predictions,
    AVG(predicted_points) as avg_predicted_points,
    AVG(confidence_score) as avg_confidence,
    SUM(CASE WHEN predicted_points IS NULL THEN 1 ELSE 0 END) as null_predictions,
    SUM(CASE WHEN predicted_points < 0 OR predicted_points > 100 THEN 1 ELSE 0 END) as invalid_predictions
  FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
  WHERE game_date = '${game_date}'
  "
}

# Main execution
main() {
  log_info "========================================="
  log_info "Backfill Current Season (${SEASON})"
  log_info "========================================="
  log_info "Full pipeline cascade: ENABLED"
  log_info "Dry run: ${DRY_RUN}"
  log_info ""

  # Get current season dates
  log_info "Fetching game dates for current season..."
  mapfile -t game_dates < <(get_current_season_dates)

  log_info "Found ${#game_dates[@]} dates to process"
  log_info "Date range: ${game_dates[0]} to ${game_dates[-1]}"
  log_info ""

  # Process each date sequentially
  local date_num=1
  for date in "${game_dates[@]}"; do
    log_info "========================================="
    log_info "Processing Date ${date_num}/${#game_dates[@]}: ${date}"
    log_info "========================================="

    # Trigger scrapers
    trigger_scrapers_for_date "$date"

    # Wait for full pipeline
    if wait_for_pipeline_complete "$date"; then
      # Verify predictions
      verify_predictions "$date"
      log_info "✅ Date ${date} complete"
    else
      log_error "❌ Date ${date} failed to complete within timeout"

      # Ask user if should continue
      read -p "Continue with next date? (y/n) " -n 1 -r
      echo
      if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Stopping backfill"
        exit 1
      fi
    fi

    log_info ""
    date_num=$((date_num + 1))
  done

  log_info "========================================="
  log_info "Current Season Backfill Complete"
  log_info "========================================="
  log_info "Run verification: ./bin/backfill/verify_current_season.sh"
}

main "$@"
```

---

### Verification Script

```bash
#!/bin/bash
# bin/backfill/verify_current_season.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
SEASON="2024-25"

echo "========================================="
echo "Current Season (${SEASON}) Verification"
echo "========================================="
echo ""

echo "Predictions Coverage:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players_with_predictions,
  COUNT(*) as total_predictions,
  AVG(predicted_points) as avg_predicted_points,
  AVG(confidence_score) as avg_confidence
FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2024-10-22'
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 20
"

echo ""
echo "Pipeline Completeness Check:"
echo "-------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
WITH dates AS (
  SELECT DISTINCT game_date
  FROM \`${PROJECT_ID}.nba_reference.nba_schedule\`
  WHERE season = '${SEASON}'
    AND game_date >= '2024-10-22'
    AND game_date <= CURRENT_DATE() - 1
),
phase2 AS (
  SELECT data_date, COUNT(DISTINCT processor_name) as p2_count
  FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
  WHERE phase = 'phase_2_raw' AND status = 'success'
  GROUP BY data_date
),
phase3 AS (
  SELECT data_date, COUNT(DISTINCT processor_name) as p3_count
  FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
  WHERE phase = 'phase_3_analytics' AND status = 'success'
  GROUP BY data_date
),
phase4 AS (
  SELECT data_date, COUNT(DISTINCT processor_name) as p4_count
  FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`
  WHERE phase = 'phase_4_precompute' AND status = 'success'
  GROUP BY data_date
),
phase5 AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as pred_count
  FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
  GROUP BY game_date
)
SELECT
  d.game_date,
  COALESCE(p2.p2_count, 0) as phase2_processors,
  COALESCE(p3.p3_count, 0) as phase3_processors,
  COALESCE(p4.p4_count, 0) as phase4_processors,
  COALESCE(p5.pred_count, 0) as predictions,
  CASE
    WHEN COALESCE(p2.p2_count, 0) >= 18
     AND COALESCE(p3.p3_count, 0) = 5
     AND COALESCE(p4.p4_count, 0) = 5
     AND COALESCE(p5.pred_count, 0) >= 100
    THEN '✅ Complete'
    ELSE '❌ Incomplete'
  END as status
FROM dates d
LEFT JOIN phase2 p2 ON d.game_date = p2.data_date
LEFT JOIN phase3 p3 ON d.game_date = p3.data_date
LEFT JOIN phase4 p4 ON d.game_date = p4.data_date
LEFT JOIN phase5 p5 ON d.game_date = p5.game_date
ORDER BY d.game_date DESC
"
```

---

## Verification Procedures {#verification-procedures}

### Master Verification Script

```bash
#!/bin/bash
# bin/backfill/verify_all.sh
#
# Master verification script - checks all phases

set -euo pipefail

echo "========================================="
echo "MASTER VERIFICATION - ALL PHASES"
echo "========================================="
echo ""

echo "Running Phase 1-2 verification..."
./bin/backfill/verify_phase1_2.sh

echo ""
echo "Running Phase 3 verification..."
./bin/backfill/verify_phase3.sh

echo ""
echo "Running Phase 4 verification..."
./bin/backfill/verify_phase4.sh

echo ""
echo "Running current season verification..."
./bin/backfill/verify_current_season.sh

echo ""
echo "========================================="
echo "SUMMARY"
echo "========================================="

bq query --use_legacy_sql=false --format=pretty "
SELECT
  phase,
  COUNT(DISTINCT data_date) as unique_dates,
  COUNT(*) as total_runs,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
  ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date >= '2020-10-01'
GROUP BY phase
ORDER BY phase
"
```

---

## Monitoring & Progress Tracking {#monitoring}

### Real-Time Progress Dashboard

```bash
#!/bin/bash
# bin/backfill/monitor_progress.sh
#
# Real-time monitoring of backfill progress

watch -n 30 'bq query --use_legacy_sql=false --format=pretty "
SELECT
  phase,
  COUNT(DISTINCT data_date) as dates,
  COUNT(*) as runs,
  SUM(CASE WHEN status = \"success\" THEN 1 ELSE 0 END) as success,
  SUM(CASE WHEN status = \"failed\" THEN 1 ELSE 0 END) as failed,
  SUM(CASE WHEN status = \"partial\" THEN 1 ELSE 0 END) as partial,
  MAX(processed_at) as last_run
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date >= \"2020-10-01\"
GROUP BY phase
ORDER BY phase
"'
```

### Progress Percentage Script

```bash
#!/bin/bash
# bin/backfill/progress_percentage.sh

PROJECT_ID="nba-props-platform"

echo "Backfill Progress:"
echo "-------------------------------------"

# Expected totals
EXPECTED_DATES=500  # Approximate for 4 seasons
EXPECTED_PHASE2_RUNS=$((EXPECTED_DATES * 21))
EXPECTED_PHASE3_RUNS=$((EXPECTED_DATES * 5))
EXPECTED_PHASE4_RUNS=$((EXPECTED_DATES * 5))

# Actual counts
ACTUAL_PHASE2=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT COUNT(*) FROM nba_reference.processor_run_history
   WHERE phase='phase_2_raw' AND status='success' AND data_date>='2020-10-01'" \
  | tail -n 1)

ACTUAL_PHASE3=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT COUNT(*) FROM nba_reference.processor_run_history
   WHERE phase='phase_3_analytics' AND status='success' AND data_date>='2020-10-01'" \
  | tail -n 1)

ACTUAL_PHASE4=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT COUNT(*) FROM nba_reference.processor_run_history
   WHERE phase='phase_4_precompute' AND status='success' AND data_date>='2020-10-01'" \
  | tail -n 1)

# Calculate percentages
PHASE2_PCT=$(awk "BEGIN {print ($ACTUAL_PHASE2 / $EXPECTED_PHASE2_RUNS) * 100}")
PHASE3_PCT=$(awk "BEGIN {print ($ACTUAL_PHASE3 / $EXPECTED_PHASE3_RUNS) * 100}")
PHASE4_PCT=$(awk "BEGIN {print ($ACTUAL_PHASE4 / $EXPECTED_PHASE4_RUNS) * 100}")

echo "Phase 2: ${ACTUAL_PHASE2}/${EXPECTED_PHASE2_RUNS} (${PHASE2_PCT}%)"
echo "Phase 3: ${ACTUAL_PHASE3}/${EXPECTED_PHASE3_RUNS} (${PHASE3_PCT}%)"
echo "Phase 4: ${ACTUAL_PHASE4}/${EXPECTED_PHASE4_RUNS} (${PHASE4_PCT}%)"
```

---

## Troubleshooting {#troubleshooting}

### Common Issues & Solutions

#### Issue 1: Scraper Fails for Specific Date

**Symptom:**
```
❌ bdl_games (HTTP 500)
```

**Diagnosis:**
```bash
# Check scraper logs
gcloud run services logs read nba-phase1-scrapers \
  --filter="jsonPayload.game_date='2024-01-15'" \
  --limit=50
```

**Solution:**
```bash
# Re-run just that scraper for that date
curl -X POST https://nba-phase1-scrapers.../scrape \
  -d '{"scraper": "bdl_games", "game_date": "2024-01-15", "skip_downstream_trigger": true}'
```

---

#### Issue 2: Phase 3 Stuck Waiting

**Symptom:**
```
⚠️ Timeout waiting for batch. Checking individual dates...
Incomplete: 2024-01-15 (3/5 processors)
```

**Diagnosis:**
```bash
# Check which processors failed
bq query --use_legacy_sql=false "
SELECT processor_name, status, errors
FROM nba_reference.processor_run_history
WHERE data_date = '2024-01-15'
  AND phase = 'phase_3_analytics'
ORDER BY processor_name
"
```

**Solution:**
```bash
# Re-run Phase 3 for that date
curl -X POST https://nba-phase3-analytics-processors.../process \
  -d '{"analysis_date": "2024-01-15", "skip_downstream_trigger": true}'
```

---

#### Issue 3: Missing Dates After Backfill

**Symptom:** Verification shows missing dates

**Diagnosis:**
```sql
-- Find missing dates
WITH expected AS (
  SELECT DISTINCT game_date
  FROM nba_reference.nba_schedule
  WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
),
actual AS (
  SELECT DISTINCT game_date
  FROM nba_raw.bdl_games
)
SELECT e.game_date
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY e.game_date
```

**Solution:**
```bash
# Create file with missing dates
bq query ... > missing_dates.txt

# Re-run backfill for just those dates
while read date; do
  echo "Processing missing date: $date"
  # Trigger scrapers...
done < missing_dates.txt
```

---

#### Issue 4: Phase 4 Low Coverage

**Symptom:**
```
dates_below_90pct: 50
```

**Diagnosis:**
```sql
-- Find dates with low coverage
WITH phase3_counts AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as p3_count
  FROM nba_analytics.player_game_summary
  GROUP BY game_date
),
phase4_counts AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as p4_count
  FROM nba_precompute.ml_feature_store_v2
  GROUP BY game_date
)
SELECT
  p3.game_date,
  p3.p3_count,
  COALESCE(p4.p4_count, 0) as p4_count,
  ROUND(100.0 * COALESCE(p4.p4_count, 0) / p3.p3_count, 2) as coverage_pct
FROM phase3_counts p3
LEFT JOIN phase4_counts p4 USING (game_date)
WHERE COALESCE(p4.p4_count, 0) / p3.p3_count < 0.90
ORDER BY coverage_pct
LIMIT 20
```

**Solution:**
```bash
# Re-run Phase 4 for low-coverage dates
bq query "..." | while read date; do
  curl -X POST https://nba-phase4-precompute-processors.../process-date \
    -d "{\"analysis_date\": \"$date\", \"skip_downstream_trigger\": true, \"force_reprocess\": true}"
done
```

---

## Timeline & Resource Planning {#timeline}

### Estimated Timeline

| Phase | Strategy | Parallelism | Time | Wall-Clock |
|-------|----------|-------------|------|------------|
| **Phases 1-2** | 10 dates × 21 scrapers | High | ~15 min/batch | 2-3 days |
| **Phase 3** | 20 dates/batch | Medium | ~20 min/batch | 4-6 hours |
| **Phase 4** | 10 dates/batch | Medium | ~30 min/batch | 4-6 hours |
| **Phase 5** | Sequential validation | Low | ~3 min/date | 2-3 hours |
| **TOTAL** | | | | **~3-4 days** |

### Resource Requirements

**BigQuery:**
- Quota needed: ~500 GB queries/day during backfill
- Cost estimate: ~$50-100 total

**Cloud Run:**
- Concurrent instances: Up to 210 (Phase 1-2 peak)
- Memory: 2-4 GB per instance
- Cost estimate: ~$30-50 total

**Pub/Sub:**
- Messages: ~15,000 total (all phases)
- Cost: ~$0.50 total (negligible)

**Total Estimated Cost:** ~$80-150 for complete backfill

### Execution Schedule

**Recommended schedule:**

**Day 1 (Morning):**
- Start Phases 1-2 backfill
- Monitor first few batches
- Let run overnight

**Day 2 (All Day):**
- Phases 1-2 continues
- Monitor periodically
- Fix any failed scrapers

**Day 3 (Morning):**
- Verify Phases 1-2 complete
- Start Phase 3 backfill (4-6 hours)
- Start Phase 4 backfill when Phase 3 done (4-6 hours)

**Day 3 (Evening):**
- Verify Phases 3-4 complete
- Start current season backfill (2-3 hours)

**Day 4:**
- Final verification
- Fix any gaps
- Enable daily processing

---

## Final Checklist

Before starting backfill:

- [ ] All backfill scripts created and tested
- [ ] Verification scripts ready
- [ ] Monitoring dashboard set up
- [ ] Alert thresholds configured
- [ ] BACKFILL_MODE=true for alert suppression
- [ ] BigQuery quota sufficient
- [ ] Cloud Run scaling limits appropriate
- [ ] Dry run tested with 1-2 dates
- [ ] Rollback plan documented
- [ ] Team notified of backfill start

During backfill:

- [ ] Monitor progress every 2-4 hours
- [ ] Check error rates
- [ ] Verify data quality on sample dates
- [ ] Track resource usage
- [ ] Document any issues

After backfill:

- [ ] Run all verification scripts
- [ ] Check completeness
- [ ] Validate data quality
- [ ] Enable daily processing
- [ ] Monitor first overnight run
- [ ] Document lessons learned

---

**Document Status:** ✅ Complete Backfill Execution Plan
**Next Action:** Create scripts in bin/backfill/ directory during Week 3
**Review Needed:** Yes - have another Claude instance review this plan
