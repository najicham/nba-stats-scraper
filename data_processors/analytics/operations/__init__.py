"""
Analytics processor operations.

This package contains standalone operation modules for BigQuery operations,
failure handling, and other utilities used by analytics processors.
"""

from .failure_handler import categorize_failure

__all__ = ['categorize_failure']
