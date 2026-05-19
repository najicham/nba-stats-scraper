# Isotonic Calibration Analysis — 2026-05-18

## TL;DR

**Do not deploy isotonic (or Platt) calibration on the regressor.** The
analysis surfaced a more fundamental issue: the regressor's raw edge
magnitude has near-zero binary predictive power on the current 2026
sample. Calibrators can't add signal — they only redistribute it. Forcing
calibration would collapse the edge spread the best-bets pipeline relies
on for rank ordering, without buying meaningful Brier/log-loss
improvement.

## Source data

- 729 graded picks (`prediction_accuracy` for `system_id =
  'catboost_v2_regressor'`, 2026-04-01 → 2026-05-17)
- Date-ordered 70/30 split: 510 train (through 2026-05-06) / 219 test
- Both OVER and UNDER included

Pulled via:
```bash
bq query --use_legacy_sql=false --format=csv --max_rows=2000 '
SELECT pitcher_lookup, game_date, predicted_strikeouts, line_value,
  ABS(predicted_strikeouts - line_value) AS edge, recommendation,
  prediction_correct, actual_strikeouts
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date >= "2026-04-01"
  AND system_id = "catboost_v2_regressor"
  AND has_prop_line = TRUE
  AND recommendation IN ("OVER","UNDER")
  AND prediction_correct IS NOT NULL
ORDER BY game_date' > /tmp/mlb_regressor_graded.csv
```

## Headline metrics (test set, N=219)

| Calibrator | Brier | LogLoss | Test Brier delta |
|---|---|---|---|
| Sigmoid (current, scale=0.7) | 0.2606 | 0.7152 | — |
| Isotonic (pooled) | 0.2572 | 0.8733 | −0.0034 |
| Platt logistic (pooled) | 0.2520 | 0.6971 | −0.0087 |
| Isotonic (per direction) | 0.2719 | 0.9883 | **+0.0113** |
| **Constant 0.5 (sigmoid scale=0.0)** | **0.2500** | **0.6931** | **−0.0106** |

Pooled Platt looks like the best apparent improvement, but it does so by
collapsing every prediction to ~0.531 — losing all discrimination. The
constant-0.5 baseline scores *better* than any of the calibrators
because the raw edge has essentially no rank signal in this sample.

## Hit rate by edge band (all 729 graded picks)

| Edge band | N | Overall HR | OVER N / HR | UNDER N / HR |
|---|---|---|---|---|
| 0.0–0.5 | 393 | 49.9% | 228 / 46.9% | 165 / 53.9% |
| 0.5–1.0 | 256 | 52.3% | 169 / 53.8% | 87 / 49.4% |
| **1.0–1.5** | **72** | 51.4% | **62 / 45.2%** | 10 / 90.0% |
| 1.5–2.0 | 8 | 75.0% | 7 / 71.4% | 1 / 100.0% |

The current sigmoid (scale=0.7) maps edge=1.0 → p_over≈0.668 and
edge=1.5 → p_over≈0.741. Actuals at those bands are 45.2% (OVER, 62
samples) — exactly the "overconfidence at edge 1.0–1.5 OVER" the
predecessor handoff cited. But the cause isn't a sigmoid scale problem;
the cause is that edge magnitude in this range doesn't track win rate
at all.

## Why a calibrator can't fix this

A calibrator (isotonic or Platt) is a monotonic, non-parametric
transformation of an existing score into well-calibrated probabilities.
It preserves the *rank order* of predictions; it can only redistribute
the score's mass to match observed frequencies. If the score has poor
discrimination (low AUC), the best a calibrator can do is collapse
everything toward the marginal hit rate — which is exactly what Platt
does here, and exactly why the constant 0.5 baseline beats it.

## Why the best-bets pipeline still works

Memory says: raw model HR ≈ 53% at edge 3+, but the BB pipeline runs
60%+ overall and 65%+ at edge 5+. That delta is the signals + filters,
not the model. The filters explicitly compensate for the regressor's
weaknesses:

- `overconfidence_cap` (MAX_EDGE=1.25) caps the regressor exactly in the
  overconfidence band (1.0–1.5).
- `away_over_blocked_policy` blocks the OVER band where HR is worst.
- Signal stacking, regime, halt — all do real work on top of the model.

Deploying a calibrator that flattens the edge distribution would
*hurt* this pipeline because it would compress the rank ordering on
which `MAX_EDGE` and the edge-based sorting depend.

## What would actually help

1. **Add features the regressor doesn't currently use.** The model
   predicts the conditional mean strikeouts but doesn't have features
   for the regimes where edge ≠ outcome. Examples to test: opponent
   contact-rate, batter k-rate distribution shape, weather, umpire (when
   table fills), park-by-handedness splits.
2. **Train a binary side-model on top of the regressor.** Use the
   regressor's predicted strikeouts + features as inputs to a small
   logistic / XGBoost classifier targeting `prediction_correct`. Much
   bigger lift than calibration on the raw score.
3. **Recalibrate quarterly with more data.** When N ≥ 2000 graded
   picks across multiple seasons, isotonic becomes more reliable.

## Artifacts

- `scripts/mlb/isotonic_calibration_analysis.py` — runnable analysis.
- `/tmp/mlb_regressor_isotonic_v1.pkl` — fitted pooled isotonic
  calibrator. Saved for reference; **not for deployment**.
- `/tmp/mlb_regressor_graded.csv` — source data export.

## If you still want to deploy something

Lowest-risk path: change `SIGMOID_SCALE` in
`predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py`
from 0.7 to a value in [0.1, 0.3]. This compresses p_over toward 0.5
without changing rank ordering. The grid search above shows training
Brier is roughly flat across [0.05, 0.30] and the test Brier *worsens*
above 0.3 (overconfident).

But again — the downstream system uses `edge`, not `p_over`, for the
edge floor and MAX_EDGE gates. Changing `SIGMOID_SCALE` mostly affects
the `p_over` field on exported picks (UI display), not pick selection.
