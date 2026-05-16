"""Bias / MAE decay thresholds — single source of truth.

Used by both:
- `bin/monitoring/bias_decay_monitor.py` (Slack alerter)
- `services/admin_dashboard/blueprints/model_health.py` (admin dashboard view)

Calibrated 2026-05-15 against 5 seasons of `prediction_accuracy` data. See
`docs/08-projects/current/2026-05-15-2025-26-anomaly-rootcause/01-MONITORING-PLAN.md`
for the validation. Primary signal is `mae_gap_7d` (model_mae − vegas_mae);
absolute `pred_bias_7d` is too noisy to alert on directly.

Tuning history:
- v1 (2026-05-15 morning): pred_bias alerts at ±1.5 K — REJECTED, ~60% of
  healthy 2024-25 days exceeded |1.5K| (chronic bias).
- v2 (2026-05-15 evening): switched to mae_gap thresholds below. Median
  mae_gap_7d in 2024-25 healthy = 0.39 K vs 1.44 K in Nov 2025 anomaly.
"""

# `mae_gap_7d > 1.0` on >= 5 of last 7 days → LOST_EDGE (standard Slack alert)
LOST_EDGE_MAE_GAP = 1.0
LOST_EDGE_DAYS_REQUIRED = 5
LOST_EDGE_WINDOW = 7

# `mae_gap_7d > 2.0` on >= 3 of last 5 days → LOSING_BAD (urgent Slack alert)
LOSING_BAD_MAE_GAP = 2.0
LOSING_BAD_DAYS_REQUIRED = 3
LOSING_BAD_WINDOW = 5

# Below this `rolling_n_7d`, suppress all verdicts as INSUFFICIENT_DATA.
MIN_N_FOR_VERDICT = 20

# WATCH gate (display only — does not fire a Slack alert).
WATCH_MAE_GAP = 0.5


def classify_verdict(row: dict) -> str:
    """Classify a single model snapshot into one of:
        LOSING_BAD, LOST_EDGE, WATCH, HEALTHY, INSUFFICIENT_DATA.

    Pure function — no I/O. Most severe verdict wins.

    Expected keys on `row`:
        rolling_n_7d:    int | None  — sample count
        mae_gap_7d:      float | None
        losing_bad_days: int | None  — count of qualifying days in last LOSING_BAD_WINDOW
        lost_edge_days:  int | None  — count of qualifying days in last LOST_EDGE_WINDOW
    """
    n = row.get('rolling_n_7d') or 0
    gap = row.get('mae_gap_7d')
    losing_bad_days = row.get('losing_bad_days') or 0
    lost_edge_days = row.get('lost_edge_days') or 0

    if n < MIN_N_FOR_VERDICT or gap is None:
        return 'INSUFFICIENT_DATA'
    if gap > LOSING_BAD_MAE_GAP and losing_bad_days >= LOSING_BAD_DAYS_REQUIRED:
        return 'LOSING_BAD'
    if gap > LOST_EDGE_MAE_GAP and lost_edge_days >= LOST_EDGE_DAYS_REQUIRED:
        return 'LOST_EDGE'
    if gap > WATCH_MAE_GAP:
        return 'WATCH'
    return 'HEALTHY'
