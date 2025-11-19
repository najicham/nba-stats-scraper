# Testing & Quality Assurance - Phase 5 Predictions

**File:** `docs/predictions/tutorials/05-testing-and-quality-assurance.md`
**Created:** 2025-11-17
**Last Updated:** 2025-11-17
**Purpose:** Complete guide to testing Phase 5 prediction systems
**Audience:** Engineers writing tests, modifying code, ensuring quality

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Testing Philosophy](#philosophy)
3. [Test Structure](#test-structure)
4. [Running Tests](#running-tests)
5. [Mock Data & Fixtures](#mock-data)
6. [Writing New Tests](#writing-tests)
7. [Test Coverage](#test-coverage)
8. [Integration Testing](#integration-testing)
9. [Testing Before Deployment](#pre-deployment)
10. [Common Testing Patterns](#patterns)
11. [Troubleshooting Tests](#troubleshooting)

---

## 🚀 Quick Start {#quick-start}

### Run All Tests

```bash
# From project root
cd /path/to/nba-stats-scraper

# Run all prediction tests
pytest predictions/ -v

# Run with coverage
pytest predictions/ --cov=predictions --cov-report=html

# Run specific test file
pytest predictions/coordinator/tests/test_coordinator.py -v

# Run specific test class
pytest predictions/coordinator/tests/test_coordinator.py::TestStartEndpoint -v

# Run specific test method
pytest predictions/coordinator/tests/test_coordinator.py::TestStartEndpoint::test_start_endpoint_success -v
```

### Expected Output

```
================================ test session starts =================================
platform linux -- Python 3.11.5, pytest-7.4.3
collected 15 items

predictions/coordinator/tests/test_coordinator.py::TestHealthEndpoints::test_index_endpoint PASSED [ 6%]
predictions/coordinator/tests/test_coordinator.py::TestHealthEndpoints::test_health_endpoint PASSED [13%]
predictions/coordinator/tests/test_coordinator.py::TestStartEndpoint::test_start_endpoint_success PASSED [20%]
...

============================= 15 passed in 2.34s ==================================
```

---

## 🎯 Testing Philosophy {#philosophy}

### Design Principles

**1. Test Without External Dependencies**
- Mock BigQuery, Pub/Sub, Cloud Storage
- Use `MockDataGenerator` for features
- Use `MockXGBoostModel` for ML predictions
- Tests should run offline

**2. Fast & Deterministic**
- Tests complete in < 5 seconds
- Use `seed` parameter for reproducibility
- No network calls, no real databases

**3. Comprehensive Coverage**
- Unit tests for individual functions
- Integration tests for end-to-end flows
- Edge cases and error handling

**4. Easy to Understand**
- Clear test names describe what's tested
- Arrange-Act-Assert pattern
- Helpful assertion messages

---

## 📁 Test Structure {#test-structure}

### Directory Layout

```
predictions/
├── coordinator/
│   ├── coordinator.py
│   ├── player_loader.py
│   ├── progress_tracker.py
│   └── tests/
│       ├── conftest.py              # Shared fixtures
│       ├── test_coordinator.py      # Coordinator Flask app tests
│       ├── test_player_loader.py    # Player loading logic tests
│       └── test_progress_tracker.py # Progress tracking tests
│
├── worker/
│   ├── worker.py
│   ├── data_loaders.py
│   ├── prediction_systems/
│   │   ├── moving_average_baseline.py
│   │   ├── xgboost_v1.py
│   │   ├── zone_matchup_v1.py
│   │   ├── similarity_balanced_v1.py
│   │   └── ensemble_v1.py
│   └── tests/
│       ├── conftest.py              # Worker-specific fixtures
│       └── test_*.py                # Worker tests
│
└── shared/
    ├── mock_data_generator.py       # Mock features & games
    └── mock_xgboost_model.py        # Mock ML model
```

### Test Organization

**Test Files:**
- `test_coordinator.py` - Flask endpoints, orchestration
- `test_player_loader.py` - BigQuery queries, request building
- `test_progress_tracker.py` - Event tracking, completion logic

**Shared Fixtures:**
- `conftest.py` - Reusable test fixtures (mocks, sample data)

**Mock Utilities:**
- `mock_data_generator.py` - Generate realistic features
- `mock_xgboost_model.py` - Simulate ML predictions

---

## ▶️ Running Tests {#running-tests}

### Basic Commands

```bash
# Run all tests (verbose)
pytest predictions/ -v

# Run tests quietly (just pass/fail)
pytest predictions/

# Run tests with coverage
pytest predictions/ --cov=predictions --cov-report=term-missing

# Generate HTML coverage report
pytest predictions/ --cov=predictions --cov-report=html
# Open: htmlcov/index.html

# Run tests in parallel (faster)
pytest predictions/ -n auto
```

### Filtering Tests

```bash
# Run only coordinator tests
pytest predictions/coordinator/tests/

# Run only worker tests
pytest predictions/worker/tests/

# Run tests matching keyword
pytest predictions/ -k "health"

# Run tests NOT matching keyword
pytest predictions/ -k "not slow"

# Run failed tests from last run
pytest predictions/ --lf

# Run failed tests first, then others
pytest predictions/ --ff
```

### Verbose Output

```bash
# Show print statements
pytest predictions/ -v -s

# Show locals on failure
pytest predictions/ -v -l

# Drop into debugger on failure
pytest predictions/ -v --pdb

# Stop on first failure
pytest predictions/ -v -x
```

---

## 🎭 Mock Data & Fixtures {#mock-data}

### Shared Fixtures (conftest.py)

**Location:** `predictions/coordinator/tests/conftest.py`

**Available Fixtures:**

```python
# Mock Google Cloud clients
mock_bigquery_client       # Mock BigQuery for queries
mock_pubsub_publisher      # Mock Pub/Sub for publishing

# Sample data
sample_game_date           # date(2025, 11, 8)
sample_players             # List of 3 players (LeBron, Curry, AD)
sample_summary_stats       # Game day summary statistics
sample_completion_event    # Worker completion message
sample_prediction_request  # Prediction request message

# Helper functions
create_mock_bigquery_row(**kwargs)  # Create mock BigQuery row
```

**Example Usage:**

```python
def test_player_loader(mock_bigquery_client, sample_players):
    """Test player loading with mocked BigQuery"""
    # Mock BigQuery to return sample players
    mock_result = Mock()
    mock_result.result.return_value = sample_players
    mock_bigquery_client.query.return_value = mock_result

    # Call function under test
    from coordinator.player_loader import PlayerLoader
    loader = PlayerLoader(mock_bigquery_client)
    players = loader.load_players_for_date(date(2025, 11, 8))

    # Assert
    assert len(players) == 3
    assert players[0]['player_lookup'] == 'lebron-james'
```

### MockDataGenerator

**Location:** `predictions/shared/mock_data_generator.py`

**Purpose:** Generate realistic NBA features and historical games for testing

**Key Methods:**

```python
from predictions.shared.mock_data_generator import MockDataGenerator

generator = MockDataGenerator(seed=42)  # Reproducible

# Generate 25 features for a player
features = generator.generate_all_features(
    player_lookup='lebron-james',
    game_date=date(2025, 11, 8),
    tier='superstar',     # 'superstar', 'star', 'starter', 'rotation', 'bench'
    position='SF'         # 'PG', 'SG', 'SF', 'PF', 'C'
)

# Features dict contains:
# - features_array: [25 floats]
# - feature_names: ['points_avg_last_5', ...]
# - feature_count: 25
# - feature_version: 'v1_baseline_25'
# - All individual features as dict keys

# Generate historical games for similarity system
historical = generator.generate_historical_games(
    player_lookup='lebron-james',
    current_date=date(2025, 11, 8),
    num_games=50,
    lookback_days=730  # 2 years
)

# Each game contains:
# - opponent_team_abbr, opponent_tier, opponent_def_rating
# - days_rest, back_to_back, is_home
# - recent_form ('hot', 'normal', 'cold')
# - points (actual points scored)
# - minutes_played

# Generate batch for multiple players
batch = generator.generate_batch(
    players=['lebron-james', 'stephen-curry', 'giannis-antetokounmpo'],
    game_date=date(2025, 11, 8)
)
```

**Player Tier Inference:**
```python
# Tier is inferred from player name if not provided
'lebron', 'curry', 'durant', 'jokic', 'giannis', 'luka' → 'superstar'
'jordan', 'embiid', 'tatum', 'booker', 'mitchell' → 'star'
'unknown', 'bench' → 'bench'
# Default → 'starter'
```

**Position Inference:**
```python
# Position is inferred from player name if not provided
'embiid', 'jokic', 'towns' → 'C'
'curry', 'luka', 'young' → 'PG'
'giannis', 'davis' → 'PF'
'booker', 'mitchell' → 'SG'
# Default → 'SF'
```

**Reproducibility:**
```python
# Use seed for deterministic results
gen1 = MockDataGenerator(seed=42)
gen2 = MockDataGenerator(seed=42)

features1 = gen1.generate_all_features('lebron-james', date(2025, 11, 8))
features2 = gen2.generate_all_features('lebron-james', date(2025, 11, 8))

assert features1['features_array'] == features2['features_array']  # Same!
```

### MockXGBoostModel

**Location:** `predictions/shared/mock_xgboost_model.py`

**Purpose:** Simulate trained XGBoost model for testing ML predictions

**Key Methods:**

```python
from predictions.shared.mock_xgboost_model import MockXGBoostModel
import numpy as np

# Create mock model
model = MockXGBoostModel(seed=42)  # Reproducible

# Predict with feature vector
features = np.array([28.5, 27.3, 26.8, 4.2, 35.0, ...])  # 25 features
prediction = model.predict(features)

print(prediction)  # array([27.8])

# Predict for multiple players
features_batch = np.array([
    [28.5, 27.3, 26.8, ...],  # Player 1
    [22.1, 21.5, 20.9, ...]   # Player 2
])
predictions = model.predict(features_batch)

print(predictions)  # array([27.8, 21.3])

# Get feature importance
importance = model.get_feature_importance()

print(importance)
# {0: 0.14, 1: 0.12, 2: 0.08, 6: 0.11, ...}
# Feature 0 (points_last_5): 14% importance
# Feature 6 (zone_mismatch): 11% importance

# Get model metadata
metadata = model.get_model_metadata()

print(metadata)
# {
#   'model_type': 'mock_xgboost',
#   'model_version': 'mock_v1',
#   'n_features': 25,
#   'is_mock': True
# }
```

**How It Works:**

The mock model simulates XGBoost by:
1. Starting with weighted recent performance baseline
2. Applying learned adjustments from other features
3. Using non-linear thresholds (e.g., fatigue < 50 → -2.5 points)
4. Adding small random variance
5. Clamping to 0-60 points range

**Example Integration:**

```python
from predictions.shared.mock_data_generator import MockDataGenerator
from predictions.shared.mock_xgboost_model import MockXGBoostModel, create_feature_vector
from datetime import date

# Generate features
generator = MockDataGenerator(seed=42)
features_dict = generator.generate_all_features('lebron-james', date(2025, 11, 8))

# Convert to numpy array for model
features_array = create_feature_vector(features_dict)

# Predict with mock model
model = MockXGBoostModel(seed=42)
prediction = model.predict(features_array)

print(f"LeBron predicted points: {prediction[0]:.1f}")
# LeBron predicted points: 27.8
```

---

## ✍️ Writing New Tests {#writing-tests}

### Test Template

```python
# predictions/coordinator/tests/test_my_feature.py

"""
Test suite for MyFeature functionality

Tests the new feature I'm adding, ensuring it works correctly
with various inputs and edge cases.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch


class TestMyFeature:
    """Test MyFeature class"""

    def test_basic_functionality(self):
        """Test basic feature behavior"""
        # Arrange (setup)
        input_value = 42
        expected_output = 84

        # Act (execute)
        from coordinator.my_feature import MyFeature
        feature = MyFeature()
        actual_output = feature.process(input_value)

        # Assert (verify)
        assert actual_output == expected_output, \
            f"Expected {expected_output}, got {actual_output}"

    def test_with_mock_data(self, sample_players):
        """Test with fixture data"""
        # Use fixture
        assert len(sample_players) == 3

        # Process
        from coordinator.my_feature import MyFeature
        feature = MyFeature()
        result = feature.process_players(sample_players)

        # Verify
        assert result['processed_count'] == 3

    @patch('coordinator.my_feature.external_service')
    def test_with_mocked_service(self, mock_service):
        """Test with mocked external dependency"""
        # Configure mock
        mock_service.call.return_value = {'status': 'success'}

        # Execute
        from coordinator.my_feature import MyFeature
        feature = MyFeature()
        result = feature.call_external()

        # Verify mock was called
        mock_service.call.assert_called_once()

        # Verify result
        assert result['status'] == 'success'

    def test_edge_case_empty_input(self):
        """Test with empty input"""
        from coordinator.my_feature import MyFeature
        feature = MyFeature()
        result = feature.process([])

        assert result == []

    def test_error_handling(self):
        """Test error handling"""
        from coordinator.my_feature import MyFeature
        feature = MyFeature()

        with pytest.raises(ValueError, match="Invalid input"):
            feature.process(None)
```

### Testing with Mock Data

```python
def test_prediction_system():
    """Test prediction system with mock features"""
    from predictions.shared.mock_data_generator import MockDataGenerator
    from predictions.worker.prediction_systems.moving_average_baseline import MovingAverageBaseline

    # Generate mock features
    generator = MockDataGenerator(seed=42)
    features = generator.generate_all_features(
        'lebron-james',
        date(2025, 11, 8),
        tier='superstar'
    )

    # Create prediction system
    system = MovingAverageBaseline()

    # Make prediction
    prediction = system.predict(
        features=features,
        prop_line=25.5
    )

    # Verify prediction structure
    assert 'predicted_points' in prediction
    assert 'confidence_score' in prediction
    assert 'recommendation' in prediction

    # Verify reasonable prediction
    assert 20 <= prediction['predicted_points'] <= 35
    assert 50 <= prediction['confidence_score'] <= 100
    assert prediction['recommendation'] in ['OVER', 'UNDER', 'PASS']
```

### Testing Error Conditions

```python
def test_invalid_features():
    """Test handling of invalid feature data"""
    from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1

    system = XGBoostV1()

    # Test with missing features
    with pytest.raises(ValueError, match="Expected 25 features"):
        system.predict(features={'points_avg_last_5': 25.0}, prop_line=25.5)

    # Test with invalid prop line
    with pytest.raises(ValueError, match="Invalid prop line"):
        valid_features = {'features_array': [0.0] * 25}
        system.predict(features=valid_features, prop_line=-1.0)
```

---

## 📊 Test Coverage {#test-coverage}

### Check Coverage

```bash
# Generate coverage report
pytest predictions/ --cov=predictions --cov-report=term-missing

# Output:
# Name                                        Stmts   Miss  Cover   Missing
# -------------------------------------------------------------------------
# predictions/coordinator/coordinator.py        150     12    92%   45-48, 112-115
# predictions/coordinator/player_loader.py      200     8     96%   89, 134-140
# predictions/coordinator/progress_tracker.py   180     15    92%   67-72, 98-103
# predictions/worker/worker.py                  120     6     95%   78-83
# -------------------------------------------------------------------------
# TOTAL                                         1250    60    95%
```

### Coverage Goals

**Target Coverage:**
- **Overall:** ≥ 80% line coverage
- **Critical paths:** ≥ 95% (coordinator orchestration, prediction systems)
- **Utility functions:** ≥ 90%
- **Error handling:** 100% (all error paths tested)

**What to Focus On:**
- ✅ Core prediction logic
- ✅ Coordinator orchestration
- ✅ Request/response handling
- ✅ Error handling and edge cases
- ⚠️ Mock utilities (lower priority)

### Viewing HTML Coverage

```bash
# Generate HTML report
pytest predictions/ --cov=predictions --cov-report=html

# Open in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

**HTML Report Features:**
- ✅ Line-by-line coverage highlighting
- ✅ Missing lines highlighted in red
- ✅ Coverage percentage per file
- ✅ Click through to see uncovered lines

---

## 🔗 Integration Testing {#integration-testing}

### End-to-End Test Example

```python
# predictions/coordinator/tests/test_integration.py

"""
Integration tests for coordinator-worker flow

Tests the complete prediction pipeline end-to-end
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.integration
class TestCoordinatorWorkerFlow:
    """Test complete coordinator→worker→predictions flow"""

    @patch('coordinator.coordinator.pubsub_publisher')
    @patch('coordinator.coordinator.bigquery_client')
    def test_full_batch_flow(self, mock_bq, mock_pubsub):
        """Test complete batch: start → publish → track → complete"""
        # 1. Mock BigQuery to return players
        mock_bq.query.return_value.result.return_value = [
            {
                'player_lookup': 'lebron-james',
                'game_id': '20251108_LAL_GSW',
                'game_date': date(2025, 11, 8)
            }
        ]

        # 2. Mock Pub/Sub publishing
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id-123'
        mock_pubsub.publish.return_value = mock_future

        # 3. Start batch via coordinator
        from coordinator.coordinator import app
        client = app.test_client()

        response = client.post('/start', json={'game_date': '2025-11-08'})

        assert response.status_code == 202
        data = response.get_json()

        # Verify batch started
        assert 'batch_id' in data
        assert data['total_tasks'] == 1

        # Verify Pub/Sub message published
        mock_pubsub.publish.assert_called_once()

        # 4. Simulate worker completion
        completion_msg = {
            'player_lookup': 'lebron-james',
            'game_date': '2025-11-08',
            'predictions_generated': 5
        }

        response = client.post('/complete', json=completion_msg)

        assert response.status_code == 200

        # 5. Check batch status
        batch_id = data['batch_id']
        response = client.get(f'/status/{batch_id}')

        assert response.status_code == 200
        status = response.get_json()

        assert status['completed'] == 1
        assert status['expected'] == 1
        assert status['status'] == 'complete'
```

### Running Integration Tests

```bash
# Run only integration tests
pytest predictions/ -m integration

# Skip integration tests (faster)
pytest predictions/ -m "not integration"

# Run integration tests with verbose output
pytest predictions/ -m integration -v -s
```

---

## 🚢 Testing Before Deployment {#pre-deployment}

### Pre-Deployment Test Checklist

**Before deploying any prediction system changes:**

```bash
# 1. Run full test suite
pytest predictions/ --cov=predictions --cov-report=term-missing

# 2. Ensure ≥80% coverage
# Check output: TOTAL coverage should be ≥80%

# 3. Run integration tests
pytest predictions/ -m integration -v

# 4. Test deployment scripts (local)
./bin/predictions/deploy/test_prediction_worker.sh dev
./bin/predictions/deploy/test_prediction_coordinator.sh dev

# 5. Manual smoke test (if deployed to dev)
# See deployment guide section on testing
```

### Deployment Test Scripts

**Location:** `bin/predictions/deploy/`

**Scripts:**
- `test_prediction_worker.sh [env]` - Test worker deployment
- `test_prediction_coordinator.sh [env]` - Test coordinator deployment

**What They Test:**
1. Health check endpoint (200 OK)
2. Service can handle requests
3. BigQuery writes work
4. Pub/Sub integration works
5. Logs show no errors

**Usage:**
```bash
# Test worker in dev environment
./bin/predictions/deploy/test_prediction_worker.sh dev

# Test coordinator in staging
./bin/predictions/deploy/test_prediction_coordinator.sh staging

# Test in production (after deployment)
./bin/predictions/deploy/test_prediction_worker.sh prod
```

**See:** [`operations/01-deployment-guide.md`](../operations/01-deployment-guide.md) section "Automated Deployment Scripts" for complete documentation.

---

## 🎨 Common Testing Patterns {#patterns}

### Pattern 1: Test with Reproducible Seeds

```python
def test_reproducible_predictions():
    """Ensure predictions are reproducible with same seed"""
    from predictions.shared.mock_data_generator import MockDataGenerator
    from predictions.shared.mock_xgboost_model import MockXGBoostModel
    from datetime import date

    # Run 1
    gen1 = MockDataGenerator(seed=42)
    model1 = MockXGBoostModel(seed=42)
    features1 = gen1.generate_all_features('lebron-james', date(2025, 11, 8))
    pred1 = model1.predict(features1['features_array'])

    # Run 2 (same seed)
    gen2 = MockDataGenerator(seed=42)
    model2 = MockXGBoostModel(seed=42)
    features2 = gen2.generate_all_features('lebron-james', date(2025, 11, 8))
    pred2 = model2.predict(features2['features_array'])

    # Should be identical
    assert pred1[0] == pred2[0]
```

### Pattern 2: Parameterized Tests

```python
@pytest.mark.parametrize("tier,expected_min,expected_max", [
    ('superstar', 28, 32),
    ('star', 22, 27),
    ('starter', 14, 21),
    ('bench', 4, 7),
])
def test_ppg_by_tier(tier, expected_min, expected_max):
    """Test PPG generation for different player tiers"""
    from predictions.shared.mock_data_generator import MockDataGenerator
    from datetime import date

    generator = MockDataGenerator(seed=42)
    features = generator.generate_all_features(
        'test-player',
        date(2025, 11, 8),
        tier=tier
    )

    ppg = features['points_avg_season']
    assert expected_min <= ppg <= expected_max, \
        f"Tier {tier}: expected {expected_min}-{expected_max}, got {ppg}"
```

### Pattern 3: Testing Async/Threaded Code

```python
import threading
from time import sleep

def test_thread_safe_tracker():
    """Test progress tracker with concurrent updates"""
    from coordinator.progress_tracker import ProgressTracker

    tracker = ProgressTracker(expected_count=100)

    # Simulate 10 workers completing 10 tasks each
    def worker_completes():
        for _ in range(10):
            tracker.mark_complete('player-X')
            sleep(0.001)

    threads = [threading.Thread(target=worker_completes) for _ in range(10)]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # Verify all 100 completed
    assert tracker.get_completed_count() == 100
    assert tracker.is_complete()
```

### Pattern 4: Testing Error Messages

```python
def test_helpful_error_messages():
    """Ensure errors have helpful messages"""
    from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1

    system = XGBoostV1()

    # Test specific error message
    with pytest.raises(ValueError) as exc_info:
        system.predict(features=None, prop_line=25.5)

    error_msg = str(exc_info.value)
    assert "features" in error_msg.lower()
    assert "required" in error_msg.lower()
```

---

## 🔧 Troubleshooting Tests {#troubleshooting}

### Common Issues

**Issue 1: Import Errors**

```bash
# Error: ModuleNotFoundError: No module named 'coordinator'

# Solution: Run pytest from project root
cd /path/to/nba-stats-scraper
pytest predictions/

# Or add project root to PYTHONPATH
export PYTHONPATH=/path/to/nba-stats-scraper:$PYTHONPATH
pytest predictions/
```

**Issue 2: Fixture Not Found**

```bash
# Error: fixture 'sample_players' not found

# Solution: Check conftest.py location
# Fixtures must be in conftest.py in same directory or parent
# predictions/coordinator/tests/conftest.py → available to all coordinator tests
```

**Issue 3: Tests Pass Locally, Fail in CI**

```python
# Common causes:
# 1. Different random seed
# 2. Timezone differences
# 3. File path assumptions

# Fix: Use explicit seeds and relative paths
def test_with_seed():
    generator = MockDataGenerator(seed=42)  # Explicit seed
    # Now reproducible in CI
```

**Issue 4: Slow Tests**

```bash
# Identify slow tests
pytest predictions/ --durations=10

# Output shows 10 slowest tests:
# 2.34s call predictions/coordinator/tests/test_integration.py::test_full_batch
# 0.89s call predictions/worker/tests/test_xgboost.py::test_training
# ...

# Options:
# 1. Mark slow tests: @pytest.mark.slow
# 2. Skip in CI: pytest predictions/ -m "not slow"
# 3. Optimize test (reduce data, mock more)
```

**Issue 5: Coverage Not Generated**

```bash
# Install pytest-cov
pip install pytest-cov

# Verify installation
pytest --version

# Should show:
# pytest 7.4.3
# plugins: cov-4.1.0, mock-3.12.0
```

### Debug Tips

```bash
# 1. Run single test with print statements
pytest predictions/coordinator/tests/test_coordinator.py::test_start -v -s

# 2. Drop into debugger on failure
pytest predictions/ --pdb

# 3. Show local variables on failure
pytest predictions/ -v -l

# 4. Capture warnings
pytest predictions/ -v -W all

# 5. See full diff on assertion failures
pytest predictions/ -vv
```

---

## 📚 Related Documentation

**Testing Tools:**
- **pytest docs:** https://docs.pytest.org/
- **pytest-cov docs:** https://pytest-cov.readthedocs.io/
- **unittest.mock docs:** https://docs.python.org/3/library/unittest.mock.html

**Phase 5 Documentation:**
- [`tutorials/01-getting-started.md`](01-getting-started.md) - Getting started with Phase 5
- [`operations/01-deployment-guide.md`](../operations/01-deployment-guide.md) - Deployment test scripts
- [`operations/03-troubleshooting.md`](../operations/03-troubleshooting.md) - Production troubleshooting

**Code Locations:**
- Test files: `predictions/*/tests/`
- Mock utilities: `predictions/shared/mock_*.py`
- Fixtures: `predictions/*/tests/conftest.py`

---

## 📝 Quick Reference

### Essential Commands

```bash
# Run all tests
pytest predictions/ -v

# Run with coverage
pytest predictions/ --cov=predictions --cov-report=html

# Run specific file
pytest predictions/coordinator/tests/test_coordinator.py

# Run tests matching keyword
pytest predictions/ -k "test_health"

# Run marked tests only
pytest predictions/ -m integration

# Stop on first failure
pytest predictions/ -x

# Show print statements
pytest predictions/ -s

# Debug on failure
pytest predictions/ --pdb
```

### Import Pattern for Tests

```python
# From test file: predictions/coordinator/tests/test_my_feature.py

# Import module under test
from coordinator.my_feature import MyFeature

# Import shared mocks
from predictions.shared.mock_data_generator import MockDataGenerator
from predictions.shared.mock_xgboost_model import MockXGBoostModel

# Import fixtures (automatically available from conftest.py)
def test_with_fixture(sample_players, mock_bigquery_client):
    # Fixtures injected by pytest
    pass
```

### Test Naming Convention

```python
class TestMyFeature:                    # Test classes start with "Test"
    def test_basic_functionality(self): # Test methods start with "test_"
        pass

    def test_error_handling(self):      # Describe what's tested
        pass

    def test_edge_case_empty_input(self):  # Include edge case context
        pass
```

---

**Version:** 1.0
**Last Updated:** 2025-11-17
**Status:** ✅ Complete

**Questions?** Check [`tutorials/01-getting-started.md`](01-getting-started.md) or [`operations/03-troubleshooting.md`](../operations/03-troubleshooting.md)
