"""
Unit tests for composable processor components.

Tests each component type in isolation to verify behavior.

Usage:
    pytest shared/processors/components/tests/test_components.py -v

Version: 1.0
Created: 2026-01-23
"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import Mock, MagicMock

from shared.processors.components.base import ComponentContext
from shared.processors.components.validators import (
    FieldValidator,
    StatisticalValidator,
    StatCheck,
    FieldSpec,
)
from shared.processors.components.transformers import (
    FieldMapper,
    FieldMapping,
    ComputedFieldTransformer,
    ComputedField,
    HashTransformer,
    QualityTransformer,
    ChainedTransformer,
)
from shared.processors.components.config import (
    ProcessorConfigBuilder,
    DependencySpec,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_context():
    """Create a sample processing context for tests."""
    return ComponentContext(
        start_date='2025-01-01',
        end_date='2025-01-01',
        run_id='test123',
        project_id='test-project',
    )


@pytest.fixture
def sample_data():
    """Create sample DataFrame for tests."""
    return pd.DataFrame({
        'game_id': ['20250101_ATL_BOS', '20250101_CHI_DEN'],
        'team_abbr': ['ATL', 'CHI'],
        'points': [105, 98],
        'fg_made': [40, 35],
        'fg_attempted': [85, 80],
        'ft_attempted': [20, 25],
        'turnovers': [12, 15],
        'offensive_rebounds': [10, 8],
    })


# =============================================================================
# VALIDATOR TESTS
# =============================================================================

class TestFieldValidator:
    """Tests for FieldValidator component."""

    def test_validates_required_fields_present(self, sample_context, sample_data):
        """Test that no issues are recorded when required fields are present."""
        validator = FieldValidator(
            required_fields=['game_id', 'team_abbr', 'points']
        )

        result = validator.validate(sample_data, sample_context)

        assert result.equals(sample_data)  # Data unchanged
        assert len(sample_context.quality_issues) == 0

    def test_records_missing_required_field(self, sample_context, sample_data):
        """Test that missing required field is recorded as critical issue."""
        validator = FieldValidator(
            required_fields=['game_id', 'missing_field']
        )

        validator.validate(sample_data, sample_context)

        assert len(sample_context.quality_issues) == 1
        issue = sample_context.quality_issues[0]
        assert issue['issue_type'] == 'missing_required_field'
        assert issue['severity'] == 'critical'
        assert issue['identifier'] == 'missing_field'

    def test_records_missing_optional_field(self, sample_context, sample_data):
        """Test that missing optional field is recorded as warning."""
        validator = FieldValidator(
            optional_fields=['plus_minus']  # Not in sample_data
        )

        validator.validate(sample_data, sample_context)

        assert len(sample_context.quality_issues) == 1
        issue = sample_context.quality_issues[0]
        assert issue['issue_type'] == 'missing_optional_field'
        assert issue['severity'] == 'warning'

    def test_validates_field_spec_min_value(self, sample_context):
        """Test that values below minimum are flagged."""
        data = pd.DataFrame({
            'points': [105, -5, 98]  # -5 is invalid
        })

        validator = FieldValidator(
            field_specs={
                'points': FieldSpec(name='points', min_value=0)
            }
        )

        validator.validate(data, sample_context)

        assert len(sample_context.quality_issues) == 1
        issue = sample_context.quality_issues[0]
        assert issue['issue_type'] == 'value_below_minimum'


class TestStatisticalValidator:
    """Tests for StatisticalValidator component."""

    def test_detects_impossible_stats(self, sample_context):
        """Test detection of FG makes > FG attempts."""
        data = pd.DataFrame({
            'fg_made': [45, 35],
            'fg_attempted': [40, 80],  # 45 > 40 is impossible
        })

        validator = StatisticalValidator(
            checks=[
                StatCheck(
                    name='fg_check',
                    check_type='lte',
                    field1='fg_made',
                    field2_or_min='fg_attempted',
                    description='FG makes <= FG attempts',
                )
            ]
        )

        validator.validate(data, sample_context)

        assert len(sample_context.quality_issues) == 1
        issue = sample_context.quality_issues[0]
        assert issue['issue_type'] == 'statistical_anomaly'
        assert issue['details']['violation_count'] == 1

    def test_validates_between_range(self, sample_context):
        """Test that values outside range are flagged."""
        data = pd.DataFrame({
            'points': [105, 250, 98]  # 250 is outside 50-200 range
        })

        validator = StatisticalValidator(
            checks=[
                StatCheck(
                    name='points_range',
                    check_type='between',
                    field1='points',
                    field2_or_min=50,
                    max_val=200,
                    description='Points between 50 and 200',
                )
            ]
        )

        validator.validate(data, sample_context)

        assert len(sample_context.quality_issues) == 1


# =============================================================================
# TRANSFORMER TESTS
# =============================================================================

class TestFieldMapper:
    """Tests for FieldMapper component."""

    def test_maps_fields_correctly(self, sample_context, sample_data):
        """Test basic field renaming."""
        mapper = FieldMapper(
            mappings=[
                FieldMapping(source='points', target='points_scored'),
                FieldMapping(source='fg_made', target='fg_makes'),
            ]
        )

        result = mapper.transform(sample_data, sample_context)

        assert len(result) == 2
        assert 'points_scored' in result[0]
        assert 'fg_makes' in result[0]
        assert result[0]['points_scored'] == 105

    def test_applies_transform_function(self, sample_context, sample_data):
        """Test that transform functions are applied."""
        mapper = FieldMapper(
            mappings=[
                FieldMapping(
                    source='points',
                    target='points_doubled',
                    transform=lambda x: x * 2
                ),
            ]
        )

        result = mapper.transform(sample_data, sample_context)

        assert result[0]['points_doubled'] == 210  # 105 * 2

    def test_uses_default_for_missing_field(self, sample_context, sample_data):
        """Test that default is used when source field is missing."""
        mapper = FieldMapper(
            mappings=[
                FieldMapping(source='missing', target='output', default='N/A'),
            ]
        )

        result = mapper.transform(sample_data, sample_context)

        assert result[0]['output'] == 'N/A'


class TestComputedFieldTransformer:
    """Tests for ComputedFieldTransformer component."""

    def test_computes_field_from_dependencies(self, sample_context):
        """Test that computed fields use dependency values."""
        data = [
            {'a': 10, 'b': 5},
            {'a': 20, 'b': 3},
        ]

        transformer = ComputedFieldTransformer(
            fields=[
                ComputedField(
                    name='sum',
                    compute=lambda r: r['a'] + r['b'],
                    depends_on=['a', 'b'],
                ),
            ]
        )

        result = transformer.transform(data, sample_context)

        assert result[0]['sum'] == 15
        assert result[1]['sum'] == 23

    def test_uses_default_when_dependency_missing(self, sample_context):
        """Test that default is used when dependency is missing."""
        data = [
            {'a': 10},  # Missing 'b'
        ]

        transformer = ComputedFieldTransformer(
            fields=[
                ComputedField(
                    name='sum',
                    compute=lambda r: r['a'] + r['b'],
                    depends_on=['a', 'b'],
                    default=-1,
                ),
            ]
        )

        result = transformer.transform(data, sample_context)

        assert result[0]['sum'] == -1


class TestHashTransformer:
    """Tests for HashTransformer component."""

    def test_adds_hash_field(self, sample_context):
        """Test that hash field is added to records."""
        data = [
            {'game_id': 'G1', 'points': 100},
            {'game_id': 'G2', 'points': 105},
        ]

        transformer = HashTransformer(
            hash_fields=['game_id', 'points'],
            output_field='data_hash',
        )

        result = transformer.transform(data, sample_context)

        assert 'data_hash' in result[0]
        assert len(result[0]['data_hash']) == 16  # Default hash length

    def test_same_data_produces_same_hash(self, sample_context):
        """Test that identical records produce identical hashes."""
        data = [
            {'game_id': 'G1', 'points': 100},
            {'game_id': 'G1', 'points': 100},  # Same as first
        ]

        transformer = HashTransformer(hash_fields=['game_id', 'points'])

        result = transformer.transform(data, sample_context)

        assert result[0]['data_hash'] == result[1]['data_hash']

    def test_different_data_produces_different_hash(self, sample_context):
        """Test that different records produce different hashes."""
        data = [
            {'game_id': 'G1', 'points': 100},
            {'game_id': 'G1', 'points': 101},  # Different points
        ]

        transformer = HashTransformer(hash_fields=['game_id', 'points'])

        result = transformer.transform(data, sample_context)

        assert result[0]['data_hash'] != result[1]['data_hash']


class TestChainedTransformer:
    """Tests for ChainedTransformer component."""

    def test_chains_transformers_in_order(self, sample_context):
        """Test that transformers are executed in sequence."""
        data = [
            {'value': 10},
        ]

        # First transformer doubles, second adds 5
        transformer = ChainedTransformer(
            transformers=[
                ComputedFieldTransformer(
                    fields=[
                        ComputedField(
                            name='doubled',
                            compute=lambda r: r['value'] * 2,
                            depends_on=['value'],
                        ),
                    ]
                ),
                ComputedFieldTransformer(
                    fields=[
                        ComputedField(
                            name='final',
                            compute=lambda r: r['doubled'] + 5,
                            depends_on=['doubled'],
                        ),
                    ]
                ),
            ]
        )

        result = transformer.transform(data, sample_context)

        assert result[0]['doubled'] == 20
        assert result[0]['final'] == 25


# =============================================================================
# CONFIG BUILDER TESTS
# =============================================================================

class TestProcessorConfigBuilder:
    """Tests for ProcessorConfigBuilder."""

    def test_builds_basic_config(self):
        """Test that builder creates valid config."""
        config = (ProcessorConfigBuilder('test_processor')
            .with_table('test_dataset', 'test_table')
            .with_loader(
                query='SELECT * FROM table',
                source_name='test_source',
            )
            .with_insert_writer()
            .build()
        )

        assert config.name == 'test_processor'
        assert config.table_name == 'test_table'
        assert config.dataset_id == 'test_dataset'
        assert len(config.loaders) == 1
        assert len(config.writers) == 1

    def test_adds_dependency(self):
        """Test that dependencies are added correctly."""
        config = (ProcessorConfigBuilder('test')
            .with_table('ds', 'tbl')
            .with_dependency(
                table='source.table',
                critical=True,
                max_age_hours_warn=12,
            )
            .with_loader(query='SELECT 1', source_name='x')
            .with_insert_writer()
            .build()
        )

        assert 'source.table' in config.dependencies
        assert config.dependencies['source.table']['critical'] is True
        assert config.dependencies['source.table']['max_age_hours_warn'] == 12

    def test_raises_on_invalid_config(self):
        """Test that build raises error on invalid config."""
        with pytest.raises(ValueError) as exc_info:
            # Missing loaders and writers
            (ProcessorConfigBuilder('test')
                .with_table('ds', 'tbl')
                .build()
            )

        assert 'loader' in str(exc_info.value).lower()


class TestDependencySpec:
    """Tests for DependencySpec."""

    def test_converts_to_dict(self):
        """Test that DependencySpec converts to dict format."""
        spec = DependencySpec(
            table='nba_raw.player_stats',
            description='Player statistics',
            critical=True,
            max_age_hours_warn=24,
        )

        result = spec.to_dict()

        assert result['field_prefix'] == 'source_player_stats'
        assert result['description'] == 'Player statistics'
        assert result['critical'] is True
        assert result['max_age_hours_warn'] == 24
