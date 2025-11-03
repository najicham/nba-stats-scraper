"""
Pytest configuration for upcoming_player_game_context tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.
"""

import sys
from unittest.mock import MagicMock

# Mock Google Cloud packages before any imports
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()

import pytest
