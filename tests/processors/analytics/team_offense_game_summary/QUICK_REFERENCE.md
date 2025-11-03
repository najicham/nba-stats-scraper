# Team Offense Game Summary Tests - Quick Reference Card

**Directory:** `tests/processors/analytics/team_offense_game_summary/`

---

## 🚀 Quick Commands

```bash
# Navigate to test directory
cd tests/processors/analytics/team_offense_game_summary/

# Run all tests (fastest way)
python run_tests.py

# Run specific test type
python run_tests.py unit           # Unit tests only (~5s)
python run_tests.py integration    # Integration tests only (~5s)

# With coverage report
python run_tests.py --coverage

# Verbose output
python run_tests.py --verbose
```

---

## 📊 Test Stats

| Metric | Value |
|--------|-------|
| **Total Tests** | 69 |
| **Unit Tests** | 58 |
| **Integration Tests** | 11 |
| **Runtime** | ~10s |
| **Coverage** | ~95% |

---

## 🎯 Test Coverage

### Calculation Methods
- ✅ `_parse_overtime_periods()` - 9 tests
- ✅ `_calculate_possessions()` - 6 tests  
- ✅ `_calculate_true_shooting_pct()` - 8 tests
- ✅ `_calculate_quality_tier()` - 7 tests

### Dependency System
- ✅ `get_dependencies()` - 9 tests
- ✅ `build_source_tracking_fields()` - 7 tests

### Stats & Monitoring
- ✅ `get_analytics_stats()` - 12 tests

### Integration Flows
- ✅ Full processor flow - 3 tests
- ✅ Overtime games - 2 tests
- ✅ Multiple games - 2 tests
- ✅ Error handling - 4 tests

---

## 🐛 Debugging

```bash
# Run single test
pytest test_unit.py::TestOvertimePeriodParsing::test_regulation_game_240_minutes -v

# Run with full traceback
pytest test_unit.py -vv --tb=long

# Stop on first failure
pytest test_unit.py -x

# Show print statements
pytest test_unit.py -s
```

---

## 📁 File Locations

```
/outputs/tests/analytics/team_offense_game_summary/
├── conftest.py              # Google Cloud mocks
├── test_unit.py             # 58 unit tests ⭐
├── test_integration.py      # 11 integration tests ⭐
├── run_tests.py             # Test runner
├── README.md                # Full documentation
└── TEST_SUITE_SUMMARY.md    # This summary
```

---

## ✅ Expected Output

```
🚀 Running All Tests...
Running: pytest -v --tb=short --color=yes

test_unit.py::TestOvertimePeriodParsing::test_regulation_game_240_minutes PASSED
test_unit.py::TestOvertimePeriodParsing::test_one_overtime_265_minutes PASSED
test_unit.py::TestOvertimePeriodParsing::test_two_overtime_290_minutes PASSED
...
test_integration.py::TestFullProcessorFlow::test_successful_processing_with_shot_zones PASSED
test_integration.py::TestErrorHandling::test_empty_dataset_handling PASSED

==================== 69 passed in 10.23s ====================
```

---

## 🎓 Key Patterns

**Floating Point Assertions:**
```python
assert result == pytest.approx(expected, abs=0.001)
```

**Mock BigQuery:**
```python
processor.bq_client = Mock()
mock_bq_client.query.return_value.to_dataframe.return_value = sample_data
```

**Test Naming:**
```python
def test_[method]_[scenario]_[expected_behavior](self):
```

---

## 📞 Help

- **Full docs:** `README.md`
- **Test guide:** `/docs/testing/unit_test_guide.md`
- **Issues:** Run with `--verbose` flag

---

**Status:** ✅ Production Ready  
**Version:** 1.0  
**Last Updated:** January 2025
