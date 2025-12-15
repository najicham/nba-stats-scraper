# Session 133 Handoff - Comprehensive Validation & Phase 5 Plan

**Date:** 2025-12-14
**Session:** 133
**Focus:** Thorough validation of Phase 3-4, known issues investigation, Phase 5 backfill planning

---

## Summary

Performed comprehensive validation of all Phase 3 and Phase 4 data using 6 parallel agents. Found two duplicate issues requiring cleanup, resolved three "known issues" as working-as-designed, and prepared a complete Phase 5 backfill plan.

**Key Outcomes:**
- Phase 3: 4/5 tables clean, 1 has 34,728 duplicates (26.6%)
- Phase 4: 4/5 tables clean, MLFS has 165 duplicates
- Known issues: All resolved (intentional design or documentation errors)
- Phase 5: 392 dates ready for predictions backfill

---

## Critical Action Items

### 1. Deduplicate `upcoming_player_game_context` (Phase 3)

**Severity:** HIGH - 34,728 duplicate records (26.6% of table)

**SQL to fix:**
```sql
-- Step 1: Verify duplicate count before deletion
SELECT COUNT(*) as total_rows,
       COUNT(DISTINCT CONCAT(universal_player_id, '-', game_id)) as unique_records,
       COUNT(*) - COUNT(DISTINCT CONCAT(universal_player_id, '-', game_id)) as duplicates
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;

-- Step 2: Create backup table (optional but recommended)
CREATE TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20241214` AS
SELECT * FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;

-- Step 3: Delete duplicates (keep earliest processed_at)
DELETE FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` t
WHERE t.processed_at NOT IN (
  SELECT MIN(processed_at)
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  GROUP BY universal_player_id, game_id
)
AND EXISTS (
  SELECT 1 FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` t2
  WHERE t2.universal_player_id = t.universal_player_id
    AND t2.game_id = t.game_id
    AND t2.processed_at < t.processed_at
);

-- Step 4: Verify after deletion
SELECT COUNT(*) as total_rows,
       COUNT(DISTINCT CONCAT(universal_player_id, '-', game_id)) as unique_records
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;
-- Expected: ~95,828 rows (was 130,556)
```

### 2. Deduplicate MLFS (Phase 4) - Lower Priority

**Severity:** LOW - 165 duplicate records (0.2% of table)

```sql
-- Verify duplicates
SELECT COUNT(*) as duplicate_pairs
FROM (
  SELECT player_lookup, game_id, COUNT(*) as cnt
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  GROUP BY player_lookup, game_id
  HAVING cnt > 1
);
-- Expected: 165

-- Delete duplicates (keep earliest)
DELETE FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` t
WHERE t.processed_at NOT IN (
  SELECT MIN(processed_at)
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  GROUP BY player_lookup, game_id
)
AND EXISTS (
  SELECT 1 FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` t2
  WHERE t2.player_lookup = t.player_lookup
    AND t2.game_id = t.game_id
    AND t2.processed_at < t.processed_at
);
```

### 3. Investigate Duplicate Root Cause

**Task:** Determine why duplicates were inserted and prevent future occurrences.

**Evidence collected:**
- `upcoming_player_game_context` duplicates: All from Dec 12, 2025 backfill
  - Timestamps within 1-2 seconds of each other (e.g., 15:36:37 to 15:36:39)
  - Same player-game combinations inserted 2-8 times
  - Examples: Stephen Curry (8x), Xavier Tillman (8x), Anthony Edwards (7x)

- `ml_feature_store_v2` duplicates: All from November 2021 dates
  - Concentrated in first month of backfill processing
  - Players like royceoneale, demarderozan, dillonbrooks affected

**Likely causes to investigate:**
1. **Concurrent execution:** Multiple workers processing same date/player
2. **Retry logic:** Failed inserts being retried without checking for existing records
3. **Missing idempotency:** No upsert/merge logic - just INSERT
4. **Checkpoint issues:** Checkpoints not being read correctly, causing re-processing

**Files to review:**
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `/home/naji/code/nba-stats-scraper/shared/bigquery/bigquery_client.py` (insert logic)

**Recommended fix pattern:**
```python
# Add MERGE/upsert instead of INSERT, or add duplicate check before insert
def insert_with_dedup(self, table_id, rows, unique_keys):
    """Insert rows, skipping duplicates based on unique_keys."""
    existing = self.query(f"SELECT {','.join(unique_keys)} FROM {table_id}")
    existing_set = {tuple(row[k] for k in unique_keys) for row in existing}
    new_rows = [r for r in rows if tuple(r[k] for k in unique_keys) not in existing_set]
    if new_rows:
        self.insert_rows(table_id, new_rows)
```

---

## Validation Results Summary

### Phase 3 Tables

| Table | Rows | Dates | Duplicates | Status |
|-------|------|-------|------------|--------|
| player_game_summary | 107,391 | 708 | 0 | ✅ Clean |
| team_offense_game_summary | 10,412 | 802 | 0 | ✅ Clean |
| team_defense_game_summary | 10,412 | 802 | 0 | ✅ Clean |
| upcoming_team_game_context | 6,196 | 450 | 0 | ✅ Clean |
| upcoming_player_game_context | 130,556 | 443 | **34,728** | ❌ Needs cleanup |

**Data Quality:**
- 99.28% gold-tier in player_game_summary
- 100% gold-tier in team_defense_game_summary
- All critical fields populated (no NULLs in primary keys)

**Known NULL fields (expected):**
- `minutes_played`: 99.47% NULL in player_game_summary (schema issue - field exists but not populated)
- `game_spread`: 100% NULL in upcoming_team_game_context (no betting lines in historical backfill)
- `current_points_line`: 46% NULL in upcoming_player_game_context (expected for historical data)

### Phase 4 Tables

| Processor | Rows | Dates | Duplicates | Phase 3 Coverage |
|-----------|------|-------|------------|------------------|
| TDZA | 15,339 | 520 | 0 | 87.8% |
| PSZA | 218,017 | 536 | 0 | 90.5% |
| PCF | 101,185 | 495 | 0 | 83.8% |
| PDC | 58,614 | 459 | 0 | 77.7% |
| MLFS | 75,688 | 453 | **165** | 76.7% |

**Coverage notes:**
- Missing dates are bootstrap periods (first 14 days of each season) - intentional
- 42 dates skipped for bootstrap across 3 seasons
- No playoff dates in backfill range (ends April 15, before playoffs)

---

## Known Issues Resolution

### Issue 1: PCF `opponent_strength_score = 0` for all records

**Status:** ✅ WORKING AS DESIGNED

**Finding:** This is a **deferred factor** intentionally set to 0.0 as a placeholder.

**Evidence:**
- Schema documentation (`schemas/bigquery/precompute/player_composite_factors.sql` line 88-90):
  ```sql
  opponent_strength_score NUMERIC(3,1),  -- PLACEHOLDER: returns 0.0
  -- TODO: Implement after 3 months if XGBoost shows >5% importance
  ```
- Processor code (`player_composite_factors_processor.py` lines 216-220):
  ```python
  # Deferred factors (set to 0)
  opponent_strength_adj = 0.0
  ```

**Design rationale:**
- 4 active factors implemented (fatigue, shot_zone_mismatch, pace, usage_spike)
- 4 deferred factors (referee, look_ahead, travel, opponent_strength) set to 0
- Plan: Evaluate after 3 months of production data; implement if XGBoost shows >5% importance

**Action:** None required. Consider removing misleading validation checks that flag this as an issue.

---

### Issue 2: MLFS ~57% production-ready rate

**Status:** ✅ EXPECTED BEHAVIOR

**Finding:** This is the **CASCADE PATTERN** working correctly. MLFS inherits incomplete status from upstream dependencies.

**Production Ready Breakdown:**
| Table | Production Ready % |
|-------|-------------------|
| PCF | ~100% |
| PSZA | 100% |
| TDZA | 100% |
| PDC | **83.4%** ← Bottleneck |
| **MLFS** | **57.1%** |

**Root cause:** `player_daily_cache` (PDC) requires ALL 4 time windows to be ≥90% complete:
- L5 (last 5 games)
- L10 (last 10 games)
- L7D (last 7 days)
- L14D (last 14 days)

Date-based windows (L7D, L14D) frequently fail due to:
- Early season: Insufficient games in 7/14 day windows
- Late season (April): Schedule compression, fewer games per week
- End-of-season player rest

**Seasonal pattern:**
| Month | MLFS Prod-Ready % | Notes |
|-------|------------------|-------|
| November | 32% | Bootstrap period |
| December | 56% | Ramping up |
| January | 65% | Normal |
| February | 65% | Normal |
| March | 69% | Peak |
| April | 64% | End-of-season |

**Action:** None required. This is quality-gating working as intended. The 43,226 production-ready records represent fully-validated feature vectors.

---

### Issue 3: "90 MLFS failures (playoff dates)"

**Status:** ❌ DOCUMENTATION ERROR

**Finding:** There were **ZERO actual failures**. The handoff document Session 132 incorrectly claimed 90 playoff failures.

**Actual breakdown:**
| Metric | Count | Notes |
|--------|-------|-------|
| Total game dates in range | 495 | From Phase 3 |
| Successfully processed | 453 | In MLFS table |
| Bootstrap skips | 42 | First 14 days/season (intentional) |
| **Actual failures** | **0** | Perfect run |

**Why "90 failures" was wrong:**
- Backfill date range: 2021-10-19 to 2024-04-15
- Regular seasons end mid-April
- Playoffs start after April 16
- **Zero playoff dates exist in the backfill range**

The "585 dates" mentioned in Session 132 was also incorrect - there are only 495 NBA game dates in the range. The 90-date discrepancy was likely calendar days without games being mistakenly counted.

**Action:** Update Session 132 handoff doc or add correction note.

---

## Phase 5 Backfill Plan

### Current State

| Component | Status | Coverage |
|-----------|--------|----------|
| Phase 5A: Predictions | ⏳ Partial | 62/453 dates (14%) |
| Phase 5B: Grading | ⏳ Partial | 61 dates graded |
| Phase 5C: Tier Adjustments | ⏳ Partial | 52% coverage |

**Existing predictions:** Nov 6, 2021 - Jan 7, 2022 (61 dates) + 1 test date (Nov 25, 2025)
**Dates needing predictions:** 392 dates

### Phase 5A: Predictions Backfill

**Command:**
```bash
cd /home/naji/code/nba-stats-scraper

# Optional: Dry run first
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --dry-run --start-date 2022-01-08 --end-date 2022-01-15

# Full backfill
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-11-02 --end-date 2024-04-14
```

**Expected results:**
- Process 392 dates (skip 61 existing + bootstrap periods)
- Generate ~392,000 new predictions (5 systems × ~200 players × 392 dates)
- Runtime: 20-30 minutes with batch loading optimization

**Systems that will generate predictions:**
1. `moving_average_baseline_v1` - Simple historical average
2. `zone_matchup_v1` - Shot zone + defensive matchups
3. `similarity_balanced_v1` - Similar games comparison
4. `xgboost_v1` - Machine learning model
5. `ensemble_v1` - Weighted combination

### Phase 5B: Grading Backfill

**Command:**
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-02 --end-date 2024-04-14
```

**Expected results:**
- Grade all ~440,000 predictions against actual results
- Compute MAE, bias, recommendation accuracy per system
- Runtime: 10-15 minutes

**Current system accuracy (from existing 61 dates):**
| System | MAE | Notes |
|--------|-----|-------|
| ensemble_v1 | 4.51 | Best performer |
| xgboost_v1 | 4.52 | Close second |
| moving_average_baseline_v1 | 4.63 | Solid baseline |
| similarity_balanced_v1 | 4.87 | Needs tuning |
| zone_matchup_v1 | 5.72 | Needs review |

### Validation Queries

```bash
# After Phase 5A - verify predictions
bq query --use_legacy_sql=false "
  SELECT
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as predictions,
    COUNT(DISTINCT system_id) as systems
  FROM nba-props-platform.nba_predictions.player_prop_predictions
"
-- Expected: ~453 dates, ~440,000 predictions, 5 systems

# After Phase 5B - verify grading
bq query --use_legacy_sql=false "
  SELECT
    system_id,
    COUNT(DISTINCT game_date) as graded_dates,
    COUNT(*) as graded_predictions,
    ROUND(AVG(absolute_error), 2) as avg_mae
  FROM nba-props-platform.nba_predictions.prediction_accuracy
  GROUP BY system_id
  ORDER BY avg_mae
"
```

---

## Files Modified This Session

None - this was a validation and planning session.

---

## Files to Review for Duplicate Investigation

1. **Upcoming Player Context Processor:**
   - `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
   - Check: Insert logic, batch handling, error retry behavior

2. **MLFS Processor:**
   - `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
   - Check: Idempotency checks, upsert vs insert

3. **BigQuery Client:**
   - `shared/bigquery/bigquery_client.py`
   - Check: Insert method, duplicate handling

4. **Backfill Base:**
   - `shared/backfill/backfill_base.py`
   - Check: Checkpoint logic, retry behavior

---

## Recommended Execution Order

1. **Run deduplication queries** (Phase 3 first, then Phase 4)
2. **Investigate duplicate root cause** (review processor code)
3. **Implement duplicate prevention** (add unique constraint or upsert logic)
4. **Run Phase 5A predictions backfill**
5. **Run Phase 5B grading backfill**
6. **Validate final results**

---

## Session Context

- Previous session (132) completed MLFS backfill
- This session performed comprehensive validation before Phase 5
- 6 parallel agents used for thorough investigation
- All "known issues" from Session 132 resolved as working-as-designed or doc errors
- System is ready for Phase 5 after duplicate cleanup

**Last Updated By:** Claude Code Session 133
**Date:** 2025-12-14 ~12:00 PST
