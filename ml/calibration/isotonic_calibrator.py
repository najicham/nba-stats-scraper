#!/usr/bin/env python3
"""
Isotonic Regression Calibrator for Post-Hoc Prediction Adjustment.

Session 124: Recommended by Opus agents as lowest-risk approach to fix any
remaining tier bias. Learns a monotonic calibration curve from data.

Usage:
    # Train calibrator
    PYTHONPATH=. python ml/calibration/isotonic_calibrator.py

    # In production, load and apply:
    calibrator = IsotonicCalibrator()
    calibrator.load(Path('models/isotonic_calibrator_v9.pkl'))
    calibrated = calibrator.calibrate(raw_predictions)
"""

import numpy as np
import joblib
from pathlib import Path
from sklearn.isotonic import IsotonicRegression


class IsotonicCalibrator:
    """Post-hoc calibration using isotonic regression."""

    def __init__(self):
        self.calibrator = IsotonicRegression(out_of_bounds='clip')
        self.fitted = False

    def fit(self, predictions: np.ndarray, actuals: np.ndarray, verbose: bool = True):
        """
        Fit calibration curve from validation data.

        Args:
            predictions: Raw model predictions (uncalibrated)
            actuals: Actual points scored
            verbose: Print tier-specific calibration stats
        """
        # Convert to float to handle BigQuery Decimal types
        predictions = np.array(predictions, dtype=np.float64)
        actuals = np.array(actuals, dtype=np.float64)

        self.calibrator.fit(predictions, actuals)
        self.fitted = True

        if verbose:
            calibrated = self.calibrator.predict(predictions)

            print("\n--- Calibration Statistics ---")
            for tier, (low, high) in [
                ('Bench (<8)', (0, 8)),
                ('Role (8-15)', (8, 15)),
                ('Starter (15-25)', (15, 25)),
                ('Star (25+)', (25, 100))
            ]:
                mask = (predictions >= low) & (predictions < high)
                if mask.sum() > 10:
                    pred_mean = predictions[mask].mean()
                    actual_mean = actuals[mask].mean()
                    cal_mean = calibrated[mask].mean()
                    print(f"  {tier}: pred={pred_mean:.1f}, actual={actual_mean:.1f}, "
                          f"calibrated={cal_mean:.1f}, adjustment={cal_mean - pred_mean:+.1f}")

        return self

    def calibrate(self, predictions: np.ndarray) -> np.ndarray:
        """Apply learned calibration to new predictions."""
        if not self.fitted:
            raise ValueError("Calibrator not fitted. Call fit() first.")
        predictions = np.array(predictions, dtype=np.float64)
        return self.calibrator.predict(predictions)

    def save(self, path: Path):
        """Save fitted calibrator."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.calibrator, path)
        print(f"Saved calibrator to {path}")

    def load(self, path: Path):
        """Load fitted calibrator."""
        self.calibrator = joblib.load(path)
        self.fitted = True
        print(f"Loaded calibrator from {path}")


def train_isotonic_calibrator():
    """Train isotonic calibrator on recent validation data."""
    from google.cloud import bigquery

    client = bigquery.Client(project='nba-props-platform')

    # Get predictions vs actuals from last 60 days, hold out last 7 for validation
    train_query = """
    SELECT
        predicted_points,
        actual_points
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
      AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND actual_points IS NOT NULL
      AND predicted_points IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    """

    df_train = client.query(train_query).to_dataframe()
    print(f"Training calibrator on {len(df_train):,} samples (60-7 days ago)")

    calibrator = IsotonicCalibrator()
    calibrator.fit(df_train['predicted_points'].values, df_train['actual_points'].values)

    # Validate on held-out week
    val_query = """
    SELECT predicted_points, actual_points, line_value
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND actual_points IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    """
    val_df = client.query(val_query).to_dataframe()

    if len(val_df) > 0:
        raw_mae = np.abs(val_df['predicted_points'] - val_df['actual_points']).mean()
        calibrated = calibrator.calibrate(val_df['predicted_points'].values)
        cal_mae = np.abs(calibrated - val_df['actual_points']).mean()

        print(f"\n--- Validation (last 7 days, {len(val_df)} samples) ---")
        print(f"  Raw MAE: {raw_mae:.3f}")
        print(f"  Calibrated MAE: {cal_mae:.3f}")
        print(f"  Improvement: {raw_mae - cal_mae:+.3f}")

        # Check hit rate impact
        lines = val_df['line_value'].values
        actuals = val_df['actual_points'].values
        raw_preds = val_df['predicted_points'].values

        raw_over_correct = ((raw_preds > lines) & (actuals > lines)).sum()
        raw_under_correct = ((raw_preds < lines) & (actuals < lines)).sum()
        raw_hr = (raw_over_correct + raw_under_correct) / len(val_df) * 100

        cal_over_correct = ((calibrated > lines) & (actuals > lines)).sum()
        cal_under_correct = ((calibrated < lines) & (actuals < lines)).sum()
        cal_hr = (cal_over_correct + cal_under_correct) / len(val_df) * 100

        print(f"\n--- Hit Rate Impact ---")
        print(f"  Raw hit rate: {raw_hr:.1f}%")
        print(f"  Calibrated hit rate: {cal_hr:.1f}%")
        print(f"  Change: {cal_hr - raw_hr:+.1f}%")

    # Save
    calibrator.save(Path('models/isotonic_calibrator_v9.pkl'))

    return calibrator


if __name__ == '__main__':
    train_isotonic_calibrator()
