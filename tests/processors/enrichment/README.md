# Enrichment Processor Tests

This directory contains comprehensive unit tests for enrichment processors that add derived data to raw datasets.

## Test Coverage

### Prediction Line Enrichment (`prediction_line_enrichment/`)
- **File:** `test_unit.py`
- **Tests:** 27 tests
- **Coverage:** ~85%

#### Test Areas:
1. **Initialization** - Dataset configuration and table naming
2. **Get Predictions Missing Lines** - Query predictions needing enrichment
3. **Get Available Props** - Retrieve betting lines with bookmaker priority
4. **Enrich Predictions** - Main enrichment logic and matching
5. **Update Predictions (MERGE)** - BigQuery MERGE statement construction
6. **Fix Recommendations** - Update NO_LINE recommendations
7. **Date Range Enrichment** - Batch processing across dates

#### Key Features Tested:
- Exact date matching for predictions and props
- Bookmaker priority (DraftKings > FanDuel > BetMGM)
- Dry-run vs live update modes
- MERGE statement field updates
- Recommendation recalculation logic
- Error handling and edge cases

## Running Tests

```bash
# Run all enrichment tests
pytest tests/processors/enrichment/ -v

# Run specific test file
pytest tests/processors/enrichment/prediction_line_enrichment/test_unit.py -v

# Run with coverage
pytest tests/processors/enrichment/ --cov=data_processors/enrichment --cov-report=html
```

## Test Patterns

### Mocking BigQuery
```python
@pytest.fixture
def mock_bq_client():
    mock_client = Mock()
    mock_client.project = 'test-project'
    mock_result = Mock()
    mock_result.to_dataframe.return_value = pd.DataFrame()
    mock_client.query.return_value = mock_result
    return mock_client
```

### Testing Query Logic
```python
def test_filters_by_game_date(processor, mock_bq_client):
    processor.get_predictions_missing_lines(date(2025, 12, 15))

    query_call = mock_bq_client.query.call_args[0][0]
    assert "game_date = '2025-12-15'" in query_call
```

## Fixtures

Common fixtures are defined in `conftest.py`:
- `mock_bq_client` - Mocked BigQuery client
- Sample data fixtures for predictions and props

## Coverage Goals

Target: 80%+ coverage for all enrichment processors
Current: 85% for prediction line enrichment

## Adding New Tests

When adding enrichment processor tests:
1. Create subdirectory: `tests/processors/enrichment/<processor_name>/`
2. Add `__init__.py` and `test_unit.py`
3. Follow existing patterns for mocking and fixtures
4. Test both happy path and error scenarios
5. Verify SQL query construction with assertions
