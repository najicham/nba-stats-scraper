# Session 476 Handoff — 9-Agent Diagnosis + Fleet Reset (Round 2)

**Date:** 2026-03-21
**Previous:** Session 475 (9-agent diagnosis, fleet reset from edge-collapsed March models, OVER floor 5→6)

## TL;DR

Second consecutive 9-agent diagnosis session. Discovered the pick drought had deeper structural causes than Session 475 addressed: CatBoost is architecturally 40% tighter than LGBM regardless of training window. Key high-edge models were disabled. Worker filters were blocking the best opportunities. Full fleet rebuild: enabled v9_low_vegas, trained new LGBM (Dec-Feb), disabled 4 dead CatBoost models. OVER floor lowered 6.0→5.0. Three filter fixes. Grading backfill triggered for 5 ungraded days.

---

## What Was Done

### 1. Root Cause Analysis (9-Agent Synthesis)

The post-Session-475 drought (0 picks Mar 21) had four compounding causes:

| Cause | Finding | Fix |
|-------|---------|-----|
| Models with real edge were disabled | v9_low_vegas (2.85 avg_abs_diff) and lgbm_vw015 (2.03) excluded from BB pipeline | Re-enabled v9_low_vegas |
| CatBoost structural edge collapse | CatBoost pred-line correlation 0.974-0.989 — symmetric trees reconstruct line via `line_vs_season_avg`. ALWAYS 40% tighter than LGBM regardless of training window | Disabled 4 collapsed models; trained fresh LGBM |
| Worker filters blocking best picks | `star_under_bias_suspect` killed Luka UNDER at 8.5 edge across all 5 models; `hot_streak_under_risk` blocked Kawhi/Wemby/Green | Exempted v9_low_vegas from star bias filter |
| `opponent_depleted_under` blocking winners | CF HR 83.3% (N=6) — was an active blocker | Demoted to observation mode |

### 2. Fleet Reset

**Disabled (zero BB candidates, dead weight):**
- `catboost_v12_noveg_train0104_0215` (0.96 avg_abs_diff)
- `catboost_v12_noveg_train0108_0215` (0.95)
- `catboost_v12_noveg_train0109_0305` (0.92)
- `catboost_v12_train0109_0305` (0.67 — worst)

**Enabled:**
- `catboost_v9_low_vegas_train0106_0205` — re-enabled, 2.85 avg_abs_diff, 57.3% UNDER HR in March

**Trained + Enabled (both passed governance):**
- `lgbm_v12_noveg_train1215_0214` — Dec 15-Feb 14 window, 63.04% HR edge 3+, 84.62% HR edge 5+, OVER 61.9%/UNDER 64.0%, Vegas bias -0.05
- `catboost_v12_noveg_train0103_0214` — Jan 3-Feb 14 window, 62.86% HR edge 3+ (trained Session 476 earlier; will be collapsed ~0.95 avg_abs_diff per architectural findings, backup only)

### 3. Code Changes (deployed to main)

**aggregator.py:**
- OVER floor: 6.0 → 5.0 (Mar 7+ 28.6% HR finding was N=3 per bucket; season-long edge 5-6 HR: 63% N=27; v9_low_vegas and new LGBM now produce edge 5-6 picks)
- `opponent_depleted_under`: moved to observation mode (CF HR 83.3% N=6 — was blocking winners)

**worker.py:**
- `star_under_bias_suspect`: added `'v9_low_vegas' not in system_id` exemption (v9_low_vegas has 0.25x vegas weight calibration; 57.3% UNDER HR March — bias doesn't apply)

### 4. Infrastructure
- Grading backfill triggered for Mar 16-20 via `/grade-date` endpoint (5 days ungraded, hiding true MAE recovery)
- Worker cache refreshed twice (post-registry changes, post-LGBM registration)
- MLB worker deployed with latest code (blacklist 28→23, multi-model fleet — was 12 days stale)
- All changes pushed to main, auto-deploy confirmed

---

## Current Fleet

| Model | avg_abs_diff (Mar 21) | Status | Notes |
|-------|----------------------|--------|-------|
| `catboost_v9_low_vegas_train0106_0205` | 2.85 | blocked+enabled | 44 days stale (trained Feb 5); watch HR |
| `lgbm_v12_noveg_train1215_0214` | ~2.0 (est, first run Mar 22) | active+enabled | NEW — Dec 15-Feb 14 |
| `lgbm_v12_noveg_train0103_0227` | 1.53 | blocked+enabled | Feb 27 training end |
| `catboost_v12_noveg_train0103_0214` | ~0.95 (est) | active+enabled | Feb-anchored CatBoost; backup |

---

## Key 9-Agent Findings (For Future Reference)

### CatBoost Architecture Issue (Permanent)
CatBoost's symmetric trees + ordered boosting produce pred-line correlation 0.974-0.989. The `--no-vegas` flag only removes 4 features, but `line_vs_season_avg` (= `vegas_line - season_avg`) survives and lets CatBoost reconstruct the line perfectly. This is NOT fixable by changing training windows. **The fleet should be LGBM/XGBoost-heavy for late-season tight markets.** CatBoost architecture fix (remove `line_vs_season_avg` from v12_noveg features) is a post-season project.

### UNDER Signal Ecosystem (Late March)
Both OVER and UNDER collapsed in March (OVER 48.5%, UNDER 41.2% BB HR). "UNDER is stable" thesis broke in late March. Active UNDER signals that are dead: `sharp_line_drop_under` COLD at 25%, `home_under` at 31%, `volatile_starter_under` at 0%. Only `bench_under` is HOT (rarely fires).

### Observation Filters Blocking Profitable UNDER
Three filters are in observation mode (not blocking) but tracking profitably:
- `bench_under_obs`: 91% CF HR — winning picks flow through
- `line_jumped_under_obs`: 100% CF HR — winning picks flow through
These are correctly observation-only. Do not re-activate.

### Market Regime
- Vegas MAE compressed to 4.16 (Mar 11 trough), partially recovered to 4.94 (Mar 15)
- 5 ungraded game days (Mar 16-20) hiding true MAE recovery — grading triggered this session
- Daily MAE spiked to 6.43 on Mar 12 (LOOSE) — recovery may be underway
- 2024-25 had NO comparable compression event — 2026-specific

---

## Open Items / What's Next

### Priority 1 — Verify Mar 22 Fleet Performance (~6 AM ET)
```sql
-- New fleet avg_abs_diff
SELECT system_id, COUNT(*) as n,
  ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_abs_diff
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-22' AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;

-- Best bets picks
SELECT game_date, system_id, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-22'
GROUP BY 1, 2;
```
Expected: v9_low_vegas at 2.85+, new LGBM at ~2.0, 2-4 picks/day total.

### Priority 2 — hot_streak_under_risk Audit
Still blocking Kawhi, Wemby, Jalen Green UNDER. Original justification: L5 > season + 3pts → 14.3% UNDER HR. Check current CF HR — if > 55% recently, demote to observation.
```sql
SELECT filter_name, counterfactual_hr, n_blocked, game_date
FROM nba_predictions.filter_counterfactual_daily
WHERE filter_name = 'hot_streak_under_risk' AND game_date >= '2026-03-01'
ORDER BY game_date DESC
```

### Priority 3 — Verify Grading Catchup + MAE Recovery
After Mar 16-20 grading completes, league_macro_daily updates with true MAE:
```sql
SELECT game_date, vegas_mae_7d, market_regime, bb_hr_7d
FROM nba_predictions.league_macro_daily
WHERE game_date >= '2026-03-15' ORDER BY game_date DESC
```
If Vegas MAE >= 5.0: consider resuming weekly-retrain-trigger CF.

### Priority 4 — v9_low_vegas HR Monitoring
Model is 44 days stale (trained to Feb 5). Strict watch:
- Disable if `rolling_hr_7d < 47%` at N >= 10
- Check model_performance_daily daily while it's accumulating picks

### Priority 5 — MLB Schedulers (deadline Mar 24)
```bash
./bin/mlb-season-resume.sh --dry-run   # verify 24 jobs
./bin/mlb-season-resume.sh             # execute Mar 24
```
Opening Day is March 27 — use runbook `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md` Phase 4 for verification.

### Priority 6 — Weekly Retrain CF Resume
Still PAUSED. Resume when Vegas MAE 7d >= 5.0:
```bash
gcloud scheduler jobs resume weekly-retrain-trigger --location=us-west2 --project=nba-props-platform
```
WARNING: When resuming, set explicit `--train-start` AND `--train-end` to force Feb cutoff. The CF default will use current date which produces collapsed models.

### Priority 7 — CatBoost Architecture Fix (post-season)
Remove `line_vs_season_avg` from v12_noveg feature set. This single feature allows CatBoost to reconstruct the Vegas line, causing structural edge collapse. Candidate fix: replace with `deviation_from_season_avg_abs` or just drop it entirely. Must validate with walk-forward before enabling.

---

## System Health After Session

| Item | Status |
|------|--------|
| Enabled fleet | 4 models (2 LGBM + v9_low_vegas + CatBoost backup) |
| OVER edge floor | 5.0 (was 6.0) |
| opponent_depleted_under | observation mode (was active) |
| star_under_bias_suspect | v9_low_vegas exempted |
| Worker cache | Refreshed (revision 00415+) |
| Grading Mar 16-20 | Triggered — in progress |
| MLB worker | Deployed (revision 00020-vcs) |
| Weekly retrain CF | Still PAUSED — resume when MAE >= 5.0 |
| Project docs | `docs/08-projects/current/late-season-476/00-PLAN.md` |

## Do NOT Do (Confirmed Dead Ends This Session)

- **Do NOT retrain CatBoost with any training window** — architecture issue, not data. Will always be collapsed at ~0.95 avg_abs_diff in tight markets.
- **Do NOT lower MIN_EDGE below 3.0**
- **Do NOT relax real_sc gate**
- **Do NOT re-activate bench_under_obs or line_jumped_under_obs** — they're observation-only correctly; picks flow through
- **Do NOT resume weekly retrain CF** until MAE >= 5.0 (would train on tight-market data → collapsed models)

## Performance Expectations (~22 Days Remaining)

| Scenario | Picks/Day | Expected HR |
|----------|-----------|-------------|
| Market tight (MAE < 4.5) | 0-1 | ~50% |
| Partial recovery (MAE 4.5-5.0) | 1-3 | 53-58% |
| Full recovery (MAE > 5.0) | 3-5 | 58-63% |
