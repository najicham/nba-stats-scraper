"""
Change Detector Wrapper for Player Game Summary

Wraps the shared PlayerChangeDetector for player game summary usage.

Extracted from: player_game_summary_processor.py::get_change_detector()
"""

import logging
from shared.change_detection.change_detector import PlayerChangeDetector

logger = logging.getLogger(__name__)


class ChangeDetectorWrapper:
    """
    Wrapper around PlayerChangeDetector for incremental processing.

    Enables 99%+ efficiency gain for mid-day updates by detecting
    which players have changed data since last processing.
    """

    @staticmethod
    def create_detector(project_id: str) -> PlayerChangeDetector:
        """
        Create a PlayerChangeDetector configured for player stats.

        Args:
            project_id: GCP project ID

        Returns:
            PlayerChangeDetector instance
        """
        return PlayerChangeDetector(project_id=project_id)
