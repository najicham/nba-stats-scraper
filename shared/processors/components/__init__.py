"""
Composable Processor Components Framework

This module provides reusable building blocks for constructing data processors.
Instead of monolithic processor classes, compose processors from discrete components:

    - DataLoaders: Load data from various sources (BigQuery, GCS, APIs)
    - Validators: Validate data quality and integrity
    - Transformers: Transform and compute analytics
    - OutputWriters: Write results to destinations
    - ConfigBuilders: Build processor configuration

Usage:
    from shared.processors.components import (
        BigQueryLoader,
        FieldValidator,
        StatsTransformer,
        BigQueryWriter,
        ComposableProcessor,
    )

    class MyProcessor(ComposableProcessor):
        @classmethod
        def configure(cls):
            return ProcessorConfig(
                name='my_processor',
                loaders=[BigQueryLoader(...)],
                validators=[FieldValidator(...)],
                transformers=[StatsTransformer(...)],
                writers=[BigQueryWriter(...)],
            )

Version: 1.0
Created: 2026-01-23
"""

from .base import (
    Component,
    DataLoader,
    Validator,
    Transformer,
    OutputWriter,
    ProcessorConfig,
    ComposableProcessor,
)
from .loaders import (
    BigQueryLoader,
    FallbackLoader,
    CachedLoader,
)
from .validators import (
    FieldValidator,
    StatisticalValidator,
    SchemaValidator,
)
from .transformers import (
    FieldMapper,
    ComputedFieldTransformer,
    HashTransformer,
    QualityTransformer,
)
from .writers import (
    BigQueryWriter,
    BigQueryMergeWriter,
)
from .config import (
    ProcessorConfigBuilder,
    DependencySpec,
    FieldSpec,
)

__all__ = [
    # Base classes
    'Component',
    'DataLoader',
    'Validator',
    'Transformer',
    'OutputWriter',
    'ProcessorConfig',
    'ComposableProcessor',
    # Loaders
    'BigQueryLoader',
    'FallbackLoader',
    'CachedLoader',
    # Validators
    'FieldValidator',
    'StatisticalValidator',
    'SchemaValidator',
    # Transformers
    'FieldMapper',
    'ComputedFieldTransformer',
    'HashTransformer',
    'QualityTransformer',
    # Writers
    'BigQueryWriter',
    'BigQueryMergeWriter',
    # Config
    'ProcessorConfigBuilder',
    'DependencySpec',
    'FieldSpec',
]
