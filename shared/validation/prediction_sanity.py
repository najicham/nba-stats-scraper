"""Prediction sanity validation — catches broken models at write time.

Session 378c: XGBoost model trained with v3.1.2 but production had v2.0.2,
producing predictions ~8.6 points too low (ALL UNDER with edges 8-13).
These overwhelmed CatBoost's legitimate edges in per-player selection.

This module validates individual prediction records before they're written
to BigQuery. Invalid predictions are marked is_active=False so they're
still written (for debugging) but invisible to best bets selection.

Bounds rationale:
- PREDICTED_POINTS_MAX = 80: NBA record is 100, prop lines max ~50.
  Wide bounds to avoid false positives on legit high scorers.
- EDGE_ABS_MAX = 20: XGBoost crisis had edges 8-13. An edge of 20
  means the model predicts 20 points above/below the line — implausible
  for any calibrated model.
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Validation bounds
PREDICTED_POINTS_MIN = 0.0
PREDICTED_POINTS_MAX = 80.0
EDGE_ABS_MAX = 20.0


def validate_prediction_record(record: dict) -> Tuple[bool, Optional[str]]:
    """Validate a single prediction record for sanity.

    Args:
        record: Prediction dict with at minimum 'predicted_points'
                and 'current_points_line' fields.

    Returns:
        Tuple of (is_valid, rejection_reason).
        is_valid=True means the record passes all checks.
        rejection_reason is None when valid, descriptive string when invalid.
    """
    predicted = record.get('predicted_points')
    line = record.get('current_points_line')

    # Skip validation for NO_LINE players (they don't enter best bets)
    if record.get('recommendation') == 'NO_LINE':
        return True, None

    # Check predicted_points range
    if predicted is None:
        return False, "predicted_points is None"

    try:
        predicted = float(predicted)
    except (TypeError, ValueError):
        return False, f"predicted_points not numeric: {predicted}"

    if predicted < PREDICTED_POINTS_MIN:
        return False, f"predicted_points={predicted:.1f} below minimum {PREDICTED_POINTS_MIN}"

    if predicted > PREDICTED_POINTS_MAX:
        return False, f"predicted_points={predicted:.1f} above maximum {PREDICTED_POINTS_MAX}"

    # Check edge (predicted - line) if line is available
    if line is not None:
        try:
            line = float(line)
            edge = abs(predicted - line)
            if edge > EDGE_ABS_MAX:
                return False, (
                    f"edge={edge:.1f} exceeds maximum {EDGE_ABS_MAX} "
                    f"(predicted={predicted:.1f}, line={line:.1f})"
                )
        except (TypeError, ValueError):
            pass  # Line not numeric — skip edge check, still validate predicted_points

    return True, None
