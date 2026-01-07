"""
MLB Statcast Scrapers (via pybaseball)

Scrapers for advanced Statcast metrics from Baseball Savant.
Uses the pybaseball library to access pitch-level and advanced metrics.

Requirements:
  pip install pybaseball

Available Scrapers:
- mlb_statcast_pitcher: Advanced pitcher metrics (velocity, spin, whiff rate)

Key Metrics for K Predictions:
- SwStr% (Swinging Strike Rate): Most predictive metric for strikeout rate
- Chase Rate: How often batters swing at pitches outside the zone
- K%: Raw strikeout percentage
- Zone%: Percentage of pitches in the strike zone
"""

from .mlb_statcast_pitcher import MlbStatcastPitcherScraper

__all__ = [
    'MlbStatcastPitcherScraper',
]
