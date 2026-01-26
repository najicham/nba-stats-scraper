"""
Regression tests for safe iterator usage patterns.

Tests prevent recurrence of "StopIteration: iterator of async" bug from Jan 25, 2026.

The bug occurred when using next() on BigQuery result iterators without providing
a default value, causing StopIteration exceptions to bubble up unexpectedly.

Safe patterns tested:
1. next(iter(result), None) - Always provide default
2. next(result, None) - Always provide default
3. next((x for x in items), None) - Always provide default for generators

Unsafe patterns that would cause bugs:
- next(iter(result)) - NO DEFAULT - will raise StopIteration
- next(result) - NO DEFAULT - will raise StopIteration

Reference: Jan 25 bug fixes in data_processors/ and predictions/

Created: 2026-01-25 (Session 18 Continuation)
"""

import pytest
from typing import Iterator, List


class MockBigQueryResult:
    """Mock BigQuery result iterator for testing"""
    def __init__(self, rows: List[dict]):
        self._rows = rows
        self._index = 0

    def __iter__(self):
        return iter(self._rows)

    def __next__(self):
        if self._index >= len(self._rows):
            raise StopIteration
        row = self._rows[self._index]
        self._index += 1
        return row


class TestSafeNextPatternWithDefault:
    """Test that next() always uses default value for safety"""

    def test_next_with_default_on_empty_result(self):
        """Test next() with default returns None for empty results"""
        empty_result = MockBigQueryResult([])

        # Safe pattern: next(iter(result), None)
        row = next(iter(empty_result), None)

        assert row is None  # Should return default, not raise StopIteration

    def test_next_with_default_on_non_empty_result(self):
        """Test next() with default returns first row when results exist"""
        result = MockBigQueryResult([{'id': 1}, {'id': 2}])

        # Safe pattern: next(iter(result), None)
        row = next(iter(result), None)

        assert row is not None
        assert row['id'] == 1

    def test_next_directly_on_iterator_with_default(self):
        """Test next() directly on iterator with default value"""
        result = MockBigQueryResult([])

        # Safe pattern: next(result, None)
        row = next(result, None)

        assert row is None  # Should return default

    def test_next_on_generator_with_default(self):
        """Test next() on generator expression with default"""
        rows = [{'name': 'Alice'}, {'name': 'Bob'}]

        # Safe pattern: next((x for x in items if condition), None)
        charlie = next((row for row in rows if row['name'] == 'Charlie'), None)

        assert charlie is None  # Should return default when not found


class TestIteratorExhaustionSafety:
    """Test safe handling of exhausted iterators"""

    def test_multiple_next_calls_on_empty_iterator(self):
        """Test that multiple next() calls on empty iterator are safe"""
        result = MockBigQueryResult([])

        # First call returns None
        row1 = next(iter(result), None)
        assert row1 is None

        # Second call also returns None (doesn't crash)
        row2 = next(iter(result), None)
        assert row2 is None

    def test_exhausting_iterator_safely(self):
        """Test exhausting iterator with safe pattern"""
        result = MockBigQueryResult([{'id': 1}])

        # Get first (and only) row
        row1 = next(result, None)
        assert row1 == {'id': 1}

        # Try to get second row (doesn't exist)
        row2 = next(result, None)
        assert row2 is None  # Safe default, not exception


class TestDefaultValueBehavior:
    """Test that default values work correctly"""

    def test_custom_default_value(self):
        """Test using custom default value instead of None"""
        result = MockBigQueryResult([])

        # Use custom default
        row = next(iter(result), {'id': -1, 'status': 'not_found'})

        assert row == {'id': -1, 'status': 'not_found'}

    def test_default_preserves_type(self):
        """Test default value has expected type"""
        result = MockBigQueryResult([])

        # Default should be dict type
        row = next(iter(result), {})

        assert isinstance(row, dict)
        assert row == {}


class TestSingleResultPatterns:
    """Test common single-result query patterns"""

    def test_check_table_exists_pattern(self):
        """Test pattern: Check if table exists (single row or None)"""
        # Pattern from processor_base.py
        def check_table_exists(table_name: str) -> bool:
            # Simulate BigQuery query result
            result = MockBigQueryResult([{'table_exists': True}])
            row = next(iter(result), None)
            return row is not None and row.get('table_exists', False)

        assert check_table_exists('test_table') is True

    def test_get_latest_record_pattern(self):
        """Test pattern: Get latest record with LIMIT 1"""
        # Pattern from predictions/coordinator/
        def get_latest_prediction(player_lookup: str):
            result = MockBigQueryResult([
                {'player': player_lookup, 'timestamp': '2026-01-25T10:00:00'}
            ])
            row = next(result, None)
            return row

        latest = get_latest_prediction('lebron-james-2544')
        assert latest is not None
        assert latest['player'] == 'lebron-james-2544'

    def test_aggregate_query_pattern(self):
        """Test pattern: Aggregate query (COUNT, SUM, etc.) always returns 1 row"""
        # Even COUNT(*) returns a row (with 0), but be safe with default
        result = MockBigQueryResult([{'count': 0}])
        row = next(iter(result), None)

        assert row is not None
        assert row['count'] == 0


class TestGeneratorExpressionSafety:
    """Test safe usage of generator expressions with next()"""

    def test_find_first_matching_item(self):
        """Test finding first matching item in collection"""
        teams = [
            {'team_id': 'LAL', 'home_away': 'HOME'},
            {'team_id': 'GSW', 'home_away': 'AWAY'}
        ]

        # Pattern: next((item for item in collection if condition), None)
        home_team = next((t for t in teams if t['home_away'] == 'HOME'), None)

        assert home_team is not None
        assert home_team['team_id'] == 'LAL'

    def test_find_nonexistent_item_returns_default(self):
        """Test that searching for nonexistent item returns default"""
        teams = [{'team_id': 'LAL'}, {'team_id': 'GSW'}]

        # Search for team that doesn't exist
        mia_team = next((t for t in teams if t['team_id'] == 'MIA'), None)

        assert mia_team is None

    def test_empty_collection_returns_default(self):
        """Test that empty collection returns default"""
        teams = []

        # Search in empty collection
        any_team = next((t for t in teams if t.get('team_id')), None)

        assert any_team is None


class TestRealWorldProcessorPatterns:
    """Test actual patterns from production processors"""

    def test_grading_processor_pattern(self):
        """Test pattern from prediction_accuracy_processor.py"""
        # Pattern: row = next(iter(result), None)
        result = MockBigQueryResult([{'accuracy': 0.65}])
        row = next(iter(result), None)

        if row:
            accuracy = row.get('accuracy', 0.0)
            assert accuracy == 0.65
        else:
            # Safe fallback
            accuracy = 0.0

    def test_player_loader_pattern(self):
        """Test pattern from player_loader.py"""
        # Pattern: row = next(results, None)
        results = MockBigQueryResult([{'player_lookup': 'curry-stephen-1966'}])
        row = next(results, None)

        if row:
            player = row['player_lookup']
            assert player == 'curry-stephen-1966'

    def test_standings_processor_pattern(self):
        """Test pattern from bdl_standings_processor.py"""
        # Pattern: next((row for row in sorted(...) if condition), None)
        rows = [
            {'team': 'LAL', 'conference_rank': 2},
            {'team': 'GSW', 'conference_rank': 1},
            {'team': 'PHX', 'conference_rank': 3}
        ]

        leader = next(
            (row for row in sorted(rows, key=lambda x: x['conference_rank'])
             if row['conference_rank'] == 1),
            None
        )

        assert leader is not None
        assert leader['team'] == 'GSW'


class TestAsyncIteratorSafety:
    """Test safety with async iterator patterns"""

    def test_async_result_iterator_with_default(self):
        """Test that async iterators use default value"""
        # Simulating BigQuery async result iterator
        result = MockBigQueryResult([])

        # Even with async results, always use default
        row = next(iter(result), None)

        assert row is None  # Should NOT raise StopIteration

    def test_multiple_processors_safe_pattern(self):
        """Test that pattern is safe across multiple processor calls"""
        def process_batch(batch_size: int):
            results = []
            for i in range(batch_size):
                # Each processor might return empty result
                result = MockBigQueryResult([])
                row = next(iter(result), None)
                results.append(row)
            return results

        # Should not crash even with all empty results
        batch = process_batch(10)

        assert len(batch) == 10
        assert all(row is None for row in batch)


class TestPreventUnsafePatterns:
    """Document unsafe patterns that should be avoided"""

    def test_unsafe_pattern_raises_stop_iteration(self):
        """Document that next() WITHOUT default raises StopIteration"""
        result = MockBigQueryResult([])

        # UNSAFE PATTERN - Don't do this!
        with pytest.raises(StopIteration):
            row = next(iter(result))  # NO DEFAULT - BAD!

    def test_unsafe_generator_without_default(self):
        """Document that generator next() without default is unsafe"""
        items = []

        # UNSAFE PATTERN - Don't do this!
        with pytest.raises(StopIteration):
            item = next((x for x in items))  # NO DEFAULT - BAD!

    def test_safe_pattern_never_raises(self):
        """Demonstrate that safe pattern never raises StopIteration"""
        result = MockBigQueryResult([])

        # SAFE PATTERN - Always do this!
        try:
            row = next(iter(result), None)  # WITH DEFAULT - GOOD!
            assert row is None
        except StopIteration:
            pytest.fail("Safe pattern should never raise StopIteration")
