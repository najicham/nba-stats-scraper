"""
Configuration builders for composable processors.

Provides declarative configuration for:
- Dependencies
- Field specifications
- Processor assembly

Version: 1.0
Created: 2026-01-23
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from .base import (
    ProcessorConfig,
    DataLoader,
    Validator,
    Transformer,
    OutputWriter,
)
from .loaders import BigQueryLoader, FallbackLoader, FallbackSource
from .validators import FieldValidator, StatisticalValidator, StatCheck, FieldSpec
from .transformers import (
    FieldMapper,
    FieldMapping,
    ComputedFieldTransformer,
    ComputedField,
    HashTransformer,
    QualityTransformer,
    MetadataTransformer,
    ChainedTransformer,
)
from .writers import BigQueryWriter, BigQueryMergeWriter

logger = logging.getLogger(__name__)


@dataclass
class DependencySpec:
    """
    Specification for an upstream data dependency.

    Used to declare what data the processor depends on.
    """
    table: str
    description: str = ''
    date_field: str = 'game_date'
    check_type: str = 'date_range'  # 'date_range', 'date_match', 'lookback'
    expected_count_min: int = 1
    max_age_hours_warn: int = 24
    max_age_hours_fail: int = 72
    critical: bool = True
    field_prefix: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for AnalyticsProcessorBase compatibility."""
        return {
            'field_prefix': self.field_prefix or f"source_{self.table.split('.')[-1]}",
            'description': self.description,
            'date_field': self.date_field,
            'check_type': self.check_type,
            'expected_count_min': self.expected_count_min,
            'max_age_hours_warn': self.max_age_hours_warn,
            'max_age_hours_fail': self.max_age_hours_fail,
            'critical': self.critical,
        }


class ProcessorConfigBuilder:
    """
    Builder for constructing ProcessorConfig declaratively.

    Provides a fluent API for assembling processor configurations.

    Example:
        config = (ProcessorConfigBuilder('player_game_summary')
            .with_table('nba_analytics', 'player_game_summary')
            .with_dependency(
                table='nba_raw.nbac_gamebook_player_stats',
                critical=True,
            )
            .with_loader(
                query='SELECT * FROM ... WHERE game_date BETWEEN ...',
                source_name='player_stats',
            )
            .with_field_validation(
                required=['game_id', 'player_id', 'points'],
                optional=['plus_minus'],
            )
            .with_computed_fields([
                ('ts_pct', calculate_ts_pct, ['points', 'fga', 'fta']),
                ('home_game', is_home_game, ['team_abbr', 'game_id']),
            ])
            .with_hash_fields(['game_id', 'player_id', 'points', 'assists'])
            .with_merge_writer(['game_id', 'player_lookup'])
            .build()
        )
    """

    def __init__(self, name: str):
        """
        Initialize config builder.

        Args:
            name: Processor name
        """
        self.name = name
        self.dataset_id = 'nba_analytics'
        self.table_name = ''
        self.dependencies: Dict[str, Dict] = {}
        self.loaders: List[DataLoader] = []
        self.validators: List[Validator] = []
        self.transformers: List[Transformer] = []
        self.writers: List[OutputWriter] = []
        self.hash_fields: List[str] = []
        self.primary_key_fields: List[str] = []
        self.processing_strategy = 'MERGE_UPDATE'

    def with_table(
        self,
        dataset_id: str,
        table_name: str
    ) -> 'ProcessorConfigBuilder':
        """Set output table."""
        self.dataset_id = dataset_id
        self.table_name = table_name
        return self

    def with_dependency(
        self,
        table: str,
        description: str = '',
        date_field: str = 'game_date',
        critical: bool = True,
        max_age_hours_warn: int = 24,
        max_age_hours_fail: int = 72,
    ) -> 'ProcessorConfigBuilder':
        """Add an upstream dependency."""
        spec = DependencySpec(
            table=table,
            description=description,
            date_field=date_field,
            critical=critical,
            max_age_hours_warn=max_age_hours_warn,
            max_age_hours_fail=max_age_hours_fail,
        )
        self.dependencies[table] = spec.to_dict()
        return self

    def with_loader(
        self,
        query: str,
        source_name: str,
        description: str = '',
    ) -> 'ProcessorConfigBuilder':
        """Add a BigQuery loader."""
        loader = BigQueryLoader(
            query=query,
            source_name=source_name,
            description=description,
        )
        self.loaders.append(loader)
        return self

    def with_fallback_loader(
        self,
        sources: List[Dict],
        on_all_fail: str = 'error',
    ) -> 'ProcessorConfigBuilder':
        """
        Add a fallback loader.

        Args:
            sources: List of source configs, each with:
                - name: Source name
                - query: SQL query
                - quality_tier: 'gold', 'silver', 'bronze'
                - quality_score: 0-100
            on_all_fail: 'error', 'skip', or 'placeholder'
        """
        fallback_sources = []
        for source in sources:
            inner_loader = BigQueryLoader(
                query=source['query'],
                source_name=source['name'],
            )
            fallback_sources.append(FallbackSource(
                name=source['name'],
                loader=lambda ctx, l=inner_loader: l.load(ctx),
                quality_tier=source.get('quality_tier', 'gold'),
                quality_score=source.get('quality_score', 100.0),
            ))

        loader = FallbackLoader(
            sources=fallback_sources,
            on_all_fail=on_all_fail,
        )
        self.loaders.append(loader)
        return self

    def with_field_validation(
        self,
        required: List[str] = None,
        optional: List[str] = None,
        specs: Dict[str, Dict] = None,
    ) -> 'ProcessorConfigBuilder':
        """
        Add field validation.

        Args:
            required: List of required field names
            optional: List of optional field names
            specs: Dict of field_name -> spec dict
        """
        field_specs = {}
        if specs:
            for name, spec_dict in specs.items():
                field_specs[name] = FieldSpec(name=name, **spec_dict)

        validator = FieldValidator(
            required_fields=required or [],
            optional_fields=optional or [],
            field_specs=field_specs,
        )
        self.validators.append(validator)
        return self

    def with_statistical_checks(
        self,
        checks: List[Dict],
    ) -> 'ProcessorConfigBuilder':
        """
        Add statistical validation checks.

        Args:
            checks: List of check configs, each with:
                - name: Check name
                - check_type: 'lte', 'lt', 'gte', 'gt', 'between'
                - field1: First field
                - field2_or_min: Second field or min value
                - max_val: Max value (for 'between')
                - description: Human-readable description
        """
        stat_checks = []
        for check in checks:
            stat_checks.append(StatCheck(**check))

        validator = StatisticalValidator(checks=stat_checks)
        self.validators.append(validator)
        return self

    def with_field_mappings(
        self,
        mappings: List[Dict],
        include_unmapped: bool = False,
    ) -> 'ProcessorConfigBuilder':
        """
        Add field mapping transformer.

        Args:
            mappings: List of mapping configs, each with:
                - source: Source field name
                - target: Target field name
                - transform: Optional transform function
                - default: Optional default value
            include_unmapped: Include fields not in mappings
        """
        field_mappings = []
        for m in mappings:
            field_mappings.append(FieldMapping(**m))

        transformer = FieldMapper(
            mappings=field_mappings,
            include_unmapped=include_unmapped,
        )
        self.transformers.append(transformer)
        return self

    def with_computed_fields(
        self,
        fields: List[tuple],
    ) -> 'ProcessorConfigBuilder':
        """
        Add computed field transformer.

        Args:
            fields: List of (name, compute_func, depends_on) tuples
        """
        computed_fields = []
        for item in fields:
            name, compute_func, depends_on = item[:3]
            default = item[3] if len(item) > 3 else None
            computed_fields.append(ComputedField(
                name=name,
                compute=compute_func,
                depends_on=depends_on,
                default=default,
            ))

        transformer = ComputedFieldTransformer(fields=computed_fields)
        self.transformers.append(transformer)
        return self

    def with_hash_fields(
        self,
        fields: List[str],
        output_field: str = 'data_hash',
    ) -> 'ProcessorConfigBuilder':
        """Add hash transformer for change detection."""
        self.hash_fields = fields
        transformer = HashTransformer(
            hash_fields=fields,
            output_field=output_field,
        )
        self.transformers.append(transformer)
        return self

    def with_quality_tracking(
        self,
        default_tier: str = 'gold',
        default_score: float = 100.0,
    ) -> 'ProcessorConfigBuilder':
        """Add quality metadata transformer."""
        transformer = QualityTransformer(
            default_tier=default_tier,
            default_score=default_score,
        )
        self.transformers.append(transformer)
        return self

    def with_metadata(
        self,
        include_source_tracking: bool = True,
        additional_fields: Dict = None,
    ) -> 'ProcessorConfigBuilder':
        """Add metadata transformer."""
        transformer = MetadataTransformer(
            include_source_tracking=include_source_tracking,
            additional_fields=additional_fields or {},
        )
        self.transformers.append(transformer)
        return self

    def with_insert_writer(self) -> 'ProcessorConfigBuilder':
        """Add simple INSERT writer."""
        writer = BigQueryWriter(
            dataset_id=self.dataset_id,
            table_name=self.table_name,
        )
        self.writers.append(writer)
        return self

    def with_merge_writer(
        self,
        primary_key_fields: List[str],
    ) -> 'ProcessorConfigBuilder':
        """Add MERGE (upsert) writer."""
        self.primary_key_fields = primary_key_fields
        writer = BigQueryMergeWriter(
            dataset_id=self.dataset_id,
            table_name=self.table_name,
            primary_key_fields=primary_key_fields,
        )
        self.writers.append(writer)
        return self

    def with_processing_strategy(self, strategy: str) -> 'ProcessorConfigBuilder':
        """Set processing strategy."""
        self.processing_strategy = strategy
        return self

    def build(self) -> ProcessorConfig:
        """
        Build the final ProcessorConfig.

        Validates configuration and returns the config object.
        """
        # Add default transformers if none specified
        if not self.transformers:
            self.transformers = [
                QualityTransformer(),
                MetadataTransformer(),
            ]

        # Build config
        config = ProcessorConfig(
            name=self.name,
            table_name=self.table_name,
            dataset_id=self.dataset_id,
            loaders=self.loaders,
            validators=self.validators,
            transformers=self.transformers,
            writers=self.writers,
            dependencies=self.dependencies,
            hash_fields=self.hash_fields,
            primary_key_fields=self.primary_key_fields,
            processing_strategy=self.processing_strategy,
        )

        # Validate
        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid processor config: {', '.join(errors)}")

        return config


def quick_processor_config(
    name: str,
    table_name: str,
    query: str,
    primary_keys: List[str],
    hash_fields: List[str] = None,
    required_fields: List[str] = None,
    computed_fields: List[tuple] = None,
    dataset_id: str = 'nba_analytics',
) -> ProcessorConfig:
    """
    Quick helper to create a simple processor config.

    For more complex configurations, use ProcessorConfigBuilder.

    Args:
        name: Processor name
        table_name: Output table name
        query: Main SQL query
        primary_keys: Primary key fields for MERGE
        hash_fields: Fields to include in change detection hash
        required_fields: Required input fields
        computed_fields: List of (name, func, deps) tuples
        dataset_id: Output dataset

    Returns:
        ProcessorConfig ready to use

    Example:
        config = quick_processor_config(
            name='simple_processor',
            table_name='my_table',
            query='SELECT * FROM source WHERE date = {start_date}',
            primary_keys=['id'],
        )
    """
    builder = (ProcessorConfigBuilder(name)
        .with_table(dataset_id, table_name)
        .with_loader(query, source_name=name)
    )

    if required_fields:
        builder.with_field_validation(required=required_fields)

    if computed_fields:
        builder.with_computed_fields(computed_fields)

    if hash_fields:
        builder.with_hash_fields(hash_fields)

    builder.with_quality_tracking()
    builder.with_metadata()
    builder.with_merge_writer(primary_keys)

    return builder.build()
