"""
Path: tests/processors/analytics/upcoming_team_game_context/conftest.py

Pytest configuration for Upcoming Team Game Context Processor tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.

This allows tests to run without full Google Cloud SDK installed.
"""

import sys
from unittest.mock import MagicMock

# Mock Google Cloud packages before any imports
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()

import pytest