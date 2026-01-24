"""
Pattern Mixins for Optimization

This module contains mixin classes that implement optimization patterns
for processors across all phases (2, 3, 4, 5).

Available Patterns:
- Pattern #1: SmartSkipMixin - Skip processing based on source relevance
- Pattern #3: EarlyExitMixin - Exit early based on conditions (no games, offseason, etc.)
- Pattern #5: CircuitBreakerMixin - Prevent infinite retry loops
- Pattern #6: TimeoutMixin - Processor-level timeout protection
- QualityMixin - Source coverage quality assessment and event logging

Usage:
    from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin, QualityMixin

    class MyProcessor(QualityMixin, SmartSkipMixin, AnalyticsProcessorBase):
        REQUIRED_FIELDS = ['points', 'minutes']
        OPTIONAL_FIELDS = ['plus_minus']

        def process(self):
            with self:  # Auto-flush quality events on exit
                data = self.fetch_data()
                quality = self.assess_quality(data, sources_used=['primary'])
                # ... process data
"""

from .smart_skip_mixin import SmartSkipMixin
from .early_exit_mixin import EarlyExitMixin
from .circuit_breaker_mixin import CircuitBreakerMixin
from .quality_mixin import QualityMixin
from .timeout_mixin import TimeoutMixin, ProcessorTimeoutError, processor_timeout

__all__ = [
    'SmartSkipMixin',
    'EarlyExitMixin',
    'CircuitBreakerMixin',
    'QualityMixin',
    'TimeoutMixin',
    'ProcessorTimeoutError',
    'processor_timeout',
]
