# Session 49 Handoff - Line Timing Tracking & Analytics Fixes

**Date**: 2026-01-15 (~22:00 ET on Jan 14)
**Focus**: Added `line_minutes_before_game` tracking, fixed analytics partition filter

---

## Executive Summary

This session added a new tracking field `line_minutes_before_game` to predictions, which captures how close to game time the betting line was captured. This enables analysis of closing line vs early line performance. Also fixed a partition filter bug affecting analytics processors.

---

## Key Changes

### 1. Line Timing Tracking (v3.6)

**New Field**: `line_minutes_before_game` (INT64)

This field tracks how many minutes before game tipoff we captured the betting line used for the prediction.

**Why It Matters**:
- **Closing lines** (captured near game time) are considered the most "efficient" - they have all information priced in
- **Early lines** (captured hours before) may have more edge before the market adjusts
- Enables analysis: "Do we perform better using closing lines or early lines?"

**Implementation**:
```
predictions/coordinator/player_loader.py  - Query minutes_before_tipoff from odds
predictions/worker/worker.py              - Pass through to prediction record
BigQuery schema                           - Added line_minutes_before_game column
```

### 2. Analytics Partition Filter Fix

**Problem**: `TeamOffenseGameSummaryProcessor` and other analytics processors were failing with "partition filter required" errors.

**Root Cause**: BigQuery tables with `require_partition_filter=true` need the partition filter FIRST in the ON clause (not appended at the end).

**Fix**: Changed `analytics_base.py:1796` to put partition filter at start of ON clause:
```python
# Before (broken):
ON {on_clause} {partition_filter}

# After (fixed):
ON {partition_prefix}{on_clause}
```

---

## Current Data State

### Line Timing in Odds Data
```sql
SELECT
    game_date,
    ROUND(AVG(minutes_before_tipoff), 0) as avg_minutes_before,
    MIN(minutes_before_tipoff) as min_minutes,
    MAX(minutes_before_tipoff) as max_minutes,
    COUNT(DISTINCT snapshot_timestamp) as snapshots
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= "2026-01-13"
GROUP BY 1 ORDER BY 1 DESC
```

**Results**:
| game_date | avg_minutes | min | max | snapshots |
|-----------|-------------|-----|-----|-----------|
| 2026-01-14 | 307 | 4 | 574 | 21 |
| 2026-01-13 | 242 | 34 | 544 | 21 |

**Interpretation**:
- We capture lines from ~9.5 hours before game to ~4 minutes before
- 21 snapshots per day = good line movement coverage
- Min values (4-34 min) represent "closing line" territory
- Max values (544-574 min) represent "early line" territory

### Predictions Coverage
- New predictions (after deployment) will have `line_minutes_before_game` populated
- Historical predictions have `line_minutes_before_game = NULL`

---

## DECISION NEEDED: Backfill Strategy

### Option A: Create Best-Effort Backfill

**Approach**: Join predictions to odds and estimate timing:
```sql
UPDATE nba_predictions.player_prop_predictions p
SET line_minutes_before_game = (
    SELECT o.minutes_before_tipoff
    FROM nba_raw.odds_api_player_points_props o
    WHERE o.player_lookup = p.player_lookup
      AND o.game_date = p.game_date
      AND o.points_line = p.current_points_line
    ORDER BY ABS(TIMESTAMP_DIFF(o.snapshot_timestamp, p.created_at, MINUTE))
    LIMIT 1
)
WHERE p.line_minutes_before_game IS NULL
  AND p.line_source_api = 'ODDS_API'
```

**Pros**:
- Enables historical analysis immediately
- Can compare "closing line" performance across all data

**Cons**:
- Imprecise - multiple snapshots may have same line value
- Only works for ODDS_API predictions (not ESTIMATED lines)
- May attribute wrong timing if line didn't change

### Option B: Skip Backfill

**Approach**: Only new predictions have timing data

**Pros**:
- Data is accurate (captured at prediction time)
- No risk of incorrect attribution

**Cons**:
- Need to wait for new predictions to accumulate
- Historical analysis limited

### Option C: Create Query But Don't Run

**Approach**: Prepare the backfill query for manual review

**Pros**:
- Human can inspect and decide
- Can run on subset first to validate

---

## Deployments Required

The code changes need to be deployed for new predictions to capture `line_minutes_before_game`:

### 1. Prediction Coordinator
```bash
docker build -f docker/prediction-coordinator.Dockerfile -t gcr.io/nba-props-platform/prediction-coordinator:latest .
docker push gcr.io/nba-props-platform/prediction-coordinator:latest
gcloud run deploy prediction-coordinator \
  --image=gcr.io/nba-props-platform/prediction-coordinator:latest \
  --region=us-west2
```

### 2. Prediction Worker
```bash
docker build -f docker/prediction-worker.Dockerfile -t gcr.io/nba-props-platform/prediction-worker:latest .
docker push gcr.io/nba-props-platform/prediction-worker:latest
gcloud run deploy prediction-worker \
  --image=gcr.io/nba-props-platform/prediction-worker:latest \
  --region=us-west2
```

### 3. Analytics Processors (Already Deployed)
✅ `nba-phase3-analytics-processors` - Deployed with partition filter fix (Rev 00057-q4j)

---

## Commits This Session

```
b16cb0b feat(predictions): Add line_minutes_before_game tracking (v3.6)
96de115 fix(analytics): Fix partition filter order in MERGE query
```

Both pushed to `main`.

---

## Other Tasks Completed

| Task | Status |
|------|--------|
| Self-heal function deployment | ✅ Deployed |
| Staging tables cleanup | ✅ 0 remaining |
| Analytics partition filter fix | ✅ Deployed |
| Live scoring verification | ✅ Working (244 records/run) |

---

## Analytics Enabled After Implementation

Once predictions have `line_minutes_before_game` populated, you can run:

```sql
-- Compare hit rates by line timing
SELECT
    CASE
        WHEN line_minutes_before_game < 60 THEN 'closing (< 1hr)'
        WHEN line_minutes_before_game < 180 THEN 'afternoon (1-3hr)'
        WHEN line_minutes_before_game < 360 THEN 'morning (3-6hr)'
        ELSE 'early (> 6hr)'
    END as line_timing,
    COUNT(*) as predictions,
    ROUND(AVG(CASE WHEN hit THEN 1.0 ELSE 0.0 END) * 100, 1) as hit_rate_pct
FROM predictions_with_results
WHERE line_minutes_before_game IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC
```

This will answer: **"Do we perform better with closing lines or early lines?"**

---

## Quick Reference

### Verify Column Added
```bash
bq show --schema nba_predictions.player_prop_predictions | grep minutes
```

### Check Current Predictions (after deployment)
```sql
SELECT player_lookup, game_date, line_minutes_before_game, current_points_line
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
  AND line_minutes_before_game IS NOT NULL
LIMIT 10
```

### Check Odds Timing Distribution
```sql
SELECT
    CASE
        WHEN minutes_before_tipoff < 60 THEN 'closing'
        WHEN minutes_before_tipoff < 180 THEN 'afternoon'
        WHEN minutes_before_tipoff < 360 THEN 'morning'
        ELSE 'early'
    END as timing,
    COUNT(*) as records
FROM nba_raw.odds_api_player_points_props
WHERE game_date = CURRENT_DATE("America/New_York")
GROUP BY 1
```

---

## Recommended Next Steps

1. **Deploy coordinator + worker** to start capturing line timing
2. **Decide on backfill strategy** (Options A, B, or C above)
3. **Wait for ~1 week of data** before analyzing line timing patterns
4. **Create dashboard** to track line timing distribution

---

**Session Duration**: ~1.5 hours
**Primary Accomplishments**: Line timing tracking, analytics fix, multiple deployments
