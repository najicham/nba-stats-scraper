"""Regression tests for the edge calibrator leak guard + direction-aware serving.

Background (2026-07-03): the v2026-07-03 calibrator was fit on backfill-leaked
`prediction_accuracy` strata (~123.8K rows all graded in one 2026-01-10 batch)
and its loader was direction-blind (every pick routed to the OVER+UNDER-pooled
`_global` curve). These tests pin both fixes:
  1. validate_training_provenance refuses bulk-batch / unverified-late-graded
     training frames.
  2. EdgeCalibrator serves direction-correct pooled fallbacks for unknown
     families, and win_prob_loader passes the family through unmangled.
"""

import numpy as np
import pandas as pd
import pytest

from ml.calibration.edge_calibrator import (
    EdgeCalibrator,
    LeakedTrainingDataError,
    validate_training_provenance,
)


def _frame(game_dates, graded_at):
    return pd.DataFrame({'game_date': game_dates, 'graded_at': graded_at})


class TestValidateTrainingProvenance:
    def test_bulk_batch_rejected(self):
        # The 2026-01-10 signature: one graded_at day spanning seasons of games
        df = _frame(
            pd.date_range('2023-01-01', periods=500, freq='D'),
            pd.Timestamp('2026-01-10', tz='UTC'),
        )
        with pytest.raises(LeakedTrainingDataError, match='bulk-batch'):
            validate_training_provenance(df)

    def test_bulk_batch_allowed_when_provenance_verified(self):
        # Live predictions graded late in one batch are harmless once each
        # row's pre-game created_at has been verified.
        df = _frame(
            pd.date_range('2026-01-01', periods=500, freq='D'),
            pd.Timestamp('2026-02-22', tz='UTC'),
        )
        validate_training_provenance(df, verified=True)  # must not raise

    def test_unverified_late_grades_rejected(self):
        dates = pd.date_range('2026-01-01', periods=100, freq='D')
        df = _frame(dates, dates.tz_localize('UTC') + pd.Timedelta(days=30))
        with pytest.raises(LeakedTrainingDataError, match='provenance'):
            validate_training_provenance(df)

    def test_prompt_grading_passes(self):
        dates = pd.date_range('2026-01-01', periods=100, freq='D')
        df = _frame(dates, dates.tz_localize('UTC') + pd.Timedelta(days=1))
        validate_training_provenance(df)  # must not raise

    def test_missing_graded_at_rejected(self):
        df = pd.DataFrame({'game_date': pd.date_range('2026-01-01', periods=5)})
        with pytest.raises(LeakedTrainingDataError, match='graded_at'):
            validate_training_provenance(df)

    def test_empty_frame_passes(self):
        validate_training_provenance(
            pd.DataFrame({'game_date': [], 'graded_at': []})
        )


def _fitted_calibrator(under_rate=0.60, over_rate=0.45, n_per_side=300):
    rng = np.random.default_rng(7)
    n = 2 * n_per_side
    edges = rng.uniform(1, 8, n)
    dirs = np.array(['UNDER'] * n_per_side + ['OVER'] * n_per_side)
    rates = np.where(dirs == 'UNDER', under_rate, over_rate)
    wins = (rng.uniform(0, 1, n) < rates).astype(float)
    fams = np.array(['v12_mae'] * n)
    return EdgeCalibrator().fit(edges, wins, fams, dirs, min_samples=100)


class TestDirectionAwareFallback:
    def test_pooled_direction_keys_are_fit(self):
        cal = _fitted_calibrator()
        assert '_pooled_UNDER' in cal.calibrators
        assert '_pooled_OVER' in cal.calibrators
        assert '_global' in cal.calibrators

    def test_unknown_family_gets_direction_correct_curve(self):
        # The direction-blind bug: unknown families routed to _global, which
        # pools OVER+UNDER. With distinct base rates, the pooled-direction
        # fallback must keep the directions apart.
        cal = _fitted_calibrator(under_rate=0.60, over_rate=0.45)
        p_under = cal.predict_win_prob(4.0, 'unknown_family', 'UNDER')
        p_over = cal.predict_win_prob(4.0, 'unknown_family', 'OVER')
        assert p_under > p_over + 0.05

    def test_none_family_uses_pooled_direction(self):
        cal = _fitted_calibrator()
        assert cal.predict_win_prob(4.0, None, 'UNDER') == pytest.approx(
            cal.predict_win_prob(4.0, 'unknown_family', 'UNDER')
        )

    def test_known_family_key_preferred(self):
        cal = _fitted_calibrator()
        # v12_mae was fit — its curve must be served, not the pooled one
        assert 'v12_mae_UNDER' in cal.calibrators
        p = cal.predict_win_prob(4.0, 'v12_mae', 'UNDER')
        expected = float(cal.calibrators['v12_mae_UNDER'].predict([4.0])[0])
        assert p == pytest.approx(expected)


class TestWinProbLoader:
    def test_missing_calibrator_dir_returns_none(self, tmp_path, monkeypatch):
        import ml.calibration.win_prob_loader as loader
        monkeypatch.setattr(loader, 'CALIBRATOR_DIR', tmp_path / 'nope')
        monkeypatch.setattr(loader, '_calibrator', None)
        monkeypatch.setattr(loader, '_load_attempted', False)
        assert loader.attach_win_prob(5.0, 'v12_noveg_mae', 'UNDER') is None

    def test_invalid_direction_returns_none(self, tmp_path, monkeypatch):
        import ml.calibration.win_prob_loader as loader
        monkeypatch.setattr(loader, 'CALIBRATOR_DIR', tmp_path / 'nope')
        monkeypatch.setattr(loader, '_calibrator', None)
        monkeypatch.setattr(loader, '_load_attempted', False)
        assert loader.attach_win_prob(5.0, 'v12_noveg_mae', 'PUSH') is None
