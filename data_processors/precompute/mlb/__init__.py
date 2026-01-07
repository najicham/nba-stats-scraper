"""
MLB Precompute Processors

Phase 4 precompute processors for MLB strikeout predictions.

Processors:
- MlbPitcherFeaturesProcessor: Compute 25-feature vector for pitcher K predictions
"""

from .pitcher_features_processor import MlbPitcherFeaturesProcessor

__all__ = [
    'MlbPitcherFeaturesProcessor',
]
