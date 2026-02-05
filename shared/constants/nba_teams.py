"""
NBA Team Constants

Canonical source of NBA team tricodes and mappings.
Session 124: Created to ensure consistency across all scripts and tools.

Usage:
    from shared.constants.nba_teams import NBA_TEAMS, NBA_TEAM_TRICODES, validate_tricode
"""

# Official NBA team tricodes (3-letter codes)
# Source: NBA.com official team abbreviations
NBA_TEAM_TRICODES = {
    'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
    'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
    'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
}

# Tricode to full team name mapping
NBA_TEAMS = {
    'ATL': 'Atlanta Hawks',
    'BOS': 'Boston Celtics',
    'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets',
    'CHI': 'Chicago Bulls',
    'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks',
    'DEN': 'Denver Nuggets',
    'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors',
    'HOU': 'Houston Rockets',
    'IND': 'Indiana Pacers',
    'LAC': 'Los Angeles Clippers',
    'LAL': 'Los Angeles Lakers',
    'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat',
    'MIL': 'Milwaukee Bucks',
    'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans',
    'NYK': 'New York Knicks',
    'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic',
    'PHI': 'Philadelphia 76ers',
    'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers',
    'SAC': 'Sacramento Kings',
    'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors',
    'UTA': 'Utah Jazz',
    'WAS': 'Washington Wizards'
}

# Reverse mapping: full name to tricode
NBA_TEAM_NAMES = {v: k for k, v in NBA_TEAMS.items()}


def validate_tricode(code: str, raise_error: bool = False) -> bool:
    """
    Validate that a string is a valid NBA team tricode.

    Args:
        code: The team code to validate (e.g., "OKC", "SAS")
        raise_error: If True, raise ValueError on invalid code

    Returns:
        True if valid, False otherwise

    Raises:
        ValueError: If raise_error=True and code is invalid

    Examples:
        >>> validate_tricode("OKC")
        True
        >>> validate_tricode("okcsa")  # Wrong format
        False
        >>> validate_tricode("XYZ", raise_error=True)
        ValueError: Invalid NBA team tricode: XYZ
    """
    # Strip whitespace and uppercase
    code = code.strip().upper()

    # Check format
    if len(code) != 3:
        if raise_error:
            raise ValueError(f"Team tricode must be exactly 3 characters, got: {code} ({len(code)} chars)")
        return False

    if not code.isalpha():
        if raise_error:
            raise ValueError(f"Team tricode must contain only letters, got: {code}")
        return False

    # Check against known teams
    if code not in NBA_TEAM_TRICODES:
        if raise_error:
            raise ValueError(
                f"Invalid NBA team tricode: {code}\n"
                f"Must be one of: {', '.join(sorted(NBA_TEAM_TRICODES))}"
            )
        return False

    return True


def validate_game_code(game_code: str, raise_error: bool = False) -> bool:
    """
    Validate game code format: YYYYMMDD/XXXXXX (8 digits + slash + 6 letters).

    Args:
        game_code: The game code to validate (e.g., "20260204/OKCSAS")
        raise_error: If True, raise ValueError on invalid code

    Returns:
        True if valid, False otherwise

    Raises:
        ValueError: If raise_error=True and code is invalid

    Examples:
        >>> validate_game_code("20260204/OKCSAS")
        True
        >>> validate_game_code("20260204/OKCSA")  # Only 5 chars
        False
    """
    import re

    # Check basic format
    pattern = r'^(\d{8})/([A-Z]{3})([A-Z]{3})$'
    match = re.match(pattern, game_code)

    if not match:
        if raise_error:
            raise ValueError(
                f"Game code must be in format YYYYMMDD/TEAMTEAM, got: {game_code}\n"
                f"Example: 20260204/OKCSAS (8 digits + slash + 6 uppercase letters)"
            )
        return False

    date_str, away, home = match.groups()

    # Validate date
    try:
        year = int(date_str[0:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])

        if not (2000 <= year <= 2100):
            raise ValueError(f"Year must be 2000-2100, got: {year}")
        if not (1 <= month <= 12):
            raise ValueError(f"Month must be 01-12, got: {month:02d}")
        if not (1 <= day <= 31):
            raise ValueError(f"Day must be 01-31, got: {day:02d}")
    except ValueError as e:
        if raise_error:
            raise ValueError(f"Invalid date in game code {game_code}: {e}")
        return False

    # Validate team codes
    try:
        validate_tricode(away, raise_error=True)
        validate_tricode(home, raise_error=True)
    except ValueError as e:
        if raise_error:
            raise ValueError(f"Invalid team code in game code {game_code}: {e}")
        return False

    # Check for same team
    if away == home:
        if raise_error:
            raise ValueError(f"Away and home teams cannot be the same: {away}")
        return False

    return True


def parse_game_code(game_code: str) -> dict:
    """
    Parse a game code into its components.

    Args:
        game_code: The game code to parse (e.g., "20260204/OKCSAS")

    Returns:
        dict with keys: date, away_team, home_team, away_team_full, home_team_full

    Raises:
        ValueError: If game code is invalid

    Example:
        >>> parse_game_code("20260204/OKCSAS")
        {
            'date': '20260204',
            'away_team': 'OKC',
            'home_team': 'SAS',
            'away_team_full': 'Oklahoma City Thunder',
            'home_team_full': 'San Antonio Spurs'
        }
    """
    import re

    validate_game_code(game_code, raise_error=True)

    match = re.match(r'^(\d{8})/([A-Z]{3})([A-Z]{3})$', game_code)
    date_str, away, home = match.groups()

    return {
        'date': date_str,
        'away_team': away,
        'home_team': home,
        'away_team_full': NBA_TEAMS[away],
        'home_team_full': NBA_TEAMS[home]
    }


# Quick validation checks at module import
assert len(NBA_TEAM_TRICODES) == 30, "Must have exactly 30 NBA teams"
assert len(NBA_TEAMS) == 30, "NBA_TEAMS mapping must have 30 entries"
assert all(len(code) == 3 for code in NBA_TEAM_TRICODES), "All tricodes must be 3 characters"
assert all(code.isupper() for code in NBA_TEAM_TRICODES), "All tricodes must be uppercase"
