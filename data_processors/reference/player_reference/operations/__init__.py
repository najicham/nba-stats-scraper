"""
Operations modules for roster registry CRUD and normalization.

Handles database operations, data aggregation, and normalization logic.
"""

from .registry_ops import RegistryOperations
from .normalizer import RosterNormalizer

__all__ = [
    'RegistryOperations',
    'RosterNormalizer',
]
