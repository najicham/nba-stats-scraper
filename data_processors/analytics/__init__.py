# analytics_processors/__init__.py
"""
Analytics processors for NBA data.
Transforms raw BigQuery data into analytics tables.
"""

from .analytics_base import AnalyticsProcessorBase

__all__ = ['AnalyticsProcessorBase']
