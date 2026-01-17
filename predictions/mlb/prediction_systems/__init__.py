# predictions/mlb/prediction_systems/__init__.py
"""
MLB Prediction Systems

This package contains all MLB prediction system implementations.
Each system inherits from BaseMLBPredictor and implements its own
prediction logic.

Available Systems:
- v1_baseline: V1.4 baseline system with 25 features
- v1_6_rolling: V1.6 system with 35 features (rolling statcast, BettingPros, line-relative)
- ensemble_v1: Weighted ensemble combining V1 + V1.6

Usage:
    from predictions.mlb.prediction_systems.v1_baseline_predictor import V1BaselinePredictor
    predictor = V1BaselinePredictor(model_path='gs://...')
    prediction = predictor.predict(pitcher_lookup, features, line)
"""

__all__ = [
    'V1BaselinePredictor',
    'V1_6RollingPredictor',
    'MLBEnsembleV1',
]
