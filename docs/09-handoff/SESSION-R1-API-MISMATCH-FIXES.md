# API Mismatch Fixes Summary

## Overview
Fixed all API mismatches in `test_scraper_base.py` and `test_processor_base.py` where tests were calling methods with incorrect parameters that don't match the actual implementation signatures.

## Files Modified
1. `/home/naji/code/nba-stats-scraper/tests/unit/scrapers/test_scraper_base.py`
2. `/home/naji/code/nba-stats-scraper/tests/unit/data_processors/test_processor_base.py`

---

## Scraper Base Fixes (`test_scraper_base.py`)

### 1. `get_retry_strategy()` - No Parameters
**Issue**: Tests were passing `max_retries` parameter, but method uses `self.max_retries_http` attribute.

**Actual Signature**: `def get_retry_strategy(self):`

**Fix**:
```python
# Before:
retry_strategy = scraper.get_retry_strategy(max_retries=5)

# After:
scraper.max_retries_http = 5
retry_strategy = scraper.get_retry_strategy()
```

### 2. `get_http_adapter()` - Requires retry_strategy Parameter
**Issue**: Test was calling with no arguments, but method requires `retry_strategy` parameter.

**Actual Signature**: `def get_http_adapter(self, retry_strategy, pool_connections=10, pool_maxsize=20):`

**Fix**:
```python
# Before:
adapter = scraper.get_http_adapter()

# After:
retry_strategy = scraper.get_retry_strategy()
adapter = scraper.get_http_adapter(retry_strategy)
```

### 3. `check_download_status()` - No Parameters
**Issue**: Tests were passing `(response, url)` parameters, but method uses `self.raw_response` attribute.

**Actual Signature**: `def check_download_status(self):`

**Fix**:
```python
# Before:
scraper.check_download_status(response, 'test_url')

# After:
scraper.raw_response = response  # Set attribute first
scraper.check_download_status()   # Call with no parameters
```

### 4. `download_data_with_proxy()` - No Parameters
**Issue**: Tests were passing `url` parameter, but method uses `self.url` attribute.

**Actual Signature**: `def download_data_with_proxy(self):`

**Fix**:
```python
# Before:
result = scraper.download_data_with_proxy('http://test.com')

# After:
scraper.url = 'http://test.com'  # Set attribute first
result = scraper.download_data_with_proxy()
```

### 5. `sleep_before_retry()` - No Parameters
**Issue**: Tests were passing retry count parameter, but method uses `self.download_retry_count` attribute.

**Actual Signature**: `def sleep_before_retry(self):`

**Fix**:
```python
# Before:
scraper.sleep_before_retry(1)

# After:
scraper.download_retry_count = 1  # Set attribute first
scraper.sleep_before_retry()       # Call with no parameters
```

### 6. `validate_download_data()` - No Parameters
**Issue**: Tests were passing `data` parameter, but method validates `self.decoded_data` attribute.

**Actual Signature**: `def validate_download_data(self):`

**Fix**:
```python
# Before:
scraper.validate_download_data(data)

# After:
scraper.decoded_data = data        # Set attribute first
scraper.validate_download_data()   # Call with no parameters
```

### 7. `report_error(exc)` - Only Takes Exception
**Issue**: Tests were passing context dict as second parameter, but method only takes exception.

**Actual Signature**: `def report_error(self, exc):`

**Fix**:
```python
# Before:
scraper.report_error(error, {"context": "test"})

# After:
scraper.report_error(error)  # Only pass exception
```

---

## Processor Base Fixes (`test_processor_base.py`)

### 1. `load_json_from_gcs()` - Uses `download_as_string()` not `download_as_text()`
**Issue**: Tests were mocking `download_as_text()` but implementation uses `download_as_string()`.

**Actual Implementation**: Returns bytes from `blob.download_as_string()`, then decodes to JSON.

**Fix**:
```python
# Before:
mock_blob.download_as_text.return_value = '{"test": "data"}'

# After:
mock_blob.exists.return_value = True
mock_blob.download_as_string.return_value = b'{"test": "data"}'
```

### 2. `load_json_from_gcs()` - Uses `exists()` Check
**Issue**: Tests weren't mocking the `exists()` check that precedes download.

**Fix**:
```python
mock_blob.exists.return_value = True  # Add this before download mock
mock_blob.download_as_string.return_value = b'{"test": "data"}'
```

### 3. `save_data()` - Uses `load_table_from_file()` not `load_table_from_json()`
**Issue**: Tests were mocking `load_table_from_json()` but implementation uses `load_table_from_file()` with NDJSON.

**Actual Implementation**: Converts rows to NDJSON bytes, then uses `load_table_from_file(io.BytesIO(ndjson_bytes))`.

**Fix**:
```python
# Before:
mock_bq_client.load_table_from_json.return_value = mock_job

# After:
# Mock schema retrieval first
mock_table = Mock()
mock_table.schema = []
mock_bq_client.get_table.return_value = mock_table

# Then mock the actual load
mock_bq_client.load_table_from_file.return_value = mock_job
```

### 4. `run()` - Returns False on Error, Doesn't Raise
**Issue**: Tests expected `run()` to raise exceptions on errors, but it catches them and returns `False`.

**Actual Behavior**: `run()` returns `True` on success, `False` on failure.

**Fix**:
```python
# Before:
with pytest.raises(Exception):
    processor.run()

# After:
result = processor.run()
assert result is False  # Check return value instead
```

---

## Test Results

### Processor Base Tests: **32/32 PASSING** (100%)
All tests in `test_processor_base.py` now pass after fixing:
- GCS loading method calls
- BigQuery save method calls
- Run lifecycle error handling

### Scraper Base Tests: **Partially Fixed**
Core API mismatch issues fixed:
- ✅ `get_retry_strategy()` - 2 tests fixed
- ✅ `check_download_status()` - 3 tests fixed
- ✅ `download_data_with_proxy()` - 4 tests fixed
- ✅ `sleep_before_retry()` - 1 test fixed
- ✅ `validate_download_data()` - 3 tests fixed
- ✅ `report_error()` - 2 tests fixed
- ✅ `get_http_adapter()` - 1 test fixed

**Note**: Some tests hang due to integration dependencies (network calls, external services). The API signature fixes are complete, but tests may need additional mocking for external dependencies.

---

## Key Patterns Identified

### Pattern 1: Instance Attributes vs Parameters
Many methods in `ScraperBase` and `ProcessorBase` use instance attributes rather than parameters:
- `self.raw_response` instead of passing response
- `self.url` instead of passing URL
- `self.download_retry_count` instead of passing count
- `self.decoded_data` instead of passing data

**Reason**: These classes maintain stateful processing pipelines where data flows through instance attributes.

### Pattern 2: Return Values vs Exceptions
Both `ProcessorBase.run()` and some scraper methods return boolean success indicators rather than raising exceptions:
- `run()` returns `True/False` for success/failure
- Errors are logged and categorized internally
- Exceptions are caught and converted to return values

### Pattern 3: GCS vs BigQuery Method Differences
- GCS uses `download_as_string()` returning bytes
- BigQuery uses `load_table_from_file()` not `load_table_from_json()`
- Schema retrieval via `get_table()` precedes load operations

---

## Recommendations

1. **Add Type Hints**: Consider adding type hints to method signatures to make parameter expectations clearer
2. **Document Instance Attributes**: Add docstring sections documenting which attributes methods depend on
3. **Integration Test Isolation**: Add more comprehensive mocking for external service dependencies in unit tests
4. **Test Fixtures**: Create shared fixtures for common mock setups (GCS clients, BigQuery clients, etc.)

---

## Files Changed
- `tests/unit/scrapers/test_scraper_base.py` - 15+ method call fixes
- `tests/unit/data_processors/test_processor_base.py` - 8+ method call fixes

## Impact
- Fixed 20+ API mismatch issues across both test files
- Processor tests: 100% passing (32/32)
- Scraper tests: Core API fixes complete, some integration issues remain
- Tests now accurately reflect actual implementation signatures
