"""
Calculator Modules for Player Game Summary

Extracted calculators for specific computation tasks:
- QualityScorer: Source coverage quality scoring
- ChangeDetector: Meaningful change detection
"""

from .quality_scorer import QualityScorer
from .change_detector import ChangeDetectorWrapper

__all__ = [
    'QualityScorer',
    'ChangeDetectorWrapper',
]
