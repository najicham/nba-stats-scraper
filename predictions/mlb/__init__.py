# predictions/mlb/__init__.py
"""
MLB Prediction Module

Pitcher strikeout predictions using XGBoost model trained on historical data.
"""

from .pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor

__all__ = ['PitcherStrikeoutsPredictor']
