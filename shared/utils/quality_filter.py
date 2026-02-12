"""
Quality filtering utilities for predictions and subsets.

Session 209: Prevents quality filtering divergence between materializer/exporters.
Critical finding: Low-quality predictions have 12.1% hit rate vs 50.3% for green quality.
"""

from typing import Dict, Any


def should_include_prediction(prediction: Dict[str, Any], subset_config: Dict[str, Any]) -> bool:
    """
    Check if prediction meets quality requirements for subset.

    Args:
        prediction: Prediction dict with quality_alert_level field
        subset_config: Subset config with require_quality_ready flag

    Returns:
        True if prediction should be included

    Session 209: Prevents quality filtering divergence between materializer/exporters.
    This shared function ensures consistent quality filtering across:
    - subset_materializer.py (lines 379-384)
    - all_subsets_picks_exporter.py (lines 498-501)
    - Any future exporters that use quality filtering

    Example:
        >>> pred = {'quality_alert_level': 'green', ...}
        >>> subset = {'require_quality_ready': True, ...}
        >>> should_include_prediction(pred, subset)
        True

        >>> pred = {'quality_alert_level': 'red', ...}
        >>> should_include_prediction(pred, subset)
        False

        >>> subset = {'require_quality_ready': False, ...}
        >>> should_include_prediction(pred, subset)
        True  # No quality requirement, include all
    """
    require_quality = subset_config.get('require_quality_ready')

    # If quality not required, include all predictions
    if not require_quality:
        return True

    # If quality required, only include green quality predictions
    quality_level = prediction.get('quality_alert_level')
    return quality_level == 'green'
