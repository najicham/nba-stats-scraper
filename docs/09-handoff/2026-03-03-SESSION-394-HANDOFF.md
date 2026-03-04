# Session 394 Handoff — Model Evaluation & Selection

**Date:** 2026-03-03
**Focus:** Research + tooling for model evaluation, selection strategy, and fleet optimization

## What Was Done

### Tools Built (Priority 1)
1. **`bin/simulate_best_bets.py`** — Simulates any model through the full best bets pipeline (filters + signals + ranking). Supports single-model, multi-model, comparison mode with bootstrap significance testing. The most important missing tool.
2. **`bin/bootstrap_hr.py`** — Statistical significance utility. Bootstrap CI, z-test, and power analysis for HR comparisons.
3. **Training window sweep templates** in `ml/experiments/grid_search_weights.py` — `training_window_sweep` (V12) and `training_window_v16` (V16) templates sweep 28-70 day windows automatically.

### Analysis Completed (Priority 2)
4. **Edge calibration (Q7):** OVER is monotonically calibrated (56%→69%). UNDER breaks at 10+ (58.4%). Models disagree wildly on what edge means (17%-82% HR at same band).
5. **Prediction correlation (Q8):** 12 enabled models are functionally 2 (11 CatBoost clones at r>0.97 + 1 LightGBM at r≈0.95). Fleet provides near-zero diversity.
6. **SC=3 analysis:** SC=3 OVER is a net loser (45.5% HR, -1.6 units). SC=3 UNDER is profitable (57.9%, +4.4 units). Blocking SC=3 OVER adds +1.6 units P&L.
7. **Filter temporal audit:** `best_bets_filter_audit` only has 1 day — need 30+ days for temporal analysis.

### Filter Change Implemented
8. **SC=3 OVER block** deployed in `aggregator.py` — blocks ALL OVER picks with SC=3. Algorithm version: `v394_sc3_over_block`. Expected impact: +1.6 units P&L, 11 fewer losing picks over 3 months.

## Key Findings

### The Fleet Diversity Problem
The 12-model fleet is an illusion. 11 CatBoost models produce r>0.97 correlated predictions and agree on direction 93-100% of the time. The single LightGBM model is the only genuine diversifier at r≈0.95. Historical models like `zone_matchup_v1` (r=0.42) had real diversity but are disabled.

**Recommendation:** Prune to 4-5 models (2-3 freshest CatBoost, 1 V16, 1 LightGBM). To get real diversity, need fundamentally different architectures/features, not retrains of the same model.

### Edge Calibration Is Direction-Dependent
OVER edge is a reliable quality signal (monotonically calibrated). UNDER edge breaks at 10+ (overconfident). All models' edge values mean different things — raw edge comparison across models is meaningless.

### Shadow Monitoring
Recommended **Option B (Post-Hoc Simulation)** using the new `simulate_best_bets.py`. Zero compute cost, can run on-demand. Option A (full shadow pipeline) is overkill when the fleet is 11 near-identical models.

## Files Changed
- `bin/simulate_best_bets.py` — NEW: Best bets simulation tool
- `bin/bootstrap_hr.py` — NEW: Statistical significance testing
- `ml/experiments/grid_search_weights.py` — Added training window sweep templates
- `ml/signals/aggregator.py` — SC=3 OVER block filter, algorithm version v394
- `CLAUDE.md` — Updated filter list
- `docs/08-projects/current/model-evaluation-and-selection/07-SESSION-394-FINDINGS.md` — Full findings

## What's Next
1. **Deploy** — Push to main (auto-deploys aggregator change)
2. **V16 retrain** — Use `training_window_v16` template with fresh data
3. **Fleet rationalization** — Disable redundant CatBoost clones
4. **Shadow monitoring setup** — Daily cron running simulate_best_bets.py for disabled models
5. **Filter audit revisit** — Wait for 30+ days of `best_bets_filter_audit` data
6. **UNDER edge cap** — Test capping UNDER edge credit at 10

## Deployment Notes
- `aggregator.py` change auto-deploys via Cloud Build when pushed
- `prediction-coordinator` trigger only watches `predictions/coordinator/**`, NOT `ml/signals/` — manual deploy needed for coordinator
- New tools (`simulate_best_bets.py`, `bootstrap_hr.py`) are CLI-only, no deployment needed
