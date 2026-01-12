# Session 12 Handoff: Pipeline Gaps & Performance Analysis

**Date:** January 12, 2026
**Status:** REQUIRES ACTION - Pipeline gaps and investigations needed
**Priority:** P1

---

## Quick Start for New Session

```bash
# 1. Read these documents first:
#    - This handoff (you're reading it)
#    - Performance guide: docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md
#    - Pipeline reliability: docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md

# 2. Check current pipeline status:
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(*) as records
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date ORDER BY cache_date"

# 3. Continue from ACTION ITEMS below
```

---

## Executive Summary

### Season Performance (CatBoost V8)

| Metric | Value | Notes |
|--------|-------|-------|
| Total Picks (with lines) | 7,688 | Season to date |
| **Win Rate** | **81.8%** | Excellent |
| Edge over breakeven | +29.4% | Very profitable |
| MAE | 6.34 | Mean absolute error |

### CRITICAL: OVER vs UNDER Split

| Recommendation | Picks | Win Rate | Avg Error |
|----------------|-------|----------|-----------|
| **UNDER** | 5,436 | **94.3%** | 3.69 |
| OVER | 2,252 | 51.6% | 12.74 |

**⚠️ OVER picks are barely better than random (51.6%)** - This needs investigation!

---

## Pipeline Status (Last 14 Days)

### Complete Pipeline View

| Date | Box Scores | Props | Analytics | Phase 4 | Predictions | Graded | Issues |
|------|------------|-------|-----------|---------|-------------|--------|--------|
| Dec 29 | 387 | 892 | 285 | 215 | 380 (183) | 264 | ✅ OK |
| Dec 30 | 141 | 350 | 131 | 75 | 113 (0) | 87 | ⚠️ No prop lines |
| Dec 31 | 316 | 1131 | 224 | 165 | 308 (141) | 224 | ✅ OK |
| Jan 01 | 105 | 1590 | 90 | 66 | 133 (0) | 90 | ⚠️ No prop lines |
| Jan 02 | 282 | 828 | 209 | 190 | 341 (154) | 209 | ✅ OK |
| Jan 03 | 210 | 2478 | 167 | 127 | 253 (133) | 167 | ✅ OK |
| Jan 04 | 282 | 2733 | 194 | 121 | 255 (118) | 169 | ✅ OK |
| Jan 05 | 209 | 1896 | 169 | 114 | 240 (121) | 169 | ✅ OK |
| Jan 06 | 175 | 1536 | 129 | 84 | 189 (0) | 129 | ⚠️ No prop lines |
| Jan 07 | 0 | 2859 | 259 | 183 | 263 (183) | 259 | ✅ OK (box scores missing in raw) |
| **Jan 08** | 106 | 1005 | 60 | **0** | **0** | **0** | ❌ **PHASE 4 FAILED** |
| Jan 09 | 347 | 3204 | 416 | 57 | **0** | **0** | ❌ **PHASE 4 PARTIAL** |
| Jan 10 | 0 | 2139 | 136 | 103 | 68 (32) | 66 | ⚠️ Partial |
| **Jan 11** | 313 | 3797 | 299 | **0** | **3** | 3 | ❌ **PHASE 4 FAILED** |
| Jan 12 | 0 | 0 | 0 | 0 | 0 | 0 | Today |

*Predictions column shows: total (with prop lines)*

---

## ACTION ITEMS

### 1. 🔴 CRITICAL: Fix Pipeline Gaps (Jan 8, 9, 11)

Phase 4 (player_daily_cache) failed for these dates, which means no predictions were generated.

```bash
# Run Phase 4 backfill for missing dates
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2026-01-08 --end-date 2026-01-11 --skip-preflight

# Then run predictions backfill
python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2026-01-08 --end-date 2026-01-11 --skip-preflight

# Then run grading
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-08 --end-date 2026-01-11
```

### 2. 🟡 INVESTIGATE: Prop Line Matching Failures

These dates have predictions but 0% prop line matching:
- Dec 30
- Jan 01
- Jan 06

Props exist in `odds_api_player_points_props` but weren't matched to predictions. This affects grading accuracy.

```bash
# Check if props were loaded after predictions were generated
bq query --use_legacy_sql=false "
SELECT
  game_date,
  MIN(scraped_at) as earliest_prop,
  MAX(scraped_at) as latest_prop
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date IN ('2025-12-30', '2026-01-01', '2026-01-06')
GROUP BY game_date"
```

### 3. 🟡 INVESTIGATE: OVER Underperformance

OVER picks are at 51.6% win rate vs 94.3% for UNDER. This is a significant discrepancy that warrants investigation.

**Possible causes:**
1. Model bias towards conservative (lower) predictions
2. Market inefficiency in UNDER lines
3. Calibration issue in confidence scoring for OVER picks

**Analysis to run:**
```sql
-- Check if OVER picks have different confidence distribution
SELECT
  recommendation,
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  ROUND(STDDEV(confidence_score), 3) as stddev_confidence,
  COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND has_prop_line = TRUE
GROUP BY recommendation
```

### 4. 🟢 LOW: Investigate Pipeline Root Cause

Why is Phase 4 failing on some days? Check:
- Cloud Scheduler logs for the Phase 4 trigger
- Cloud Run logs for the precompute processor
- Whether there's a pattern (day of week, game count, etc.)

```bash
# Check Cloud Function logs
gcloud functions logs read nba-phase4-precompute --limit=100

# Check scheduler status
gcloud scheduler jobs describe phase4-daily --location=us-west2
```

---

## What Was Completed This Session

### Gap Recovery (Oct 22 - Nov 13)

| Task | Status | Details |
|------|--------|---------|
| Historical props loaded | ✅ | 23 dates, 10,189 records |
| Phase 4 reprocessed | ✅ | 17 dates (Nov 4+) |
| Predictions available | ✅ | 9 dates, 2,212 predictions |
| Grading complete | ✅ | All available predictions graded |

**Note:** Oct 22 - Nov 3 is bootstrap period (not enough games for Phase 4).

### Commits Made

```
2198ff9 - docs(handoff): Complete Oct 22 - Nov 13 gap recovery
57c16da - feat(backfill): Add --historical flag to props backfill script
```

---

## Key Files & Documentation

### Performance Analysis
- `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md` - How to analyze performance
- `docs/08-projects/current/ml-model-v8-deployment/FAIR-COMPARISON-ANALYSIS.md` - System comparison

### Pipeline Reliability
- `docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md` - Known issues
- `docs/08-projects/current/pipeline-reliability-improvements/2026-01-11-GAP-RECOVERY-PLAN.md` - Gap recovery details

### Backfill Scripts
- `scripts/backfill_odds_api_props.py` - Props backfill (now with --historical flag)
- `backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py` - Phase 4
- `backfill_jobs/prediction/player_prop_predictions_backfill.py` - Predictions
- `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py` - Grading

### Previous Handoffs
- `docs/09-handoff/2026-01-11-SESSION-11-GAP-RECOVERY.md` - Gap recovery (completed)

---

## Summary of Open Issues

| Priority | Issue | Action |
|----------|-------|--------|
| 🔴 P0 | Jan 8, 9, 11 missing predictions | Run backfills |
| 🟡 P1 | OVER 51.6% win rate | Investigate |
| 🟡 P1 | Dec 30, Jan 1, Jan 6 no prop lines | Investigate timing |
| 🟢 P2 | Pipeline failures root cause | Check logs |

---

## Performance Quick Reference

```bash
# Overall season performance
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE"

# By recommendation
bq query --use_legacy_sql=false "
SELECT recommendation, COUNT(*) as picks,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2025-10-01' AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER') AND has_prop_line = TRUE
GROUP BY recommendation"
```
