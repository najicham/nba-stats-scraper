"""Deferred (placeholder) factor calculators.

These factors are planned for future versions but return 0.0 for v1_4factors.
"""

from typing import Optional
import pandas as pd
from .base_factor import BaseFactor


class RefereeFavorabilityFactor(BaseFactor):
    """Placeholder for referee favorability factor.

    Future implementation will analyze:
    - Referee foul calling tendencies
    - Player foul drawing rates
    - Historical matchup data

    Current: Returns 0.0
    """

    @property
    def name(self) -> str:
        return 'referee_favorability_score'

    @property
    def context_field(self) -> str:
        return 'referee_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Return 0.0 (placeholder)."""
        return 0.0

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Return placeholder context."""
        return {'status': 'deferred', 'version': 'v1_4factors'}

    def get_range(self) -> tuple[float, float]:
        return (-5.0, 5.0)  # Planned range


class LookAheadPressureFactor(BaseFactor):
    """Placeholder for look-ahead pressure factor.

    Future implementation will analyze:
    - Importance of upcoming games
    - Schedule difficulty ahead
    - Playoff race pressure

    Current: Returns 0.0
    """

    @property
    def name(self) -> str:
        return 'look_ahead_pressure_score'

    @property
    def context_field(self) -> str:
        return 'look_ahead_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Return 0.0 (placeholder)."""
        return 0.0

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Return placeholder context."""
        return {'status': 'deferred', 'version': 'v1_4factors'}

    def get_range(self) -> tuple[float, float]:
        return (-3.0, 3.0)  # Planned range


class TravelImpactFactor(BaseFactor):
    """Placeholder for travel impact factor.

    Future implementation will analyze:
    - Travel distance
    - Time zone changes
    - Back-to-back travel scenarios

    Current: Returns 0.0
    """

    @property
    def name(self) -> str:
        return 'travel_impact_score'

    @property
    def context_field(self) -> str:
        return 'travel_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Return 0.0 (placeholder)."""
        return 0.0

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Return placeholder context."""
        return {'status': 'deferred', 'version': 'v1_4factors'}

    def get_range(self) -> tuple[float, float]:
        return (-2.0, 2.0)  # Planned range


class OpponentStrengthFactor(BaseFactor):
    """Placeholder for opponent strength factor.

    Future implementation will analyze:
    - Opponent defensive rating
    - Head-to-head history
    - Matchup-specific adjustments

    Current: Returns 0.0
    """

    @property
    def name(self) -> str:
        return 'opponent_strength_score'

    @property
    def context_field(self) -> str:
        return 'opponent_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Return 0.0 (placeholder)."""
        return 0.0

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Return placeholder context."""
        return {'status': 'deferred', 'version': 'v1_4factors'}

    def get_range(self) -> tuple[float, float]:
        return (-5.0, 5.0)  # Planned range
