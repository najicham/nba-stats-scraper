"""
Path: data_processors/precompute/team_defense_zone_analysis/__init__.py

Team Defense Zone Analysis Processor Package

This package contains the processor that aggregates team defensive performance
by court zone (paint, mid-range, perimeter) over the last 15 games.

The processor analyzes how well each NBA team defends different areas of the court
and compares their performance to league averages. This data is used by player
prediction models to adjust for opponent defensive strength.

Key Features:
- Processes all 30 NBA teams nightly
- Analyzes 3 zones: paint, mid-range, three-point
- Compares to dynamic league averages
- Identifies defensive strengths and weaknesses
- Handles early season with placeholder rows
- Uses v4.0 dependency tracking
"""

from .team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor

__all__ = ['TeamDefenseZoneAnalysisProcessor']