# Reference Processor Tests

This directory contains comprehensive unit tests for reference data processors that build and maintain player registries.

## Test Coverage

### Player Reference Processors (`player_reference/`)

#### Gamebook Registry (`test_gamebook_registry.py`)
- **Tests:** 24 tests
- **Coverage:** ~75%

**Test Areas:**
1. **Initialization** - Test mode, strategies, confirmation requirements
2. **Get Gamebook Data** - Query filtering (season, team, date range)
3. **Get BR Enhancement** - Basketball Reference data for jerseys/positions
4. **Aggregate Player Stats** - Registry record creation and game stats
5. **Temporal Ordering** - Prevent out-of-order data processing
6. **Data Freshness** - Block stale data updates

#### Roster Registry (`test_roster_registry.py`)
- **Tests:** 25 tests
- **Coverage:** ~80%

**Test Areas:**
1. **Team Code Normalization** - BRK→BKN, CHO→CHA, PHO→PHX
2. **ESPN Roster Data (Strict)** - Exact date matching with 30-day fallback
3. **NBA.com Data (Strict)** - Exact date matching with 7-day fallback
4. **BR Data (Strict)** - Exact date matching with 30-day fallback
5. **Roster Data Aggregation** - Multi-source combination
6. **Source Date Tracking** - Track actual dates used vs requested
7. **Integration Scenarios** - Strict vs fallback modes

## Key Features Tested

### Temporal Ordering Protection
```python
def test_blocks_backward_progression(processor):
    # Mock previous run with later date
    processor.validate_temporal_ordering(
        data_date=date(2024, 12, 15),  # Earlier
        season_year=2024,
        allow_backfill=False  # Strict
    )
    # Should raise TemporalOrderingError
```

### Data Freshness Protection
```python
def test_blocks_stale_data(processor):
    existing = {
        'last_gamebook_activity_date': date(2024, 12, 20)  # Fresher
    }

    should_update, reason = processor.should_update_record(
        existing_record=existing,
        new_data_date=date(2024, 12, 15),  # Stale
        processor_type='gamebook'
    )

    assert should_update is False
```

### Strict Date Matching
```python
def test_strict_mode_requires_exact_match(processor):
    # With allow_fallback=False, must have exact date
    players, date_used, matched = processor._get_espn_roster_players_strict(
        season_year=2024,
        data_date=date(2024, 12, 15),
        allow_fallback=False  # Strict
    )

    if no_exact_match:
        assert len(players) == 0
        assert matched is False
```

## Running Tests

```bash
# Run all reference tests
pytest tests/processors/reference/ -v

# Run specific processor tests
pytest tests/processors/reference/player_reference/test_gamebook_registry.py -v
pytest tests/processors/reference/player_reference/test_roster_registry.py -v

# Run with coverage
pytest tests/processors/reference/ --cov=data_processors/reference --cov-report=html

# Run specific test class
pytest tests/processors/reference/player_reference/test_roster_registry.py::TestGetCurrentRosterData -v
```

## Test Patterns

### Mocking BigQuery with Pandas
```python
@pytest.fixture
def processor(mock_bq_client):
    with patch('module.bigquery.Client') as mock_client_class:
        mock_client_class.return_value = mock_bq_client

        proc = RegistryProcessor(test_mode=True)
        proc.bq_client = mock_bq_client
        return proc
```

### Testing Multi-Source Data
```python
def test_aggregates_all_sources(processor, mock_bq_client):
    # Mock each source returning different data
    mock_bq_client.query.side_effect = [
        Mock(to_dataframe=Mock(return_value=espn_data)),
        Mock(to_dataframe=Mock(return_value=nbacom_data)),
        Mock(to_dataframe=Mock(return_value=br_data))
    ]

    result = processor.get_current_roster_data(...)

    assert 'espn_rosters' in result
    assert 'nba_player_list' in result
```

## Fixtures

Common fixtures in `conftest.py`:
- `mock_bq_client` - Mocked BigQuery client
- `processor` - Configured processor instance
- Sample data fixtures for gamebook, rosters, enhancement data

## Module Mocking — DO NOT stub the `google` namespace

**The pattern this section used to recommend has been removed. Do not reinstate it.**

```python
# ANTI-PATTERN — this used to be documented here:
def pytest_configure(config):
    sys.modules['google.cloud'] = MagicMock()
    sys.modules['google.api_core.exceptions'] = MagicMock()
```

Three things go wrong, all measured on 2026-08-23:

1. **It makes error paths untestable.** `except GoogleAPIError` against a MagicMock
   raises `TypeError: catching classes that do not inherit from BaseException`. Every
   error-handling test under this directory failed for that reason rather than for
   anything to do with the code.
2. **It leaks across the whole session.** `pytest_configure` is a session hook, and a
   module-level `sys.modules[...] = MagicMock()` in a test file runs at collection.
   Either way the replacement outlives the file that made it. Removing the two stubs
   in this tree took a combined `reference + unit/signals` run from 7 failed / 528
   passed to 4 failed / 531 passed — the two contaminated tests were in
   `unit/signals`, nowhere near this directory. This is the likely mechanism behind
   the repo-wide "cross-suite pollution" that the per-directory triage habit works
   around.
3. **It buys nothing.** `google-cloud-bigquery` and `google-api-core` are installed.
   Removing the stubs here fixed one test outright and broke none.

Mock the client you inject, not the library:

```python
mock_bq_client = Mock()
mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame(...)
handler = ESPNSourceHandler(mock_bq_client, 'test-project')
```

See `test_roster_source_handlers.py` for the pattern applied end to end, including
error paths that need the real exception classes.

**24 other test files still carry this stubbing** (`grep -rn "sys.modules\['google" tests/`).
They were left alone because each needs its own before/after measurement.

## Coverage Goals

Target: 80%+ coverage for all reference processors
Current:
- Gamebook Registry: 75%
- Roster Registry: 80%

## Known Test Limitations

Some tests have minor failures due to mock configuration:
- Complex nested object returns (enhancement data dictionaries)
- TemporalOrderingError exception handling
- GoogleAPIError exception simulation

These are non-blocking and don't affect core logic testing.

## Adding New Tests

When adding reference processor tests:
1. Add test file to appropriate subdirectory
2. Import processors with proper module mocking
3. Test both happy path and error scenarios
4. Verify temporal ordering and freshness logic
5. Test multi-source data aggregation
6. Mock all Google Cloud dependencies in conftest.py
