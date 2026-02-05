# Session 128 Final Handoff - Breakout Classifier Complete

**Date:** 2026-02-05
**Duration:** ~4 hours
**Status:** Breakout classifier trained and shadow mode integration complete, deployment in progress

---

## Executive Summary

Session 128 accomplished major breakout detection milestones:
1. **Trained 7 breakout classifier experiments** - Found winning configuration
2. **Winner: EXP_COMBINED_BEST** - AUC 0.7302 (exceeds 0.65 target)
3. **Created shadow mode integration** - Ready for validation
4. **Deployment in progress** - prediction-worker being updated

---

## What Was Accomplished

### 1. Breakout Classifier Experiments (7 total)

| Rank | Experiment | AUC | Config |
|------|------------|-----|--------|
| **1** | **EXP_COMBINED_BEST** | **0.7302** | 1.75x + PPG 6-20 |
| 2 | EXP_BREAKOUT_1_75X | 0.7007 | 1.75x + PPG 8-16 |
| 3 | EXP_WIDER_PPG | 0.6670 | 1.5x + PPG 6-20 |
| 4 | EXP_SESSION126_FEATURES | 0.6433 | 1.5x + PPG 8-16 |
| 5 | EXP_ENHANCED_ALL | 0.6282 | 1.5x + 12 features |
| 6 | BREAKOUT_V1 | 0.6170 | Baseline |
| 7 | EXP_DEEP_MODEL | 0.5932 | Depth 8 (overfitting) |

**Key Findings:**
- Higher breakout threshold (1.75x) works best
- Wider PPG range (6-20) provides more training data
- Deeper models overfit
- CV ratio validated as strong predictor (16-19% importance)

### 2. Winning Model Details

**Model:** models/breakout_exp_EXP_COMBINED_BEST_20260205_084509.cbm

| Property | Value |
|----------|-------|
| AUC-ROC | 0.7302 |
| Precision | 60.5% |
| Optimal Threshold | 0.769 |
| Breakout Multiplier | 1.75x |
| PPG Range | 6-20 |

**Feature Importance:**
1. points_avg_season: 20.9%
2. cv_ratio: 16.6%
3. opponent_def_rating: 15.7%

### 3. Shadow Mode Infrastructure Created

**Files:**
- predictions/worker/prediction_systems/breakout_classifier_v1.py
- ml/experiments/breakout_experiment_runner.py
- Worker integration in predictions/worker/worker.py (~line 1706)

**What shadow mode does:**
- Runs classifier on every prediction
- Stores results in features_snapshot.breakout_shadow
- Does NOT filter bets yet (validation first)

---

## Deployment Status

**CRITICAL: Check if deployment completed**

\`\`\`bash
# Check deployed commit
gcloud run services describe prediction-worker --region=us-west2 \
    --format="value(metadata.labels.commit-sha)"

# Should be: 2e7cf8bf
# If still eb7ce85b, run:
./bin/deploy-service.sh prediction-worker
\`\`\`

---

## Commits

\`\`\`
2e7cf8bf feat: Add breakout classifier with shadow mode (Session 128)
\`\`\`

---

## Immediate Next Steps

1. **Verify deployment completed** (check commit sha)
2. **If needed, deploy prediction-worker**
3. **After predictions run, verify shadow data:**

\`\`\`sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(JSON_VALUE(features_snapshot, '$.breakout_shadow.risk_score') IS NOT NULL) as with_shadow
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-06'
GROUP BY game_date;
\`\`\`

---

## Key Files

| File | Purpose |
|------|---------|
| predictions/worker/prediction_systems/breakout_classifier_v1.py | Classifier |
| predictions/worker/worker.py:1706 | Shadow mode integration |
| models/breakout_exp_EXP_COMBINED_BEST_*.cbm | Best model |
| experiments/results/*.json | Experiment results |

---

*Session 128 Complete - Next: Verify deployment, collect shadow data*
