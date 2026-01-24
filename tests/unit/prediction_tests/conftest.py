# tests/unit/prediction_tests/conftest.py
"""Pytest configuration for prediction tests."""
import sys
import os

# Add project root to path FIRST before any other imports
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _project_root in sys.path:
    sys.path.remove(_project_root)
sys.path.insert(0, _project_root)
