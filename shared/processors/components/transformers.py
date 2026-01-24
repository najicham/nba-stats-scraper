"""
Data transformation components for the composable processor framework.

Transformers convert raw data into output records:
- Field mapping and renaming
- Computed field calculations
- Hash generation for change detection
- Quality metadata attachment

Version: 1.0
Created: 2026-01-23
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd

from .base import Transformer, ComponentContext

logger = logging.getLogger(__name__)


@dataclass
class FieldMapping:
    """Mapping from source field to output field."""
    source: str
    target: str
    transform: Optional[Callable[[Any], Any]] = None
    default: Any = None


class FieldMapper(Transformer):
    """
    Map and rename fields from source to output schema.

    Handles:
    - Field renaming
    - Type conversion
    - Default values
    - Field-level transformations

    Example:
        mapper = FieldMapper(
            mappings=[
                FieldMapping(source='game_id', target='game_id'),
                FieldMapping(source='points', target='points_scored', transform=int),
                FieldMapping(source='fg_pct', target='field_goal_pct',
                            transform=lambda x: round(x, 3) if x else None),
            ],
            include_unmapped=False,  # Only output mapped fields
        )
    """

    def __init__(
        self,
        mappings: List[FieldMapping],
        include_unmapped: bool = False,
        name: Optional[str] = None,
    ):
        """
        Initialize field mapper.

        Args:
            mappings: List of field mappings
            include_unmapped: If True, include source fields not in mappings
            name: Optional component name
        """
        super().__init__(name=name)
        self.mappings = mappings
        self.include_unmapped = include_unmapped

    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Map fields to output schema.

        Args:
            data: Input data
            context: Processing context

        Returns:
            List of mapped record dictionaries
        """
        # Convert DataFrame to list of dicts if needed
        if isinstance(data, pd.DataFrame):
            records = data.to_dict('records')
        else:
            records = data

        output_records = []
        for record in records:
            output_record = self._map_record(record)
            output_records.append(output_record)

        logger.debug(f"Mapped {len(output_records)} records")
        return output_records

    def _map_record(self, record: Dict) -> Dict:
        """Map a single record."""
        output = {}

        # Apply explicit mappings
        mapped_sources = set()
        for mapping in self.mappings:
            mapped_sources.add(mapping.source)

            if mapping.source in record:
                value = record[mapping.source]

                # Apply transform if specified
                if mapping.transform and value is not None:
                    try:
                        value = mapping.transform(value)
                    except Exception as e:
                        logger.debug(
                            f"Transform failed for {mapping.source}: {e}"
                        )
                        value = mapping.default
            else:
                value = mapping.default

            output[mapping.target] = value

        # Include unmapped fields if requested
        if self.include_unmapped:
            for key, value in record.items():
                if key not in mapped_sources and key not in output:
                    output[key] = value

        return output


@dataclass
class ComputedField:
    """Definition of a computed field."""
    name: str
    compute: Callable[[Dict], Any]
    depends_on: List[str] = field(default_factory=list)
    default: Any = None


class ComputedFieldTransformer(Transformer):
    """
    Add computed fields to records.

    Handles:
    - Derived calculations (e.g., efficiency metrics)
    - Conditional logic
    - Multi-field computations

    Example:
        transformer = ComputedFieldTransformer(
            fields=[
                ComputedField(
                    name='ts_pct',
                    compute=lambda r: calculate_ts_pct(r['points'], r['fga'], r['fta']),
                    depends_on=['points', 'fga', 'fta'],
                ),
                ComputedField(
                    name='home_game',
                    compute=lambda r: r['team_abbr'] == parse_home_team(r['game_id']),
                    depends_on=['team_abbr', 'game_id'],
                ),
            ]
        )
    """

    def __init__(
        self,
        fields: List[ComputedField],
        name: Optional[str] = None,
    ):
        """
        Initialize computed field transformer.

        Args:
            fields: List of computed field definitions
            name: Optional component name
        """
        super().__init__(name=name)
        self.fields = fields

    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Add computed fields to records.

        Args:
            data: Input records
            context: Processing context

        Returns:
            Records with computed fields added
        """
        # Convert DataFrame to list of dicts if needed
        if isinstance(data, pd.DataFrame):
            records = data.to_dict('records')
        else:
            records = list(data)  # Copy to avoid modifying input

        for record in records:
            for field_def in self.fields:
                try:
                    # Check dependencies
                    missing_deps = [
                        dep for dep in field_def.depends_on
                        if dep not in record or record[dep] is None
                    ]

                    if missing_deps:
                        record[field_def.name] = field_def.default
                        continue

                    # Compute value
                    value = field_def.compute(record)
                    record[field_def.name] = value

                except Exception as e:
                    logger.debug(
                        f"Computation failed for {field_def.name}: {e}"
                    )
                    record[field_def.name] = field_def.default

        return records


class HashTransformer(Transformer):
    """
    Add data hash for change detection.

    Computes a SHA256 hash of specified fields to detect meaningful changes.
    Used by downstream processors to skip reprocessing unchanged data.

    Example:
        transformer = HashTransformer(
            hash_fields=['game_id', 'player_id', 'points', 'assists'],
            output_field='data_hash',
        )
    """

    def __init__(
        self,
        hash_fields: List[str],
        output_field: str = 'data_hash',
        hash_length: int = 16,
        name: Optional[str] = None,
    ):
        """
        Initialize hash transformer.

        Args:
            hash_fields: Fields to include in hash calculation
            output_field: Name of output hash field
            hash_length: Number of hash characters to keep
            name: Optional component name
        """
        super().__init__(name=name)
        self.hash_fields = hash_fields
        self.output_field = output_field
        self.hash_length = hash_length

    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Add hash to each record.

        Args:
            data: Input records
            context: Processing context

        Returns:
            Records with hash field added
        """
        # Convert DataFrame to list of dicts if needed
        if isinstance(data, pd.DataFrame):
            records = data.to_dict('records')
        else:
            records = list(data)

        for record in records:
            record[self.output_field] = self._calculate_hash(record)

        return records

    def _calculate_hash(self, record: Dict) -> str:
        """Calculate hash for a single record."""
        hash_data = {
            field: record.get(field)
            for field in self.hash_fields
        }

        # Sort keys for consistent ordering
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)

        # Calculate SHA256 and truncate
        full_hash = hashlib.sha256(sorted_data.encode()).hexdigest()
        return full_hash[:self.hash_length]

    def validate_config(self) -> List[str]:
        """Validate transformer configuration."""
        errors = []
        if not self.hash_fields:
            errors.append(f"{self.name}: hash_fields cannot be empty")
        return errors


class QualityTransformer(Transformer):
    """
    Add quality metadata columns to records.

    Adds standard quality columns based on context:
    - quality_tier
    - quality_score
    - quality_issues
    - data_sources

    Example:
        transformer = QualityTransformer(
            default_tier='gold',
            default_score=100.0,
        )
    """

    def __init__(
        self,
        default_tier: str = 'gold',
        default_score: float = 100.0,
        include_legacy_columns: bool = True,
        name: Optional[str] = None,
    ):
        """
        Initialize quality transformer.

        Args:
            default_tier: Default quality tier
            default_score: Default quality score
            include_legacy_columns: Include backward-compatible columns
            name: Optional component name
        """
        super().__init__(name=name)
        self.default_tier = default_tier
        self.default_score = default_score
        self.include_legacy_columns = include_legacy_columns

    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Add quality metadata to records.

        Args:
            data: Input records
            context: Processing context

        Returns:
            Records with quality columns added
        """
        # Convert DataFrame to list of dicts if needed
        if isinstance(data, pd.DataFrame):
            records = data.to_dict('records')
        else:
            records = list(data)

        # Build quality columns from context
        quality_columns = self._build_quality_columns(context)

        for record in records:
            record.update(quality_columns)

        return records

    def _build_quality_columns(self, context: ComponentContext) -> Dict:
        """Build quality columns from context."""
        # Determine tier and score
        tier = self.default_tier
        score = self.default_score

        # Degrade based on context
        if context.sources_used:
            # Check if backup source was used
            for source_name, metadata in context.source_metadata.items():
                if metadata.get('quality_tier'):
                    tier = metadata['quality_tier']
                if metadata.get('quality_score'):
                    score = metadata['quality_score']

        # Collect issues
        issues = [
            issue['issue_type']
            for issue in context.quality_issues
        ]

        # Build columns
        columns = {
            'quality_tier': tier,
            'quality_score': score,
            'quality_issues': issues,
            'data_sources': context.sources_used,
            'quality_calculated_at': datetime.now(timezone.utc).isoformat(),
        }

        # Add legacy columns if requested
        if self.include_legacy_columns:
            columns.update({
                'is_production_ready': tier in ('gold', 'silver'),
                'data_quality_tier': tier,
                'data_quality_score': score,
                'quality_metadata': {
                    'sources_used': context.sources_used,
                    'issues': issues,
                },
            })

        return columns


class MetadataTransformer(Transformer):
    """
    Add standard metadata columns to records.

    Adds:
    - processed_at: Timestamp
    - created_at: Timestamp
    - source tracking fields

    Example:
        transformer = MetadataTransformer(
            include_source_tracking=True,
        )
    """

    def __init__(
        self,
        include_source_tracking: bool = True,
        additional_fields: Dict[str, Any] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize metadata transformer.

        Args:
            include_source_tracking: Include source_* fields
            additional_fields: Static fields to add to all records
            name: Optional component name
        """
        super().__init__(name=name)
        self.include_source_tracking = include_source_tracking
        self.additional_fields = additional_fields or {}

    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Add metadata to records.

        Args:
            data: Input records
            context: Processing context

        Returns:
            Records with metadata added
        """
        # Convert DataFrame to list of dicts if needed
        if isinstance(data, pd.DataFrame):
            records = data.to_dict('records')
        else:
            records = list(data)

        now = datetime.now(timezone.utc).isoformat()

        for record in records:
            # Add timestamps
            record['processed_at'] = now
            if 'created_at' not in record:
                record['created_at'] = now

            # Add source tracking
            if self.include_source_tracking:
                record.update(self._build_source_tracking(context))

            # Add additional fields
            record.update(self.additional_fields)

        return records

    def _build_source_tracking(self, context: ComponentContext) -> Dict:
        """Build source tracking fields from context."""
        fields = {}

        for source_name, metadata in context.source_metadata.items():
            prefix = f"source_{source_name.replace('.', '_')}"
            fields[f"{prefix}_last_updated"] = metadata.get('loaded_at')
            fields[f"{prefix}_rows_found"] = metadata.get('rows_loaded')

        return fields


class ChainedTransformer(Transformer):
    """
    Chain multiple transformers together.

    Runs transformers in order, passing output of each to the next.

    Example:
        transformer = ChainedTransformer(
            transformers=[
                FieldMapper(mappings=[...]),
                ComputedFieldTransformer(fields=[...]),
                HashTransformer(hash_fields=[...]),
                QualityTransformer(),
                MetadataTransformer(),
            ]
        )
    """

    def __init__(
        self,
        transformers: List[Transformer],
        name: Optional[str] = None,
    ):
        """
        Initialize chained transformer.

        Args:
            transformers: List of transformers to chain
            name: Optional component name
        """
        super().__init__(name=name)
        self.transformers = transformers

    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Run all transformers in sequence.

        Args:
            data: Input data
            context: Processing context

        Returns:
            Fully transformed records
        """
        result = data

        for transformer in self.transformers:
            result = transformer.transform(result, context)

        return result

    def validate_config(self) -> List[str]:
        """Validate all inner transformers."""
        errors = []
        for transformer in self.transformers:
            errors.extend(transformer.validate_config())
        return errors
