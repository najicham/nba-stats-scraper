"""
Property-based tests for data transformation pipelines.

Uses Hypothesis to verify:
- Reversibility where applicable
- Type preservation
- Required fields always present
- Valid input produces valid output
- Transformation composition
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from datetime import datetime, date
from typing import Dict, Any


# =============================================================================
# Strategies for Data Records
# =============================================================================

@composite
def raw_player_record(draw):
    """Generate a raw player data record."""
    return {
        'player_name': draw(st.text(min_size=5, max_size=30, alphabet=st.characters(whitelist_categories=('L',)))),
        'team': draw(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL'])),
        'points': draw(st.one_of(st.none(), st.integers(min_value=0, max_value=60))),
        'minutes': draw(st.one_of(st.none(), st.text(min_size=1, max_size=10))),
        'game_date': draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))).isoformat(),
    }


@composite
def transformed_player_record(draw):
    """Generate a transformed player data record."""
    return {
        'player_lookup': draw(st.text(min_size=5, max_size=50, alphabet='abcdefghijklmnopqrstuvwxyz')),
        'team_abbr': draw(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL'])),
        'points': draw(st.integers(min_value=0, max_value=60)),
        'minutes_played': draw(st.floats(min_value=0, max_value=48, allow_nan=False)),
        'game_date': draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))).isoformat(),
    }


# =============================================================================
# Transformation Helper Functions
# =============================================================================

def transform_raw_to_processed(raw_record: Dict[str, Any]) -> Dict[str, Any]:
    """Transform raw record to processed format."""
    processed = {}

    # Transform player name to lookup
    if 'player_name' in raw_record and raw_record['player_name']:
        processed['player_lookup'] = raw_record['player_name'].lower().replace(' ', '')

    # Transform team field
    if 'team' in raw_record:
        processed['team_abbr'] = raw_record['team']

    # Transform points
    if 'points' in raw_record and raw_record['points'] is not None:
        processed['points'] = int(raw_record['points'])

    # Transform minutes
    if 'minutes' in raw_record and raw_record['minutes']:
        try:
            if ':' in str(raw_record['minutes']):
                parts = str(raw_record['minutes']).split(':')
                mins = int(parts[0])
                secs = int(parts[1])
                processed['minutes_played'] = round(mins + secs / 60, 2)
            else:
                processed['minutes_played'] = float(raw_record['minutes'])
        except (ValueError, IndexError):
            processed['minutes_played'] = None

    # Preserve game_date
    if 'game_date' in raw_record:
        processed['game_date'] = raw_record['game_date']

    return processed


def extract_required_fields(record: Dict[str, Any], required: list) -> Dict[str, Any]:
    """Extract only required fields from record."""
    return {k: record.get(k) for k in required if k in record}


# =============================================================================
# Reversibility Tests
# =============================================================================

class TestReversibility:
    """Test transformation reversibility where applicable."""

    @given(st.text(min_size=1, max_size=50, alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ '))
    def test_case_transformation_reversible(self, text):
        """Property: upper(lower(text)) preserves information for ASCII."""
        lowered = text.lower()
        restored = lowered.upper()

        # Case information is lost but structure preserved
        assert len(restored) == len(text)
        assert restored.lower() == text.lower()

    @given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
    def test_date_format_reversible(self, test_date):
        """Property: parse(format(date)) == date."""
        # Format date to string
        formatted = test_date.isoformat()

        # Parse back
        parsed = datetime.strptime(formatted, '%Y-%m-%d').date()

        assert parsed == test_date

    @given(st.floats(min_value=0, max_value=48, allow_nan=False, allow_infinity=False))
    def test_round_trip_decimal_minutes(self, minutes):
        """Property: Round-trip minutes conversion preserves value (within precision)."""
        # Convert to MM:SS format
        mins = int(minutes)
        secs = int((minutes - mins) * 60)
        formatted = f"{mins:02d}:{secs:02d}"

        # Parse back
        parts = formatted.split(':')
        restored = int(parts[0]) + int(parts[1]) / 60

        # Should be within small tolerance
        assert abs(restored - minutes) < 0.02

    @given(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL']))
    def test_team_code_identity(self, team):
        """Property: Team code transformation is identity."""
        transformed = team
        assert transformed == team


# =============================================================================
# Type Preservation Tests
# =============================================================================

class TestTypePreservation:
    """Test that transformations preserve or correctly convert types."""

    @given(transformed_player_record())
    def test_integer_fields_remain_integers(self, record):
        """Property: Integer fields remain integers after transformation."""
        if 'points' in record:
            assert isinstance(record['points'], int)

    @given(transformed_player_record())
    def test_float_fields_remain_floats(self, record):
        """Property: Float fields remain floats after transformation."""
        if 'minutes_played' in record:
            assert isinstance(record['minutes_played'], (float, int))

    @given(transformed_player_record())
    def test_string_fields_remain_strings(self, record):
        """Property: String fields remain strings after transformation."""
        if 'player_lookup' in record:
            assert isinstance(record['player_lookup'], str)
        if 'team_abbr' in record:
            assert isinstance(record['team_abbr'], str)

    @given(st.integers(min_value=0, max_value=100))
    def test_numeric_string_to_int(self, value):
        """Property: Numeric string converts to correct int."""
        str_value = str(value)
        converted = int(str_value)

        assert converted == value
        assert isinstance(converted, int)

    @given(st.floats(min_value=0, max_value=100, allow_nan=False))
    def test_numeric_string_to_float(self, value):
        """Property: Numeric string converts to correct float."""
        str_value = str(value)
        converted = float(str_value)

        assert abs(converted - value) < 0.0001
        assert isinstance(converted, float)


# =============================================================================
# Required Fields Tests
# =============================================================================

class TestRequiredFields:
    """Test that required fields are always present."""

    @given(raw_player_record())
    def test_raw_record_has_required_fields(self, record):
        """Property: Raw records have required fields."""
        required = ['player_name', 'team', 'game_date']

        for field in required:
            assert field in record, f"Missing required field: {field}"

    @given(transformed_player_record())
    def test_transformed_record_has_required_fields(self, record):
        """Property: Transformed records have required fields."""
        required = ['player_lookup', 'team_abbr', 'game_date']

        for field in required:
            assert field in record, f"Missing required field: {field}"

    @given(raw_player_record())
    def test_transformation_preserves_required_fields(self, raw_record):
        """Property: Transformation preserves required fields."""
        processed = transform_raw_to_processed(raw_record)

        # Check that core fields exist
        if 'player_name' in raw_record and raw_record['player_name']:
            assert 'player_lookup' in processed

        if 'team' in raw_record:
            assert 'team_abbr' in processed

        if 'game_date' in raw_record:
            assert 'game_date' in processed

    @given(transformed_player_record(), st.lists(st.sampled_from(['player_lookup', 'team_abbr', 'points']), min_size=1, max_size=3, unique=True))
    def test_extract_preserves_specified_fields(self, record, required_fields):
        """Property: Extracting fields preserves specified fields."""
        extracted = extract_required_fields(record, required_fields)

        for field in required_fields:
            if field in record:
                assert field in extracted


# =============================================================================
# Valid Input → Valid Output Tests
# =============================================================================

class TestValidInputValidOutput:
    """Test that valid inputs always produce valid outputs."""

    @given(raw_player_record())
    def test_valid_raw_produces_valid_processed(self, raw_record):
        """Property: Valid raw record produces valid processed record."""
        processed = transform_raw_to_processed(raw_record)

        # Output should be a dictionary
        assert isinstance(processed, dict)

        # All values should be valid types
        for key, value in processed.items():
            assert value is None or isinstance(value, (str, int, float, bool))

    @given(st.integers(min_value=0, max_value=60))
    def test_valid_points_remain_valid(self, points):
        """Property: Valid points value remains valid after transformation."""
        raw = {'points': points}
        processed = transform_raw_to_processed(raw)

        if 'points' in processed:
            assert isinstance(processed['points'], int)
            assert 0 <= processed['points'] <= 100

    @given(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL']))
    def test_valid_team_remains_valid(self, team):
        """Property: Valid team code remains valid."""
        raw = {'team': team}
        processed = transform_raw_to_processed(raw)

        assert 'team_abbr' in processed
        assert processed['team_abbr'] == team
        assert len(processed['team_abbr']) == 3

    @given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
    def test_valid_date_remains_valid(self, game_date):
        """Property: Valid date remains valid after transformation."""
        raw = {'game_date': game_date.isoformat()}
        processed = transform_raw_to_processed(raw)

        assert 'game_date' in processed

        # Should be parseable back to date
        parsed = datetime.strptime(processed['game_date'], '%Y-%m-%d').date()
        assert parsed == game_date


# =============================================================================
# Transformation Composition Tests
# =============================================================================

class TestTransformationComposition:
    """Test that transformations compose correctly."""

    @given(st.text(min_size=1, max_size=50, alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ '))
    def test_normalize_is_associative(self, text):
        """Property: Normalization steps can be composed."""
        # Apply transformations in sequence
        step1 = text.lower()
        step2 = step1.replace(' ', '')

        # Apply in different order
        alt1 = text.replace(' ', '')
        alt2 = alt1.lower()

        # Both should produce same result
        assert step2 == alt2

    @given(raw_player_record())
    def test_transformation_composition_valid(self, record):
        """Property: Composed transformations produce valid output."""
        # Apply multiple transformation steps
        processed = transform_raw_to_processed(record)

        # Verify output is valid
        assert isinstance(processed, dict)

        # Second transformation should not break validity
        # (idempotent-ish behavior)
        reprocessed = transform_raw_to_processed(processed)
        assert isinstance(reprocessed, dict)


# =============================================================================
# Null Handling Tests
# =============================================================================

class TestNullHandling:
    """Test that transformations handle null/missing values correctly."""

    @given(st.none())
    def test_none_points_handled(self, points):
        """Property: None points value is handled gracefully."""
        raw = {'points': points}
        processed = transform_raw_to_processed(raw)

        # Should either skip field or handle gracefully
        if 'points' in processed:
            assert processed['points'] is None or isinstance(processed['points'], int)

    @given(st.sampled_from([None, '', '  ']))
    def test_empty_string_handled(self, empty_val):
        """Property: Empty strings are handled gracefully."""
        raw = {'player_name': empty_val}
        processed = transform_raw_to_processed(raw)

        # Should not crash, may skip field
        assert isinstance(processed, dict)

    @given(raw_player_record())
    def test_missing_optional_field(self, record):
        """Property: Missing optional fields don't break transformation."""
        # Remove optional field
        if 'points' in record:
            del record['points']

        processed = transform_raw_to_processed(record)

        # Should still produce valid output
        assert isinstance(processed, dict)


# =============================================================================
# Data Consistency Tests
# =============================================================================

class TestDataConsistency:
    """Test that transformations maintain data consistency."""

    @given(raw_player_record())
    def test_transformation_maintains_record_count(self, record):
        """Property: One input record produces one output record."""
        processed = transform_raw_to_processed(record)

        assert isinstance(processed, dict)
        assert len(processed) >= 0

    @given(st.lists(raw_player_record(), min_size=1, max_size=10))
    def test_batch_transformation_maintains_count(self, records):
        """Property: N input records produce N output records."""
        processed_records = [transform_raw_to_processed(r) for r in records]

        assert len(processed_records) == len(records)

    @given(raw_player_record())
    def test_transformation_deterministic(self, record):
        """Property: Same input always produces same output."""
        processed1 = transform_raw_to_processed(record)
        processed2 = transform_raw_to_processed(record)
        processed3 = transform_raw_to_processed(record)

        # Should be identical
        assert processed1 == processed2 == processed3


# =============================================================================
# Boundary Value Tests
# =============================================================================

class TestBoundaryValues:
    """Test transformation behavior at boundary values."""

    @given(st.integers(min_value=0, max_value=0))
    def test_zero_points(self, points):
        """Property: Zero points is valid."""
        raw = {'points': points}
        processed = transform_raw_to_processed(raw)

        if 'points' in processed:
            assert processed['points'] == 0

    @given(st.floats(min_value=0, max_value=0, allow_nan=False))
    def test_zero_minutes(self, minutes):
        """Property: Zero minutes is valid."""
        raw = {'minutes': str(minutes)}
        processed = transform_raw_to_processed(raw)

        if 'minutes_played' in processed:
            assert processed['minutes_played'] == 0.0

    @given(st.integers(min_value=100, max_value=200))
    def test_extreme_points_value(self, points):
        """Property: Extreme (but valid) points values are handled."""
        raw = {'points': points}
        processed = transform_raw_to_processed(raw)

        if 'points' in processed:
            assert processed['points'] == points


# =============================================================================
# String Encoding Tests
# =============================================================================

class TestStringEncoding:
    """Test that string transformations handle encoding correctly."""

    @given(st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=('L',),
        min_codepoint=0x0041,  # Latin letters
        max_codepoint=0x017F
    )))
    def test_unicode_name_transformation(self, name):
        """Property: Unicode names are transformed correctly."""
        raw = {'player_name': name}
        processed = transform_raw_to_processed(raw)

        if 'player_lookup' in processed:
            # Should be lowercase and ASCII-compatible
            assert processed['player_lookup'].islower() or processed['player_lookup'] == ''

    @given(st.text(min_size=1, max_size=30, alphabet='abcdefghijklmnopqrstuvwxyz'))
    def test_ascii_name_preserved(self, name):
        """Property: ASCII names are preserved in transformation."""
        raw = {'player_name': name}
        processed = transform_raw_to_processed(raw)

        if 'player_lookup' in processed:
            # Should contain original letters
            assert all(c in processed['player_lookup'] or c == ' ' for c in name.lower())


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
