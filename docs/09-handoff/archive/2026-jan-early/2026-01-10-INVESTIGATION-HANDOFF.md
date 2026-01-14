# Investigation Handoff: Player Matching & Daily Operations Check

**Date:** 2026-01-10
**Status:** NEEDS INVESTIGATION
**Priority:** High

---

## Executive Summary

The BettingPros scraper Brotli issue was fixed and deployed. However, investigation revealed a **player name matching problem** that limits prediction coverage. Additionally, need to verify yesterday's (Jan 9) predictions performed correctly and review daily orchestration health.

---

## Issue 1: Player Name Matching Problem (HIGH PRIORITY)

### The Problem

Only 37 of 87 players with Vegas lines can get predictions because player names don't match between data sources.

```
Players with Vegas lines:  87
Players with features:     79
Players that MATCH:        37  ← Only 42% coverage!
```

### Investigation Queries

```sql
-- 1. Check which players have lines but no features
WITH lines AS (
  SELECT DISTINCT player_lookup
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = '2026-01-10'
),
features AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2026-01-10'
)
SELECT l.player_lookup as player_with_line_no_feature
FROM lines l
LEFT JOIN features f USING(player_lookup)
WHERE f.player_lookup IS NULL
LIMIT 20;

-- 2. Check which players have features but no lines
WITH lines AS (
  SELECT DISTINCT player_lookup
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = '2026-01-10'
),
features AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2026-01-10'
)
SELECT f.player_lookup as player_with_feature_no_line
FROM features f
LEFT JOIN lines l USING(player_lookup)
WHERE l.player_lookup IS NULL
LIMIT 20;

-- 3. Sample player_lookup formats from each source
SELECT 'bettingpros' as source, player_lookup, COUNT(*) as cnt
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = '2026-01-10'
GROUP BY player_lookup
LIMIT 10;

SELECT 'feature_store' as source, player_lookup, COUNT(*) as cnt
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-10'
GROUP BY player_lookup
LIMIT 10;
```

### Possible Causes

1. **Name format differences** - e.g., "LeBron James" vs "lebronjames" vs "lebron_james"
2. **Name resolution not running** - The name resolution pipeline may not have run
3. **New players** - Players who just joined the league may not be in the registry
4. **BettingPros name changes** - BettingPros may have changed their player naming

### Files to Check

- `data_processors/reference/player_registry/` - Player name resolution logic
- `predictions/worker/prediction_loader.py` - How predictions load player data
- `backfill_jobs/reference/` - Reference data backfill jobs

---

## Issue 2: Today's Predictions Status

### Current State (Jan 10, 2026)

All predictions for today have `NO_LINE` because they were generated before Vegas lines were scraped:

```sql
SELECT system_id, recommendation, COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-10'
GROUP BY system_id, recommendation;
```

**Result:**
| system_id | recommendation | count |
|-----------|----------------|-------|
| catboost_v8 | NO_LINE | 36 |
| ensemble_v1 | NO_LINE | 36 |
| (etc.) | NO_LINE | 36 |

### What Should Happen

1. When Vegas lines were scraped (17:24 UTC), the pipeline should trigger re-predictions
2. Predictions should be updated with real lines and OVER/UNDER recommendations
3. The `ml-feature-store-daily` job runs at 23:30 UTC to update features

### Verification Queries

```sql
-- Check if predictions were regenerated after lines came in
SELECT
  system_id,
  recommendation,
  COUNT(*) as count,
  MAX(updated_at) as last_updated
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-10'
GROUP BY system_id, recommendation;

-- Check prediction worker activity
-- Run: gcloud logging read 'resource.labels.service_name="prediction-worker"' --project=nba-props-platform --limit=50 --freshness=2h
```

---

## Issue 3: Yesterday's Results (Jan 9, 2026)

### Verification Needed

1. **Did predictions run correctly?**
2. **Were predictions graded?**
3. **What was the win rate?**

### Queries to Run

```sql
-- 1. Check Jan 9 prediction coverage
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as picks,
  COUNTIF(recommendation = 'NO_LINE') as no_line,
  COUNTIF(current_points_line IS NOT NULL) as with_real_line
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-09'
GROUP BY system_id;

-- 2. Check if Jan 9 was graded
SELECT
  system_id,
  COUNT(*) as graded,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(COUNTIF(prediction_correct = TRUE) /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-09'
GROUP BY system_id;

-- 3. CatBoost v8 specific performance on Jan 9
SELECT
  recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(COUNTIF(prediction_correct = TRUE) / COUNT(*) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-09'
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY recommendation;
```

---

## Issue 4: Daily Orchestration Health Check

### Jobs to Verify

| Job | Schedule | What to Check |
|-----|----------|---------------|
| `grading-daily` | 11:00 UTC | Did Jan 9 get graded? |
| `ml-feature-store-daily` | 23:30 UTC | Did features update? |
| `daily-yesterday-analytics` | 06:30 UTC | Did analytics run? |
| `execute-workflows` | :05 each hour | Are workflows executing? |

### Commands to Run

```bash
# Check scheduler job status
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 \
  --format="table(name,schedule,state,lastAttemptTime)"

# Check recent workflow executions
gcloud logging read 'textPayload=~"workflow" AND textPayload=~"complete"' \
  --project=nba-props-platform --limit=20 --freshness=24h

# Check for errors in the last 24 hours
gcloud logging read 'severity>=ERROR' --project=nba-props-platform \
  --limit=50 --freshness=24h --format="table(timestamp,resource.labels.service_name,textPayload)"
```

---

## Fixed This Session

### BettingPros Brotli Issue ✅

**Root Cause:** BettingPros API returned Brotli-compressed responses, but `brotli` package not installed.

**Fix:** Removed `br` from Accept-Encoding in `scrapers/utils/nba_header_utils.py`

**Commit:** `3f21072 fix(scraper): Remove Brotli from Accept-Encoding for BettingPros`

**Deployed:** Yes, to `nba-phase1-scrapers` Cloud Run service

**Verified:** 87 player props scraped successfully for Jan 10

---

## Phase 5B Grading Backfill Completed ✅

Earlier in this session, the full Phase 5B grading backfill was completed:
- 851 dates processed
- 485,191 predictions graded
- 0 failures

**Fair Comparison Results:**

| System | Picks | Win Rate | MAE |
|--------|-------|----------|-----|
| **catboost_v8** | 47,995 | **74.4%** | **4.00** |
| moving_average_baseline | 45,132 | 59.7% | 5.00 |
| ensemble_v1 | 39,617 | 58.6% | 5.03 |

CatBoost v8 outperforms by 14.7 percentage points.

---

## Recommended Investigation Order

1. **Player Name Matching** (High Priority)
   - Run the investigation queries above
   - Identify the naming format differences
   - Determine if name resolution needs to run or be fixed

2. **Yesterday's Results** (Medium Priority)
   - Verify Jan 9 predictions were graded
   - Check catboost_v8 win rate for Jan 9
   - Ensure grading pipeline is working

3. **Today's Predictions** (Medium Priority)
   - Check if predictions were regenerated after lines came in
   - Verify feature store has today's data
   - Monitor next prediction run

4. **Orchestration Health** (Low Priority)
   - Verify all scheduled jobs ran
   - Check for any errors in logs
   - Ensure pipelines are healthy

---

## Files Modified This Session

| File | Change |
|------|--------|
| `scrapers/utils/nba_header_utils.py` | Removed 'br' from Accept-Encoding |
| `docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md` | Added Phase 5B/5C grading steps |
| `docs/08-projects/current/ml-model-v8-deployment/FAIR-COMPARISON-ANALYSIS.md` | Updated with final results |

---

## Related Documentation

- `docs/09-handoff/2026-01-10-GRADING-BACKFILL-SESSION.md` - Phase 5B grading details
- `docs/08-projects/current/ml-model-v8-deployment/` - ML v8 deployment project
- `docs/02-operations/backfill/runbooks/phase5b-prediction-grading-backfill.md` - Grading runbook

---

## Quick Commands Reference

```bash
# Check today's prediction status
bq query --use_legacy_sql=false 'SELECT system_id, recommendation, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = "2026-01-10" GROUP BY 1,2'

# Check yesterday's grading
bq query --use_legacy_sql=false 'SELECT system_id, COUNTIF(prediction_correct) as wins, COUNT(*) as total FROM nba_predictions.prediction_accuracy WHERE game_date = "2026-01-09" GROUP BY 1'

# Check recent errors
gcloud logging read 'severity>=ERROR' --project=nba-props-platform --limit=20 --freshness=6h

# Trigger prediction workflow manually (if needed)
curl -X POST "https://nba-phase1-scrapers-756957797294.us-west2.run.app/workflow/predictions" -H "Content-Type: application/json" -d '{"date": "2026-01-10"}'
```
