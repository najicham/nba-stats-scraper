"""Signal Discovery Framework for NBA Props Best Bets.

Provides signal evaluation, registry, and aggregation for curating
high-quality picks from multiple independent signal sources.
"""

from ml.signals.base_signal import BaseSignal, SignalResult
from ml.signals.registry import SignalRegistry
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.player_blacklist import compute_player_blacklist

__all__ = ['BaseSignal', 'SignalResult', 'SignalRegistry', 'BestBetsAggregator', 'compute_player_blacklist']
