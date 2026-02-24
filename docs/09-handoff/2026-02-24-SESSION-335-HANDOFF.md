# Session 335 Handoff — Hardening Complete, Edge-5+ Health Check, Multi-Model Analysis

**Date:** 2026-02-24
**Focus:** Completed all 4 remaining hardening items from Sessions 332-334, deep-dived multi-model filter architecture, added edge-5+ health monitoring
**Status:** COMPLETE — pushed to main, all builds SUCCESS

## Current System State

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim, promoted Session 332) |
| Champion State | HEALTHY — 59.6% HR 7d (N=47) |
| Champion Edge 5+ | **LOSING — 41.7% HR 14d (N=12, -16.6pp premium)** |
| Best Bets 7d | **7-3 (70.0% HR)** |
| Best Bets 30d | **34-16 (68.0% HR)** |
| Shadow Models | 7 enabled families, 4 freshly retrained (Jan 4–Feb 15) |
| Deployment Drift | ZERO — all 8 builds SUCCESS after push |
| Pre-commit Hooks | **18 hooks** (added `validate-auto-deploy-consistency`) |

## What This Session Did

### 1. Completed All 4 Remaining Hardening Items

All LOW-priority items from the Session 334/335 backlog — now shipped:

| Item | File(s) | Change |
|------|---------|--------|
| Post-retrain registry check | `bin/retrain.sh` | Auto-runs `validate_model_registry.py --skip-gcs` after training |
| Hardcoded pattern extraction | `shared/config/cross_model_subsets.py`, `ml/signals/supplemental_data.py` | New `build_noveg_mae_sql_filter()` helper replaces hardcoded `LIKE 'catboost_v12_noveg%'` |
| CompletionTracker improvements | `shared/utils/completion_tracker.py` | Thread-safe lazy init (double-check locking), 10s check interval (was 30s), circuit breaker (5 failures → 5min backoff) |
| Auto-deploy consistency hook | `.pre-commit-hooks/validate_auto_deploy_consistency.py`, `.pre-commit-config.yaml` | Validates Cloud Run services in drift check have auto-deploy coverage |

**Commit:** `070657bf` — all 69 existing unit tests pass, all verifications pass.

### 2. Deep-Dived Multi-Model Filter Architecture

Researched how filters work when multiple models exist in the same family. Key findings:

- **Production uses `multi_model=True`** — all families compete per player-game
- **Selection is purely edge-based**: `ORDER BY ABS(edge) DESC, system_id DESC`
- **Filters apply AFTER selection**, not per-model
- **No health weighting exists** — a BLOCKED model can win selection if it has higher edge
- **Champion V12 only contributed 5 of 104 best-bets picks (4.8%) over 60 days** — shadow models do the heavy lifting

### 3. Discovered Critical Edge-5+ Health Divergence

**Edge-5+ HR is NOT decoupled from overall decay — it's often WORSE:**

| Model | Overall State | Overall HR 7d | Edge 5+ HR 14d | Premium |
|-------|--------------|---------------|----------------|---------|
| v12_noveg_q45_0125 | BLOCKED | 46.9% | 83.3% (N=6) | +36.4pp |
| v9_low_vegas_0205 | HEALTHY | 59.5% | 60.0% (N=15) | +0.5pp |
| **catboost_v12** | **HEALTHY** | **58.3%** | **41.7% (N=12)** | **-16.6pp** |
| catboost_v9 | BLOCKED | 47.1% | 41.7% (N=12) | -5.4pp |
| v9_q43_0125 | BLOCKED | 43.8% | 40.0% (N=10) | -3.8pp |
| v12_q43_1225_0205 | BLOCKED | 13.6% | 16.7% (N=6) | +3.1pp |

**V9 weekly edge 5+ trend shows complete collapse:** 84.6% (Jan 19) → 30.2% (Feb 2) → 28.6% (Feb 16)

### 4. Added Edge-5+ Health Check to Daily Steering

New **Step 1.5** in `/daily-steering` skill shows per-model edge-5+ HR alongside overall health. Surfaces models that are HEALTHY overall but LOSING at high edge (like V12 champion at 41.7%).

Also fixed Step 2.5 bugs: `predicted_value`/`actual_value` → `predicted_points`/`actual_points`, `catboost_v9` → `catboost_v12`.

### 5. Decision: Don't Add Health-Weighted Selection

After thorough analysis, decided **against** health-weighted model selection:
- Session 323 replay proved blocking beats oracle selection (29.9% vs 17.7% ROI)
- V9+V12 agreement is ANTI-correlated with winning (33.3% HR when both agree OVER)
- "Two-stage pipeline" is a documented dead end
- All predictions are already graded in `prediction_accuracy` — shadow monitoring is free

**Instead:** Monitor edge-5+ health daily. If a model is LOSING at edge 5+ AND has a replacement in the same family, consider excluding it from multi-model selection. But this should be a manual decision, not automated.

## Priority 1 (Next Session): Verify Fresh Models Producing Predictions

The 4 fresh models registered Feb 23 should be generating predictions for today's 11-game slate:

```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) as preds
   FROM nba_predictions.player_prop_predictions
   WHERE game_date >= '2026-02-24'
     AND system_id LIKE '%train0104_0215%'
   GROUP BY 1 ORDER BY 1"
```

## Priority 2: Monitor V9 in Best Bets

V9 is BLOCKED overall AND LOSING at edge 5+ (41.7%, N=12 over 14d). It still contributed 66% of best bets picks last 30 days. The fresh retrains should naturally outcompete it through higher edge, but monitor:

```bash
# V9's contribution to best bets this week
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-02-24'
GROUP BY 1 ORDER BY 2 DESC"
```

If V9 still dominates picks AND its edge-5+ HR stays below 52.4%, consider manual exclusion from the multi-model query.

## Priority 3: Standard Daily Checks

```bash
/daily-steering           # Now includes edge-5+ health section
/validate-daily
./bin/check-deployment-drift.sh --verbose
```

## Files Changed This Session

| File | Change |
|------|--------|
| `bin/retrain.sh` | Post-retrain registry validation block |
| `shared/config/cross_model_subsets.py` | New `build_noveg_mae_sql_filter()` helper |
| `ml/signals/supplemental_data.py` | Replaced hardcoded v12_noveg pattern with helper |
| `shared/utils/completion_tracker.py` | Thread-safe init, 10s interval, circuit breaker |
| `.pre-commit-hooks/validate_auto_deploy_consistency.py` | NEW — drift/deploy consistency check |
| `.pre-commit-config.yaml` | Added validate-auto-deploy-consistency hook |
| `.claude/skills/daily-steering/SKILL.md` | Added Step 1.5 edge-5+ health, fixed Step 2.5 bugs |

## Key Insights for Future Sessions

1. **Edge magnitude ≠ prediction quality.** A model can produce high-edge picks that lose money. The edge-5+ premium can be negative.
2. **Multi-model selection is edge-only.** No health, no accuracy, no recency weighting. This is by design (Session 323 validated simplicity beats sophistication).
3. **Shadow monitoring is free.** `prediction_accuracy` grades ALL predictions from ALL models. No new infrastructure needed to check any model's performance at any edge threshold.
4. **Best bets filters provide partial protection.** V9 best-bets HR (62.5% Feb 2 week) was much higher than V9 raw edge-5+ HR (30.2%). But the gap is closing as decay deepens.
5. **The system may self-correct.** Fresh retrains should produce competitive edges and naturally displace decaying models in multi-model selection.
