# Session 78 Handoff - February 2, 2026

## Session Summary

Fixed critical bug in prediction deactivation logic that was causing 85% of predictions to be incorrectly marked `is_active=FALSE`, breaking grading (which only processes active predictions).

---

## Key Accomplishments

### 1. Fixed is_active Deactivation Bug (CRITICAL)

**Problem:** The deactivation query in `batch_staging_writer.py` partitioned by `(game_id, player_lookup)` but **NOT** by `system_id`. This caused all but ONE prediction system to be deactivated per player/game.

**Impact:**
- Feb 1: 169 of 170 ACTUAL_PROP predictions were `is_active=FALSE`
- Feb 2: 222 of 222 ACTUAL_PROP predictions were `is_active=FALSE`
- Grading only processed 1 V9 prediction for Feb 1 instead of ~120

**Root Cause:** Line 516 in `predictions/shared/batch_staging_writer.py`:
```python
# BEFORE (wrong):
PARTITION BY game_id, player_lookup

# AFTER (fixed):
PARTITION BY game_id, player_lookup, system_id
```

**Fix Applied:**
- Commit: `3ea7a0a3`
- File: `predictions/shared/batch_staging_writer.py:516`
- Deployed: `prediction-worker-00068-zf6`

### 2. Data Repair

Re-activated 1,447 incorrectly deactivated predictions for Feb 1-2:

```sql
UPDATE `nba_predictions.player_prop_predictions` T
SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP()
WHERE game_date IN (DATE('2026-02-01'), DATE('2026-02-02'))
  AND is_active = FALSE
  AND prediction_id IN (
    SELECT prediction_id FROM (
      SELECT prediction_id,
        ROW_NUMBER() OVER (PARTITION BY game_id, player_lookup, system_id ORDER BY created_at DESC) as rn
      FROM `nba_predictions.player_prop_predictions`
      WHERE game_date IN (DATE('2026-02-01'), DATE('2026-02-02'))
    ) WHERE rn = 1
  )
```

### 3. Re-ran Grading Backfill

After fixing is_active, re-ran grading for Jan 25 - Feb 1:
- **Before fix:** 118 predictions graded for Feb 1
- **After fix:** 820 predictions graded for Feb 1
- **Total:** 2,382 predictions graded across 8 dates

---

## Current System State

### Model Performance (V9)
| Tier | Predictions | Hit Rate |
|------|-------------|----------|
| High Edge (5+) | 29 | 65.5% |
| Standard | 510 | 53.1% |

### Feb 2 Pre-Game Status
- 4 games scheduled (NOP@CHA, HOU@IND, MIN@MEM, PHI@LAC)
- 68 active V9 predictions
- Daily Signal: **RED** (6.3% pct_over - heavy UNDER skew)

### Deployments
| Service | Revision | Commit | Fix |
|---------|----------|--------|-----|
| prediction-worker | 00068-zf6 | 3ea7a0a3 | system_id in deactivation partition |

---

## How to Detect This Bug in Future

If grading shows unexpectedly low coverage, check:

```sql
-- Check is_active distribution by line_source
SELECT game_date, line_source, is_active, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND system_id = 'catboost_v9'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- Expected: ACTUAL_PROP predictions should be is_active=TRUE
-- Bug symptom: ACTUAL_PROP mostly is_active=FALSE, NO_PROP_LINE is is_active=TRUE
```

---

## Priority Tasks for Next Session

### P1: Verify run_mode Fix (Session 77)
Check if Feb 3 early predictions show `prediction_run_mode='EARLY'`:
```sql
SELECT prediction_run_mode, FORMAT_TIMESTAMP('%H:%M', created_at, 'America/New_York') as time_ET, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-03') AND system_id = 'catboost_v9'
GROUP BY 1, 2 ORDER BY time_ET;
```

### P2: Monitor Feb 2 Game Processing
After tonight's 4 games complete, verify overnight processing:
- Phase 3 should show 5/5 processors complete
- `player_game_summary` should have records for all 4 games

### P3: Investigate Vegas Line Coverage
Today's feature store shows only 40.5% Vegas line coverage (target: ≥80%). Investigate if this is:
- Normal for game-day timing (lines not yet available)
- Data extraction issue

---

## Files Modified This Session

| File | Change | Commit |
|------|--------|--------|
| `predictions/shared/batch_staging_writer.py` | Added system_id to deactivation partition | 3ea7a0a3 |

---

## Key Learnings

### Deactivation Logic Must Include All Business Key Fields

When deactivating "duplicate" predictions, the partition must include ALL fields that define uniqueness:
- `game_id` - which game
- `player_lookup` - which player
- `system_id` - which prediction system (CRITICAL - was missing!)

Without `system_id`, all prediction systems compete for the same "active" slot, leaving only one active per player/game.

### Symptom Pattern to Watch For

If you see this pattern, suspect the deactivation bug:
```
ACTUAL_PROP + is_active=FALSE: Many records
NO_PROP_LINE + is_active=TRUE: Few records
```

This indicates actionable predictions (with lines) are being deactivated while non-actionable predictions (no lines) remain active.

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
