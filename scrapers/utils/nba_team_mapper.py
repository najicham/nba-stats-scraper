# FILE: scrapers/utils/nba_team_mapper.py
"""
NBA Team Name to Abbreviation Mapper

Shared utility for converting Odds API team names to NBA standard abbreviations
and building team-based path suffixes following NBA.com gameCode conventions.

Usage:
    from scrapers.utils.nba_team_mapper import build_teams_suffix, get_team_abbr
    
    # In scraper transform_data():
    teams_suffix = build_teams_suffix("Los Angeles Lakers", "Detroit Pistons")
    # Returns: "LALDET"
    
    # For GCS path building:
    self.opts["teams"] = teams_suffix
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Team name to abbreviation mapping for Odds API responses
NBA_TEAM_NAME_TO_ABBR: Dict[str, str] = {
    # Full team names as they appear in Odds API responses
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS", 
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",  # Handle both formats
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS"
}


def get_team_abbr(team_name: str) -> str:
    """
    Convert full team name to 3-letter abbreviation.
    
    Args:
        team_name: Full team name from Odds API (e.g., "Los Angeles Lakers")
        
    Returns:
        3-letter team abbreviation (e.g., "LAL")
        Falls back to first 3 letters if team not found in mapping
        
    Examples:
        >>> get_team_abbr("Los Angeles Lakers")
        'LAL'
        >>> get_team_abbr("Detroit Pistons") 
        'DET'
        >>> get_team_abbr("Unknown Team")
        'UNK'
    """
    if team_name in NBA_TEAM_NAME_TO_ABBR:
        return NBA_TEAM_NAME_TO_ABBR[team_name]
    
    # Fallback: use first 3 letters (uppercase, remove spaces)
    return team_name.replace(" ", "")[:3].upper()


def build_teams_suffix(away_team: str, home_team: str) -> str:
    """
    Build team suffix for GCS paths following NBA.com gameCode conventions.
    
    Format matches NBA.com gameCode pattern: "20230101/SACMEM" -> we use "SACMEM" part
    
    Args:
        away_team: Away team full name (e.g., "Los Angeles Lakers")
        home_team: Home team full name (e.g., "Detroit Pistons")
        
    Returns:
        Team suffix in format: "LALDET" (away + home, no separator)
        
    Examples:
        >>> build_teams_suffix("Los Angeles Lakers", "Detroit Pistons")
        'LALDET'
        >>> build_teams_suffix("Golden State Warriors", "Boston Celtics")
        'GSWBOS'
    """
    away_abbr = get_team_abbr(away_team)
    home_abbr = get_team_abbr(home_team)
    return f"{away_abbr}{home_abbr}"


def parse_teams_from_event(event_data: Dict) -> tuple[str, str]:
    """
    Extract away and home team names from Odds API event data.
    
    Args:
        event_data: Event dictionary from Odds API response
        
    Returns:
        Tuple of (away_team, home_team) names
        
    Example:
        >>> event = {"away_team": "Los Angeles Lakers", "home_team": "Detroit Pistons"}
        >>> parse_teams_from_event(event)
        ('Los Angeles Lakers', 'Detroit Pistons')
    """
    away_team = event_data.get("away_team", "")
    home_team = event_data.get("home_team", "")
    return away_team, home_team


def build_event_teams_suffix(event_data: Dict) -> str:
    """
    Convenience function to build teams suffix directly from event data.
    
    Args:
        event_data: Event dictionary from Odds API response
        
    Returns:
        Team suffix string (e.g., "LALDET")
        
    Example:
        >>> event = {"away_team": "Los Angeles Lakers", "home_team": "Detroit Pistons"}
        >>> build_event_teams_suffix(event)
        'LALDET'
    """
    away_team, home_team = parse_teams_from_event(event_data)
    return build_teams_suffix(away_team, home_team)


# Test and validation functions
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    logger.info("=== NBA Team Mapper Test ===")

    # Test individual team mapping
    test_teams = [
        "Los Angeles Lakers",
        "Golden State Warriors",
        "Miami Heat",
        "Unknown Team Name"  # Test fallback
    ]

    logger.info("1. Individual Team Mapping:")
    for team in test_teams:
        abbr = get_team_abbr(team)
        logger.info(f"  {team:25} -> {abbr}")

    # Test team suffix building
    test_matchups = [
        ("Los Angeles Lakers", "Detroit Pistons"),
        ("Golden State Warriors", "Boston Celtics"),
        ("Miami Heat", "Denver Nuggets"),
        ("Phoenix Suns", "Milwaukee Bucks")
    ]

    logger.info("2. Team Suffix Building (NBA.com gameCode style):")
    for away, home in test_matchups:
        suffix = build_teams_suffix(away, home)
        logger.info(f"  {away} @ {home}")
        logger.info(f"    -> {suffix}")

    # Test with event data structure
    logger.info("3. Event Data Processing:")
    sample_event = {
        "id": "da359da99aa27e97d38f2df709343998",
        "sport_key": "basketball_nba",
        "commence_time": "2023-11-30T00:10:00Z",
        "home_team": "Detroit Pistons",
        "away_team": "Los Angeles Lakers"
    }

    suffix = build_event_teams_suffix(sample_event)
    logger.info(f"  Event: {sample_event['away_team']} @ {sample_event['home_team']}")
    logger.info(f"  Teams suffix: {suffix}")
    logger.info(f"  Expected GCS path component: {sample_event['id']}-{suffix}")

    logger.info(f"4. All Available Teams ({len(NBA_TEAM_NAME_TO_ABBR)}):")
    for team, abbr in sorted(NBA_TEAM_NAME_TO_ABBR.items()):
        logger.debug(f"  {abbr}: {team}")
        