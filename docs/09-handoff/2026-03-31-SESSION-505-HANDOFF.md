# Session 505 Handoff — 2026-03-31 (Tuesday)

**Context:** Session 504 fixed the governance gate (60% → 53%). Session 505 ran an 8-agent
pre-retrain audit, executed the retrain, then ran a 4-agent investigation into the suspicious
79.66% governance HR. All major blockers from the pick drought are now resolved.

---

## Current System State

### NBA Fleet — FRESH (retrained today)

| Model | State | Enabled | Training Window |
|-------|-------|---------|-----------------|
| `lgbm_v12_noveg_train0126_0323` | active | YES | Jan 26 – Mar 23 |
| `catboost_v12_noveg_train0126_0323` | active | YES | Jan 26 – Mar 23 |

**Fleet diversity restored** — 1 LGBM + 1 CatBoost. `combo_3way`, `book_disagreement`,
`combo_he_ms` signals will fire again.

Deactivated today (BLOCKED/DEGRADING):
- `lgbm_v12_noveg_train0121_0318` (was 41.7% HR)
- `lgbm_v12_noveg_train0103_0227` (was 50.5% HR)
- `catboost_v12_noveg_train0121_0318` (was 52.9% HR)

### Season Record
- **Season: 89-61 (59.3% HR)** — updated with drought losses
- **March: 19-27 (41.3%)** — drought period pulled it down
- **Edge 5+: 65.8%** — still validated

---

## What Happened This Session

### 1. 8-Agent Pre-Retrain Audit (Unanimous GO)

All 8 agents (4 Opus + 4 Sonnet) reviewed the system before retraining. Key confirmations:
- Governance gate confirmed at 53% (deployed 04:44 UTC today)
- 3,393 clean training rows, 50 game dates — sufficient
- Market NORMAL (vegas_mae 5.22), no TIGHT cap interference
- Under-prediction bias confirmed real: -0.87 pts (Jan-Feb) → -2.1 pts (March)
- Coordinator URL correct, all builds SUCCESS, 7 games scheduled
- TIGHT cap bug confirmed but **manual retrain bypasses it** (retrain.sh calls quick_retrain.py directly)

### 2. Retrain Executed

```bash
./bin/retrain.sh --all --enable --no-production-lines
```

Both families passed all governance gates. Old BLOCKED models deactivated.
Registry synced, worker cache refreshed (new revision live).

### 3. Governance HR Investigation (79.66% is an Artifact)

Both new models reported 79.66% HR at edge 3+ (N=59). A 4-agent investigation confirmed
this is **not leakage** but a small-sample artifact:

**Root causes:**
1. **N=59 is tiny** — CI ±10-13pp. Live models in the same window (Mar 24-30) hit only
   46.9–56.9% at edge 3+. The 79.66% is ~4 sigma above the true baseline.
2. **Population mismatch** — backtest cherry-picks 59 edge-3+ players out of 529 (11%).
   In live production, 94%+ of predictions qualify as edge 3+. Completely different pools.
3. **Near-identical models** — both LGBM and CatBoost v12_noveg use same 50 features,
   same window → nearly identical predictions → select same 59 games → same wins.
   LGBM actually got 67.47% at N=83 on the same window (slightly broader threshold).
4. **No leakage confirmed** — ground truth is real actual points from `player_game_summary`.
   `_noveg` excludes all 4 vegas features from training.

**Expected live HR: ~53%** — consistent with 2-season walk-forward baseline.
**Do NOT make promotion decisions based on 79.66%.** Require 2+ days live shadow grading.

---

## Open Items (Priority Order)

### 1. Monitor New Models (ONGOING — next 2 days)

New models have 0 graded predictions. Shadow performance unknown. Monitor:

```bash
# Check predictions generated today
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT system_id, COUNT(*) as preds, ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_edge
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id IN ('lgbm_v12_noveg_train0126_0323','catboost_v12_noveg_train0126_0323')
GROUP BY 1"

# Check graded accuracy after games complete
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT system_id, game_date,
  COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END)*100, 1) as hr,
  COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n
FROM nba_predictions.prediction_accuracy
WHERE game_date >= CURRENT_DATE() - 2
  AND system_id IN ('lgbm_v12_noveg_train0126_0323','catboost_v12_noveg_train0126_0323')
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2"
```

### 2. Fix TIGHT Cap Bug in weekly_retrain CF (fix before next Monday)

File: `orchestration/cloud_functions/weekly_retrain/main.py`
Function: `cap_to_last_loose_market_date()`
Bug: `days_since_tight` measured from shifted `train_end` (14 days behind today), not `date.today()`
Fix: Change `days_since_tight = (train_end - latest_tight).days` → `days_since_tight = (date.today() - latest_tight).days`

This must be fixed before next Monday (April 6) when the weekly CF fires again.
Manual retrain bypasses the bug entirely (retrain.sh passes dates directly to quick_retrain.py).

### 3. MLB `bp_pitcher_props` Scraper — 0 K Lines for Entire 2026 Season

**Critical for MLB accuracy.** The `bp_pitcher_props` scraper has not run since 2025-09-28.
Three features are missing for EVERY pitcher every day:
- `f30_k_avg_vs_line`
- `f32_line_level`
- `f44_over_implied_prob`

Investigation needed: Is the scraper failing silently? Is BettingPros K line URL changed?
Check: `scrapers/` for the bp_pitcher_props scraper implementation and recent scheduler logs.

### 4. `under_low_rsc` Filter — Approaching Demotion Threshold

CF HR = 54.2%, N=24. At N=30 with CF HR >= 55%, auto-demotion triggers.
After new models generate UNDER picks, monitor this carefully.
If UNDER pick volume < 3/day, consider manual demotion:
```bash
python bin/monitoring/reset_demoted_filter.py --filter-name under_low_rsc --dry-run
```

### 5. `usage_surge_over` — Revert to SHADOW

Graduated to PRODUCTION in Session 495 but immediately COLD at 35.3% HR.
Check 7d HR after new model data arrives. If still COLD, revert in `aggregator.py`.

### 6. `friday_over_block` — Watch April 3

87.5% CF HR (N=8) — blocked 7/8 winners last Friday. Not at N=30 threshold yet.
Check `filter_overrides` table after April 3.

---

## New Discovery: Eval HR Inflation Pattern

The governance eval (backtest) inflates HR vs live for structural reasons:
1. Backtest edge-3+ pool (N=59) ≠ live edge-3+ pool (N≈300/day)
2. A 7-day eval window is insufficient for statistical reliability on a 53% model
3. Both models in same family will always score nearly identically (same features, same window)

**Implication for future retrains:** The governance HR is a minimum floor check, not a
performance predictor. A model passing at 53% and a model "passing" at 79% should be
treated identically until live shadow data accumulates. Consider logging this caveat in
the retrain output.

---

## MLB Status

- **K lines missing for entire 2026 season** — `bp_pitcher_props` scraper dead
- **Worker is healthy** — predictions running daily (9-11 non-blocked/day via fallback)
- **Re-trigger today** after lineup data arrives (~11 AM ET):
  ```bash
  TOKEN=$(gcloud auth print-identity-token --audiences=https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app)
  curl -X POST https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/predict-batch \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2026-03-31", "write_to_bigquery": true}'
  ```

---

## Key Commands

```bash
# Check new model predictions today
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT system_id, COUNT(*) as n FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id LIKE '%0126_0323%' GROUP BY 1"

# Check best bets picks today
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE() GROUP BY 1,2 ORDER BY 2"

# Season record
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT COUNTIF(prediction_correct) as wins, COUNTIF(NOT prediction_correct) as losses,
  ROUND(COUNTIF(prediction_correct)*100.0/COUNT(*),1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-11-01' AND is_best_bet = TRUE
  AND prediction_correct IS NOT NULL AND has_prop_line = TRUE"

# Monitor signal health post-retrain
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT signal_name, signal_regime, hr_7d, hit_count_7d
FROM nba_predictions.signal_health_daily
WHERE game_date = CURRENT_DATE() - 1
  AND signal_name IN ('combo_3way','book_disagreement','combo_he_ms','home_under','under_low_rsc','usage_surge_over')
ORDER BY signal_regime, hr_7d DESC"
```

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| (retrain only) | New models registered via BQ — no code commits |

---

## Quick Start for Next Session

```bash
/daily-steering          # Morning report
/validate-daily          # Pipeline health
# Check if new models generating best bets
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, COUNT(*) as picks FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1"
```

If picks are coming in: monitor quality, watch `under_low_rsc` CF HR.
If still drought: check new model predictions are active (`refresh-model-cache.sh --verify`).
Priority fix: TIGHT cap bug before Monday April 6.
