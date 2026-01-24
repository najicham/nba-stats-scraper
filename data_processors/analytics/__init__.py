# analytics_processors/__init__.py
"""
Analytics processors for NBA data.
Transforms raw BigQuery data into analytics tables.

Includes async support for processors that benefit from concurrent
BigQuery query execution. See async_analytics_base.py for details.
"""

from .analytics_base import AnalyticsProcessorBase
from .async_analytics_base import AsyncAnalyticsProcessorBase, AsyncQueryBatch
from .async_orchestration import (
    run_processor_with_async_support,
    run_processors_concurrently,
    register_async_processor,
    get_async_processor,
    is_async_processor,
)

__all__ = [
    # Base classes
    'AnalyticsProcessorBase',
    'AsyncAnalyticsProcessorBase',
    'AsyncQueryBatch',
    # Orchestration utilities
    'run_processor_with_async_support',
    'run_processors_concurrently',
    'register_async_processor',
    'get_async_processor',
    'is_async_processor',
]
