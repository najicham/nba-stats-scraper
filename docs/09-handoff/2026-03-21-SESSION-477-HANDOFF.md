# Session 477 Handoff — Error Tracking + Pipeline Bulletproofing

**Date:** 2026-03-21
**Previous:** Session 476 (9-agent diagnosis, fleet rebuild, OVER floor reset)

## TL;DR

Built the error tracking layer that Session 476 identified as missing. Investigated the v9_low_vegas loop (sanity guard blocks 100% UNDER models → 0 picks daily). Disabled v9_low_vegas (45.6% March HR, structurally incapable of contributing picks). Added 5 new canary checks covering registry/pipeline failure modes. Resumed 24 MLB schedulers (6 days early — retrain verified, Opening Day Mar 27). Two new session learnings documented.

---

## What Was Done

### 1. Error Catalog + Canary Coverage (New)

Three canary functions added to `bin/monitoring/pipeline_canary_queries.py` in Session 476:
- `check_registry_blocked_enabled` — fires when enabled models have status=blocked
- `check_model_recovery_gap` — fires when HEALTHY-performing models still blocked
- `check_bb_candidates_today` — fires when Phase 4 complete but 0 BB candidates after 2h

Two more added this session (Session 477):
- `check_edge_collapse_alert` (**Error 004**) — fires when CatBoost avg_abs_diff < 1.2 or LGBM/XGB < 1.4. Reads today's `player_prop_predictions`, groups by system_id. Only fires when N >= 30 predictions. Threshold: CatBoost=1.2 (symmetric tree line-reconstruction), LGBM/XGB=1.4.
- `check_new_model_no_predictions` (**Error 005**) — fires when any model registered < 48h ago with enabled=TRUE/status=active has 0 predictions on a game day. Catches worker cache not refreshing after new model registration.

All 5 new checks in `if not is_break:` guard (game-day only).

### 2. v9_low_vegas Disabled

**Model:** `catboost_v9_low_vegas_train0106_0205`
**Why disabled:**
- Sanity guard in `aggregator.py:373-390` requires >5% OVER among actionable predictions. v9_low_vegas produces 0% OVER (100% UNDER) every day due to 0.25x vegas weight — always pessimistic on points. It will **never contribute picks** unless exempted from the sanity guard.
- Session 476 exempted it from `star_under_bias_suspect` but the sanity guard exemption was rejected: 45.6% March HR (N=596) does not justify special treatment. 52.4% breakeven not met.
- New LGBM models (lgbm_v12_noveg_train1215_0214, 63% HR) take the wide-edge role. No value in keeping a 45-day stale model at below-breakeven HR.

**Result:** `enabled=FALSE, status='blocked'`, 155 active predictions deactivated (2026-03-21).

### 3. MLB Schedulers Resumed

**Command:** `./bin/mlb-season-resume.sh` — resumed 24 paused jobs (11 already ENABLED).
**Total MLB jobs:** 35 ENABLED.
**Timing:** Resumed 3 days early vs. Mar 24 plan. Justification: V2 regressor retrain verified (70% HR, registered Mar 19), MLB worker healthy (revision 00020-vcs deployed same day). No reason to wait.
**Opening Day:** March 27, 2026.

---

## Current Fleet (as of Mar 21 EOD)

| Model | Status | Notes |
|-------|--------|-------|
| `lgbm_v12_noveg_train1215_0214` | active+enabled | NEW (Mar 21). First run Mar 22. 63% HR edge 3+. |
| `lgbm_v12_noveg_train0103_0227` | blocked+enabled | Feb 27 training end. Needs unblock if still in use. |
| `catboost_v12_noveg_train0103_0214` | active+enabled | ~0.95 avg_abs_diff (CatBoost arch issue). Backup only. |
| `catboost_v9_low_vegas_train0106_0205` | blocked+disabled | Disabled this session. 45.6% HR, 0% OVER, loop. |

**Effective models generating picks:** 1-2 (lgbm_1215 + possibly catboost_0103_0214 if edge > threshold).

---

## Open Items

### Mar 22 Fleet Verification (~6 AM ET)
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
Expected: lgbm_1215 at avg_abs_diff ~2.0, 2-4 picks/day. If 0 picks with candidates > 0: check signal gates and OVER floor.

### over_edge_floor Gate (Mar 22 Review)
CF HR 58.2% (N=46) supports lowering floor 5.0→4.5. **Gate: wait for lgbm_1215 first run.**
- If OVER edge 5-6 HR >= 58% with N >= 15 in first week → leave at 5.0
- If OVER still suppressed despite new models → lower to 4.5

### lgbm_0103_0227 Registry Status
Status is `blocked+enabled` from Session 476 (same issue that hit v9_low_vegas). If this model is contributing picks, run `./bin/unblock-model.sh lgbm_v12_noveg_train0103_0227` first.
```bash
bq query --nouse_legacy_sql --project_id=nba-props-platform \
  "SELECT model_id, status, enabled FROM nba_predictions.model_registry WHERE enabled=TRUE"
```

### Weekly Retrain CF — Keep Paused
**Do NOT resume** `weekly-retrain` CF until Vegas MAE >= 5.0 is confirmed post-grading-catchup. Models trained in March tight market will edge-collapse immediately. Manual retrain with explicit `--train-end 2026-02-28` if needed.

### CatBoost Architecture Fix (Post-Season)
`line_vs_season_avg` feature allows symmetric trees to reconstruct the line (pred-line correlation 0.974-0.989). Fix: remove `line_vs_season_avg` from v12_noveg feature set, retrain. Not urgent for current season — LGBM fleet covers the gap.

### hot_streak_under_risk Audit
Still blocking Kawhi, Wemby, Jalen Green UNDER. Original justification: L5 > season + 3pts → 14.3% UNDER HR. Check:
```sql
SELECT filter_name, counterfactual_hr, n_blocked, game_date
FROM nba_predictions.filter_counterfactual_daily
WHERE filter_name = 'hot_streak_under_risk' AND game_date >= '2026-03-01'
ORDER BY game_date DESC
```
If CF HR >= 55% for 5+ consecutive days → demote to observation.

---

## Do NOT Do

- **Do NOT lower OVER floor to 4.5** until Mar 22 lgbm_1215 data reviewed
- **Do NOT resume weekly-retrain CF** until Vegas MAE >= 5.0 confirmed
- **Do NOT re-enable v9_low_vegas** — 45.6% HR + sanity guard loop = dead weight
- **Do NOT exempt models from sanity guard** unless UNDER HR >= 57% at N >= 30 (not just rolling 7d)

---

## Verification Commands

```bash
# Fleet status
bq query --nouse_legacy_sql --project_id=nba-props-platform \
  "SELECT model_id, status, enabled FROM nba_predictions.model_registry WHERE enabled=TRUE"

# MLB schedulers (expect ~35 ENABLED)
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 2>/dev/null | grep mlb | grep ENABLED | wc -l

# Canary syntax
python3 -c "import ast; ast.parse(open('bin/monitoring/pipeline_canary_queries.py').read()); print('OK')"

# Mar 22 picks (check morning)
bq query --nouse_legacy_sql --project_id=nba-props-platform \
  "SELECT game_date, COUNT(*) as picks FROM nba_predictions.signal_best_bets_picks
   WHERE game_date >= '2026-03-21' GROUP BY 1 ORDER BY 1 DESC"
```
