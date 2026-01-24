#!/usr/bin/env python3
"""
MLB Game ID Converter

Centralized utility for MLB game ID conversion and validation.
Standardizes all game IDs to format: YYYYMMDD_AWAY_HOME

Features:
- Multiple source format support (Statcast, ESPN, BR, internal)
- Doubleheader handling (game 1 vs game 2)
- Validation against MLB team codes
- Parsing and construction utilities

Usage:
    from shared.utils.mlb_game_id_converter import MLBGameIdConverter

    converter = MLBGameIdConverter()

    # Standardize any game ID format
    standard_id = converter.to_standard("20240615_NYY_BOS")

    # Parse components
    date, away, home = converter.parse("20240615_NYY_BOS")

    # Create game ID
    game_id = converter.create("2024-06-15", "NYY", "BOS")

    # Handle doubleheaders
    game1_id = converter.create("2024-06-15", "NYY", "BOS", game_number=1)
    game2_id = converter.create("2024-06-15", "NYY", "BOS", game_number=2)

Created: 2026-01-13
"""

import logging
import re
from datetime import datetime, date
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Valid MLB team abbreviations (30 teams)
# Includes both 2-letter and 3-letter variants
VALID_MLB_TEAMS = {
    # American League
    'BAL', 'BOS', 'NYY', 'TB', 'TBR', 'TOR',  # AL East
    'CLE', 'CWS', 'CHW', 'DET', 'KC', 'KCR', 'MIN',  # AL Central
    'HOU', 'LAA', 'ANA', 'OAK', 'SEA', 'TEX',  # AL West
    # National League
    'ATL', 'MIA', 'FLA', 'NYM', 'PHI', 'WSH', 'WSN', 'WAS',  # NL East
    'CHC', 'CIN', 'MIL', 'PIT', 'STL',  # NL Central
    'ARI', 'AZ', 'COL', 'LAD', 'SD', 'SDP', 'SF', 'SFG',  # NL West
}

# Canonical team codes (normalize variants to these)
CANONICAL_TEAM_CODES = {
    'TBR': 'TB', 'TAM': 'TB', 'TBA': 'TB',
    'KCR': 'KC', 'KAN': 'KC',
    'CHW': 'CWS', 'CHA': 'CWS',
    'ANA': 'LAA', 'CAL': 'LAA', 'ANH': 'LAA',
    'FLA': 'MIA',
    'WSN': 'WSH', 'WAS': 'WSH',
    'AZ': 'ARI', 'PHX': 'ARI',
    'SDP': 'SD', 'SDG': 'SD',
    'SFG': 'SF', 'SFN': 'SF',
}


@dataclass
class ParsedGameId:
    """Parsed components of a game ID."""
    game_date: date
    away_team: str
    home_team: str
    game_number: Optional[int] = None  # 1 or 2 for doubleheaders
    is_valid: bool = True
    error_message: Optional[str] = None


class MLBGameIdConverter:
    """
    MLB Game ID converter and validator.

    Standardizes game IDs to format: YYYYMMDD_AWAY_HOME
    Handles doubleheaders with suffix: YYYYMMDD_AWAY_HOME_1 or _2
    """

    # Standard format: YYYYMMDD_AWAY_HOME or YYYYMMDD_AWAY_HOME_N
    STANDARD_PATTERN = re.compile(
        r'^(\d{8})_([A-Z]{2,3})_([A-Z]{2,3})(?:_([12]))?$'
    )

    # Statcast format: various
    STATCAST_PATTERN = re.compile(
        r'^(\d{4})-(\d{2})-(\d{2})_([A-Z]{2,3})@([A-Z]{2,3})$'
    )

    # ESPN format: gameId from ESPN API
    ESPN_PATTERN = re.compile(r'^(\d{9,12})$')

    # Date-only format with teams in path
    DATE_TEAMS_PATTERN = re.compile(
        r'^(\d{4})-?(\d{2})-?(\d{2})[-_]([A-Z]{2,3})[-_@]([A-Z]{2,3})$'
    )

    def __init__(self):
        self.valid_teams = VALID_MLB_TEAMS
        self.canonical_codes = CANONICAL_TEAM_CODES

    def normalize_team_code(self, code: str) -> str:
        """Normalize team code to canonical form."""
        upper = code.upper()
        return self.canonical_codes.get(upper, upper)

    def is_valid_team(self, code: str) -> bool:
        """Check if team code is valid."""
        return code.upper() in self.valid_teams

    def parse(self, game_id: str) -> ParsedGameId:
        """
        Parse a game ID into its components.

        Args:
            game_id: Game ID in any supported format

        Returns:
            ParsedGameId with components or error info
        """
        if not game_id:
            return ParsedGameId(
                game_date=date.today(),
                away_team="",
                home_team="",
                is_valid=False,
                error_message="Empty game ID"
            )

        game_id = game_id.strip()

        # Try standard format first
        match = self.STANDARD_PATTERN.match(game_id.upper())
        if match:
            date_str, away, home, game_num = match.groups()
            try:
                game_date = datetime.strptime(date_str, '%Y%m%d').date()
                return ParsedGameId(
                    game_date=game_date,
                    away_team=self.normalize_team_code(away),
                    home_team=self.normalize_team_code(home),
                    game_number=int(game_num) if game_num else None,
                    is_valid=True
                )
            except ValueError as e:
                return ParsedGameId(
                    game_date=date.today(),
                    away_team=away,
                    home_team=home,
                    is_valid=False,
                    error_message=f"Invalid date: {e}"
                )

        # Try Statcast format: 2024-06-15_NYY@BOS
        match = self.STATCAST_PATTERN.match(game_id.upper())
        if match:
            year, month, day, away, home = match.groups()
            try:
                game_date = date(int(year), int(month), int(day))
                return ParsedGameId(
                    game_date=game_date,
                    away_team=self.normalize_team_code(away),
                    home_team=self.normalize_team_code(home),
                    is_valid=True
                )
            except ValueError as e:
                return ParsedGameId(
                    game_date=date.today(),
                    away_team=away,
                    home_team=home,
                    is_valid=False,
                    error_message=f"Invalid date: {e}"
                )

        # Try date-teams format: 20240615-NYY-BOS or 2024-06-15_NYY_BOS
        match = self.DATE_TEAMS_PATTERN.match(game_id.upper())
        if match:
            year, month, day, away, home = match.groups()
            try:
                game_date = date(int(year), int(month), int(day))
                return ParsedGameId(
                    game_date=game_date,
                    away_team=self.normalize_team_code(away),
                    home_team=self.normalize_team_code(home),
                    is_valid=True
                )
            except ValueError as e:
                return ParsedGameId(
                    game_date=date.today(),
                    away_team=away,
                    home_team=home,
                    is_valid=False,
                    error_message=f"Invalid date: {e}"
                )

        return ParsedGameId(
            game_date=date.today(),
            away_team="",
            home_team="",
            is_valid=False,
            error_message=f"Unrecognized game ID format: {game_id}"
        )

    def to_standard(self, game_id: str) -> Optional[str]:
        """
        Convert any game ID format to standard format.

        Args:
            game_id: Game ID in any supported format

        Returns:
            Standard format game ID or None if invalid
        """
        parsed = self.parse(game_id)
        if not parsed.is_valid:
            logger.warning(f"Invalid game ID: {game_id} - {parsed.error_message}")
            return None

        return self.create(
            game_date=parsed.game_date,
            away_team=parsed.away_team,
            home_team=parsed.home_team,
            game_number=parsed.game_number
        )

    def create(
        self,
        game_date: date | str,
        away_team: str,
        home_team: str,
        game_number: Optional[int] = None
    ) -> str:
        """
        Create a standard game ID.

        Args:
            game_date: Game date (date object or 'YYYY-MM-DD' string)
            away_team: Away team code
            home_team: Home team code
            game_number: 1 or 2 for doubleheaders (optional)

        Returns:
            Standard format game ID: YYYYMMDD_AWAY_HOME or YYYYMMDD_AWAY_HOME_N
        """
        # Handle string date
        if isinstance(game_date, str):
            game_date = datetime.strptime(game_date, '%Y-%m-%d').date()

        # Normalize team codes
        away = self.normalize_team_code(away_team)
        home = self.normalize_team_code(home_team)

        # Format date
        date_str = game_date.strftime('%Y%m%d')

        # Build game ID
        game_id = f"{date_str}_{away}_{home}"

        # Add game number for doubleheaders
        if game_number in (1, 2):
            game_id += f"_{game_number}"

        return game_id

    def validate(self, game_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a game ID.

        Args:
            game_id: Game ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        parsed = self.parse(game_id)

        if not parsed.is_valid:
            return False, parsed.error_message

        # Validate teams
        if not self.is_valid_team(parsed.away_team):
            return False, f"Invalid away team: {parsed.away_team}"

        if not self.is_valid_team(parsed.home_team):
            return False, f"Invalid home team: {parsed.home_team}"

        # Validate date is reasonable (not too far in past or future)
        today = date.today()
        min_date = date(2000, 1, 1)  # Earliest reasonable MLB data
        max_date = date(today.year + 1, 12, 31)  # Max 1 year in future

        if parsed.game_date < min_date:
            return False, f"Date too old: {parsed.game_date}"

        if parsed.game_date > max_date:
            return False, f"Date too far in future: {parsed.game_date}"

        return True, None

    def get_date(self, game_id: str) -> Optional[date]:
        """Extract date from game ID."""
        parsed = self.parse(game_id)
        return parsed.game_date if parsed.is_valid else None

    def get_teams(self, game_id: str) -> Optional[Tuple[str, str]]:
        """Extract (away_team, home_team) from game ID."""
        parsed = self.parse(game_id)
        if parsed.is_valid:
            return (parsed.away_team, parsed.home_team)
        return None

    def is_doubleheader(self, game_id: str) -> bool:
        """Check if game ID indicates a doubleheader game."""
        parsed = self.parse(game_id)
        return parsed.game_number is not None

    def get_game_number(self, game_id: str) -> Optional[int]:
        """Get game number (1 or 2) for doubleheader, None otherwise."""
        parsed = self.parse(game_id)
        return parsed.game_number


# Singleton instance
_converter_instance: Optional[MLBGameIdConverter] = None


def get_mlb_game_id_converter() -> MLBGameIdConverter:
    """Get singleton MLBGameIdConverter instance."""
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = MLBGameIdConverter()
    return _converter_instance


# Convenience functions
def standardize_mlb_game_id(game_id: str) -> Optional[str]:
    """Convert any MLB game ID format to standard format."""
    return get_mlb_game_id_converter().to_standard(game_id)


def validate_mlb_game_id(game_id: str) -> bool:
    """Validate an MLB game ID."""
    is_valid, _ = get_mlb_game_id_converter().validate(game_id)
    return is_valid


def create_mlb_game_id(
    game_date: date | str,
    away_team: str,
    home_team: str,
    game_number: Optional[int] = None
) -> str:
    """Create a standard MLB game ID."""
    return get_mlb_game_id_converter().create(
        game_date, away_team, home_team, game_number
    )


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    converter = MLBGameIdConverter()

    logger.info("MLB Game ID Converter Test")
    logger.info("=" * 60)

    # Test various formats
    test_ids = [
        "20240615_NYY_BOS",
        "20240615_NYY_BOS_1",  # Doubleheader game 1
        "20240615_NYY_BOS_2",  # Doubleheader game 2
        "2024-06-15_NYY@BOS",  # Statcast format
        "20240615-NYY-BOS",    # Hyphenated
        "2024-06-15_TBR_KC",   # Alternate codes
        "invalid_game_id",
    ]

    for game_id in test_ids:
        parsed = converter.parse(game_id)
        if parsed.is_valid:
            standard = converter.to_standard(game_id)
            logger.info(f"{game_id:30} -> {standard}")
            if parsed.game_number:
                logger.debug(f"{'':30}    (Doubleheader game {parsed.game_number})")
        else:
            logger.warning(f"{game_id:30} -> INVALID: {parsed.error_message}")

    logger.info("Create game IDs:")
    logger.info(converter.create("2024-06-15", "NYY", "BOS"))
    logger.info(converter.create("2024-06-15", "NYY", "BOS", game_number=1))
    logger.info(converter.create("2024-06-15", "NYY", "BOS", game_number=2))
