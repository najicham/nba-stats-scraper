# Session 100 Handoff - Feature Mismatch Investigation Setup

**Date:** 2026-02-03
**Time:** 6:50 PM UTC (10:50 AM PT)
**Model:** Claude Opus 4.5

---

## Session Summary

Session 100 continued investigation from Session 98 (conversation was lost due to context limit). Documented the critical **feature mismatch issue** where predictions use wrong feature values that don't match the ML Feature Store.

---

## Key Discovery

### The Core Problem

Predictions are using **completely different feature values** than what's stored in `ml_feature_store_v2`:

| Metric | Feature Store | Prediction Used | Difference |
|--------|--------------|-----------------|------------|
| pts_avg_5 | 24.2 | 12.8 | -11.4 |
| pts_avg_10 | 25.9 | 6.4 | -19.5 |
| quality_score | 87.59 | 65.46 | -22.13 |

### Why This Matters

1. Model predicted Lauri Markkanen at 15.3 points instead of ~22-23
2. Vegas line was 26.5 - model incorrectly recommended UNDER
3. This pattern caused 0/7 high-edge hit rate on Feb 2
4. 100% UNDER bias in all predictions

### Critical Finding

The **65.46 quality score does NOT exist in the feature store**. All feature store entries for Feb 3 have quality scores of 71.38, 75.19, 82.73, or 87.59 - never 65.46.

This means the prediction worker is getting features from **somewhere other than the feature store**.

---

## Timeline of Events

```
2026-02-02 22:30:18 UTC - Feature store populated (quality 87.59) ✓
2026-02-02 23:12:42 UTC - Predictions created (quality 65.46) ✗
2026-02-03 09:15:00 UTC - Model revert deployed (Session 97)
2026-02-03 17:45:00 UTC - Feature mismatch discovered
```

---

## What Was Done This Session

### 1. Created Investigation Project

**Location:** `docs/08-projects/current/feature-mismatch-investigation/`

Files created:
- `PROBLEM-DEFINITION.md` - Detailed problem statement with data
- `HANDOFF.md` - Investigation guide for next session

### 2. Verified Current State

| Check | Status |
|-------|--------|
| Model reverted to working version | ✅ |
| All services deployed | ✅ |
| Feature store has correct data | ✅ |
| Predictions use correct features | ❌ **BROKEN** |
| Feb 3 games started | Not yet (all Scheduled) |

### 3. Ruled Out Causes

| Cause | Status | Evidence |
|-------|--------|----------|
| Wrong model | ✅ Fixed | Reverted to working model |
| Feature store empty | ❌ Not the cause | Store has 87.59 quality data |
| Multiple feature versions | ❌ Not the cause | Only one entry per player |

---

## Root Cause Hypotheses

### Most Likely: Coordinator Pre-computes Features

The coordinator (`predictions/coordinator/coordinator.py`, 109KB) might compute features before the feature store is populated, and those computed values are used instead of fresh data.

### Alternative: Stale Cache

The worker's feature cache (5 min TTL) might have served data from before Session 99 fix.

### Alternative: Query Parameter Mismatch

Worker might query with wrong `feature_version` parameter.

---

## Files to Investigate

### Primary
| File | Size | Why |
|------|------|-----|
| `predictions/worker/worker.py` | - | Feature loading at line ~794 |
| `predictions/worker/data_loaders.py` | - | Feature query at line ~839 |
| `predictions/coordinator/coordinator.py` | 109KB | Might have feature computation |
| `predictions/coordinator/player_loader.py` | 66KB | Might pre-load features |

### Supporting
| File | Why |
|------|-----|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | How features are computed |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | 65.46 calculation logic |

---

## Related Handoffs

| Session | Document | Relevance |
|---------|----------|-----------|
| 99 | `2026-02-03-SESSION-99-HANDOFF.md` | Fixed feature quality 65%→85% |
| 98 | `2026-02-03-SESSION-98-HANDOFF.md` | Phase 3 completion issues |
| 97 | `2026-02-03-SESSION-97-HANDOFF.md` | Model revert, quality fields |

---

## Immediate Actions for Next Session

### 1. Priority: Fix Tonight's Predictions

Games are still scheduled. Re-run predictions to verify if issue persists:

```bash
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/trigger" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-03", "force_refresh": true}'
```

Then verify:
```sql
SELECT player_lookup, predicted_points, feature_quality_score,
       JSON_EXTRACT_SCALAR(critical_features, '$.feature_quality_score') as snapshot_quality
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-03' AND system_id = 'catboost_v9'
ORDER BY created_at DESC
LIMIT 5
```

### 2. Priority: Find the Source of 65.46 Quality

Follow investigation guide in `docs/08-projects/current/feature-mismatch-investigation/HANDOFF.md`

---

## Verification Queries

### Check Feature Store (Should show 87.59)
```sql
SELECT player_lookup, feature_quality_score, features[OFFSET(0)] as pts_avg_5
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'laurimarkkanen' AND game_date = '2026-02-03'
```

### Check Prediction (Currently shows 65.46)
```sql
SELECT player_lookup, predicted_points, critical_features
FROM nba_predictions.player_prop_predictions
WHERE player_lookup = 'laurimarkkanen' AND game_date = '2026-02-03'
  AND system_id = 'catboost_v9'
```

---

## Session 101 Priorities

1. **[P0]** Re-run predictions for Feb 3 if games haven't started
2. **[P0]** Find source of 65.46 quality score / wrong features
3. **[P1]** Fix the code path that's computing/loading wrong features
4. **[P1]** Deploy fix
5. **[P2]** Add validation to detect feature mismatches

---

## Files Changed This Session

| File | Change |
|------|--------|
| `docs/08-projects/current/feature-mismatch-investigation/PROBLEM-DEFINITION.md` | Created - problem documentation |
| `docs/08-projects/current/feature-mismatch-investigation/HANDOFF.md` | Created - investigation guide |
| `docs/09-handoff/2026-02-03-SESSION-100-HANDOFF.md` | Created - this file |

---

## Environment Status

| Item | Status |
|------|--------|
| prediction-worker | Rev 00092-z47 (model reverted) |
| prediction-coordinator | Up to date |
| nba-phase3-analytics-processors | Up to date |
| nba-phase4-precompute-processors | Up to date |
| Feb 3 games | 10 games, all Scheduled |

---

**End of Session 100**
