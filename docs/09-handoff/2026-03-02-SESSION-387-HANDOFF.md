# Session 387 Handoff — March 2, 2026

## Summary

Fleet triage, signal revival, and forward-looking automation plan. Fixed 2 high-value dead signals, cleaned fleet of 4 inconsistent models, fixed data quality issues, and designed a 3-tier automation plan for fleet lifecycle management.

## What Changed

### Critical Signal Fixes (DEPLOYED)
1. **`line_rising_over` revived** (96.6% backtest HR): `prev_prop_lines` CTE in `supplemental_data.py` was querying dead champion model `catboost_v12` (0 predictions). Removed model-specific filter — prop lines are bookmaker lines, not model-dependent. This also fixes `prop_line_delta`-based filters (line_jumped_under, line_dropped_under, line_dropped_over) which were all silently broken.

2. **`fast_pace_over` revived** (81.5% backtest HR): Threshold was 102.0 but `feature_18` (opponent_pace) is normalized 0-1 in the feature store. Changed to 0.75 (≈ top 25% of teams by pace, maps to raw pace ~102+).

3. **`model_health` removed from `ACTIVE_SIGNALS`**: Intentionally excluded from `pick_signal_tags` at the annotator level. Was never going to appear in `signal_health_daily`.

### Data Quality Fixes
4. **Edge storage**: UNDER picks stored with negative signed edge after Feb 22 code change. Fixed both BQ write and JSON export to use `abs(edge)`. Backfilled 10 historical rows.

5. **`deactivate_model.py`**: Referenced non-existent `updated_at` column in `model_registry`. Fixed.

### Fleet Cleanup
6. **4 models deactivated** (status set to `blocked`):
   - `catboost_v12_noveg_q45_train1102_0125` (was `enabled=False, status=active`)
   - `catboost_v12_noveg_q55_tw_train0105_0215` (was `enabled=False, status=shadow`)
   - `catboost_v9_q45_train1102_0125` (was `enabled=False, status=active`)
   - `catboost_v12_noveg_mae_train0104_0215` (was `enabled=False, status=disabled`)

   Remaining 3 from Session 386 recommendation were already blocked.

### Infrastructure
7. **Paused `nba-env-var-check-prod`** scheduler job (was firing every 5 min against non-existent endpoint).
8. **Deployed `nba-grading-service`** (was 1 commit behind).
9. **`best_bets_all_exporter`**: Added `games_scheduled` field for frontend context.

## Deployments

| Service | Method | Status |
|---------|--------|--------|
| `nba-grading-service` | Manual deploy | COMPLETE |
| `prediction-coordinator` | Manual deploy (ml/signals changes) | IN PROGRESS |
| `phase6-export` | Cloud Build auto-deploy | IN PROGRESS |
| `post-grading-export` | Cloud Build auto-deploy | IN PROGRESS |
| `live-export` | Cloud Build auto-deploy | IN PROGRESS |

## What Was NOT Done

- **self-heal-predictions timeout**: Function is at Gen1 max (540s). Needs code optimization or Gen2 migration. Low priority.
- **Signal firing canary**: Designed but not implemented yet. See plan doc.
- **Auto-disable BLOCKED models**: Designed but not implemented yet. See plan doc.

## Forward-Looking Plan

See `docs/08-projects/current/fleet-lifecycle-automation/00-PLAN.md`

Three tiers:
1. **Auto-disable BLOCKED shadow models** — extend decay_detection CF
2. **Signal firing canary** — detect when signals stop firing (would have caught both dead signals)
3. **Registry hygiene automation** — weekly cleanup of inconsistent states

## Active Fleet (13 enabled models)

```
catboost_v12_noveg_60d_vw025_train1222_0219
catboost_v12_noveg_train0103_0227
catboost_v12_noveg_train0108_0215
catboost_v12_noveg_train0110_0220
catboost_v12_noveg_train1222_0214
catboost_v12_noveg_train1228_0222       (NEW - 68.8% backtest)
catboost_v12_train0104_0215
catboost_v12_train0104_0222
catboost_v12_train1228_0222             (NEW - 76.9% backtest)
catboost_v16_noveg_rec14_train1201_0215
catboost_v16_noveg_train1201_0215
lgbm_v12_noveg_train0103_0227
lgbm_v12_noveg_train1102_0209
```

## Verify on Next Game Day

1. `line_rising_over` and `fast_pace_over` appearing in pick signal tags
2. `prop_line_delta` being populated (was NULL due to champion dependency)
3. Edge values stored as positive in `signal_best_bets_picks`
4. Session 386 prevention system: `system_id` populated in `best_bets_published_picks`
5. No picks from disabled models in signal best bets

## Key Insight

**Signals that depend on external state can silently die.** `line_rising_over` depended on the champion model having predictions. `fast_pace_over` depended on a specific normalization scale. Neither had monitoring for "signal stopped firing." The signal firing canary (Tier 2 of the automation plan) would catch this class of failures immediately.
