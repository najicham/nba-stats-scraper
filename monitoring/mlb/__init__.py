"""
MLB Monitoring Package

Provides monitoring capabilities for the MLB prediction pipeline:
- Gap Detection: Find GCS files not processed to BigQuery
- Freshness Checker: Alert on stale data
- Prediction Coverage: Ensure all pitchers get predictions
- Execution Monitor: Detect stuck processors
- Stall Detector: Identify pipeline halts

Usage:
    from monitoring.mlb import MlbGapDetector, MlbFreshnessChecker

    detector = MlbGapDetector()
    results = detector.check_all(game_date='2025-08-15')
"""

from .mlb_gap_detection import MlbGapDetector
from .mlb_freshness_checker import MlbFreshnessChecker
from .mlb_prediction_coverage import MlbPredictionCoverageMonitor
from .mlb_stall_detector import MlbStallDetector

__all__ = [
    'MlbGapDetector',
    'MlbFreshnessChecker',
    'MlbPredictionCoverageMonitor',
    'MlbStallDetector'
]
