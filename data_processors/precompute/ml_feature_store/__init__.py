# File: data_processors/precompute/ml_feature_store/__init__.py
"""
ML Feature Store V2 - Phase 4 Precompute Processor

Generates and caches 25 ML features for all active NBA players nightly.
Features are read by Phase 5 prediction systems throughout the day.

Package Contents:
- MLFeatureStoreProcessor: Main processor class
- FeatureExtractor: Query Phase 3/4 tables
- FeatureCalculator: Calculate derived features (6 total)
- QualityScorer: Calculate feature quality score (0-100)
- BatchWriter: Write features in batches of 100 rows
"""

from .ml_feature_store_processor import MLFeatureStoreProcessor

__all__ = ['MLFeatureStoreProcessor']

__version__ = '1.0.0'
