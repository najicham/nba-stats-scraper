"""Composite factor calculators for player performance adjustments.

This package contains modular factor calculators following the BaseFactor pattern.
Each factor calculates an adjustment score and provides debugging context.

Active Factors (v1_4factors):
- FatigueFactor: Rest, workload, and age impact (-5.0 to 0.0)
- ShotZoneMismatchFactor: Player zone strength vs defense (-10.0 to +10.0)
- PaceFactor: Game pace differential impact (-3.0 to +3.0)
- UsageSpikeFactor: Projected usage increase (+star boost) (-3.0 to +3.0)

Deferred Factors (placeholder):
- RefereeFavorabilityFactor
- LookAheadPressureFactor
- TravelImpactFactor
- OpponentStrengthFactor
"""

from .base_factor import BaseFactor
from .fatigue_factor import FatigueFactor
from .shot_zone_mismatch import ShotZoneMismatchFactor
from .pace_factor import PaceFactor
from .usage_spike_factor import UsageSpikeFactor
from .deferred_factors import (
    RefereeFavorabilityFactor,
    LookAheadPressureFactor,
    TravelImpactFactor,
    OpponentStrengthFactor,
)

# Active factors for v1_4factors
ACTIVE_FACTORS = [
    FatigueFactor(),
    ShotZoneMismatchFactor(),
    PaceFactor(),
    UsageSpikeFactor(),
]

# Deferred factors (return 0.0)
DEFERRED_FACTORS = [
    RefereeFavorabilityFactor(),
    LookAheadPressureFactor(),
    TravelImpactFactor(),
    OpponentStrengthFactor(),
]

# All factors combined
ALL_FACTORS = ACTIVE_FACTORS + DEFERRED_FACTORS


def calculate_all_factors(player_row, player_shot=None, team_defense=None):
    """Calculate all factor scores for a player.

    Args:
        player_row: Player context data (pd.Series or dict)
        player_shot: Player shot zone data (optional)
        team_defense: Team defense data (optional)

    Returns:
        dict: Factor name -> adjustment value
    """
    return {
        factor.name: factor.calculate(player_row, player_shot, team_defense)
        for factor in ALL_FACTORS
    }


def build_all_contexts(player_row, player_shot=None, team_defense=None):
    """Build context JSON for all factors.

    Args:
        player_row: Player context data (pd.Series or dict)
        player_shot: Player shot zone data (optional)
        team_defense: Team defense data (optional)

    Returns:
        dict: Context field name -> context dict
    """
    return {
        factor.context_field: factor.build_context(player_row, player_shot, team_defense)
        for factor in ALL_FACTORS
    }


__all__ = [
    'BaseFactor',
    'FatigueFactor',
    'ShotZoneMismatchFactor',
    'PaceFactor',
    'UsageSpikeFactor',
    'RefereeFavorabilityFactor',
    'LookAheadPressureFactor',
    'TravelImpactFactor',
    'OpponentStrengthFactor',
    'ACTIVE_FACTORS',
    'DEFERRED_FACTORS',
    'ALL_FACTORS',
    'calculate_all_factors',
    'build_all_contexts',
]
