# Session 104: Idempotency Fix and Validation Checklist

**Date:** 2025-12-10
**Status:** COMPLETE with follow-up items

---

## Executive Summary

This session completed the idempotency fix for prediction backfills (P6 from Session 103), investigated data quality issues, and created a comprehensive validation checklist document for future backfill operations.

---

## Work Completed This Session

### 1. Idempotency Fix (P6 from S103)
**Status:** COMPLETE
**Commit:** `b7507cc`

Added pre-delete logic to `backfill_jobs/prediction/player_prop_predictions_backfill.py:316-347`:
- DELETE existing predictions for date before INSERT
- Allows safe re-runs without creating duplicates
- Added game_id to query and write functions (populated at write time)

**Code Changes:**
```python
# Lines 338-347: Pre-delete for idempotency
delete_query = f"""
DELETE FROM `{PREDICTIONS_TABLE}`
WHERE game_date = '{game_date.isoformat()}'
"""
delete_job = self.bq_client.query(delete_query)
delete_job.result()  # Wait for completion
deleted_count = delete_job.num_dml_affected_rows or 0
if deleted_count > 0:
    logger.info(f"  Deleted {deleted_count} existing predictions for {game_date} (idempotency)")
```

### 2. Comprehensive Validation Checklist
**Status:** COMPLETE
**Commits:** `189682e`, `e69f8fb`
**Location:** `docs/02-operations/backfill/backfill-validation-checklist.md`

Created 451-line checklist covering:
1. Pre-backfill checks
2. Post-backfill validation
3. Data integrity & quality
4. Gap analysis
5. Failure record analysis
6. Name resolution checks
7. Performance monitoring
8. Downstream impact analysis

### 3. Investigation: Bad Confidence Scores
**Status:** ROOT CAUSE IDENTIFIED, NOT YET FIXED

**Finding:** 40 predictions have confidence > 1.0 (values like 52.0, 84.0)
- All on date 2025-11-25 (from daily production run, NOT backfill)
- Root cause: Scale mismatch between daily worker and backfill

**Technical Details:**
| Component | Scale | Location |
|-----------|-------|----------|
| Daily worker | 0-100 | `predictions/worker/worker.py:872` calls `normalize_confidence()` |
| Backfill script | 0-1 | `backfill_jobs/prediction/player_prop_predictions_backfill.py:387` stores raw |
| ensemble_v1 | 0-100 | `predictions/worker/prediction_systems/ensemble_v1.py:313` |
| moving_average | 0.2-0.8 | `predictions/worker/prediction_systems/moving_average_baseline.py:271` |

**Fix Required:** Align all writers on same scale (recommend 0-1)

### 4. Investigation: PSZA UNTRACKED Nov 2-4
**Status:** RESOLVED - NOT A BUG

**Finding:** PSZA shows "UNTRACKED" for Nov 2-4 because:
- PSZA requires 10 games per player
- By Nov 2 (day 14 of season), 0 players had 10 games
- This is expected bootstrap behavior

**Evidence:**
```sql
SELECT COUNT(*) as players_with_10_games
FROM (
  SELECT player_lookup
  FROM nba_analytics.player_game_summary
  WHERE game_date < '2021-11-02'
  GROUP BY player_lookup
  HAVING COUNT(*) >= 10
)
-- Result: 0
```

---

## Current Data State

| Metric | Value |
|--------|-------|
| Total predictions | 34,166 |
| Duplicates | 0 (fixed in S103) |
| NULL game_id | 0 (fixed in S103) |
| Bad confidence scores | 40 (on 2025-11-25 only) |
| Nov dates with data | 24 |
| Dec dates with data | 30 |

### Prediction Accuracy (Nov-Dec 2021)
| System | MAE | Predictions |
|--------|-----|-------------|
| xgboost_v1 | 4.45 | 8,486 |
| zone_matchup_v1 | 4.99 | 8,486 |
| moving_average | 5.46 | 8,486 |
| ensemble_v1 | 5.58 | 8,486 |

---

## Key Documents and Files

### Validation Checklist (NEW)
**Path:** `docs/02-operations/backfill/backfill-validation-checklist.md`

Use this checklist after every backfill run. It contains:
- 7-part validation framework
- SQL queries for each check
- Known issues with root causes
- Checklist template for tracking

### Related Files
| File | Purpose |
|------|---------|
| `backfill_jobs/prediction/player_prop_predictions_backfill.py` | Phase 5 predictions (now with idempotency) |
| `scripts/validate_backfill_coverage.py` | Main validation script |
| `predictions/worker/worker.py` | Daily prediction worker |
| `predictions/worker/data_loaders.py` | `normalize_confidence()` function |

---

## TODO Items for Next Session

### Priority 1: Fix Confidence Scale Mismatch
**Estimated Impact:** 40 records affected (current), all future daily runs

**Options:**
- **Option A (Recommended):** Change `normalize_confidence()` to output 0-1
  - Location: `predictions/worker/data_loaders.py:811`
  - Also update ensemble_v1 to output 0-1 instead of 0-100
- **Option B:** Change backfill to normalize to 0-100
  - Location: `backfill_jobs/prediction/player_prop_predictions_backfill.py:387`

**Action:** Pick a canonical scale (0-1 recommended) and align all writers

### Priority 2: Extend Backfill to Jan-Apr 2022
**Status:** Optional but recommended

The 2021-22 season runs through April 2022. Current backfill covers:
- Phase 4: Nov 2, 2021 - Dec 31, 2021 (complete)
- Phase 5: Nov 2, 2021 - Dec 31, 2021 (complete)

**Command to extend:**
```bash
# Phase 4 first (TDZA, PSZA, PCF, PDC, MLFS)
./bin/backfill/run_phase4_backfill.sh --start-date 2022-01-01 --end-date 2022-04-30

# Then Phase 5
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2022-01-01 --end-date 2022-04-30 --skip-preflight
```

### Priority 3: Clean Up Bad Confidence Records
After fixing the scale mismatch, clean up the 40 bad records:
```sql
DELETE FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-11-25'
  AND confidence_score > 1.0;
```

---

## Investigations to Run

The next session should study:

### 1. Confidence Scale Alignment
**What to study:**
- `predictions/worker/data_loaders.py` - `normalize_confidence()` function
- `predictions/worker/prediction_systems/*.py` - What scales each system uses
- `predictions/worker/worker.py:872` - How daily worker writes confidence

**Questions to answer:**
- What scale does each prediction system output?
- What does the database schema expect?
- What do downstream consumers expect?

### 2. Daily vs Backfill Pipeline Differences
**What to study:**
- `predictions/worker/worker.py` - Daily prediction flow
- `backfill_jobs/prediction/player_prop_predictions_backfill.py` - Backfill flow

**Questions to answer:**
- What other differences exist between daily and backfill?
- Are there other data transformations that differ?

### 3. December Sparse Prediction Dates
**Background:** Session 104 found 4 dates with sparse predictions:
- Dec 14, 16, 19, 21, 22, 23, 29 have fewer predictions than expected

**What to investigate:**
```sql
-- Check why these dates have sparse predictions
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date IN ('2021-12-14', '2021-12-16', '2021-12-19', '2021-12-21', '2021-12-22', '2021-12-23', '2021-12-29')
GROUP BY game_date
ORDER BY game_date;
```

**Hypothesis:** These may be COVID protocol dates when games were postponed

---

## How to Use the Validation Checklist

After any backfill run:

1. **Read the checklist:** `docs/02-operations/backfill/backfill-validation-checklist.md`

2. **Run quick validation:**
```bash
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD --details
```

3. **Check for duplicates:**
```sql
SELECT COUNT(*) - COUNT(DISTINCT CONCAT(game_date, '|', player_lookup, '|', system_id)) as duplicates
FROM nba_predictions.player_prop_predictions;
```

4. **Check data quality:**
```sql
-- Confidence scores should be 0-1
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE confidence_score > 1.0 OR confidence_score < 0;

-- No NULL game_ids
SELECT COUNTIF(game_id IS NULL) FROM nba_predictions.player_prop_predictions;
```

5. **Review Section 7 of checklist** for known issues and their root causes

---

## Git Status

**Commits this session:**
1. `b7507cc` - feat: Add idempotency and game_id to prediction backfill
2. `189682e` - docs: Add comprehensive backfill validation checklist
3. `e69f8fb` - docs: Move validation checklist to backfill dir and add root cause for confidence issue

**Pushed:** Yes, all commits pushed to origin/main

---

## Session 103 → 104 Progress Summary

| Item | S103 Status | S104 Status |
|------|-------------|-------------|
| P1: Deduplication | COMPLETE | COMPLETE |
| P2: NULL game_id fix | COMPLETE | COMPLETE |
| P3: Nov 1 investigation | COMPLETE | COMPLETE |
| P4: Stale failure cleanup | COMPLETE | COMPLETE |
| P5: Nov 5-14 predictions | PENDING | COMPLETE (done early S104) |
| P6: Idempotency | PENDING | COMPLETE |
| Validation checklist | - | NEW (created) |
| Confidence scale fix | - | ROOT CAUSE FOUND, NOT FIXED |
