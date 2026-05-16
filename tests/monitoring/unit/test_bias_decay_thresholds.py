"""Unit tests for shared.monitoring.bias_decay_thresholds.classify_verdict.

The function is a pure dict-in/string-out classifier used by both the Slack
alerter (`bin/monitoring/bias_decay_monitor.py`) and the admin dashboard
(`services/admin_dashboard/blueprints/model_health.py`). Coverage matters
because a boundary flip (e.g. `>` → `>=`) would change alert behavior with no
type-check signal.
"""

import pytest

from shared.monitoring.bias_decay_thresholds import (
    classify_verdict,
    LOST_EDGE_MAE_GAP,
    LOST_EDGE_DAYS_REQUIRED,
    LOSING_BAD_MAE_GAP,
    LOSING_BAD_DAYS_REQUIRED,
    MIN_N_FOR_VERDICT,
    WATCH_MAE_GAP,
)


def _row(**overrides):
    """Build a row dict with sane defaults; override only the field under test."""
    base = {
        'rolling_n_7d': MIN_N_FOR_VERDICT,  # exactly at floor, so passes
        'mae_gap_7d': 0.0,
        'losing_bad_days': 0,
        'lost_edge_days': 0,
    }
    base.update(overrides)
    return base


class TestClassifyVerdict:
    # --- INSUFFICIENT_DATA ---

    def test_below_min_n_returns_insufficient_data(self):
        assert classify_verdict(_row(rolling_n_7d=MIN_N_FOR_VERDICT - 1)) == 'INSUFFICIENT_DATA'

    def test_null_gap_returns_insufficient_data(self):
        assert classify_verdict(_row(mae_gap_7d=None)) == 'INSUFFICIENT_DATA'

    def test_zero_n_returns_insufficient_data(self):
        assert classify_verdict(_row(rolling_n_7d=0)) == 'INSUFFICIENT_DATA'

    def test_missing_n_returns_insufficient_data(self):
        # rolling_n_7d absent — defaults to 0
        row = {'mae_gap_7d': 0.0, 'losing_bad_days': 0, 'lost_edge_days': 0}
        assert classify_verdict(row) == 'INSUFFICIENT_DATA'

    # --- LOSING_BAD (most severe) ---

    def test_losing_bad_fires(self):
        row = _row(mae_gap_7d=2.5, losing_bad_days=LOSING_BAD_DAYS_REQUIRED,
                   lost_edge_days=LOST_EDGE_DAYS_REQUIRED)
        assert classify_verdict(row) == 'LOSING_BAD'

    def test_losing_bad_just_below_gap_threshold_falls_to_lost_edge(self):
        # gap == LOSING_BAD_MAE_GAP (not strictly greater) → not losing_bad
        row = _row(mae_gap_7d=LOSING_BAD_MAE_GAP, losing_bad_days=5,
                   lost_edge_days=LOST_EDGE_DAYS_REQUIRED)
        assert classify_verdict(row) == 'LOST_EDGE'

    def test_losing_bad_needs_enough_days(self):
        # gap above threshold but only 2 days (need 3)
        row = _row(mae_gap_7d=2.5, losing_bad_days=LOSING_BAD_DAYS_REQUIRED - 1,
                   lost_edge_days=LOST_EDGE_DAYS_REQUIRED)
        assert classify_verdict(row) == 'LOST_EDGE'

    # --- LOST_EDGE ---

    def test_lost_edge_fires(self):
        row = _row(mae_gap_7d=1.5, lost_edge_days=LOST_EDGE_DAYS_REQUIRED)
        assert classify_verdict(row) == 'LOST_EDGE'

    def test_lost_edge_just_below_gap_threshold_falls_to_watch(self):
        # gap == LOST_EDGE_MAE_GAP (= 1.0) is not strictly > 1.0 → falls through
        row = _row(mae_gap_7d=LOST_EDGE_MAE_GAP,
                   lost_edge_days=LOST_EDGE_DAYS_REQUIRED)
        assert classify_verdict(row) == 'WATCH'  # since 1.0 > 0.5 (WATCH gate)

    def test_lost_edge_needs_enough_days(self):
        # gap above 1.0 but only 4 days qualifying (need 5)
        row = _row(mae_gap_7d=1.5, lost_edge_days=LOST_EDGE_DAYS_REQUIRED - 1)
        assert classify_verdict(row) == 'WATCH'

    # --- WATCH ---

    def test_watch_fires_on_single_day_over_threshold(self):
        row = _row(mae_gap_7d=0.7)  # > 0.5 but doesn't qualify for LOST_EDGE
        assert classify_verdict(row) == 'WATCH'

    def test_watch_at_exact_threshold_falls_to_healthy(self):
        # gap == WATCH_MAE_GAP (= 0.5) is not strictly > 0.5
        row = _row(mae_gap_7d=WATCH_MAE_GAP)
        assert classify_verdict(row) == 'HEALTHY'

    # --- HEALTHY ---

    def test_healthy_at_zero_gap(self):
        assert classify_verdict(_row(mae_gap_7d=0.0)) == 'HEALTHY'

    def test_healthy_at_negative_gap(self):
        # Model BETTER than Vegas — healthy
        assert classify_verdict(_row(mae_gap_7d=-0.5)) == 'HEALTHY'

    def test_min_n_floor_is_inclusive(self):
        # rolling_n_7d == MIN_N_FOR_VERDICT is NOT insufficient
        assert classify_verdict(_row(rolling_n_7d=MIN_N_FOR_VERDICT)) == 'HEALTHY'

    # --- Severity ordering / regression guards ---

    def test_losing_bad_outranks_lost_edge_when_both_qualify(self):
        # gap > 2.0 AND losing_bad_days >= 3 AND lost_edge_days >= 5
        # All three conditions met — should report LOSING_BAD (most severe wins)
        row = _row(mae_gap_7d=2.5, losing_bad_days=4,
                   lost_edge_days=LOST_EDGE_DAYS_REQUIRED + 1)
        assert classify_verdict(row) == 'LOSING_BAD'

    def test_missing_days_counts_default_to_zero(self):
        # Row missing losing_bad_days/lost_edge_days keys altogether
        row = {'rolling_n_7d': MIN_N_FOR_VERDICT, 'mae_gap_7d': 2.5}
        assert classify_verdict(row) == 'WATCH'  # gap > 0.5 but no qualifying days
