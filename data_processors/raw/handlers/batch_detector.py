"""
Batch detector for identifying batch processing triggers.

Detects three types of batch processing:
1. Scraper backfill batch triggers (metadata.trigger_type == 'batch_processing')
2. ESPN roster batch triggers (file paths)
3. Basketball Reference roster batch triggers (file paths)
4. OddsAPI batch triggers (file paths)
"""

import logging
import re


logger = logging.getLogger(__name__)


class BatchDetector:
    """Detects and routes batch processing triggers."""

    def is_batch_trigger(self, normalized_message: dict) -> bool:
        """
        Check if message is a batch processing trigger.

        Args:
            normalized_message: Normalized message from MessageHandler

        Returns:
            True if this is a batch trigger, False otherwise
        """
        # Check for explicit batch trigger from scraper backfill
        metadata = normalized_message.get('_metadata', {})
        if metadata.get('trigger_type') == 'batch_processing':
            return True

        # Check for ESPN roster file/folder paths (batch mode)
        file_path = normalized_message.get('name', '')
        if 'espn/rosters' in file_path:
            return True

        # Check for Basketball Reference roster files (batch mode)
        if 'basketball-ref/season-rosters' in file_path and not file_path.endswith('/'):
            return True

        # Check for OddsAPI files (batch mode)
        # Game lines and props for non-history paths
        if ('odds-api/game-lines' in file_path or 'odds-api/player-props' in file_path):
            # Skip history paths - they have their own processing
            if 'history' not in file_path and not file_path.endswith('/'):
                return True

        return False

    def get_batch_type(self, normalized_message: dict) -> str:
        """
        Determine the type of batch processing needed.

        Args:
            normalized_message: Normalized message from MessageHandler

        Returns:
            Batch type: 'espn', 'br', 'oddsapi_backfill', 'espn_folder', or None
        """
        # Check for explicit batch trigger from scraper backfill
        metadata = normalized_message.get('_metadata', {})
        if metadata.get('trigger_type') == 'batch_processing':
            scraper_type = metadata.get('scraper_type', '')
            scraper_name = normalized_message.get('_scraper_name', '')

            if scraper_type == 'espn_roster' or 'espn_roster' in scraper_name:
                return 'espn_backfill'
            else:
                # Default: Basketball Reference Roster Batch
                return 'br_backfill'

        # Check file path patterns
        file_path = normalized_message.get('name', '')

        # ESPN roster folder paths
        if 'espn/rosters' in file_path and file_path.endswith('/'):
            return 'espn_folder'

        # ESPN roster file paths (with lock)
        if 'espn/rosters' in file_path and not file_path.endswith('/'):
            # Extract date to verify it's a valid roster file
            date_match = re.search(r'espn/rosters/(\d{4}-\d{2}-\d{2})/', file_path)
            if date_match:
                return 'espn'

        # Basketball Reference roster files (with lock)
        if 'basketball-ref/season-rosters' in file_path and not file_path.endswith('/'):
            # Extract season to verify it's a valid roster file
            season_match = re.search(r'basketball-ref/season-rosters/(\d{4}-\d{2})/', file_path)
            if season_match:
                return 'br'

        # OddsAPI files (with lock)
        if ('odds-api/game-lines' in file_path or 'odds-api/player-props' in file_path):
            # Skip history paths
            if 'history' not in file_path and not file_path.endswith('/'):
                date_match = re.search(r'odds-api/[^/]+/(\d{4}-\d{2}-\d{2})/', file_path)
                if date_match:
                    if 'game-lines' in file_path:
                        return 'oddsapi_game_lines'
                    else:
                        return 'oddsapi_props'

        return None
