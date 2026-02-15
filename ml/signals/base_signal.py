"""Base classes for the Signal Discovery Framework."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SignalResult:
    """Result of evaluating a single signal against a prediction."""
    qualifies: bool
    confidence: float  # 0.0 to 1.0
    source_tag: str
    metadata: Dict = field(default_factory=dict)


class BaseSignal(ABC):
    """Abstract base class for all signal evaluators.

    Each signal evaluates a prediction + supplemental data and returns
    a SignalResult indicating whether the pick qualifies and with what
    confidence.

    Args:
        prediction: Dict from prediction_accuracy (backtest) or
                    player_prop_predictions (live). Expected keys:
                    player_lookup, game_id, game_date, predicted_points,
                    line_value, recommendation, edge, prediction_correct, etc.
        features: Dict of feature store values keyed by name (indices 0-53).
        supplemental: Dict of extra data (V12 prediction, 3PT stats, etc.).
    """

    tag: str = ""
    description: str = ""

    @abstractmethod
    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        """Evaluate whether a prediction qualifies for this signal."""
        ...

    def _no_qualify(self) -> SignalResult:
        """Shortcut for a non-qualifying result."""
        return SignalResult(qualifies=False, confidence=0.0, source_tag=self.tag)
