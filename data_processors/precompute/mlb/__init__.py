"""
MLB Precompute Processors

Phase 4 precompute processors for MLB strikeout predictions.

Processors:
- MlbPitcherFeaturesProcessor: Compute 35-feature vector for pitcher K predictions
- MlbLineupKAnalysisProcessor: Bottom-up K expectations from lineup data
"""

from .pitcher_features_processor import MlbPitcherFeaturesProcessor
from .lineup_k_analysis_processor import MlbLineupKAnalysisProcessor

__all__ = [
    'MlbPitcherFeaturesProcessor',
    'MlbLineupKAnalysisProcessor',
]
