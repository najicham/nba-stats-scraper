"""
Path: tests/processors/precompute/player_composite_factors/conftest.py

Pytest configuration for Player Composite Factors tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.

This allows tests to run without full Google Cloud SDK installed.
"""

import sys
from unittest.mock import MagicMock

# Mock Google Cloud packages before any imports
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()

import pytest
