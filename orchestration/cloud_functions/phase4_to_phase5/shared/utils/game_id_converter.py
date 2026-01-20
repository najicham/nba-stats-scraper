"""
Game ID Converter Utility

Centralized utility for converting, validating, and normalizing game IDs
across different NBA data sources.

Standard Format: YYYYMMDD_AWAY_HOME (e.g., "20251229_ATL_OKC")

Different sources use different formats:
- Standard: YYYYMMDD_AWAY_HOME (bdl_player_boxscores, most analytics tables)
- NBA.com: 10-digit code (e.g., "0022500447") - used by nbac_gamebook
- API IDs: Various numeric formats (e.g., "18447269")

This utility provides:
1. Format detection
2. Conversion between formats
3. Parsing of standard format
4. Validation

Usage:
    from shared.utils.game_id_converter import GameIdConverter

    converter = GameIdConverter()

    # Check format
    converter.is_standard_format("20251229_ATL_OKC")  # True
    converter.is_nba_com_format("0022500447")  # True

    # Convert to standard format
    game_id = converter.to_standard_format(
        game_date="2025-12-29",
        away_abbr="ATL",
        home_abbr="OKC"
    )  # "20251229_ATL_OKC"

    # Parse standard format
    date_str, away, home = converter.parse_standard_format("20251229_ATL_OKC")
    # ("20251229", "ATL", "OKC")

Created: 2025-12-30
"""

import re
import logging
from datetime import date, datetime
from typing import Tuple, Optional, Union

logger = logging.getLogger(__name__)


class GameIdConverter:
    """
    Centralized utility for game ID conversion and validation.

    Standardizes all game IDs to format: YYYYMMDD_AWAY_HOME
    """

    # Regex patterns for format detection
    STANDARD_PATTERN = re.compile(r'^(\d{8})_([A-Z]{3})_([A-Z]{3})$')
    NBA_COM_PATTERN = re.compile(r'^00\d{8}$')  # 10 digits starting with 00
    NUMERIC_PATTERN = re.compile(r'^\d+$')  # Any numeric ID

    # Valid NBA team abbreviations (30 teams)
    VALID_TEAMS = {
        'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }

    def is_standard_format(self, game_id: str) -> bool:
        """
        Check if game_id is in standard YYYYMMDD_AWAY_HOME format.

        Args:
            game_id: The game ID to check

        Returns:
            True if in standard format with valid date and team codes
        """
        if not game_id or not isinstance(game_id, str):
            return False

        match = self.STANDARD_PATTERN.match(game_id)
        if not match:
            return False

        date_str, away, home = match.groups()

        # Validate date
        try:
            datetime.strptime(date_str, '%Y%m%d')
        except ValueError:
            return False

        # Validate team abbreviations
        if away not in self.VALID_TEAMS or home not in self.VALID_TEAMS:
            return False

        # Away and home should be different
        if away == home:
            return False

        return True

    def is_nba_com_format(self, game_id: str) -> bool:
        """
        Check if game_id is in NBA.com format (10-digit code starting with 00).

        Examples: "0022500447", "0022400123"

        Args:
            game_id: The game ID to check

        Returns:
            True if in NBA.com format
        """
        if not game_id or not isinstance(game_id, str):
            return False
        return bool(self.NBA_COM_PATTERN.match(game_id))

    def is_numeric_format(self, game_id: str) -> bool:
        """
        Check if game_id is a pure numeric ID (like API IDs).

        Args:
            game_id: The game ID to check

        Returns:
            True if purely numeric
        """
        if not game_id or not isinstance(game_id, str):
            return False
        return bool(self.NUMERIC_PATTERN.match(game_id))

    def detect_format(self, game_id: str) -> str:
        """
        Detect the format of a game ID.

        Args:
            game_id: The game ID to check

        Returns:
            One of: 'standard', 'nba_com', 'numeric', 'unknown'
        """
        if self.is_standard_format(game_id):
            return 'standard'
        if self.is_nba_com_format(game_id):
            return 'nba_com'
        if self.is_numeric_format(game_id):
            return 'numeric'
        return 'unknown'

    def to_standard_format(
        self,
        game_date: Union[str, date],
        away_abbr: str,
        home_abbr: str
    ) -> str:
        """
        Convert game components to standard format: YYYYMMDD_AWAY_HOME

        Args:
            game_date: Game date as string (YYYY-MM-DD or YYYYMMDD) or date object
            away_abbr: Away team abbreviation (e.g., "ATL")
            home_abbr: Home team abbreviation (e.g., "OKC")

        Returns:
            Standardized game ID (e.g., "20251229_ATL_OKC")

        Raises:
            ValueError: If inputs are invalid
        """
        # Handle date
        if isinstance(game_date, date):
            date_str = game_date.strftime('%Y%m%d')
        elif isinstance(game_date, str):
            # Remove hyphens if present: "2025-12-29" → "20251229"
            date_str = game_date.replace('-', '')
            # Validate
            if len(date_str) != 8 or not date_str.isdigit():
                raise ValueError(f"Invalid date format: {game_date}. Expected YYYY-MM-DD or YYYYMMDD")
            # Validate it's a real date
            try:
                datetime.strptime(date_str, '%Y%m%d')
            except ValueError:
                raise ValueError(f"Invalid date: {game_date}")
        else:
            raise ValueError(f"game_date must be str or date, got {type(game_date)}")

        # Normalize team abbreviations
        away_abbr = away_abbr.upper().strip()
        home_abbr = home_abbr.upper().strip()

        # Validate teams
        if away_abbr not in self.VALID_TEAMS:
            raise ValueError(f"Invalid away team: {away_abbr}")
        if home_abbr not in self.VALID_TEAMS:
            raise ValueError(f"Invalid home team: {home_abbr}")
        if away_abbr == home_abbr:
            raise ValueError(f"Away and home teams cannot be the same: {away_abbr}")

        game_id = f"{date_str}_{away_abbr}_{home_abbr}"
        logger.debug(f"Generated standard game_id: {game_id}")
        return game_id

    def parse_standard_format(self, game_id: str) -> Tuple[str, str, str]:
        """
        Parse a standard format game ID into components.

        Args:
            game_id: Game ID in format YYYYMMDD_AWAY_HOME

        Returns:
            Tuple of (date_str, away_abbr, home_abbr)
            e.g., ("20251229", "ATL", "OKC")

        Raises:
            ValueError: If game_id is not in standard format
        """
        if not self.is_standard_format(game_id):
            raise ValueError(f"Invalid standard format game_id: {game_id}")

        match = self.STANDARD_PATTERN.match(game_id)
        return match.groups()

    def safe_parse_standard_format(
        self,
        game_id: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Safely parse a game ID, returning None values if not in standard format.

        This is useful when you need to handle mixed formats gracefully.

        Args:
            game_id: Game ID (any format)

        Returns:
            Tuple of (date_str, away_abbr, home_abbr) or (None, None, None)
        """
        if not game_id:
            return (None, None, None)

        if not self.is_standard_format(game_id):
            logger.debug(f"Cannot parse non-standard game_id: {game_id}")
            return (None, None, None)

        match = self.STANDARD_PATTERN.match(game_id)
        return match.groups()

    def get_date_from_game_id(self, game_id: str) -> Optional[date]:
        """
        Extract the game date from a standard format game ID.

        Args:
            game_id: Game ID in standard format

        Returns:
            date object or None if parsing fails
        """
        date_str, _, _ = self.safe_parse_standard_format(game_id)
        if date_str:
            try:
                return datetime.strptime(date_str, '%Y%m%d').date()
            except ValueError:
                pass
        return None

    def get_teams_from_game_id(self, game_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract away and home teams from a standard format game ID.

        Args:
            game_id: Game ID in standard format

        Returns:
            Tuple of (away_abbr, home_abbr) or (None, None) if parsing fails
        """
        _, away, home = self.safe_parse_standard_format(game_id)
        return (away, home)

    def normalize_game_id(
        self,
        game_id: str,
        game_date: Optional[Union[str, date]] = None,
        away_abbr: Optional[str] = None,
        home_abbr: Optional[str] = None
    ) -> Optional[str]:
        """
        Normalize a game ID to standard format.

        If game_id is already in standard format, returns it as-is.
        If not, requires game_date, away_abbr, and home_abbr to build standard format.

        Args:
            game_id: Original game ID (any format)
            game_date: Game date (required if game_id is not standard format)
            away_abbr: Away team (required if game_id is not standard format)
            home_abbr: Home team (required if game_id is not standard format)

        Returns:
            Standardized game ID or None if cannot normalize
        """
        # Already standard format
        if self.is_standard_format(game_id):
            return game_id

        # Need additional info to normalize
        if not all([game_date, away_abbr, home_abbr]):
            logger.warning(
                f"Cannot normalize game_id '{game_id}' without game_date, away_abbr, home_abbr"
            )
            return None

        try:
            return self.to_standard_format(game_date, away_abbr, home_abbr)
        except ValueError as e:
            logger.error(f"Failed to normalize game_id '{game_id}': {e}")
            return None

    def validate_game_id(self, game_id: str, strict: bool = True) -> bool:
        """
        Validate a game ID.

        Args:
            game_id: The game ID to validate
            strict: If True, only accepts standard format.
                   If False, accepts any recognized format.

        Returns:
            True if valid
        """
        if strict:
            return self.is_standard_format(game_id)
        else:
            format_type = self.detect_format(game_id)
            return format_type != 'unknown'


# Module-level singleton for convenience
_converter: Optional[GameIdConverter] = None


def get_game_id_converter() -> GameIdConverter:
    """Get the singleton GameIdConverter instance."""
    global _converter
    if _converter is None:
        _converter = GameIdConverter()
    return _converter


# Convenience functions using the singleton
def to_standard_game_id(
    game_date: Union[str, date],
    away_abbr: str,
    home_abbr: str
) -> str:
    """
    Convert game components to standard format.

    Convenience function - see GameIdConverter.to_standard_format() for details.
    """
    return get_game_id_converter().to_standard_format(game_date, away_abbr, home_abbr)


def parse_game_id(game_id: str) -> Tuple[str, str, str]:
    """
    Parse a standard format game ID.

    Convenience function - see GameIdConverter.parse_standard_format() for details.
    """
    return get_game_id_converter().parse_standard_format(game_id)


def is_standard_game_id(game_id: str) -> bool:
    """
    Check if game_id is in standard format.

    Convenience function - see GameIdConverter.is_standard_format() for details.
    """
    return get_game_id_converter().is_standard_format(game_id)
