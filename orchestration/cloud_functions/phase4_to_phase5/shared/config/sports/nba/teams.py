"""
NBA Teams Configuration.

Contains all NBA team data for use throughout the application.
"""

TEAMS = [
    {"teamId": "1610612737", "abbr": "ATL", "slug": "hawks", "name": "Atlanta Hawks", "conference": "East"},
    {"teamId": "1610612738", "abbr": "BOS", "slug": "celtics", "name": "Boston Celtics", "conference": "East"},
    {"teamId": "1610612751", "abbr": "BKN", "slug": "nets", "name": "Brooklyn Nets", "conference": "East"},
    {"teamId": "1610612766", "abbr": "CHA", "slug": "hornets", "name": "Charlotte Hornets", "conference": "East"},
    {"teamId": "1610612741", "abbr": "CHI", "slug": "bulls", "name": "Chicago Bulls", "conference": "East"},
    {"teamId": "1610612739", "abbr": "CLE", "slug": "cavaliers", "name": "Cleveland Cavaliers", "conference": "East"},
    {"teamId": "1610612742", "abbr": "DAL", "slug": "mavericks", "name": "Dallas Mavericks", "conference": "West"},
    {"teamId": "1610612743", "abbr": "DEN", "slug": "nuggets", "name": "Denver Nuggets", "conference": "West"},
    {"teamId": "1610612765", "abbr": "DET", "slug": "pistons", "name": "Detroit Pistons", "conference": "East"},
    {"teamId": "1610612744", "abbr": "GSW", "slug": "warriors", "name": "Golden State Warriors", "conference": "West"},
    {"teamId": "1610612745", "abbr": "HOU", "slug": "rockets", "name": "Houston Rockets", "conference": "West"},
    {"teamId": "1610612754", "abbr": "IND", "slug": "pacers", "name": "Indiana Pacers", "conference": "East"},
    {"teamId": "1610612746", "abbr": "LAC", "slug": "clippers", "name": "Los Angeles Clippers", "conference": "West"},
    {"teamId": "1610612747", "abbr": "LAL", "slug": "lakers", "name": "Los Angeles Lakers", "conference": "West"},
    {"teamId": "1610612763", "abbr": "MEM", "slug": "grizzlies", "name": "Memphis Grizzlies", "conference": "West"},
    {"teamId": "1610612748", "abbr": "MIA", "slug": "heat", "name": "Miami Heat", "conference": "East"},
    {"teamId": "1610612749", "abbr": "MIL", "slug": "bucks", "name": "Milwaukee Bucks", "conference": "East"},
    {"teamId": "1610612750", "abbr": "MIN", "slug": "timberwolves", "name": "Minnesota Timberwolves", "conference": "West"},
    {"teamId": "1610612740", "abbr": "NOP", "slug": "pelicans", "name": "New Orleans Pelicans", "conference": "West"},
    {"teamId": "1610612752", "abbr": "NYK", "slug": "knicks", "name": "New York Knicks", "conference": "East"},
    {"teamId": "1610612760", "abbr": "OKC", "slug": "thunder", "name": "Oklahoma City Thunder", "conference": "West"},
    {"teamId": "1610612753", "abbr": "ORL", "slug": "magic", "name": "Orlando Magic", "conference": "East"},
    {"teamId": "1610612755", "abbr": "PHI", "slug": "sixers", "name": "Philadelphia 76ers", "conference": "East"},
    {"teamId": "1610612756", "abbr": "PHX", "slug": "suns", "name": "Phoenix Suns", "conference": "West"},
    {"teamId": "1610612757", "abbr": "POR", "slug": "blazers", "name": "Portland Trail Blazers", "conference": "West"},
    {"teamId": "1610612758", "abbr": "SAC", "slug": "kings", "name": "Sacramento Kings", "conference": "West"},
    {"teamId": "1610612759", "abbr": "SAS", "slug": "spurs", "name": "San Antonio Spurs", "conference": "West"},
    {"teamId": "1610612761", "abbr": "TOR", "slug": "raptors", "name": "Toronto Raptors", "conference": "East"},
    {"teamId": "1610612762", "abbr": "UTA", "slug": "jazz", "name": "Utah Jazz", "conference": "West"},
    {"teamId": "1610612764", "abbr": "WAS", "slug": "wizards", "name": "Washington Wizards", "conference": "East"},
]

# Basketball Reference uses slightly different abbreviations
BASKETBALL_REF_TEAMS = [
    "ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
]

# Valid team abbreviations set
VALID_TEAM_ABBRS = {team["abbr"] for team in TEAMS}

# Team ID to abbreviation mapping
TEAM_ID_TO_ABBR = {team["teamId"]: team["abbr"] for team in TEAMS}

# Abbreviation to team ID mapping
ABBR_TO_TEAM_ID = {team["abbr"]: team["teamId"] for team in TEAMS}
