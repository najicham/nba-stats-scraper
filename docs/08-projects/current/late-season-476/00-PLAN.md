# Late Season 2026 — Session 476 Action Plan

**Created:** 2026-03-21
**Context:** 9-agent diagnosis of 10-day pick drought. ~23 game days left in regular season.

---

## Situation Summary

The pick drought (Mar 12-21) had multiple compounding causes:
1. **4 enabled CatBoost models edge-collapsed** (0.67-0.96 avg_abs_diff) — structural CatBoost architecture issue
2. **Models with real edge were disabled** — v9_low_vegas (2.85) and lgbm_vw015 (2.03) excluded from BB pipeline
3. **Worker filters blocking best opportunities** — star_under_bias blocking Luka UNDER at 8.5 edge, hot_streak blocking Kawhi/Wemby/Green
4. **opponent_depleted_under filter blocking winners** — 83.3% CF HR (N=6), was active with 44.4% original HR

Key structural finding: **CatBoost is architecturally 40% tighter than LGBM** — symmetric trees + ordered boosting reconstruct the Vegas line via `line_vs_season_avg` feature even in no-vegas mode. This is permanent. LGBM's leaf-wise growth maintains prediction variance. Fleet must be LGBM/XGBoost-heavy to survive late-season tight markets.

---

## Changes Made (Session 476)

### Registry (BQ)
- [x] **Enable** `catboost_v9_low_vegas_train0106_0205` (avg_abs_diff 2.85, 57.3% UNDER HR March)
- [x] **Disable** `catboost_v12_noveg_train0104_0215` (avg_abs_diff 0.96, zero BB candidates)
- [x] **Disable** `catboost_v12_noveg_train0108_0215` (avg_abs_diff 0.95, zero BB candidates)
- [x] **Disable** `catboost_v12_noveg_train0109_0305` (avg_abs_diff 0.92, zero BB candidates)
- [x] **Disable** `catboost_v12_train0109_0305` (avg_abs_diff 0.67, worst collapse)

### Code (aggregator.py)
- [x] **OVER floor**: 6.0 → 5.0 (season-long edge 5-6 HR: 63% N=27; Mar 7+ collapse was N=3)
- [x] **opponent_depleted_under**: demoted to observation (CF HR 83.3% N=6, blocking winners)

### Code (worker.py)
- [x] **star_under_bias_suspect**: exempt `v9_low_vegas` family (57.3% UNDER HR March; bias was observed on old v9 champion model only)

### Infrastructure
- [x] Grading backfill triggered for Mar 16-20 (5 ungraded days, hiding MAE recovery)
- [x] Worker cache refreshed (revision 00415+)
- [x] Pushed to main → auto-deploy triggered

### Training (COMPLETE)
- [x] **LGBM Dec-Feb anchored** `lgbm_v12_noveg_train1215_0214`: ALL GATES PASSED
  - HR edge 3+: 63.04%, HR edge 5+: 84.62% (N=13), OVER: 61.9%, UNDER: 64.0%
  - Vegas bias: -0.05, MAE: 5.16 vs 5.50 baseline
  - Best segments: edge 5-7 at 88.9% (N=9), Starters UNDER 72.7% (N=11)
  - Registered as `lgbm_v12_noveg_train1215_0214`, enabled=TRUE, worker cache refreshed

---

## Final Fleet After Session 476

| Model | avg_abs_diff (Mar 21) | Status | Notes |
|-------|----------------------|--------|-------|
| `catboost_v9_low_vegas_train0106_0205` | **2.85** | enabled | Re-enabled; trained to Feb 5; watch HR closely |
| `lgbm_v12_noveg_train1215_0214` | ~2.0 (est) | **NEW** | Dec 15-Feb 14, 63% HR gate |
| `lgbm_v12_noveg_train0103_0227` | 1.53 | enabled | Feb 27 training end |
| `catboost_v12_noveg_train0103_0214` | ~0.95 (est) | enabled | Feb-anchored CatBoost; backup only |

---

## Open Items / What's Next

### Priority 1 — Monitor Tomorrow (Mar 22)
Check if v9_low_vegas generates BB picks:
```sql
SELECT game_date, system_id, COUNT(*) as picks, AVG(edge) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-22'
GROUP BY 1, 2
```

Check avg_abs_diff for new fleet:
```sql
SELECT system_id, COUNT(*) as n,
  ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_abs_diff
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-22' AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
```

### Priority 2 — hot_streak_under_risk Audit (next session)
Filter blocked Kawhi, Wemby, Jalen Green UNDER today.
Check CF HR — if > 55%, demote to observation.
```sql
SELECT filter_name, counterfactual_hr, n_blocked, game_date
FROM nba_predictions.filter_counterfactual_daily
WHERE filter_name = 'hot_streak_under_risk' AND game_date >= '2026-03-01'
ORDER BY game_date DESC
```

### Priority 3 — Verify Grading Catchup
After Mar 16-20 grading completes, league_macro_daily will update with true MAE trajectory.
Check: `SELECT game_date, vegas_mae_7d, market_regime FROM nba_predictions.league_macro_daily WHERE game_date >= '2026-03-15' ORDER BY game_date DESC`

### Priority 4 — v9_low_vegas HR Monitoring
This model is 44 days stale (trained to Feb 5). Watch 7d rolling HR closely.
If 7d HR drops below 45%: disable immediately.
Governance threshold: disable if `rolling_hr_7d < 47%` at N >= 10.

### Priority 5 — CatBoost Architecture Fix (post-season)
Per 9-agent finding: remove `line_vs_season_avg` from v12 no-vegas features.
This feature literally encodes `vegas_line - season_avg`, allowing CatBoost to reconstruct the line.
Alternative: increase CatBoost l2_leaf_reg to 10-20, reduce depth to 4.
**Do not pursue until post-season** — too risky mid-season.

---

## Do NOT Do

- Do NOT retrain CatBoost with any window — architectural issue, not data issue
- Do NOT lower MIN_EDGE below 3.0
- Do NOT relax real_sc gate
- Do NOT add March training data to any model
- Do NOT expect 65%+ BB HR — late season target is 53-58%

---

## Performance Expectations (Remaining ~23 Days)

| Scenario | Picks/Day | Expected HR |
|----------|-----------|-------------|
| Market stays tight (MAE < 4.5) | 0-1 | ~50% |
| Partial recovery (MAE 4.5-5.0) | 1-3 | 53-58% |
| Full recovery (MAE > 5.0) | 3-5 | 58-63% |

Best realistic outcome: 50-70 picks over remaining season at 53-58% HR.
