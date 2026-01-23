# Cascade Reprocessing Protocol

**Document:** 06-CASCADE-PROTOCOL.md
**Created:** January 22, 2026

---

## Overview

This document defines the step-by-step protocol for handling data backfills and the resulting cascade of dependent records that need reprocessing.

---

## When Cascade Reprocessing is Needed

Cascade reprocessing is required when:

1. **Missing data is backfilled:** Raw or analytics data that was previously missing is now available
2. **Data is corrected:** Existing data was wrong and has been updated
3. **Schema changes:** Data structure changes require re-calculation

This document focuses on case #1 (backfill), which is the most common scenario.

---

## The Cascade Effect Explained

When data for a specific date is backfilled:

```
Backfilled: Jan 1

Jan 1 data is now used in rolling windows for:
├── Jan 2:  Window includes Jan 1 (game 1 of 10)
├── Jan 3:  Window includes Jan 1 (game 2 of 10)
├── Jan 4:  Window includes Jan 1 (game 3 of 10)
│   ...
├── Jan 14: Window includes Jan 1 (game ~10 of 10)
├── Jan 15: Jan 1 might still be in window
│   ...
└── Jan 21: Jan 1 pushed out of window for most players

Impact duration: ~14-21 days after backfilled date
```

---

## Full Cascade Protocol

### Phase 1: Identify the Gap

**Trigger:** Discovery that historical data is missing

**Steps:**

1. **Identify missing dates:**
   ```bash
   # Query to find missing dates
   python bin/check_data_completeness.py --start-date 2026-01-01 --end-date 2026-01-21
   ```

2. **Document the gap:**
   - Start date of gap
   - End date of gap
   - Affected tables
   - Root cause (scraper failure, API issue, etc.)

3. **Estimate impact:**
   ```
   Gap: Jan 1 - Jan 5 (5 days)
   Cascade end: Jan 5 + 21 days = Jan 26
   Affected range: Jan 2 - Jan 26 (25 days)
   Estimated records: 25 days × 500 players = 12,500 features
   ```

---

### Phase 2: Backfill Raw Data

**Goal:** Get the missing raw data into the system

**Steps:**

1. **Run catch-up scrapers:**
   ```bash
   # For team boxscore data
   python backfill_jobs/scrapers/nbac_team_boxscore/scraper.py \
       --start-date 2026-01-01 --end-date 2026-01-05

   # For gamebook data
   python backfill_jobs/scrapers/nbac_gamebook/scraper.py \
       --start-date 2026-01-01 --end-date 2026-01-05
   ```

2. **Verify raw data:**
   ```sql
   SELECT game_date, COUNT(*) as records
   FROM nba_raw.nbac_team_boxscore
   WHERE game_date BETWEEN '2026-01-01' AND '2026-01-05'
   GROUP BY game_date
   ORDER BY game_date;
   ```

3. **Log completion:**
   - Record which dates were backfilled
   - Record any remaining gaps

---

### Phase 3: Backfill Analytics

**Goal:** Process raw data into analytics tables

**Steps:**

1. **Run Phase 2 processors (raw → analytics):**
   ```bash
   # Process player game summary
   python backfill_jobs/analytics/player_game_summary_backfill.py \
       --start-date 2026-01-01 --end-date 2026-01-05

   # Process team summaries
   python backfill_jobs/analytics/team_game_summary_backfill.py \
       --start-date 2026-01-01 --end-date 2026-01-05
   ```

2. **Verify analytics data:**
   ```sql
   SELECT game_date, COUNT(DISTINCT player_lookup) as players
   FROM nba_analytics.player_game_summary
   WHERE game_date BETWEEN '2026-01-01' AND '2026-01-05'
   GROUP BY game_date
   ORDER BY game_date;
   ```

---

### Phase 4: Run Cascade Detection

**Goal:** Identify all feature records that need reprocessing

**Steps:**

1. **Run cascade detector:**
   ```bash
   python bin/cascade_reprocessor.py detect \
       --backfill-start 2026-01-01 \
       --backfill-end 2026-01-05 \
       --output cascade_affected.json
   ```

2. **Review output:**
   ```json
   {
       "backfill_dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
       "cascade_start": "2026-01-02",
       "cascade_end": "2026-01-26",
       "total_affected_records": 12500,
       "affected_by_date": {
           "2026-01-02": ["player_a", "player_b", ...],
           "2026-01-03": ["player_a", "player_c", ...],
           ...
       }
   }
   ```

3. **Validate scope:**
   - Is the number of affected records reasonable?
   - Are there any unexpected players/dates?

---

### Phase 5: Backfill Precompute (Phase 4 Tables)

**Goal:** Regenerate Phase 4 precompute tables for gap dates

**Steps:**

1. **Run Phase 4 processors for gap dates:**
   ```bash
   # Player daily cache
   python backfill_jobs/precompute/player_daily_cache/backfill.py \
       --start-date 2026-01-01 --end-date 2026-01-05

   # Player composite factors
   python backfill_jobs/precompute/player_composite_factors/backfill.py \
       --start-date 2026-01-01 --end-date 2026-01-05

   # Team defense zone analysis
   python backfill_jobs/precompute/team_defense_zone_analysis/backfill.py \
       --start-date 2026-01-01 --end-date 2026-01-05
   ```

---

### Phase 6: Cascade Feature Store Reprocessing

**Goal:** Regenerate all affected feature records

**Steps:**

1. **Run cascade reprocessor:**
   ```bash
   python bin/cascade_reprocessor.py reprocess \
       --affected-file cascade_affected.json \
       --batch-size 100 \
       --parallel-dates 3
   ```

2. **Monitor progress:**
   ```
   Processing cascade...
   Date 2026-01-02: 500 players [============================] 100%
   Date 2026-01-03: 500 players [============================] 100%
   ...
   Date 2026-01-26: 500 players [============================] 100%

   Total: 12,500 records processed in 2h 15m
   ```

3. **Or run manually date-by-date:**
   ```bash
   for date in 2026-01-{02..26}; do
       python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
           --date $date --skip-preflight
   done
   ```

---

### Phase 7: Verify Completeness

**Goal:** Confirm all affected records are now complete

**Steps:**

1. **Query completeness status:**
   ```sql
   SELECT
       game_date,
       COUNT(*) as total,
       COUNTIF(historical_completeness.is_complete) as complete,
       COUNTIF(NOT historical_completeness.is_complete) as incomplete
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date BETWEEN '2026-01-02' AND '2026-01-26'
   GROUP BY game_date
   ORDER BY game_date;
   ```

2. **Expected result:**
   ```
   game_date   | total | complete | incomplete
   ------------|-------|----------|------------
   2026-01-02  | 500   | 500      | 0
   2026-01-03  | 500   | 500      | 0
   ...
   2026-01-26  | 500   | 500      | 0
   ```

3. **If incomplete records remain:**
   - Investigate why
   - Check for secondary gaps
   - Re-run for specific players if needed

---

### Phase 8: Cascade Predictions (Optional)

**Goal:** Regenerate predictions for affected dates (if historical)

**When needed:**
- If affected dates are historical (for grading/analysis)
- If predictions were made with incomplete features

**Steps:**

1. **Identify predictions needing re-run:**
   ```sql
   SELECT DISTINCT game_date
   FROM nba_predictions.ml_predictions_v2
   WHERE game_date BETWEEN '2026-01-02' AND '2026-01-26'
     AND feature_incomplete_flag = TRUE;
   ```

2. **Re-run prediction coordinator:**
   ```bash
   python bin/run_prediction_coordinator.py \
       --start-date 2026-01-02 \
       --end-date 2026-01-26 \
       --force-rerun
   ```

---

### Phase 9: Document and Close

**Goal:** Complete documentation for future reference

**Steps:**

1. **Create incident report:**
   - Root cause
   - Dates affected
   - Actions taken
   - Records reprocessed
   - Time to remediate

2. **Update prevention measures:**
   - What monitoring gaps existed?
   - What alerting should be added?
   - What code changes could prevent recurrence?

3. **Close out:**
   - Mark cascade as complete
   - Remove `needs_reprocessing` flags
   ```sql
   UPDATE nba_predictions.ml_feature_store_v2
   SET historical_completeness.needs_reprocessing = FALSE
   WHERE game_date BETWEEN '2026-01-02' AND '2026-01-26'
     AND historical_completeness.is_complete = TRUE;
   ```

---

## Quick Reference: CLI Commands

### Check Completeness Status

```bash
# Check single date
python bin/check_data_completeness.py --date 2026-01-15

# Check date range
python bin/check_data_completeness.py \
    --start-date 2026-01-01 \
    --end-date 2026-01-31

# Check specific player
python bin/check_data_completeness.py \
    --player lebron_james \
    --date 2026-01-15
```

### Run Cascade Detection

```bash
# Detect affected records
python bin/cascade_reprocessor.py detect \
    --backfill-start 2026-01-01 \
    --backfill-end 2026-01-05 \
    --output affected.json

# Dry run (show what would be done)
python bin/cascade_reprocessor.py detect \
    --backfill-start 2026-01-01 \
    --backfill-end 2026-01-05 \
    --dry-run
```

### Run Cascade Reprocessing

```bash
# Full reprocess from affected file
python bin/cascade_reprocessor.py reprocess \
    --affected-file affected.json

# Reprocess specific date range
python bin/cascade_reprocessor.py reprocess \
    --start-date 2026-01-02 \
    --end-date 2026-01-26

# Reprocess specific players
python bin/cascade_reprocessor.py reprocess \
    --players lebron_james,kevin_durant \
    --start-date 2026-01-02 \
    --end-date 2026-01-26
```

### Verify Results

```bash
# Verify completeness after cascade
python bin/check_data_completeness.py verify \
    --start-date 2026-01-02 \
    --end-date 2026-01-26 \
    --expect-complete
```

---

## Cascade Timing Estimates

| Backfill Scope | Cascade Scope | Est. Time |
|----------------|---------------|-----------|
| 1 day | ~21 days, 10,500 records | ~1.5 hours |
| 5 days | ~26 days, 13,000 records | ~2 hours |
| 14 days | ~35 days, 17,500 records | ~3 hours |
| 30 days | ~51 days, 25,500 records | ~4.5 hours |

*Based on ~500 players/day, ~15 seconds/player for feature generation*

---

## Troubleshooting

### Issue: Cascade Shows 0 Affected Records

**Possible causes:**
1. `historical_completeness` column not populated on existing records
2. Backfilled date already in contributing_game_dates (no missing data)
3. Query parameters incorrect

**Resolution:**
```sql
-- Check if metadata exists
SELECT COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE historical_completeness.games_found IS NOT NULL
  AND game_date >= '2026-01-02';
```

### Issue: Some Records Still Incomplete After Cascade

**Possible causes:**
1. Secondary gap (another missing date)
2. Player-specific issue (DNP, trade, etc.)
3. Source data still missing

**Resolution:**
```sql
-- Find remaining incomplete and why
SELECT
    player_lookup,
    historical_completeness.missing_game_dates,
    historical_completeness.incompleteness_reason
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-15'
  AND NOT historical_completeness.is_complete;
```

### Issue: Cascade Taking Too Long

**Possible causes:**
1. Too many dates processing serially
2. Database contention
3. Large batch sizes

**Resolution:**
```bash
# Reduce batch size
python bin/cascade_reprocessor.py reprocess \
    --affected-file affected.json \
    --batch-size 50

# Process fewer dates in parallel
python bin/cascade_reprocessor.py reprocess \
    --affected-file affected.json \
    --parallel-dates 2
```

---

## Monitoring During Cascade

### Progress Query

```sql
SELECT
    game_date,
    COUNT(*) as total,
    COUNTIF(historical_completeness.is_complete) as processed,
    COUNTIF(historical_completeness.needs_reprocessing) as pending
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2026-01-02' AND '2026-01-26'
GROUP BY game_date
ORDER BY game_date;
```

### Estimated Time Remaining

```sql
WITH progress AS (
    SELECT
        COUNTIF(historical_completeness.is_complete AND NOT historical_completeness.needs_reprocessing) as done,
        COUNTIF(historical_completeness.needs_reprocessing) as remaining
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date BETWEEN '2026-01-02' AND '2026-01-26'
)
SELECT
    done,
    remaining,
    ROUND(remaining * 0.03, 1) as est_minutes_remaining  -- ~0.03 min per record
FROM progress;
```

---

## Related Documents

- `04-SOLUTION-ARCHITECTURE.md` - System architecture
- `05-DATA-MODEL.md` - Data structures
- `07-IMPLEMENTATION-PLAN.md` - Implementation phases

---

**Document Status:** Complete
