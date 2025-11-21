"""
Pattern Mixins for Optimization

This module contains mixin classes that implement optimization patterns
for processors across all phases (2, 3, 4, 5).

Available Patterns:
- Pattern #1: SmartSkipMixin - Skip processing based on source relevance
- Pattern #3: EarlyExitMixin - Exit early based on conditions (no games, offseason, etc.)
- Pattern #5: CircuitBreakerMixin - Prevent infinite retry loops

Usage:
    from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin
    
    class MyProcessor(AnalyticsProcessorBase, SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin):
        RELEVANT_SOURCES = {
            'nba_raw.nbac_gamebook_player_stats': True,
            'nba_raw.odds_api_props': False
        }
"""

from .smart_skip_mixin import SmartSkipMixin
from .early_exit_mixin import EarlyExitMixin
from .circuit_breaker_mixin import CircuitBreakerMixin

__all__ = ['SmartSkipMixin', 'EarlyExitMixin', 'CircuitBreakerMixin']
