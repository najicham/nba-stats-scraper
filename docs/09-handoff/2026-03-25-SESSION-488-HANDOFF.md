# Session 488 Handoff — 2026-03-25 (Morning Check)

**Previous commit:** `32d37204` — docs: update CLAUDE.md with Session 487 pick drought and filter findings
**Branch:** main

---

## Context: What Changed Yesterday (Session 487)

Yesterday was a major diagnostic session. 9 agents (6 analysis + 3 review) investigated the pick drought and executed several changes. Key facts a new session needs:

### Fleet Changes (BQ-only, no deploy)
- **Deactivated** `lgbm_v12_noveg_train1001_0316` — 167-day window through TIGHT period, underperforming (1.43 avg_abs_diff)
- **Deactivated** `catboost_v12_noveg_train0103_0228` — unexplained re-enablement, 1.13 avg_abs_diff (worst in fleet)
- **Re-enabled** `catboost_v12_noveg_train0118_0315` — CatBoost, Jan 18–Mar 15 window, HEALTHY 7 consecutive days before decay CF disabled it. **First predictions today (Mar 25).**

### Code Change (deployed)
- **`volatile_scoring_over` → SHADOW_SIGNALS** (commit `687a3a88`) — was counting toward `real_sc` with 20% BB HR. Now in shadow.

### Current Enabled Fleet (4 models)
| Model | Framework | State (Mar 23) | Notes |
|-------|-----------|----------------|-------|
| `lgbm_v12_noveg_train0103_0227` | LGBM | HEALTHY 59.5% | Anchor |
| `lgbm_v12_noveg_train0103_0228` | LGBM | BLOCKED 50.0% | Monitor |
| `lgbm_v12_noveg_train1215_0214` | LGBM | BLOCKED 45.7% | Decay CF may auto-disable today |
| `catboost_v12_noveg_train0118_0315` | CatBoost | active (re-enabled) | First production day today |

### Pick Drought Context
- **2 picks in 7 days (Mar 18–24) across 40+ games.** System effectively offline.
- Root cause: fleet diversity collapse — 4+ LGBM clones at r≥0.95, cross-model signals (`combo_3way`, `book_disagreement`) cannot fire.
- CatBoost re-enablement is the partial fix. Full fix: Monday retrain (Mar 30).
- All models avg_abs_diff 1.04–1.45 — very few predictions reach edge 5+.

---

## Morning Checklist

### 1. Did picks recover? (Most important)

```sql
SELECT game_date, system_id, COUNT(*) as n
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = '2026-03-25'
GROUP BY 1, 2
```

Expected: >0 picks. If still 0, check the funnel (see below).

### 2. CatBoost model first day — avg_abs_diff and edge generation

```sql
SELECT system_id, COUNT(*) as predictions,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_abs_diff,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as edge_5plus
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-03-25' AND is_active = TRUE
GROUP BY 1 ORDER BY avg_abs_diff DESC
```

Watch: did `catboost_v12_noveg_train0118_0315` produce any edge 5+ picks? Did it differ meaningfully from the LGBMs?

### 3. Decay CF auto-disable check (runs 11 AM ET)

```sql
SELECT model_id, enabled, status
FROM `nba-props-platform.nba_predictions.model_registry`
WHERE enabled = TRUE
ORDER BY model_id
```

`lgbm_v12_noveg_train1215_0214` was BLOCKED 2 days as of Mar 23. Decay CF may have auto-disabled it today. Fleet must stay ≥ 3 enabled. If it drops to 3, do NOT panic — that's still above the safety floor.

### 4. Filter funnel (if picks = 0)

```sql
SELECT game_date, filter_reason, recommendation, COUNT(*) as blocked,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as cf_hr
FROM `nba-props-platform.nba_predictions.best_bets_filtered_picks`
WHERE game_date = '2026-03-25'
GROUP BY 1, 2, 3
ORDER BY 3 DESC
```

And the top-level funnel:

```sql
SELECT game_date, total_candidates, passed_filters, total_candidates - passed_filters as rejected
FROM `nba-props-platform.nba_predictions.best_bets_filter_audit`
WHERE game_date = '2026-03-25'
```

### 5. Model performance daily (after grading)

```sql
SELECT model_id, state, ROUND(rolling_hr_7d, 1) as hr_7d, rolling_n_7d as n_7d
FROM `nba-props-platform.nba_predictions.model_performance_daily`
WHERE game_date = (SELECT MAX(game_date) FROM `nba-props-platform.nba_predictions.model_performance_daily`)
  AND enabled = TRUE
ORDER BY rolling_hr_7d DESC
```

---

## Key Upcoming Events

| Date | Event |
|------|-------|
| **Mar 25 (today)** | 12-game slate — first real test of cleaned fleet |
| **Mar 27** | MLB Opening Day — run verification queries from Session 486 handoff |
| **Mar 28** | MLB `mlb_league_macro.py` backfill after first games grade |
| **Mar 30, 5 AM ET** | Weekly retrain CF fires — expected models: `lgbm_v12_noveg_train0110_0307`, `catboost_v12_noveg_train0110_0307`. Cap fires → Jan 10–Mar 7 window, zero TIGHT contamination. |

---

## Active Constraints (Do Not Change Without Review)

- **OVER edge floor: 5.0** — do not lower, 5-season finding holds
- **`high_spread_over_would_block`: KEEP ACTIVE** — all-time CF HR 50% (7-7, N=14). Do not demote without N≥30
- **`projection_consensus_over`: DO NOT GRADUATE** — BB HR 1-8 (12.5%)
- **`usage_surge_over`: DO NOT GRADUATE** — BB HR 40% (N=5), not prediction-level 68%
- **`mae_gap_obs`: KEEP AS OBSERVATION** — revisit at N≥30 sustained 7+ days CF HR ≤40%

---

## If Pick Drought Continues Today

If Mar 25 (12-game slate) still produces 0 picks:
1. Check if CatBoost predictions look different from LGBMs (different players? different directions?)
2. Check if any cross-model signals fired at prediction level in `signal_health_daily`
3. The next lever is Monday's retrain — no other quick fixes available
4. Do NOT lower the OVER edge floor or demote filters based on 30-day March data

---

## MLB Opening Day Verification (Mar 27 — 2 days away)

Queries to run Mar 27 evening:
```sql
-- Expected: 15-20 predictions
SELECT game_date, COUNT(*) as n FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2026-03-27' GROUP BY 1;

-- Expected: 3-5 picks
SELECT game_date, COUNT(*) as picks FROM mlb_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27' GROUP BY 1;
```

And Mar 28 morning:
```sql
SELECT game_date, COUNT(*) as graded FROM mlb_predictions.prediction_accuracy
WHERE game_date = '2026-03-27' GROUP BY 1;
```
