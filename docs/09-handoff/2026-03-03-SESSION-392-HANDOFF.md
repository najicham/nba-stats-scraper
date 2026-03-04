# Session 392 Handoff — BQ Correlated Subquery Fix + HOME OVER Block Removal

**Date:** 2026-03-03
**Status:** Fix pushed, builds deploying, re-export NOT yet triggered

## Critical Fix: Signal Best Bets Export Broken

Session 391's `UNION DISTINCT SELECT model_id FROM UNNEST(...)` in the `disabled_models` CTE caused BigQuery's query planner to fail with "Correlated subqueries that reference other tables are not supported." This broke ALL signal-best-bets exports — 0 picks since Session 391 deployed.

**Root cause:** The `UNNEST` inside a CTE with `UNION DISTINCT`, combined with the `model_hr` nested subquery and the full 10-table join chain, exceeded BQ's de-correlation capacity.

**Fix (committed `bab62268`, pushed):** Replace `UNION DISTINCT + UNNEST` with `OR model_id IN ('catboost_v12', 'catboost_v9')` in `supplemental_data.py` (both multi_model and single_model paths).

### After Build Completes

```bash
# 1. Verify phase6-export build succeeded
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5 --format="table(id,status,substitutions.TRIGGER_NAME)"

# 2. Trigger re-export for today
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "2026-03-03"}'

# 3. Wait 60s, verify picks exist
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT COUNT(*) as picks FROM nba_predictions.signal_best_bets_picks WHERE game_date = '2026-03-03'"

# 4. Check logs for any remaining errors
gcloud functions logs read phase6-export --region=us-west2 --project=nba-props-platform --limit=10
```

## HOME OVER Block Removed

The HOME OVER block added in Session 390 (43.8% HR, N=16) was removed because:
1. **N=16 was contaminated by disabled model picks** — Session 391 found 6/10 losses came from dead models
2. **Combined with AWAY block, it blocked ALL OVER picks** from v12_noveg/v9 families (HOME blocked by home_over, AWAY blocked by away_noveg)
3. Clean data needed before reimplementing

Change in `aggregator.py`: `ALGORITHM_VERSION = 'v392_disabled_model_drain_fix'`, home_over filter removed from filter_counts dict and filter loop.

## Other Session 391 Fixes Already Deployed

These were committed + pushed by Session 391 (`b7b171ea`) and are live:
- **supplemental_data.py**: Disabled model exclusion from per-player selection (the UNNEST version that broke — now fixed)
- **aggregator.py**: Filter dominance WARNING when any filter >50% rejection
- **player_blacklist.py**: Excludes disabled/blocked models from HR calculation
- **worker.py**: `ENABLE_LEGACY_V9`/`ENABLE_LEGACY_V12` env vars (default false)
- **signal_best_bets_exporter.py**: Filter audit trail to `best_bets_filter_audit`
- **daily_health_check**: Model registry consistency check
- **decay_detection**: Consecutive drought detection
- **registry.py**: volatile_scoring_over DISABLED (50% HR live)
- **signal_health.py**: volatile_scoring_over removed from ACTIVE_SIGNALS

## Key Findings from Analysis

### Blacklist Inflated by Disabled Models
With disabled models excluded from HR calculation, **ZERO players** qualify for blacklisting (<40% HR on 8+ edge-3+ picks from enabled models). The 113-player blacklist was entirely caused by disabled model predictions.

### Fleet Status
- 13 enabled models, newest 4 days stale (Feb 27), oldest 22 days
- V16 families lead at 66.7% HR, lowest MAE (3.88-4.09)
- LightGBM weakest (56% HR, 6.30 MAE) — `lgbm_v12_noveg_train1102_0209` deactivated via `deactivate_model.py`
- 2,283 catboost_v12 zombie predictions deactivated via BQ UPDATE

### Signals
- `fast_pace_over` and `self_creation_over` missing from `signal_health_daily` — code fixes exist but weren't deployed until Session 391 push. Now deployed via `ml/signals/**` trigger.
- `volatile_scoring_over` disabled — 50% HR (4-4 in 21 days)
- Signal count still important: SC≥5 = 85.7% vs SC=3 = 50%

### League Trends
- Blowout rate doubled: 15% (Jan) → 32% (late Feb). Starters sit in Q4 → kills OVER predictions
- Scoring averages flat (~10.5 ppg), pace stable (~100 poss) — not a league-wide scoring change
- OVER collapse is structural (blowouts + minutes unpredictability), not model miscalibration

## Remaining Items (Next Session)

1. **Verify re-export works** — trigger after build completes, confirm picks > 0
2. **Retrain V16 on fresh 56-day window** — best-performing family needs fresh data
3. **Evaluate LightGBM fleet** — consider disabling remaining lgbm models (56% HR)
4. **Monitor signal firing** — fast_pace_over and self_creation_over should appear in signal_health_daily within 24h
5. **Blowout-aware signal** — explore minutes-in-blowout feature or home-blowout filter for OVER picks
6. **Signal count floor analysis** — SC≥5 at 85.7% suggests raising floor may help, but volume drops
