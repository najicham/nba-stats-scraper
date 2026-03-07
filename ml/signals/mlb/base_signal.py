"""Base classes for MLB Signal Discovery Framework."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class MLBSignalResult:
    """Result of evaluating a single MLB signal against a prediction."""
    qualifies: bool
    confidence: float  # 0.0 to 1.0
    source_tag: str
    metadata: Dict = field(default_factory=dict)


class BaseMLBSignal(ABC):
    """Abstract base class for all MLB signal evaluators.

    Each signal evaluates a pitcher prediction + supplemental data and returns
    an MLBSignalResult indicating whether the pick qualifies.

    Args:
        prediction: Dict with pitcher_lookup, game_date, predicted_strikeouts,
                    line_value, recommendation, edge, etc.
        features: Dict of feature values from pitcher_game_summary/feature store.
        supplemental: Dict of extra data (Statcast rolling, game context, etc.).
    """

    tag: str = ""
    description: str = ""
    direction: str = ""  # "OVER", "UNDER", or "" for both
    is_shadow: bool = False  # Shadow signals accumulate data but don't affect picks
    is_negative_filter: bool = False  # Negative filters block picks

    @abstractmethod
    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        """Evaluate whether a prediction qualifies for this signal."""
        ...

    def _no_qualify(self) -> MLBSignalResult:
        """Shortcut for a non-qualifying result."""
        return MLBSignalResult(qualifies=False, confidence=0.0, source_tag=self.tag)

    def _qualify(self, confidence: float = 1.0, **metadata) -> MLBSignalResult:
        """Shortcut for a qualifying result."""
        return MLBSignalResult(
            qualifies=True, confidence=confidence,
            source_tag=self.tag, metadata=metadata,
        )
