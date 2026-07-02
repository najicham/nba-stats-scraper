# A4 — Loss Function Bake-off Decision

**Status:** ABANDONED (Session 4, 2026-05-13).
**Verdict:** Keep production RMSE regressor. Skip Session 5 (A4 deploy). Resume roadmap at Session 6.

## Bake-off summary

All three runs used `scripts/mlb/training/season_replay.py`, same harness, same data window (2024-04-01 → 2025-10-01, 6,409 samples, 14-day fixed retrain, 36 features, edge floor 0.75 home / 1.25 away, top-5/day, UNDER disabled).

| Metric | RMSE (control) | Poisson (S3) | Quantile(0.5) (S4) |
|---|---|---|---|
| BB record | **933-603** | 878-581 | 864-601 |
| BB HR | **60.7%** | 60.2% | 59.0% |
| P&L | **+231.5u** | +186.8u | +138.2u |
| ROI | **12.0%** | 10.4% | 7.7% |
| Picks/day | 4.5 | 4.3 | 4.3 |
| Ultra HR | **68.1%** (N=395) | 66.3% (N=338) | 64.5% (N=332) |
| Home HR | **64.3%** | 63.9% | 61.6% |
| Away HR | **56.7%** | 56.0% | 56.2% |
| 2025-04 HR | **53.9%** (+3.1u) | 47.9% (-6.9u) | 50.7% (-3.8u) |

RMSE wins every metric. Δ vs RMSE: Poisson −0.5pp HR / −44.7u P&L; Quantile −1.7pp HR / −93.3u P&L. Quantile is the worst of the three across the board.

## Decision per roadmap branch logic

`05-REVISED-PLAN.md` branch logic:
- Poisson WF flat (< 2pp HR) → fall back to Quantile(0.5).
- If Quantile also flat-to-worse → **abandon A4, skip Session 5, proceed to Session 6 with current RMSE model.**

Both alternatives lose. Production stays on `loss_function='RMSE'` (default in `train_regressor_v2.py:83`). The `--loss-function` CLI flag added in Session 3 remains as the override path for future experiments but is NOT used by the production retrain CF.

## What does NOT happen

- No deploy of a Poisson or Quantile model.
- No model registry change.
- No update to `predictions/mlb/` worker code.
- The Apr-2024 fix (Session 524) and `cap_to_pre_late_season` (NBA Session 514) remain the only production training adjustments.

## What gets retained

- `season_replay.py --loss-function` flag (Session 3, zero behavior change at default).
- `season_replay.py --output-tag` flag (Session 3, namespacing for A/B output dirs).
- Three result directories (`results/mlb_walkforward_a4_{rmse,poisson,quantile}/`) — kept for reference, not committed (gitignored as `results/*/`).

## Why RMSE wins (hypotheses, not validated)

- **Loss alignment with edge mechanic:** The BB pipeline thresholds on raw `predicted_k - line` (which is what RMSE optimizes). Poisson penalizes large-error positive residuals more (negative log-likelihood is asymmetric on count data), which can bias predictions toward the mean and erode high-edge picks. Quantile(0.5) optimizes median, not mean — which is a worse proxy for the line midpoint in a right-skewed K distribution.
- **N is small for distributional gains:** ~3K-5K training rows per retrain × 36 features. The benefit of a count-aware loss matters more at higher dimensionality / lower N. RMSE with depth-6 trees already captures the shape well at this scale.
- **April is the bottleneck:** Both alternatives tanked 2025-04 (47.9% / 50.7% vs RMSE's 53.9%). April is when training cap matters most (Session 514 cap_to_pre_late_season parallel). Loss function changes don't fix the training-data composition problem.

## Reopen criteria

Don't redo A4 unless ALL of:
1. New regressor architecture (V3+, not RMSE+CatBoost on V2 features).
2. ≥ 2x current training volume (full 2022-2025 with replay data infill).
3. Apr-2024 + Apr-2025 are both ≥ 5pp lower vs RMSE baseline.

Until then, A4's verdict is **CLOSED — RMSE wins**.
