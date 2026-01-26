"""Base class for composite factor calculators."""

from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class BaseFactor(ABC):
    """Abstract base class for composite factor calculators.

    Each factor calculator is responsible for:
    1. Calculating a score/adjustment value from player data
    2. Building context JSON for debugging
    3. Providing metadata about the factor
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Factor name for output field (e.g., 'fatigue_score')."""

    @property
    @abstractmethod
    def context_field(self) -> str:
        """Context JSON field name (e.g., 'fatigue_context_json')."""

    @abstractmethod
    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Calculate the factor adjustment value.

        Args:
            player_row: Player context data
            player_shot: Player shot zone analysis (optional)
            team_defense: Team defense zone analysis (optional)

        Returns:
            Adjustment value (range depends on factor)
        """

    @abstractmethod
    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Build context JSON for debugging and analysis.

        Args:
            player_row: Player context data
            player_shot: Player shot zone analysis (optional)
            team_defense: Team defense zone analysis (optional)

        Returns:
            Dictionary with context information
        """

    def get_range(self) -> tuple[float, float]:
        """Get the expected range for this factor.

        Returns:
            Tuple of (min_value, max_value)
        """
        return (-10.0, 10.0)  # Default range
