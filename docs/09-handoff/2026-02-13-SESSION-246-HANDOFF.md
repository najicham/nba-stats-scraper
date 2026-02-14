# Session 246 Handoff: Shadow Deploy + Production Promotion Plan

**Date:** 2026-02-13
**Focus:** Shadow deploy RSM50_HUBER_V2, create production plan for 3 candidate models
**Status:** Shadow deployed, comprehensive plan written, study guide created

---

## What Was Done

### 1. Shadow Deployed RSM50_HUBER_V2 (COMPLETED)

First model to pass all 6 governance gates (62.5% HR edge 3+, 88 samples). Deployed as V12 shadow model.

**Steps completed:**
1. Uploaded model to GCS: `gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149.cbm`
2. Updated GCS manifest (`catboost/v9/manifest.json`) with full model metadata
3. Synced manifest to BigQuery `model_registry` table
4. Updated `CATBOOST_V12_MODEL_PATH` env var on `prediction-worker` Cloud Run service
5. Verified service health (5/5 checks pass)
6. Verified registry entry (SHA256: `27d213a82308`, 50 features, shadow status)

**Model runs as `catboost_v12` system_id.** Replaces the previous V12 MAE shadow model. The Huber model generates 2.5x more edge 3+ picks (88 vs 35 in backtest), giving better monitoring signal.

### 2. Established Performance Baselines (Feb 1-12)

| System | Total Graded | Edge 3+ | Edge 3+ Correct | HR 3+ |
|--------|-------------|---------|-----------------|-------|
| catboost_v9 (champion) | 2,288 | 207 | 76 | **36.7%** |
| catboost_v12 (old shadow) | 2,139 | 56 | 28 | **50.0%** |

Champion V9 deeply decayed (36.7% vs 52.4% breakeven). Old V12 shadow at breakeven (50.0%). RSM50_HUBER_V2 backtested at 62.5% — monitoring will confirm if this holds in live shadow.

### 3. Comprehensive Experiment Review

Compiled results from all Sessions 228-245 experiments. See study guide at `docs/08-projects/current/model-improvement-analysis/26-ML-STUDY-GUIDE.md`.

### 4. Extended Eval Blocked by All-Star Break

No games Feb 13-18. Feb 19+ games scheduled but not yet played. Extended eval cannot run until post-ASB data is available (~Feb 20-21).

---

## The 3 Candidate Models

### Model A: RSM50_HUBER_V2 (Shadow Deployed)

| Property | Value |
|----------|-------|
| System ID | `catboost_v12` (shadow) |
| Features | V12 (50, no vegas) |
| Loss | Huber:delta=5 |
| RSM | 0.5 + Depthwise |
| HR Edge 3+ | 62.5% (88 samples) |
| Governance | **6/6 PASS** |
| Status | Shadow deployed, generating live predictions |
| GCS | `gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149.cbm` |
| SHA256 | `27d213a82308215ea40560e6c6973f227f486080cdfad1daadc201d20f0bc916` |

**Strengths:** High volume (88 edge 3+ picks in 12 eval days), balanced direction, passed all gates.
**Risk:** 62.5% HR is good but not spectacular. Huber loss changes feature importance significantly (points_std_last_10 becomes #2 at 20.6%).

### Model B: V12_RSM50_FIXED (Highest Raw HR)

| Property | Value |
|----------|-------|
| Features | V12 (50, no vegas) |
| Loss | MAE |
| RSM | 0.5 + Depthwise |
| HR Edge 3+ | **71.4%** (35 samples) |
| Governance | 5/6 (fails n<50) |
| Status | Needs extended eval |

**Strengths:** Highest HR of any model (71.4%), balanced OVER/UNDER (71.4%/71.4%).
**Risk:** Only 35 edge 3+ samples. MAE loss produces fewer high-edge picks. Need 15+ more samples to pass governance.

### Model C: 3PT Cold Filter (Post-Prediction Rule)

| Property | Value |
|----------|-------|
| Type | Post-prediction rule (not a model) |
| Signal | BOOST OVER when player's last-5-game 3PT% < 28% |
| HR | 77.5% (40 picks, +48% ROI) |
| Anti-signal | FLAG OVER when 3PT% > 50% (51.3% HR, -2.1% ROI) |
| Status | Needs out-of-sample validation |

**Strengths:** Strongest single signal found (77.5%). Market mispricing, not random noise.
**Risk:** n=40 per bucket. Tested on same data that discovered the pattern. Not yet validated OOS.

---

## Production Promotion Plan

### Phase 1: Validate (Feb 19-25, post-ASB)

**Goal:** Confirm models work on live data, not just backtests.

| Task | When | Success Criteria |
|------|------|-----------------|
| Monitor RSM50_HUBER_V2 shadow | Feb 19+ (automatic) | Predictions flowing, no errors |
| Run extended eval for V12_RSM50_FIXED | After Feb 21 (2+ game days) | 50+ edge 3+ samples, HR >= 60% |
| 3PT cold split-sample test | Anytime (SQL) | Signal holds on Feb 1-12 when trained on Nov-Jan |
| 3PT cold forward test | Feb 19+ (after games) | Signal holds on new predictions |

**Monitoring queries:**

```bash
# Shadow predictions flowing?
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions,
       COUNTIF(recommendation IN ('OVER','UNDER') AND ABS(predicted_points - current_points_line) >= 3) as edge_3plus
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-19' AND system_id = 'catboost_v12'
GROUP BY 1 ORDER BY 1"

# Shadow grading (after games finalize)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as graded,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge_3plus,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge_3plus_hits,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
             NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as hr_3plus_pct
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-19' AND system_id = 'catboost_v12'
GROUP BY 1 ORDER BY 1"
```

### Phase 2: Multi-Season Backtest (Can Start Now)

**Goal:** Test models on 2024-25 season data to check they're not overfit to the current season.

The feature store has data back to Nov 2024. We can train on a subset and evaluate on known historical periods.

```bash
# Backtest 1: Train on Nov 2024 - Mar 2025, eval on Apr 2025 (playoffs)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "MULTISEASON_APR25" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --loss-function "Huber:delta=5" \
  --train-start 2024-11-01 --train-end 2025-03-31 \
  --eval-start 2025-04-01 --eval-end 2025-04-15 \
  --walkforward --include-no-line --force --skip-register

# Backtest 2: Train on Nov 2024 - Jan 2025, eval on Feb 2025
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "MULTISEASON_FEB25" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --loss-function "Huber:delta=5" \
  --train-start 2024-11-01 --train-end 2025-01-31 \
  --eval-start 2025-02-01 --eval-end 2025-02-28 \
  --walkforward --include-no-line --force --skip-register

# Backtest 3: Same config, MAE loss (compare Huber vs MAE on old data)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "MULTISEASON_FEB25_MAE" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --train-start 2024-11-01 --train-end 2025-01-31 \
  --eval-start 2025-02-01 --eval-end 2025-02-28 \
  --walkforward --include-no-line --force --skip-register
```

**What we're looking for:**
- Does the V12 + RSM50 + Huber recipe work on a completely different season?
- Is the Feb 2026 eval window an anomaly or is the model genuinely better?
- Does Huber consistently produce more edge 3+ picks without killing HR?

### Phase 3: Promotion Decision (Feb 25-28)

After accumulating shadow data + multi-season backtests:

| Scenario | Action |
|----------|--------|
| Shadow HR 3+ >= 60% AND multi-season confirms | **Promote RSM50_HUBER_V2 to production** |
| V12_RSM50_FIXED passes 50-sample gate at 65%+ | Consider as primary (higher HR, fewer picks) |
| Shadow HR < 52.4% | Keep decayed champion, investigate why backtest didn't hold |
| Multi-season backtest fails | Model is overfit to current season, do NOT promote |

**Promote command:**
```bash
# This replaces the champion model
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149.cbm"
```

Note: Promotion requires updating `CATBOOST_V9_MODEL_PATH` (the champion slot), not the V12 path. The current champion loads from this env var. After promotion, the old `catboost_v9` system_id continues to work — it just loads the new model file.

### Phase 4: 3PT Cold Filter (After Promotion)

Only implement after the base model is promoted and stable. Layering filters on a decayed champion wastes effort.

1. Validate split-sample (Nov-Jan discovery, Feb holdout)
2. Validate forward (Feb 19+ predictions)
3. If both pass: implement as post-prediction confidence boost/flag in the enrichment pipeline
4. Track separately from base model performance

---

## Multi-Season Testing Plan

### Available Historical Data

```bash
# Check feature store date range
bq query --use_legacy_sql=false "
SELECT MIN(game_date) as earliest, MAX(game_date) as latest, COUNT(DISTINCT game_date) as game_days
FROM nba_predictions.ml_feature_store_v2"
```

### Test Matrix

| Test | Train Period | Eval Period | What It Tests |
|------|-------------|-------------|---------------|
| **FEB25** | Nov 2024 - Jan 2025 | Feb 2025 | Does recipe work 1 year ago? |
| **APR25** | Nov 2024 - Mar 2025 | Apr 2025 | Works on late-season/playoff-adjacent? |
| **DEC25** | Nov 2024 - Nov 2025 | Dec 2025 | Works with 13-month training window? |
| **JAN26** | Nov 2025 - Dec 2025 | Jan 2026 | Works on short 2-month training? |
| **Current** | Nov 2025 - Jan 2026 | Feb 2026 | The eval we already have (62.5% / 71.4%) |

**Key questions:**
- Is V12 + RSM + Huber robust across seasons, or overfit to 2025-26?
- Does the optimal training window length matter (2 months vs 5 months vs 13 months)?
- Are there seasonal patterns (e.g., post-ASB players underperform)?

---

## Key Artifacts

- **GCS Model:** `gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149.cbm`
- **SHA256:** `27d213a82308215ea40560e6c6973f227f486080cdfad1daadc201d20f0bc916`
- **System ID:** `catboost_v12` (shadow mode)
- **Study Guide:** `docs/08-projects/current/model-improvement-analysis/26-ML-STUDY-GUIDE.md`
- **Experiment Results:** `docs/08-projects/current/mean-reversion-analysis/07-SESSION-245-AUGMENTATION-FIX-AND-RESULTS.md`

---

## Dead Ends (Carry Forward)

- V14 engineered FG% features (0.00 importance)
- V13 raw FG% features (0.00 importance when V12 works)
- V14 + Huber combo (severe UNDER bias)
- RSM50 + quantile (too UNDER-biased)
- Edge Classifier Model 2 (AUC < 0.50)
- Continuation filter (suppresses best bets)
- Game total 230-234 filter (December artifact)

---

## Schema Reminders

- `prediction_accuracy`: `line_value` (not prop_line), `actual_points` (not actual_stat), `predicted_points`, `prediction_correct`
- `player_prop_predictions`: `current_points_line` (not line_value, not prop_line)
- Feature store JOIN key: `(player_lookup, game_date)` — use `pd.to_datetime().strftime('%Y-%m-%d')`
