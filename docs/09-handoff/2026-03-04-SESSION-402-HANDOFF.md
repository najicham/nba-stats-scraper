# Session 402 Handoff — away_noveg Removal + Fleet Evaluation

**Date:** 2026-03-04
**Algorithm:** `v401_away_noveg_removed`
**Status:** Deployed, auto-build triggered. Both v400b (star_under) and v401 (away_noveg) take effect Mar 5 pipeline.

---

## Changes Made

### 1. away_noveg Filter REMOVED (aggregator.py)

**Was:** Block v12_noveg/v9 family + AWAY game (43-48% HR from Sessions 347/365).
**Now:** Removed entirely.

**Evidence (thorough multi-query analysis):**

| Metric | Value |
|--------|-------|
| March AWAY noveg HR | **60.0%** (N=45) — well above breakeven |
| Newer models (Jan+ training) AWAY | 61.0% vs 63.3% HOME — **zero gap** |
| Old models (train_1102) AWAY | 44.1% — this was the actual root cause |
| February AWAY noveg HR | 51.8% — marginal, justified filter at the time |
| Rejections | **9 in 2 days** — #1 blocker, blocking profitable picks |

**Root cause:** Model staleness, not structural HOME/AWAY difference. The old November-trained models (Q43, Q45 on train_1102) had catastrophic 44.1% AWAY but those are now disabled. The currently active fleet shows no HOME/AWAY performance gap.

**Per-model detail:**
- Old Q43/Q45 (train_1102): 43-44% AWAY — terrible, but already disabled
- MAE models: 58.6% AWAY — above breakeven
- V16 noveg: 76.9% AWAY — actually BETTER away than home
- LightGBM: 56.5% AWAY — above breakeven

### 2. Algorithm Version Bumped

`v400b_star_under_removed` → `v401_away_noveg_removed`

### 3. CLAUDE.md Updated

Negative filter #9 updated to reflect removal.

---

## Fleet Evaluation (All 10 Enabled Models)

### Models With Graded Data (since Feb 15)

| Model | Edge 3+ HR | Edge 3+ N | MAE | Status |
|-------|-----------|-----------|-----|--------|
| catboost_v12_train0104_0222 | **85.7%** | 7 | 5.87 | Active (only vegas-weighted) |
| catboost_v12_noveg_train0103_0227 | **80.0%** | 5 | 4.88 | Active (freshest) |
| catboost_v12_noveg_train0108_0215 | **77.8%** | 9 | 5.01 | Active |
| catboost_v16_noveg_train1201_0215 | **73.3%** | 15 | 3.74 | Active (best MAE) |
| lgbm_v12_noveg_train0103_0227 | **72.7%** | 11 | 6.12 | Active (LightGBM) |

### Models Just Started (Mar 4, zero graded)

| Model | Notes |
|-------|-------|
| catboost_v12_noveg_train0104_0215 | New champion candidate (67.57% backtest). Needs weeks. |
| catboost_v16_noveg_train0105_0221 | V16 variant, shadow |
| lgbm_v12_noveg_vw015_train1215_0208 | LightGBM + vegas weight, shadow |
| xgb_v12_noveg_s42_train1215_0208 | XGBoost seed 42, shadow |
| xgb_v12_noveg_s999_train1215_0208 | XGBoost seed 999, shadow |

**No models meet disable threshold** (< 45% HR on 20+ graded edge 3+ picks). Fleet is healthy but young.

**No production champion designated.** 0 models have `is_production = TRUE`. This doesn't block predictions but means no model is officially "champion."

---

## Volume Impact Assessment

### Filter Rejection Breakdown (Last 2 Game Days)

| Filter | Mar 4 | Mar 3 | Action |
|--------|-------|-------|--------|
| **away_noveg** | 3 | 6 | **REMOVED** |
| **star_under** | 0 | 2 | **REMOVED (Session 400b)** |
| over_edge_floor | 1 | 4 | Keep (25% HR) |
| line_jumped_under | 2 | 2 | Keep (38.2% HR) |
| bench_under | 2 | 0 | Keep (43.1% HR) |
| signal_count | 1 | 1 | Keep (signal density) |
| line_dropped_under | 1 | 0 | Keep (35.2% HR) |

**star_under + away_noveg = 42% of all rejections.** Expected volume: 2-3x more picks per day.

Mar 3 estimate: 1 → up to 9 picks. Mar 4 estimate: 1 → up to 4 picks.
(Upper bounds — some freed picks may hit other downstream filters.)

### Best Bets Recent Record

| Date | Picks | W-L | HR |
|------|-------|-----|-----|
| Mar 4 | 2 | ungraded | — |
| Mar 1 | 2 | 2-0 | 100% |
| Feb 28 | 6 | 2-3 | 40% |
| Feb 27 | 1 | 0-1 | 0% |
| Feb 26 | 5 | 2-2 | 50% |
| Feb 24 | 2 | 1-1 | 50% |
| Feb 22 | 4 | 4-0 | 100% |

Graded: 11-7 (61.1%). Low volume = high per-day variance.

---

## Other Findings

### Signal Rescue
- 1 live rescue: Jaylen Wells OVER 12.5 (edge 3.5, via `high_scoring_environment_over`)
- Need 14+ days for evaluation. Zero picks below edge 3.0 seen yet.

### Legacy Model Leak
- Legacy `catboost_v12` sourced 4 best bets picks Feb 19-24 (25% HR)
- No picks after Feb 24 — Session 391 fix is working
- `ENABLE_LEGACY_V12` env var not set on worker (defaults to false)

### Brier-Weighted Model Selection (Step 7 Research)
- Enabled models too young for 30-day Brier scores
- All models in the Brier table are BLOCKED/disabled
- **Defer to mid-March** when fleet has 14+ days of data

### New Scrapers Status (from Session 401)
- **7/10 working:** FantasyPros (271 rows), DailyFantasyFuel (112), Dimers (20), TeamRankings (30), HashtagBasketball (34), RotoWire (480), Covers referee (76)
- **3 failing:** NumberFire (redirects to FanDuel, needs JS), VSiN (AJAX), NBA Tracking (timeout)
- `date=TODAY` bug fixed in `e695bffc` (ConfigMixin resolves to actual ET date)

---

## Deployment

```
Commit: bf030977 feat: remove away_noveg filter
Builds: deploy-phase6-export, deploy-prediction-coordinator triggered
Both v400b + v401 changes take effect on Mar 5 pipeline run (~6 AM ET)
```

---

## Monitoring Queries (Next Session)

### A. Verify v401 is Active
```sql
SELECT DISTINCT algorithm_version, game_date
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-05'
```
Expected: `v401_away_noveg_removed`

### B. Volume Recovery
```sql
SELECT game_date, total_candidates, passed_filters,
  JSON_VALUE(rejected_json, '$.away_noveg') as away_blocked,
  JSON_VALUE(rejected_json, '$.star_under') as star_blocked
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-03'
ORDER BY game_date DESC
```
Expected: away_noveg = 0, star_under = 0, passed_filters significantly higher

### C. Star UNDER Monitor
```sql
SELECT FORMAT_DATE("%Y-W%V", pa.game_date) as week,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy pa
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
  AND pa.has_prop_line = TRUE AND pa.recommendation = 'UNDER'
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND pa.line_value >= 25 AND pa.prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
```

### D. AWAY Picks Now Flowing
```sql
SELECT bb.game_date, bb.player_lookup, bb.recommendation, ROUND(bb.edge, 1) as edge,
  bb.system_id, pa.prediction_correct as hit
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
JOIN nba_reference.nba_schedule s ON bb.game_id = s.game_id AND bb.game_date = s.game_date
WHERE bb.game_date >= '2026-03-05'
  AND s.home_team_tricode != bb.team  -- AWAY
ORDER BY bb.game_date DESC
```
