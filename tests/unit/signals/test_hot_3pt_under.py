"""Tests for Hot3ptUnderSignal."""

import pytest
from ml.signals.hot_3pt_under import Hot3ptUnderSignal


@pytest.fixture
def signal():
    return Hot3ptUnderSignal()


def _make_pred(recommendation='UNDER', line_value=20.0):
    return {'recommendation': recommendation, 'line_value': line_value}


def _make_supp(three_pct_last_3=0.45, three_pct_season=0.33, three_pa_per_game=6.0):
    return {
        'three_pt_stats': {
            'three_pct_last_3': three_pct_last_3,
            'three_pct_season': three_pct_season,
            'three_pa_per_game': three_pa_per_game,
        }
    }


class TestHot3ptUnder:
    def test_qualifies_hot_streak(self, signal):
        """Hot 3PT streak (45% vs 33% season) → qualifies."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.45, three_pct_season=0.33)
        result = signal.evaluate(pred, supplemental=supp)
        assert result.qualifies
        assert result.source_tag == 'hot_3pt_under'
        assert result.metadata['three_pt_diff'] == pytest.approx(0.12, abs=0.001)

    def test_not_hot_enough(self, signal):
        """3PT diff < 10% → does not qualify."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.38, three_pct_season=0.33)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies

    def test_over_direction_blocked(self, signal):
        """OVER direction → does not qualify."""
        pred = _make_pred(recommendation='OVER')
        supp = _make_supp(three_pct_last_3=0.50, three_pct_season=0.33)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies

    def test_low_volume_blocked(self, signal):
        """Low 3PA per game → does not qualify."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.50, three_pct_season=0.33, three_pa_per_game=2.0)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies

    def test_no_supplemental(self, signal):
        """Missing supplemental → does not qualify."""
        result = signal.evaluate(_make_pred(), supplemental=None)
        assert not result.qualifies

    def test_confidence_scales(self, signal):
        """Larger hot streak → higher confidence."""
        pred = _make_pred()
        mild = signal.evaluate(pred, supplemental=_make_supp(0.44, 0.33))
        extreme = signal.evaluate(pred, supplemental=_make_supp(0.55, 0.33))
        assert extreme.confidence > mild.confidence

    def test_just_above_threshold(self, signal):
        """Diff just above 10% → qualifies."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.44, three_pct_season=0.33)
        result = signal.evaluate(pred, supplemental=supp)
        assert result.qualifies

    def test_just_below_threshold(self, signal):
        """Diff just below 10% → does not qualify."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.42, three_pct_season=0.33)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies
