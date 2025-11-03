"""
Pytest configuration for team_offense_game_summary tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.

Path: tests/processors/analytics/team_offense_game_summary/conftest.py
"""

import sys
from unittest.mock import MagicMock

# Mock Google Cloud packages before any imports
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()

import pytest
