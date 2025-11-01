#!/usr/bin/env python3
"""
Path: data_processors/precompute/player_composite_factors/__init__.py

Player Composite Factors Processor Package
==========================================

Precompute processor for calculating composite adjustment factors
that combine fatigue, matchup, pace, and usage context into quantified
scores for Phase 5 predictions.

Week 1-4 Implementation:
    - 4 active factors: fatigue, shot_zone_mismatch, pace, usage_spike
    - 4 deferred factors: referee, look_ahead, matchup_history, momentum (set to 0)
"""

from .player_composite_factors_processor import PlayerCompositeFactorsProcessor

__all__ = ['PlayerCompositeFactorsProcessor']

__version__ = '1.0.0'
__author__ = 'NBA Props Platform Team'
__description__ = 'Player composite factors precompute processor with v4.0 dependency tracking'
