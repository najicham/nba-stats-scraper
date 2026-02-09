# Session 171 Handoff -- Pipeline Throughput & Reliability Fixes

**Date:** 2026-02-09
**Duration:** Full session
**Commits:** 2 (75c6218c, 6e2b3900)

## Executive Summary

Session 171 fixed 3 pipeline throughput/reliability issues: same-day BACKFILL blocking, excessive publish delay (45s to 9s), and stale Pub/Sub message infinite retries. Also added `PUBLISH_METRICS` structured logging and stale message ACKing for past-date failures across 3 worker code paths.

## What Was Done

### Code Changes

| Change | File | Commit | Risk |
|--------|------|--------|------|
| BACKFILL date guard `>=` changed to `>` | `predictions/coordinator/coordinator.py:1218` | `75c6218c` | LOW |
| Publish delay 0.1s changed to 0.02s (5x faster) | `predictions/coordinator/coordinator.py:3288` | `75c6218c` | LOW |
| Added `invalid_features`, `quality_too_low` to PERMANENT_SKIP_REASONS | `predictions/worker/worker.py:176-177` | `75c6218c` | LOW |
| Stale message ACK for line quality validation (past dates) | `predictions/worker/worker.py:809-816` | `75c6218c` | LOW |
| Stale message ACK for general exceptions (>1 day old) | `predictions/worker/worker.py:955-965` | `75c6218c` | LOW |
| PUBLISH_METRICS structured logging (duration, rate, batch) | `predictions/coordinator/coordinator.py:3254,3304-3308` | `6e2b3900` | LOW |
| Stale message ACK for transient failures (past dates) | `predictions/worker/worker.py:852-859` | `6e2b3900` | LOW |

### Deployment

- Both commits pushed to `main`
- Cloud Build auto-deploy triggered for prediction-coordinator and prediction-worker
- No manual deployment needed

## Verification Status

| Item | Status | Notes |
|------|--------|-------|
| Feb 9 BACKFILL | **Pending** | Needs re-trigger after deploy completes (same-day guard now fixed) |
| Feb 8 Grading | **Pending** | Games are Final, needs grading trigger |
| Publish metrics | **Pending** | Will see `PUBLISH_METRICS` in coordinator logs after next batch |
| Stale message cleanup | **Pending** | Will see `STALE_MESSAGE` in worker logs as Feb 6/7 messages get ACKed |

## Hit Rate Investigation (from Session 170 queries)

### Edge 3+ Hit Rate by Week

| Week | Edge 3+ HR | Sample | avg_pvl |
|------|-----------|--------|---------|
| Jan 11 | **71.7%** | 127 | +0.95 |
| Jan 18 | **66.7%** | 110 | -0.05 |
| Jan 25 | **55.4%** | 98 | -0.20 |
| Feb 1 | **48.1%** | 81 | -0.01 |

### Investigation Findings

| Hypothesis | Verdict | Evidence |
|-----------|---------|----------|
| Market sharpening | **RULED OUT** | Vegas miss from line stable across weeks |
| Model MAE degradation | **Concerning** | MAE 4.64 (Jan) to 5.40 (Feb) -- needs monitoring |
| OVER/UNDER asymmetry | **Confirmed** | OVER picks: 57.1% (profitable), UNDER picks: 48.4% (losing) |
| Signal dead | **No** | Feb 7 bounced back to 66.7% -- signal still present |

### Key Takeaway

The model is not broken -- OVER picks remain profitable. UNDER bias from Sessions 168-170 bugs contaminated some grading data. Clean BACKFILL predictions with fixed Vegas pipeline should show better numbers. If hit rate stays below 55% with clean data, a retrain is warranted.

## OddsAPI Investigation

| Date | OddsAPI Line % | Notes |
|------|---------------|-------|
| Feb 8 | **83%** | Healthy -- most lines sourced from OddsAPI |
| Feb 9 | **18%** | Anomalous -- only 18% despite 131 players having DK data in BigQuery |

Root cause of Feb 9 OddsAPI drop still unknown. Possible causes:
- Query timeout (30s per player, sequential)
- Timing mismatch between scrape and prediction run
- OddsAPI data present in BQ but query filter mismatch

## Current State

### Production
- **Model:** `catboost_v9_33features_20260201_011018` (SHA: `5b3a187b`)
- **Deployed commits:** `75c6218c`, `6e2b3900`
- **Multi-line:** Disabled (Session 170)
- **Vegas pipeline:** Fixed (Sessions 168-170)

### Backfill/Grading Status

| Date | Backfill | Grading | avg_pvl | Notes |
|------|----------|---------|---------|-------|
| Feb 4 | Complete | Needs re-grade | -0.24 | Backfilled in Session 170 |
| Feb 5 | Complete | Graded | -0.11 | |
| Feb 6 | Complete | Graded | -0.15 | |
| Feb 7 | Complete | Graded | -0.03 | |
| Feb 8 | Complete | **Not graded** | 0.00 | 53 active preds, games Final |
| Feb 9 | **Pending** | N/A | TBD | Same-day guard now fixed, needs re-trigger |

---

## NEXT SESSION PROMPT

Copy this into the next session:

---

### Session 172 -- Verify All Fixes + Grade + OddsAPI Investigation

**Context:** Session 171 fixed pipeline throughput (5x publish speedup) and reliability (stale message ACKing, same-day BACKFILL). Session 170 fixed multi-line dedup bug and Vegas line pipeline. All deployed via Cloud Build.

**Read:** `docs/09-handoff/2026-02-09-SESSION-171-HANDOFF.md`

### P0: Verify Feb 10 FIRST-run predictions with all fixes

This is the first FIRST-run with ALL fixes deployed (multi-line disabled + Vegas recovery + fresh base_line + faster publish + stale message ACKing). Check:

```sql
-- After Feb 10 FIRST run (~6 AM ET):
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as vegas_source
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1, 6;
```

**Target:** avg_pvl within +/-1.5, OVER/UNDER balance >25% each direction, vegas_source NOT null.

### P1: Grade Feb 8, re-trigger and grade Feb 9

```sql
-- Check if Feb 8 is graded
SELECT game_date, COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-08', '2026-02-09')
GROUP BY 1;

-- Check Feb 9 backfill status (should work now with same-day guard fix)
SELECT game_date, prediction_run_mode, is_active, COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09'
GROUP BY 1, 2, 3;
```

If Feb 9 BACKFILL missing:
```
POST /start {"game_date":"2026-02-09","prediction_run_mode":"BACKFILL"}
```

### P2: Investigate OddsAPI line matching failure

Feb 9 had only 18% OddsAPI lines vs 83% on Feb 8, despite 131 players having DraftKings data in BigQuery. Investigate:

```sql
-- Check raw OddsAPI data availability for Feb 9
SELECT game_date, COUNT(DISTINCT player_name) as players_with_odds
FROM nba_raw.odds_api_player_props
WHERE game_date = '2026-02-09' AND bookmaker = 'draftkings'
GROUP BY 1;

-- Compare line sources Feb 8 vs Feb 9
SELECT game_date,
  JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as vegas_source,
  COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date IN ('2026-02-08', '2026-02-09')
  AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
```

- Check coordinator logs for line query timeouts
- Add logging to `_query_actual_betting_line` if needed
- Consider batching line queries instead of per-player sequential

### P3: Hit rate investigation -- consider model retrain

Edge 3+ hit rate declined from 71.7% to 48.1% over 4 weeks. Now that multi-line and Vegas bugs are fixed, re-evaluate with clean BACKFILL predictions:

```sql
SELECT
  DATE_TRUNC(pa.game_date, WEEK) as week,
  COUNT(*) as graded,
  COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
  ON pa.player_lookup = p.player_lookup AND pa.game_date = p.game_date AND pa.system_id = p.system_id
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= '2026-01-12'
  AND pa.actual_points IS NOT NULL
  AND pa.line_value IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND p.is_active = TRUE
  AND p.prediction_run_mode = 'BACKFILL'
GROUP BY 1
ORDER BY 1;
```

If still declining with clean predictions, consider `/model-experiment` with extended training window through late January.

### P4: Wire up remaining consolidation metrics

Batch consolidation metrics exist but are not wired up. Check `predictions/coordinator/` for metric functions that are defined but not called. Low effort, high observability value.

### P5: Check STALE_MESSAGE and PUBLISH_METRICS in Cloud Logging

```bash
# Verify stale messages being cleaned up
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"STALE_MESSAGE"' \
  --limit=10 --freshness=24h --project=nba-props-platform

# Verify publish metrics appearing
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"PUBLISH_METRICS"' \
  --limit=5 --freshness=24h --project=nba-props-platform
```

---
