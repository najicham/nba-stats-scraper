# Backfill Operations Guide

**File:** `docs/02-operations/backfill/backfill-guide.md`
**Created:** 2025-11-18 14:45 PST
**Last Updated:** 2026-01-23 (Added historical betting lines backfill scenario)
**Purpose:** Step-by-step guide for running backfills safely and effectively
**Status:** Current
**Audience:** Engineers running backfills, on-call engineers, operators

---

> **Important:** This guide contains conceptual information about backfill workflows.
> For **working scripts and commands**, see [README.md](./README.md) which has the current
> validation workflow and script references.

---

## 🎯 Overview

**This document covers:**
- ✅ When to backfill vs when to skip
- ✅ Backfill order and sequencing (phase-by-phase, not date-by-date)
- ✅ Date range calculation (including lookback windows)
- ✅ Validation before/after each phase
- ✅ Partial backfill recovery
- ✅ Early season special handling

**For Working Scripts:** See [README.md - Validation Workflow](./README.md#validation-workflow)

**Related Documentation:**
- [README.md](./README.md) - Current scripts and validation workflow
- [backfill-mode-reference.md](./backfill-mode-reference.md) - What changes in backfill mode
- `docs/01-architecture/cross-date-dependencies.md` - Why backfill order matters

---

## 📋 When to Backfill

### Scenario 1: Historical Data (Full Season)

**Use Case:** Fill 2023-24 season data before predictions go live

**Details:**
- **Date Range:** Oct 24, 2023 - Apr 14, 2024 (~180 game dates)
- **Phases:** All (1-5)
- **Lookback:** Start Phase 2-3 from ~Oct 1 to have context for first games
- **Timeline:** 3-5 days depending on parallelization
- **Validation:** Critical - use range completeness queries

**When to Run:**
- Before launching predictions for historical analysis
- To train ML models on historical data
- To populate dashboards with historical trends

**Risks:**
- Long-running, easy to miss errors
- Must validate thoroughly between phases
- Any gap blocks downstream phases

---

### Scenario 2: Gap Filling (Missing Days)

**Use Case:** Daily scrapers failed Nov 8-14, need to fill the gap

**Details:**
- **Date Range:** Nov 8-14 (7 dates)
- **Phases:** All (1-5)
- **Lookback:** Include ~30 days before Nov 8 for Phase 4 context
- **Timeline:** Few hours to 1 day
- **Validation:** Medium - check gap is fully filled

**When to Run:**
- Scrapers failed for multiple consecutive days
- GCP outage caused data loss
- Discovered historical gaps during validation

**Risks:**
- Might miss that lookback window is needed
- Could run Phase 4 without historical context

---

### Scenario 3: Re-Processing (Data Fix)

**Use Case:** Scraped data had error, manually fixed in GCS, need to re-run processors

**Details:**
- **Date Range:** Nov 15 (1 date typically)
- **Phases:** Phase 2-5 only (Phase 1 scraper data already corrected)
- **Lookback:** Not needed if only re-processing same date
- **Timeline:** Minutes to hours
- **Validation:** Low - single date validation

**When to Run:**
- Discovered data quality issue in raw scraped data
- Manual fix applied to GCS files
- Need to re-trigger downstream processing

**Risks:**
- Forgetting to delete old processed data first
- Re-running Phase 1 unnecessarily (wastes time)

---

### Scenario 4: Downstream Re-Processing

**Use Case:** Manual change in BigQuery Phase 3 table, need to re-run Phase 4-5

**Details:**
- **Date Range:** Nov 10-15 (variable)
- **Phases:** Phase 4-5 only (Phase 3 already has correct data)
- **Lookback:** Check if Phase 4 needs historical re-processing too
- **Timeline:** Minutes to hours
- **Validation:** Medium - verify propagation

**When to Run:**
- Fixed data quality issue in Phase 3 table
- Changed business logic, need to re-calculate
- Discovered error in Phase 4/5, fixed processor code

**Risks:**
- Re-running too many phases unnecessarily
- Not re-running enough phases (missing dependencies)
- Forgetting that Phase 4 might need historical dates re-run if lookback logic changed

---

### Scenario 5: Historical Betting Lines Backfill

**Use Case:** Predictions show placeholder lines (20.0) because live Odds API didn't capture data

**Details:**
- **Date Range:** Specific dates with missing betting context
- **Phases:** Phase 1 (historical scrapers) + prediction re-run
- **Timeline:** Minutes per date
- **Validation:** Check predictions no longer have placeholders

**When to Run:**
- Predictions have `current_points_line = 20.0` (placeholder value)
- Odds API scraper failed or was unavailable on a game date
- Backfilling betting context for past predictions

**Workflow:**

```bash
# Step 1: Use HISTORICAL Odds API scrapers (NOT the live ones!)
# Get event IDs first
python -m scrapers.oddsapi.oddsa_events_his \
    --game_date 2026-01-21 \
    --snapshot_timestamp 2026-01-21T18:00:00Z \
    --debug

# Step 2: For each event_id, get player props
python -m scrapers.oddsapi.oddsa_player_props_his \
    --event_id <EVENT_ID> \
    --game_date 2026-01-21 \
    --snapshot_timestamp 2026-01-21T18:00:00Z \
    --markets player_points \
    --debug

# Step 3: Run processor to load into BigQuery
python -m data_processors.raw.odds_api_props_processor --date 2026-01-21

# Step 4: Re-run predictions
curl -X POST "https://prediction-coordinator-.../start" \
    -H "X-API-Key: $COORD_KEY" \
    -d '{"game_date": "2026-01-21"}'
```

**Risks:**
- Using live scrapers instead of historical (won't work for past dates)
- Wrong snapshot_timestamp (events disappear after game starts)
- API rate limit (500 requests/month)

> **See Also:** [Scrapers Reference - Historical Odds API Backfill](../../06-reference/scrapers.md#historical-odds-api-backfill-workflow) for detailed instructions.

---

### Scenario 6: Early Season Backfill

**Use Case:** Season just started, filling first 10 games with limited historical data

**Details:**
- **Date Range:** Oct 22 - Nov 5 (first ~10 game dates)
- **Phases:** All (1-5)
- **Lookback:** No historical context available
- **Timeline:** Hours to 1 day
- **Validation:** Expect degraded quality scores

**When to Run:**
- Season start backfill
- New team/league added mid-season

**Risks:**
- Expecting normal quality scores (won't happen)
- Not enabling early_season_mode flags
- Users expecting full predictions (won't be accurate)

---

## 🔄 Backfill Order and Sequencing

### Golden Rule: Phase-by-Phase, Not Date-by-Date

**Why:**
- Cross-date dependencies require historical data
- Phase 4 for Nov 8 needs Phase 3 for Oct 29-Nov 7
- Running date-by-date fails when historical data missing

**Correct Approach:**
```
1. Run Phase 2 for ALL dates
2. Validate Phase 2 complete
3. Run Phase 3 for ALL dates
4. Validate Phase 3 complete
5. Run Phase 4 for target dates (has historical context now)
6. Validate Phase 4 complete
7. Run Phase 5 for target dates
8. Final validation
```

**Incorrect Approach:**
```
❌ For each date:
    - Run Phase 2
    - Run Phase 3
    - Run Phase 4  (fails: needs historical Phase 3 data)
    - Run Phase 5
```

---

### Parallelization Strategy

**Within a Phase: Parallel ✅**
- Can run multiple dates in parallel within same phase
- Example: Run Phase 2 for Nov 8, 9, 10 simultaneously

**Across Phases: Sequential ❌**
- Cannot run Phase 3 for Nov 8 until Phase 2 for Nov 8 complete
- Cannot run Phase 4 for Nov 8 until Phase 3 for Oct 29-Nov 7 complete

**Example:**
```bash
# Good: Parallel within phase
for date in Nov-08 Nov-09 Nov-10; do
  run_phase2 $date &  # Run in background, parallel
done
wait  # Wait for all Phase 2 to complete

# Good: Sequential across phases
validate_phase2_complete
run_phase3_all_dates
validate_phase3_complete
run_phase4_all_dates
```

---

## 📐 Date Range Calculation

### Step 1: Define Target Range

**What the user wants to backfill:**
```
TARGET_START="2024-11-08"
TARGET_END="2024-11-14"
```

---

### Step 2: Calculate Lookback Window

**For Phase 4 processors that need historical context:**
```
LOOKBACK_DAYS=30  # ~30 days should capture ~10 games
```

---

### Step 3: Calculate Phase Ranges

**Phase 2-3 Range (includes lookback):**
```bash
PHASE_23_START=$(date -d "$TARGET_START - $LOOKBACK_DAYS days" +%Y-%m-%d)
PHASE_23_END=$TARGET_END

# Result: Oct 9 - Nov 14
```

**Phase 4-5 Range (target only):**
```bash
PHASE_45_START=$TARGET_START
PHASE_45_END=$TARGET_END

# Result: Nov 8 - Nov 14
```

---

## ✅ Validation Before/After Each Phase

> **Working Scripts:** The validation scripts below are the actual working tools.
> See [README.md - Validation Workflow](./README.md#validation-workflow) for the complete workflow.

### Before Starting Phase N

**Checklist:**
- [ ] Phase N-1 complete for ALL dates in range
- [ ] No missing dates in Phase N-1
- [ ] Row counts meet minimum thresholds
- [ ] Sample check: Pick 3 random dates, verify data quality

**Working Commands:**
```bash
# Pre-flight check - verify all phases have data
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date 2024-11-08 --end-date 2024-11-14 --verbose

# Verify Phase 3 is ready before running Phase 4
.venv/bin/python bin/backfill/verify_phase3_for_phase4.py \
    --start-date 2024-11-08 --end-date 2024-11-14
```

---

### After Completing Phase N

**Checklist:**
- [ ] Run coverage validation
- [ ] Check for cascade contamination (NULL/zero critical fields)
- [ ] Verify no missing dates
- [ ] Check processed_at timestamps are recent

**Working Commands:**
```bash
# Check coverage and identify failures
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2024-11-08 --end-date 2024-11-14 --details --reconcile

# Check data quality (cascade contamination)
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2024-11-08 --end-date 2024-11-14 --strict

# Final verification
.venv/bin/python bin/backfill/verify_backfill_range.py \
    --start-date 2024-11-08 --end-date 2024-11-14
```

---

### Validation Scripts Reference

| Script | Purpose | Phase |
|--------|---------|-------|
| `bin/backfill/preflight_check.py` | Check data availability before backfill | All |
| `bin/backfill/verify_phase3_for_phase4.py` | Verify Phase 3 ready for Phase 4 | 3→4 |
| `bin/backfill/verify_backfill_range.py` | Full verification after backfill | 3-4 |
| `scripts/validate_backfill_coverage.py` | Player-level coverage check | 4 |
| `scripts/validate_cascade_contamination.py` | Critical field validation | 3-5 |

---

## 🎯 Complete Backfill Examples

> **Note:** These examples show the **workflow and concepts**. Some commands reference
> scripts that are pseudocode for illustration. For actual working commands, see:
> - [README.md - Validation Workflow](./README.md#validation-workflow)
> - [Quick Reference](#common-commands-quick-reference) at the end of this doc

### Example 1: Backfill Nov 8-14 (Gap Fill)

**Scenario:** Daily scrapers failed Nov 8-14, need to fill the gap

#### Step 1: Calculate Ranges

```bash
./bin/backfill/calculate_range.sh 2024-11-08 2024-11-14 30

# Output:
# Phase 2-3 range: 2024-10-09 to 2024-11-14
# Phase 4-5 range: 2024-11-08 to 2024-11-14

# Export variables
export PHASE_23_START=2024-10-09
export PHASE_23_END=2024-11-14
export PHASE_45_START=2024-11-08
export PHASE_45_END=2024-11-14
```

---

#### Step 2: Check Existing Data

```bash
./bin/backfill/check_existing.sh $PHASE_23_START $PHASE_23_END

# Sample output:
# date       | phase2 | phase3 | phase4 | phase5 | status
# -----------|--------|--------|--------|--------|------------------
# 2024-10-09 | ❌     | ❌     | ❌     | ❌     | ❌ Need Phase 2-5
# ...
# 2024-11-07 | ✅     | ✅     | ❌     | ❌     | ⚠️ Need Phase 4-5
# 2024-11-08 | ❌     | ❌     | ❌     | ❌     | ❌ Need Phase 2-5
# ...
```

**Analysis:**
- Oct 9 - Oct 31: Missing Phase 2-3 (needed for lookback)
- Nov 1 - Nov 7: Have Phase 2-3 ✅ (skip these)
- Nov 8 - Nov 14: Missing everything (target range)

---

#### Step 3: Run Phase 1 (Scrapers)

```bash
# Navigate to backfill jobs directory
cd /home/naji/code/nba-stats-scraper/backfill_jobs

# Run scrapers for Oct 9-31
./run_scraper_backfill.sh --start=2024-10-09 --end=2024-10-31

# Wait for completion, then run scrapers for Nov 8-14
./run_scraper_backfill.sh --start=2024-11-08 --end=2024-11-14
```

**Validation:**
```bash
# Check scrapers completed successfully
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=scraper-backfill" \
  --limit=50 \
  --format=json \
  | jq '.[] | select(.severity == "ERROR")'

# Should return empty if no errors
```

---

#### Step 4: Run Phase 2 (Raw Processors)

```bash
# List of Phase 2 processors
PHASE2_PROCESSORS=(
  "nbac-gamebook"
  "nbac-team-boxscore"
  "odds-api-spreads"
  "odds-api-player-points"
  # Add more as needed
)

# Run each processor for Oct 9 - Nov 14
for processor in "${PHASE2_PROCESSORS[@]}"; do
  echo "Running Phase 2: $processor for $PHASE_23_START to $PHASE_23_END"

  gcloud run jobs execute phase2-$processor \
    --region us-central1 \
    --set-env-vars "START_DATE=$PHASE_23_START,END_DATE=$PHASE_23_END" \
    --wait  # Wait for completion before starting next
done
```

**Alternative: Parallel Execution**
```bash
# Run all Phase 2 processors in parallel (faster)
for processor in "${PHASE2_PROCESSORS[@]}"; do
  gcloud run jobs execute phase2-$processor \
    --region us-central1 \
    --set-env-vars "START_DATE=$PHASE_23_START,END_DATE=$PHASE_23_END" &
done

# Wait for all to complete
wait
```

---

#### Step 5: Validate Phase 2

```bash
./bin/backfill/validate_phase.sh 2 $PHASE_23_START $PHASE_23_END

# Check output for ❌ or ⚠️
# If any failures, check logs:
gcloud run jobs describe phase2-nbac-gamebook --region us-central1
gcloud run jobs logs read phase2-nbac-gamebook --region us-central1 --limit=100
```

---

#### Step 6: Run Phase 3 (Analytics)

```bash
PHASE3_PROCESSORS=(
  "player-game-summary"
  "team-offense-game-summary"
  "team-defense-game-summary"
  # Add more as needed
)

for processor in "${PHASE3_PROCESSORS[@]}"; do
  echo "Running Phase 3: $processor for $PHASE_23_START to $PHASE_23_END"

  gcloud run jobs execute phase3-$processor \
    --region us-central1 \
    --set-env-vars "START_DATE=$PHASE_23_START,END_DATE=$PHASE_23_END" \
    --wait
done
```

---

#### Step 7: Validate Phase 3

```bash
./bin/backfill/validate_phase.sh 3 $PHASE_23_START $PHASE_23_END

# Critical checkpoint: Phase 4 cannot run without complete Phase 3
# If validation fails, STOP and fix Phase 3 first
```

---

#### Step 8: Run Phase 4 (Precompute)

**Now safe to run Phase 4 for Nov 8-14 (has Oct 9-Nov 7 historical context)**

```bash
PHASE4_PROCESSORS=(
  "player-shot-zone-analysis"
  "player-composite-factors"
  # Add more as needed
)

for processor in "${PHASE4_PROCESSORS[@]}"; do
  echo "Running Phase 4: $processor for $PHASE_45_START to $PHASE_45_END"

  gcloud run jobs execute phase4-$processor \
    --region us-central1 \
    --set-env-vars "START_DATE=$PHASE_45_START,END_DATE=$PHASE_45_END" \
    --wait
done
```

---

#### Step 9: Validate Phase 4

```bash
./bin/backfill/validate_phase.sh 4 $PHASE_45_START $PHASE_45_END
```

---

#### Step 10: Run Phase 5 (Predictions)

```bash
gcloud run jobs execute phase5-prediction-coordinator \
  --region us-central1 \
  --set-env-vars "START_DATE=$PHASE_45_START,END_DATE=$PHASE_45_END" \
  --wait
```

---

#### Step 11: Final Validation

```bash
# Check all phases complete for target range
./bin/backfill/check_existing.sh $PHASE_45_START $PHASE_45_END

# All dates should show:
# date       | phase2 | phase3 | phase4 | phase5 | status
# -----------|--------|--------|--------|--------|------------
# 2024-11-08 | ✅     | ✅     | ✅     | ✅     | ✅ Complete
# 2024-11-09 | ✅     | ✅     | ✅     | ✅     | ✅ Complete
# ...
# 2024-11-14 | ✅     | ✅     | ✅     | ✅     | ✅ Complete

echo "✅ Backfill complete for $PHASE_45_START to $PHASE_45_END"
```

---

### Example 2: Full Season Backfill (2023-24)

**Scenario:** Backfill entire 2023-24 season before launching predictions

#### Step 1: Define Ranges

```bash
SEASON_START="2023-10-24"
SEASON_END="2024-04-14"
LOOKBACK_DAYS=30

# Include lookback for first games
export PHASE_23_START="2023-10-01"
export PHASE_23_END="2024-04-14"
export PHASE_45_START="2023-10-24"
export PHASE_45_END="2024-04-14"

echo "Season backfill: $SEASON_START to $SEASON_END"
echo "Phase 2-3: $PHASE_23_START to $PHASE_23_END (~196 days)"
echo "Phase 4-5: $PHASE_45_START to $PHASE_45_END (~174 days)"
```

---

#### Step 2: Check Existing Data

```bash
./bin/backfill/check_existing.sh $PHASE_23_START $PHASE_23_END | tee existing_data.txt

# Count incomplete dates
INCOMPLETE_COUNT=$(grep "❌ Need Phase" existing_data.txt | wc -l)
echo "Incomplete dates: $INCOMPLETE_COUNT"

# If ~170-180 dates incomplete → Full backfill needed
# If <50 dates incomplete → Gap-fill only
```

---

#### Step 3: Run Phase 1-3 (Can Parallelize)

**Option A: Sequential (Safer)**
```bash
# Phase 1
cd /home/naji/code/nba-stats-scraper/backfill_jobs
./run_scraper_backfill.sh --start=$PHASE_23_START --end=$PHASE_23_END

# Phase 2
./run_phase2_backfill.sh --start=$PHASE_23_START --end=$PHASE_23_END

# Validate
./bin/backfill/validate_phase.sh 2 $PHASE_23_START $PHASE_23_END

# Phase 3
./run_phase3_backfill.sh --start=$PHASE_23_START --end=$PHASE_23_END

# Validate
./bin/backfill/validate_phase.sh 3 $PHASE_23_START $PHASE_23_END
```

**Option B: Parallel (Faster, More Complex)**
```bash
# Divide date range into chunks of 30 days
START_DATE=$PHASE_23_START
END_DATE=$PHASE_23_END

# Generate 30-day chunks
current=$START_DATE
while [ "$current" \< "$END_DATE" ]; do
  chunk_end=$(date -d "$current + 29 days" +%Y-%m-%d)
  if [ "$chunk_end" \> "$END_DATE" ]; then
    chunk_end=$END_DATE
  fi

  echo "Processing chunk: $current to $chunk_end"

  # Run Phase 2 for chunk
  gcloud run jobs execute phase2-nbac-gamebook \
    --region us-central1 \
    --set-env-vars "START_DATE=$current,END_DATE=$chunk_end" &

  current=$(date -d "$chunk_end + 1 day" +%Y-%m-%d)
done

wait  # Wait for all chunks to complete
```

---

#### Step 4: Validate Phase 3 Complete Before Phase 4

```bash
echo "Validating Phase 3 for all dates..."
./bin/backfill/validate_phase.sh 3 $PHASE_23_START $PHASE_23_END

if [ $? -ne 0 ]; then
  echo "❌ Phase 3 incomplete. Finding failed dates..."

  # Find failed dates
  bq query --use_legacy_sql=false --format=csv "
  WITH date_range AS (
    SELECT date
    FROM UNNEST(GENERATE_DATE_ARRAY(DATE('$PHASE_23_START'), DATE('$PHASE_23_END'))) AS date
  ),
  phase3_dates AS (
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date BETWEEN '$PHASE_23_START' AND '$PHASE_23_END'
  )
  SELECT dr.date as missing_date
  FROM date_range dr
  LEFT JOIN phase3_dates p3 ON dr.date = p3.game_date
  WHERE p3.game_date IS NULL
  ORDER BY dr.date
  " > failed_dates.txt

  echo "Failed dates saved to failed_dates.txt"
  echo "Re-run Phase 3 for these dates before proceeding to Phase 4"
  exit 1
fi
```

---

#### Step 5: Run Phase 4-5 for Season Only

```bash
echo "Running Phase 4 for $PHASE_45_START to $PHASE_45_END"

# Phase 4 has historical context now (Oct 1 - Apr 14 Phase 3 data available)
./run_phase4_backfill.sh --start=$PHASE_45_START --end=$PHASE_45_END

# Validate
./bin/backfill/validate_phase.sh 4 $PHASE_45_START $PHASE_45_END

# Phase 5
echo "Running Phase 5 for $PHASE_45_START to $PHASE_45_END"
gcloud run jobs execute phase5-prediction-coordinator \
  --region us-central1 \
  --set-env-vars "START_DATE=$PHASE_45_START,END_DATE=$PHASE_45_END"
```

---

#### Step 6: Final Validation & Report

```bash
echo "====================================="
echo "Season Backfill Validation Report"
echo "====================================="
echo "Season: 2023-24"
echo "Range: $PHASE_45_START to $PHASE_45_END"
echo ""

# Count complete dates
COMPLETE_COUNT=$(./bin/backfill/check_existing.sh $PHASE_45_START $PHASE_45_END \
  | grep "✅ Complete" | wc -l)

TOTAL_DAYS=$(( ( $(date -d $PHASE_45_END +%s) - $(date -d $PHASE_45_START +%s) ) / 86400 + 1 ))

echo "Complete dates: $COMPLETE_COUNT / $TOTAL_DAYS"
echo "Percentage: $(( COMPLETE_COUNT * 100 / TOTAL_DAYS ))%"

if [ $COMPLETE_COUNT -eq $TOTAL_DAYS ]; then
  echo "✅ BACKFILL COMPLETE"
else
  echo "⚠️ BACKFILL INCOMPLETE"
  echo "Missing dates:"
  ./bin/backfill/check_existing.sh $PHASE_45_START $PHASE_45_END | grep "❌"
fi
```

---

### Example 3: Re-Processing After Data Fix

**Scenario:** Nov 15 scraped data had error, manually fixed in GCS, need to re-run processors

#### Step 1: Identify What Needs Re-Processing

```bash
FIX_DATE="2024-11-15"

# Check current state
./bin/backfill/check_existing.sh $FIX_DATE $FIX_DATE

# Output shows:
# 2024-11-15 | ✅ | ✅ | ✅ | ✅ | ✅ Complete

# But data is wrong, need to re-process
```

---

#### Step 2: Delete Old Processed Data (Optional)

**If processor is not idempotent:**
```bash
# Delete Phase 2 data for Nov 15
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = '$FIX_DATE';

DELETE FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date = '$FIX_DATE';

-- Delete other Phase 2 tables
"

# Delete downstream phases
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '$FIX_DATE';

-- Delete Phase 3, 4, 5 tables
"
```

**If processor IS idempotent:**
```bash
# Skip deletion, processor will overwrite/update
```

---

#### Step 3: Re-Run Phase 2-5 for Nov 15

```bash
# Phase 1 already has corrected data in GCS, skip scrapers

# Phase 2
for processor in nbac-gamebook nbac-team-boxscore odds-api-spreads; do
  gcloud run jobs execute phase2-$processor \
    --region us-central1 \
    --set-env-vars "START_DATE=$FIX_DATE,END_DATE=$FIX_DATE" \
    --wait
done

# Validate
./bin/backfill/validate_phase.sh 2 $FIX_DATE $FIX_DATE

# Phase 3
for processor in player-game-summary team-offense-game-summary; do
  gcloud run jobs execute phase3-$processor \
    --region us-central1 \
    --set-env-vars "START_DATE=$FIX_DATE,END_DATE=$FIX_DATE" \
    --wait
done

# Validate
./bin/backfill/validate_phase.sh 3 $FIX_DATE $FIX_DATE

# Phase 4-5
gcloud run jobs execute phase4-player-composite-factors \
  --region us-central1 \
  --set-env-vars "START_DATE=$FIX_DATE,END_DATE=$FIX_DATE" \
  --wait

gcloud run jobs execute phase5-prediction-coordinator \
  --region us-central1 \
  --set-env-vars "START_DATE=$FIX_DATE,END_DATE=$FIX_DATE" \
  --wait
```

---

#### Step 4: Verify Fix Propagated

```bash
# Check row counts
bq query --use_legacy_sql=false "
SELECT
  'Phase 2' as phase,
  COUNT(*) as row_count,
  MAX(created_at) as last_update
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = '$FIX_DATE'

UNION ALL

SELECT 'Phase 3', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '$FIX_DATE'

UNION ALL

SELECT 'Phase 4', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date = '$FIX_DATE';
"

# Verify last_update timestamps are recent (within last hour)
```

---

## 🌱 Early Season Special Handling

### Problem: First 10 Games Have No Historical Data

**Scenario:**
- Season starts Oct 22
- Backfilling Oct 22 - Nov 5 (first ~10 game dates)
- Phase 4 processors expect 10-game lookback
- Only 0-9 games available for first 10 dates

---

### Solution: Enable Early Season Mode

**Phase 1-3: Run Normally**
```bash
EARLY_SEASON_START="2024-10-22"
EARLY_SEASON_END="2024-11-05"

# Phase 1-3 don't need historical context
./bin/backfill/run_phases_1_3.sh \
  --start=$EARLY_SEASON_START \
  --end=$EARLY_SEASON_END
```

---

**Phase 4-5: Enable Degraded Mode**
```bash
# Run Phase 4 with early_season_mode flag
gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "START_DATE=$EARLY_SEASON_START,END_DATE=$EARLY_SEASON_END,EARLY_SEASON_MODE=true"

# Processor behavior:
# - Oct 22: 0 games → quality_score = 0, skip or use defaults
# - Oct 24: 1 game  → quality_score = 10, degraded
# - Oct 27: 3 games → quality_score = 30, degraded
# - Nov 1:  6 games → quality_score = 60, medium
# - Nov 5:  10 games → quality_score = 100 ✅ normal

# Run Phase 5 (predictions will have low confidence for early dates)
gcloud run jobs execute phase5-prediction-coordinator \
  --region us-central1 \
  --set-env-vars "START_DATE=$EARLY_SEASON_START,END_DATE=$EARLY_SEASON_END,EARLY_SEASON_MODE=true"
```

---

**Validate & Report Quality Scores**
```bash
# Check quality scores distribution
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as player_count,
  AVG(quality_score) as avg_quality_score,
  MIN(quality_score) as min_quality,
  MAX(quality_score) as max_quality,
  COUNTIF(early_season_flag = true) as early_season_count
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE game_date BETWEEN '$EARLY_SEASON_START' AND '$EARLY_SEASON_END'
GROUP BY game_date
ORDER BY game_date;
"

# Expected output:
# game_date  | player_count | avg_quality_score | early_season_count
# -----------|--------------|-------------------|-------------------
# 2024-10-22 | 450          | 15                | 450  (all early season)
# 2024-10-24 | 445          | 25                | 445
# 2024-10-27 | 448          | 40                | 448
# 2024-11-01 | 442          | 65                | 442
# 2024-11-05 | 447          | 95                | 120  (some reached 10 games)
```

---

## 🔧 Partial Backfill Recovery

### Problem: Phase 3 Failed Midway Through Range

**Scenario:**
- Running Phase 3 for Oct 9 - Nov 14
- Phase 3 completed Oct 9-10, then failed Nov 11-14
- Don't want to re-run completed dates

---

### Step 1: Diagnose Which Dates Failed

```bash
START_DATE="2024-10-09"
END_DATE="2024-11-14"

./bin/backfill/check_existing.sh $START_DATE $END_DATE | grep "Phase 3"

# Output:
# 2024-10-09 | ✅ | ✅ | ...
# 2024-10-10 | ✅ | ✅ | ...
# 2024-11-11 | ✅ | ❌ | ...  ← Failed here
# 2024-11-12 | ✅ | ❌ | ...
# 2024-11-13 | ✅ | ❌ | ...
# 2024-11-14 | ✅ | ❌ | ...
```

---

### Step 2: Extract Failed Dates

```bash
# Get list of failed dates
bq query --use_legacy_sql=false --format=csv "
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE('$START_DATE'), DATE('$END_DATE'))) AS date
),
phase3_dates AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
)
SELECT dr.date
FROM date_range dr
LEFT JOIN phase3_dates p3 ON dr.date = p3.game_date
WHERE p3.game_date IS NULL
ORDER BY dr.date;
" | tail -n +2 > failed_dates.txt

cat failed_dates.txt
# 2024-11-11
# 2024-11-12
# 2024-11-13
# 2024-11-14
```

---

### Step 3: Re-Run Only Failed Dates

```bash
# Calculate new range (only failed dates)
RECOVERY_START=$(head -n 1 failed_dates.txt)  # 2024-11-11
RECOVERY_END=$(tail -n 1 failed_dates.txt)    # 2024-11-14

echo "Re-running Phase 3 for: $RECOVERY_START to $RECOVERY_END"

# Re-run Phase 3 for failed dates only
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=$RECOVERY_START,END_DATE=$RECOVERY_END" \
  --wait
```

---

### Step 4: Validate Recovery

```bash
./bin/backfill/validate_phase.sh 3 $START_DATE $END_DATE

# Should now show all dates complete
```

---

### Alternative: Re-Run Individual Dates

**If dates are non-contiguous:**
```bash
# failed_dates.txt contains:
# 2024-10-15
# 2024-10-22
# 2024-11-03

while read date; do
  echo "Re-running Phase 3 for $date"
  gcloud run jobs execute phase3-player-game-summary \
    --region us-central1 \
    --set-env-vars "START_DATE=$date,END_DATE=$date" \
    --wait
done < failed_dates.txt
```

---

## 📊 Monitoring Backfill Progress

Use these tools to monitor backfill progress:

```bash
# Check coverage at any point
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2024-11-08 --end-date 2024-11-14 --details

# Quick phase coverage query
bq query --use_legacy_sql=false '
SELECT
  "Phase3" as phase, COUNT(DISTINCT game_date) as dates
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN "2024-11-08" AND "2024-11-14"
UNION ALL
SELECT "Phase4", COUNT(DISTINCT game_date)
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN "2024-11-08" AND "2024-11-14"'
```

---

## ⚡ Parallel Backfilling (15x Speedup)

**Status**: ✅ Available for Phase 3 analytics (as of January 2026)
**Performance**: 15x speedup using 15 concurrent workers

### Overview

Phase 3 analytics backfill scripts now support parallel processing using ThreadPoolExecutor, reducing backfill time from ~17 hours to ~1-2 hours.

**Scripts with parallel support:**
- `team_defense_game_summary_analytics_backfill.py`
- `upcoming_player_game_context_analytics_backfill.py`
- `upcoming_team_game_context_analytics_backfill.py`

### Basic Usage

```bash
export PYTHONPATH=.

# Sequential mode (original, slower)
python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2022-05-21 --end-date 2026-01-03

# Parallel mode (15x faster)
python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2022-05-21 --end-date 2026-01-03 --parallel --workers 15
```

### Running All 3 Scripts in Parallel

For maximum speed, run all 3 scripts concurrently:

```bash
# Background execution with logging
nohup python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2022-05-21 --end-date 2026-01-03 --parallel --workers 15 \
  > /tmp/team_defense_parallel_$(date +%Y%m%d_%H%M%S).log 2>&1 &

nohup python3 backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-12-04 --end-date 2026-01-03 --parallel --workers 15 \
  > /tmp/upcoming_player_parallel_$(date +%Y%m%d_%H%M%S).log 2>&1 &

nohup python3 backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-03 --parallel --workers 15 \
  > /tmp/upcoming_team_parallel_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Monitoring Parallel Backfills

```bash
# Check running processes
ps aux | grep "parallel.*backfill" | grep python3

# Monitor logs
tail -f /tmp/*_parallel_*.log

# Check BigQuery progress
bq query --use_legacy_sql=false "
SELECT
  'team_defense' as table, COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date >= '2021-10-19'
UNION ALL
SELECT 'upcoming_player', COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= '2021-10-19'
UNION ALL
SELECT 'upcoming_team', COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date >= '2021-10-19'
ORDER BY table
"
```

### Checkpoints and Resume

Parallel backfills support automatic resume from checkpoints:

```bash
# Automatically resumes from checkpoint (default)
python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2022-05-21 --end-date 2026-01-03 --parallel --workers 15

# Start fresh (clear checkpoint)
python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2022-05-21 --end-date 2026-01-03 --parallel --workers 15 --no-resume
```

**Checkpoint location**: `/tmp/backfill_checkpoints/{job_name}_{start_date}_{end_date}.json`

### Performance Comparison

| Mode | Total Time | Dates/Hour | Use Case |
|------|------------|------------|----------|
| Sequential | 17 hours | ~25 dates/hour | Testing, small ranges |
| Parallel (4 workers) | 4 hours | ~100 dates/hour | Medium ranges |
| Parallel (15 workers) | 1-2 hours | ~400 dates/hour | Production backfills |

### Known Issues

**Non-Critical Warnings** (can be ignored):
- `WARNING: Quota exceeded: partition modifications` - Metadata table only, no impact
- `WARNING: Failed to write circuit state` - Circuit breaker tracking, no impact on processing

### When to Use Parallel vs Sequential

**Use Parallel (--parallel --workers 15) when:**
- Backfilling >100 dates
- Time is critical
- System resources available

**Use Sequential (default) when:**
- Backfilling <20 dates
- Testing/debugging
- System under load
- Troubleshooting issues

### Full Documentation

See `docs/08-projects/current/phase3-phase4-complete-execution-2026-01-05/PARALLEL-BACKFILL-IMPLEMENTATION.md` for:
- Implementation details
- Architecture decisions
- Testing results
- Troubleshooting guide

---

## 🔗 Related Documentation

**Architecture:**
- `docs/01-architecture/cross-date-dependencies.md` - Why backfill order matters
- `docs/01-architecture/pipeline-design.md` - Overview of 5-phase system

**Monitoring:**
- `docs/monitoring/05-data-completeness-validation.md` - Validation queries
- `docs/monitoring/01-grafana-monitoring-guide.md` - Real-time monitoring

**Recovery:**
- `docs/operations/02-dlq-recovery-guide.md` - DLQ recovery for processing failures

**Deployment:**
- `docs/processors/README.md` - Processor deployment guides
- `bin/*/deploy/` - Deployment scripts

---

## 📝 Quick Reference

### Pre-Flight Checklist

Before starting any backfill:
- [ ] Calculate date ranges (including lookback)
- [ ] Check what data already exists
- [ ] Verify Cloud Run jobs are deployed
- [ ] Confirm BigQuery tables exist
- [ ] Test with 1-2 dates first
- [ ] Have rollback plan ready

---

### Backfill Execution Checklist

During backfill:
- [ ] Run phases sequentially (2 → 3 → 4 → 5)
- [ ] Validate after each phase completes
- [ ] Monitor progress (logs, BigQuery row counts)
- [ ] Document any failures
- [ ] Keep notes on what worked/didn't work

---

### Post-Backfill Checklist

After backfill:
- [ ] Final validation (all dates, all phases)
- [ ] Row count reconciliation
- [ ] Sample data quality checks
- [ ] Document completion in handoff/notes
- [ ] Alert stakeholders (predictions team, etc.)

---

### Common Commands Quick Reference

```bash
# Pre-flight check
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date <start> --end-date <end>

# Verify Phase 3 ready for Phase 4
.venv/bin/python bin/backfill/verify_phase3_for_phase4.py \
    --start-date <start> --end-date <end>

# Run Phase 4 backfill
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date <start> --end-date <end>

# Validate coverage after backfill
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date <start> --end-date <end> --details

# Check for cascade contamination
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date <start> --end-date <end> --strict
```

---

**Created:** 2025-11-18
**Last Updated:** 2025-12-08
**Status:** Current
