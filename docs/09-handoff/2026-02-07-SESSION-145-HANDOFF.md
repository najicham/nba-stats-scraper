# Session 145 Handoff: Vegas Optional + Deployment Completion

**Date:** 2026-02-07
**Focus:** Make vegas features optional in zero-tolerance, complete Session 144 deployments
**Status:** Vegas optional implemented. Deployments in progress. Backfill running.

## Context

Session 144 found that only 37-45% of feature store records are fully complete despite 100% player coverage. Three root causes: cache timing (FIXED in 144), shot zone gaps (PARTIALLY FIXED in 144), and vegas line absence for ~60% of players (bench players without prop lines).

Session 145 addresses the vegas issue by making vegas features **optional** in zero-tolerance gating.

## What Was Done

### 1. Vegas Features Made Optional (CRITICAL)

**The Problem:** Zero-tolerance blocks predictions when ANY feature defaults. Vegas lines (features 25-27) are unavailable for ~60% of players because sportsbooks don't publish prop lines for bench players. This blocked ~60% of predictions unnecessarily.

**The Fix:** New `FEATURES_OPTIONAL` set (features 25, 26, 27) excluded from zero-tolerance gating. Vegas defaults are still tracked for visibility but don't block predictions.

**Changes across 4 files:**

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | Added `FEATURES_OPTIONAL = set(FEATURES_VEGAS)` |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Added `OPTIONAL_FEATURES`, `required_default_count`, updated `is_quality_ready` and alert levels |
| `predictions/coordinator/quality_gate.py` | Fetches and uses `required_default_count` instead of `default_feature_count` |
| `predictions/worker/worker.py` | Defense-in-depth uses `required_default_count` |

**New BigQuery column:** `required_default_count INT64` in `ml_feature_store_v2` - counts only REQUIRED feature defaults (excludes optional vegas).

**Backwards compatible:** `required_default_count` falls back to `default_feature_count` when NULL (for old records before this column existed).

**Tested:**
- Vegas-only defaults: `default_feature_count=3`, `required_default_count=0`, `is_quality_ready=True`
- Mixed defaults: `default_feature_count=2`, `required_default_count=1`, `is_quality_ready=False`

### 2. Deployments (Session 144 code)

Three deployments kicked off for Session 144 cache miss fix:
- `nba-phase4-precompute-processors` - cache miss fallback
- `nba-phase3-analytics-processors` - timing breakdown
- `nba-phase2-raw-processors` - timing breakdown

**NOTE:** These deployments have the Session 144 code but NOT the Session 145 vegas optional changes. Vegas optional requires a second round of deployments.

### 3. Backfill Progress

2025-26 season `feature_N_source` backfill restarted (failed in Session 144 due to end date in future). Processing ~66 dates.

### 4. Project Docs Updated

Updated `docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md` with Session 144-145 progress, root cause analysis, and remaining work.

## NOT Done - Tasks for Next Session

### Task 1: Deploy Vegas Optional Changes (HIGH PRIORITY)

After Session 144 deployments finish, deploy the Session 145 vegas optional code:

```bash
# Commit first
git add -A && git commit -m "feat: Make vegas features optional in zero-tolerance gating (Session 145)"

# Deploy all affected services
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh prediction-coordinator
./bin/deploy-service.sh prediction-worker
```

### Task 2: Verify Vegas Optional Impact

After deployment, check next day's prediction count:

```sql
-- Before: ~75 predictions/day. After: should be ~150+
SELECT game_date,
  COUNT(*) as total_records,
  COUNTIF(is_quality_ready) as quality_ready,
  COUNTIF(required_default_count = 0) as req_defaults_zero,
  COUNTIF(default_feature_count = 0) as all_defaults_zero,
  ROUND(COUNTIF(is_quality_ready) / COUNT(*) * 100, 1) as pct_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1;
```

### Task 3: Run 2021 Season Backfill

```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31 --skip-preflight
```

### Task 4: Add Scraper Health Monitoring (Vegas Lines)

User requirement: Alert when star players (tier 1-2, >20 PPG) are missing vegas lines. This indicates a scraper issue, not normal bench player absence.

Options:
- Add to quality_scorer.py alerts
- Add to canary monitoring
- Add to `/validate-daily` skill

### Task 5: Fix PlayerDailyCacheProcessor Root Cause

The cache miss fallback is a band-aid. The proper fix:
- **File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- **Current:** Queries `upcoming_player_game_context WHERE game_date = TODAY` → ~175 players
- **Fix:** Also query all active season players (like shot zone processor does) → ~457 players
- **Ref:** Shot zone processor at `data_processors/precompute/player_shot_zone_analysis/` shows the correct approach

## Architecture: How Vegas Optional Works

```
quality_scorer.py                    quality_gate.py / worker.py
┌──────────────────────┐             ┌─────────────────────────┐
│ default_feature_count│─── total ──▸│ Still written to BQ     │
│ = 3 (incl vegas)     │             │ for visibility          │
│                      │             │                         │
│ required_default_cnt │─── gate ──▸│ Used for zero-tolerance │
│ = 0 (excl vegas)     │             │ blocking                │
│                      │             │                         │
│ vegas_default_count  │── monitor ▸│ Scraper health check    │
│ = 3                  │             │ (star player alerts)    │
│                      │             │                         │
│ is_quality_ready     │             │ TRUE (vegas doesn't     │
│ = TRUE               │             │ block predictions)      │
└──────────────────────┘             └─────────────────────────┘
```

## Key Design Decision

**Vegas defaults are VISIBLE but NOT BLOCKING.** The user explicitly wants to know when lines are missing (for scraper debugging), but doesn't want to block predictions when the absence is normal (bench players). The `default_feature_count` still tracks ALL defaults. Only `required_default_count` and `is_quality_ready` exclude optional features.

**No projected lines in the feature vector.** The user prefers clarity: when there's no line, there's no line. Projected lines (if added) go in a separate field, never in the features array.
