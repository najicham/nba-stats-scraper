"""Tests for LineDriftedDownUnderSignal."""

import pytest
from ml.signals.line_drifted_down_under import LineDriftedDownUnderSignal


@pytest.fixture
def signal():
    return LineDriftedDownUnderSignal()


def _make_pred(recommendation='UNDER', bp_line_movement=-0.3):
    return {'recommendation': recommendation, 'bp_line_movement': bp_line_movement}


class TestLineDriftedDownUnder:
    def test_qualifies_small_drift(self, signal):
        """Line drifted down -0.3 → qualifies."""
        result = signal.evaluate(_make_pred(bp_line_movement=-0.3))
        assert result.qualifies
        assert result.source_tag == 'line_drifted_down_under'
        assert result.metadata['bp_line_movement'] == -0.3

    def test_qualifies_at_boundary(self, signal):
        """Line drifted -0.2 → qualifies (within -0.5 to -0.1)."""
        result = signal.evaluate(_make_pred(bp_line_movement=-0.2))
        assert result.qualifies

    def test_too_small_drift(self, signal):
        """Line moved -0.05 → does not qualify (above -0.1 threshold)."""
        result = signal.evaluate(_make_pred(bp_line_movement=-0.05))
        assert not result.qualifies

    def test_too_large_drift(self, signal):
        """Line dropped -0.6 → does not qualify (below -0.5 threshold)."""
        result = signal.evaluate(_make_pred(bp_line_movement=-0.6))
        assert not result.qualifies

    def test_positive_movement_blocked(self, signal):
        """Line rose → does not qualify."""
        result = signal.evaluate(_make_pred(bp_line_movement=0.5))
        assert not result.qualifies

    def test_over_direction_blocked(self, signal):
        """OVER direction → does not qualify."""
        result = signal.evaluate(_make_pred(recommendation='OVER', bp_line_movement=-0.3))
        assert not result.qualifies

    def test_no_movement_data(self, signal):
        """Missing bp_line_movement → does not qualify."""
        result = signal.evaluate({'recommendation': 'UNDER'})
        assert not result.qualifies

    def test_none_movement(self, signal):
        """None bp_line_movement → does not qualify."""
        result = signal.evaluate({'recommendation': 'UNDER', 'bp_line_movement': None})
        assert not result.qualifies

    def test_exactly_at_min_boundary(self, signal):
        """Line drifted exactly -0.5 → qualifies (inclusive lower bound)."""
        result = signal.evaluate(_make_pred(bp_line_movement=-0.5))
        assert result.qualifies

    def test_just_above_min_boundary(self, signal):
        """Line drifted -0.49 → qualifies (within range)."""
        result = signal.evaluate(_make_pred(bp_line_movement=-0.49))
        assert result.qualifies
