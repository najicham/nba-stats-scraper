# Path: tests/predictions/__init__.py
"""
Unit tests for Phase 5 predictions

Test Structure:
    - test_mock_data_generator.py: Mock data generation tests
    - test_base_predictor.py: Base predictor interface tests (future)
    - test_moving_average.py: Moving average system tests (future)
    - test_zone_matchup.py: Zone matchup system tests (future)
    - test_similarity.py: Similarity system tests (future)
    - test_xgboost.py: XGBoost system tests (future)
    - test_ensemble.py: Ensemble system tests (future)

Run all tests:
    pytest tests/unit/predictions/ -v

Run specific test:
    pytest tests/unit/predictions/test_mock_data_generator.py -v

Run with coverage:
    pytest tests/unit/predictions/ --cov=predictions --cov-report=html
"""
import sys
from pathlib import Path

# Ensure project root is at the beginning of sys.path to avoid
# namespace conflicts with test directories
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
