# Session 401 Plan

**Prerequisites:** Session 400/400b deployed. Algorithm `v400b_star_under_removed`. Star UNDER unblocked, signal-first UNDER ranking live, new model in shadow fleet.

---

## Step 1: Grade Last Night + Validate Changes (10 min)

Run `/daily-steering` first, then validate the Session 400 changes landed:

```sql
-- 1a. Check algorithm version
SELECT DISTINCT algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-05'

-- 1b. Did star UNDER picks flow through?
SELECT player_lookup, recommendation, ROUND(edge, 1) as edge,
  ROUND(composite_score, 2) as composite, line_value,
  pa.prediction_correct as hit, pa.actual_points
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date = '2026-03-04'
ORDER BY composite_score DESC

-- 1c. Volume comparison (before vs after)
SELECT game_date, total_candidates, passed_filters,
  JSON_VALUE(rejected_json, '$.star_under') as star_blocked,
  algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-02'
ORDER BY game_date DESC

-- 1d. UNDER composite scores (should be signal quality scale ~1-10, not edge)
SELECT player_lookup, recommendation, ROUND(composite_score, 2) as composite,
  ROUND(edge, 1) as edge, real_signal_count
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-04' AND recommendation = 'UNDER'
ORDER BY game_date, composite_score DESC
```

**Expected:** star_under = 0, volume up ~2-4 picks, UNDER composite on signal scale.

---

## Step 2: Evaluate `away_noveg` Filter (20 min)

**Why:** #1 remaining filter blocker — 9 rejections in last 14 days on only 2 game days. March noveg HR is recovering (67.9% N=81 overall). The filter was created during Session 347/365 when v12_noveg AWAY was 43-48% HR. Post-toxic-window recovery may have invalidated it.

### 2a. Gather data

```sql
-- away_noveg HR by month (need is_home from schedule join)
-- Check if AWAY noveg performance has recovered
SELECT FORMAT_DATE("%Y-%m", pa.game_date) as month,
  CASE WHEN pa.player_lookup IN (
    SELECT player_lookup FROM nba_predictions.player_prop_predictions p
    JOIN nba_reference.nba_schedule s ON p.game_id = s.game_id AND p.game_date = s.game_date
    WHERE -- player's team = away_team
    1=1
  ) THEN 'AWAY' ELSE 'HOME' END as location,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy pa
WHERE pa.game_date >= '2026-01-01'
  AND pa.has_prop_line = TRUE
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND pa.prediction_correct IS NOT NULL
  AND pa.system_id LIKE '%noveg%'
GROUP BY 1, 2 ORDER BY 1, 2
```

*Note: The HOME/AWAY determination is tricky from prediction_accuracy alone. May need to check how the aggregator determines `is_home` and query accordingly. Explore the `ml_feature_store_v2` or prediction metadata.*

### 2b. Decision framework

| March AWAY noveg HR | Action |
|---------------------|--------|
| >= 55% on N >= 30 | Remove `away_noveg` filter |
| 50-55% on N >= 30 | Keep but narrow to v9 only (v12_noveg may have recovered) |
| < 50% on N >= 30 | Keep as-is |

### 2c. Check per-model AWAY performance

Some noveg models may have recovered while others haven't. Consider model-specific rather than blanket blocking.

---

## Step 3: New Model Promotion Decision (10 min)

`catboost_v12_noveg_train0104_0215` has been in shadow since Mar 4. Check live performance:

```sql
SELECT system_id,
  COUNT(*) as graded,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_wins,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL) as edge3_total,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-03-04'
  AND has_prop_line = TRUE
  AND system_id IN (
    SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE
  )
GROUP BY 1 HAVING graded >= 5
ORDER BY edge3_hr DESC
```

**Promote if:** edge 3+ HR >= 60% on 10+ graded picks. Run:
```bash
bq query 'UPDATE nba_predictions.model_registry SET is_production=TRUE, status="production" WHERE model_id="catboost_v12_noveg_train0104_0215"'
```

**If insufficient data** (< 10 graded edge 3+): Wait another day. Model should be fine — backtest was 67.57%.

---

## Step 4: Fleet Cleanup (15 min)

10 enabled models. Some are old or redundant:

| Model | Training End | Age (days) | Action |
|-------|-------------|------------|--------|
| `catboost_v16_noveg_train1201_0215` | Feb 15 | 17d | Keep (V16 diversity) |
| `lgbm_v12_noveg_vw015_train1215_0208` | Feb 8 | 24d | Keep (LightGBM diversity) |
| `xgb_v12_noveg_s42_train1215_0208` | Feb 8 | 24d | Keep (XGBoost diversity) |
| `xgb_v12_noveg_s999_train1215_0208` | Feb 8 | 24d | Keep (XGBoost seed diversity) |
| `catboost_v12_noveg_train0108_0215` | Feb 15 | 17d | Evaluate — overlaps new model |
| `catboost_v12_noveg_train0103_0227` | Feb 27 | 5d | Keep (freshest, longest window) |
| `catboost_v12_noveg_train0104_0215` | Feb 15 | NEW | Keep (Session 400 champion) |
| `lgbm_v12_noveg_train0103_0227` | Feb 27 | 5d | Keep (fresh LightGBM) |
| `catboost_v12_train0104_0222` | Feb 22 | 10d | Keep (only vegas-weighted model) |
| `catboost_v16_noveg_train0105_0221` | Feb 21 | 11d | Evaluate — overlaps V16 Dec model |

**Check:** Are any models consistently sourcing losing best bets picks? Use decay detection:
```bash
PYTHONPATH=. python bin/compare-model-performance.py
```

Disable any model with < 45% live HR on 20+ graded edge 3+ picks.

---

## Step 5: Signal Rescue Check (5 min)

Quick check if more rescues happened:

```sql
SELECT game_date, player_lookup, recommendation, rescue_signal,
  ROUND(edge, 1) as edge, real_signal_count
FROM nba_predictions.signal_best_bets_picks
WHERE signal_rescued = TRUE AND game_date >= '2026-03-04'
ORDER BY game_date
```

If N >= 5, start checking HR. Otherwise just note volume.

---

## Step 6: Investigate Remaining Volume Levers (30 min, if time)

After star_under removal, the filter rejection ranking is:

| Filter | 14-day Rejections | Notes |
|--------|-------------------|-------|
| `away_noveg` | 9 | Step 2 above |
| `star_under` | 5 | NOW REMOVED |
| `over_edge_floor` | 5 | OVER edge < 5.0 = 25% HR in BB (keep) |
| `line_jumped_under` | 3 | UNDER + line jumped 2+ |
| `bench_under` | 2 | UNDER + line < 12 = 43.1% (keep) |

After `away_noveg` evaluation, the next lever is `line_jumped_under`. Check if it's still justified:

```sql
SELECT FORMAT_DATE("%Y-%m", game_date) as month,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-12-01'
  AND has_prop_line = TRUE AND recommendation = 'UNDER'
  AND ABS(predicted_points - line_value) >= 3
  AND prediction_correct IS NOT NULL
  -- need prop_line_delta >= 2.0, may need feature store join
GROUP BY 1 ORDER BY 1
```

### Other volume ideas (research, don't implement):

- **Lower OVER edge floor to 4.0** for signal-rescue-eligible picks? (Currently 5.0, but rescue already bypasses it)
- **Relax familiar_matchup from 6 to 8 games?** Check if 6-7 game matchups are still losing.
- **UNDER edge 7+ block relaxation** — currently blocks all V9 UNDER 7+. Check if non-V9 models at UNDER 7+ are profitable.

---

## Step 7: Brier-Weighted Model Selection (Research Only, 20 min)

If Steps 1-5 are quick, start researching Brier-weighted selection:

```sql
-- Current Brier scores by model (30-day)
SELECT model_id, brier_score_30d, hit_rate_30d, picks_30d
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  AND picks_30d >= 10
ORDER BY brier_score_30d ASC
```

**Concept:** Instead of selecting per-player picks by highest edge, weight edge by inverse Brier score. Well-calibrated models get more influence. This addresses the known issue where stale models generate inflated edges that win selection but lose bets.

**Implementation sketch:**
```python
# In supplemental_data.py, per-player selection ROW_NUMBER:
# Current: ORDER BY edge DESC
# Proposed: ORDER BY edge * (1 / brier_score_30d) DESC
# Or: ORDER BY edge * model_hr_weight * calibration_weight DESC
```

Don't implement yet — just gather data on whether this would have changed outcomes.

---

## Priority Order

1. **Step 1** — Grade + validate (always first)
2. **Step 2** — away_noveg evaluation (biggest remaining volume lever)
3. **Step 3** — New model promotion (quick win if data supports it)
4. **Step 5** — Signal rescue check (30 seconds)
5. **Step 4** — Fleet cleanup (if any models are clearly failing)
6. **Step 6** — Additional volume levers (if time)
7. **Step 7** — Brier research (if time)

---

## Don't Do

- Don't add a seasonal star_under filter — research proved it's model-specific, not structural
- Don't lower OVER edge floor below 5.0 — 25% HR in best bets context (only 4 picks, but terrible)
- Don't touch signal rescue criteria yet — need 14+ days of data
- Don't retrain more models — we just added one, fleet has 10 enabled. Focus on evaluation.
