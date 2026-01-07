"""
MLB Teams Configuration.

Contains all MLB team data for use throughout the application.
"""

TEAMS = [
    # American League East
    {"teamId": "110", "abbr": "BAL", "slug": "orioles", "name": "Baltimore Orioles", "league": "AL", "division": "East"},
    {"teamId": "111", "abbr": "BOS", "slug": "redsox", "name": "Boston Red Sox", "league": "AL", "division": "East"},
    {"teamId": "147", "abbr": "NYY", "slug": "yankees", "name": "New York Yankees", "league": "AL", "division": "East"},
    {"teamId": "139", "abbr": "TB", "slug": "rays", "name": "Tampa Bay Rays", "league": "AL", "division": "East"},
    {"teamId": "141", "abbr": "TOR", "slug": "bluejays", "name": "Toronto Blue Jays", "league": "AL", "division": "East"},

    # American League Central
    {"teamId": "114", "abbr": "CLE", "slug": "guardians", "name": "Cleveland Guardians", "league": "AL", "division": "Central"},
    {"teamId": "116", "abbr": "DET", "slug": "tigers", "name": "Detroit Tigers", "league": "AL", "division": "Central"},
    {"teamId": "118", "abbr": "KC", "slug": "royals", "name": "Kansas City Royals", "league": "AL", "division": "Central"},
    {"teamId": "142", "abbr": "MIN", "slug": "twins", "name": "Minnesota Twins", "league": "AL", "division": "Central"},
    {"teamId": "145", "abbr": "CWS", "slug": "whitesox", "name": "Chicago White Sox", "league": "AL", "division": "Central"},

    # American League West
    {"teamId": "117", "abbr": "HOU", "slug": "astros", "name": "Houston Astros", "league": "AL", "division": "West"},
    {"teamId": "108", "abbr": "LAA", "slug": "angels", "name": "Los Angeles Angels", "league": "AL", "division": "West"},
    {"teamId": "133", "abbr": "OAK", "slug": "athletics", "name": "Oakland Athletics", "league": "AL", "division": "West"},
    {"teamId": "136", "abbr": "SEA", "slug": "mariners", "name": "Seattle Mariners", "league": "AL", "division": "West"},
    {"teamId": "140", "abbr": "TEX", "slug": "rangers", "name": "Texas Rangers", "league": "AL", "division": "West"},

    # National League East
    {"teamId": "144", "abbr": "ATL", "slug": "braves", "name": "Atlanta Braves", "league": "NL", "division": "East"},
    {"teamId": "146", "abbr": "MIA", "slug": "marlins", "name": "Miami Marlins", "league": "NL", "division": "East"},
    {"teamId": "121", "abbr": "NYM", "slug": "mets", "name": "New York Mets", "league": "NL", "division": "East"},
    {"teamId": "143", "abbr": "PHI", "slug": "phillies", "name": "Philadelphia Phillies", "league": "NL", "division": "East"},
    {"teamId": "120", "abbr": "WSH", "slug": "nationals", "name": "Washington Nationals", "league": "NL", "division": "East"},

    # National League Central
    {"teamId": "112", "abbr": "CHC", "slug": "cubs", "name": "Chicago Cubs", "league": "NL", "division": "Central"},
    {"teamId": "113", "abbr": "CIN", "slug": "reds", "name": "Cincinnati Reds", "league": "NL", "division": "Central"},
    {"teamId": "158", "abbr": "MIL", "slug": "brewers", "name": "Milwaukee Brewers", "league": "NL", "division": "Central"},
    {"teamId": "134", "abbr": "PIT", "slug": "pirates", "name": "Pittsburgh Pirates", "league": "NL", "division": "Central"},
    {"teamId": "138", "abbr": "STL", "slug": "cardinals", "name": "St. Louis Cardinals", "league": "NL", "division": "Central"},

    # National League West
    {"teamId": "109", "abbr": "ARI", "slug": "dbacks", "name": "Arizona Diamondbacks", "league": "NL", "division": "West"},
    {"teamId": "115", "abbr": "COL", "slug": "rockies", "name": "Colorado Rockies", "league": "NL", "division": "West"},
    {"teamId": "119", "abbr": "LAD", "slug": "dodgers", "name": "Los Angeles Dodgers", "league": "NL", "division": "West"},
    {"teamId": "135", "abbr": "SD", "slug": "padres", "name": "San Diego Padres", "league": "NL", "division": "West"},
    {"teamId": "137", "abbr": "SF", "slug": "giants", "name": "San Francisco Giants", "league": "NL", "division": "West"},
]

# Valid team abbreviations set
VALID_TEAM_ABBRS = {team["abbr"] for team in TEAMS}

# Team ID to abbreviation mapping
TEAM_ID_TO_ABBR = {team["teamId"]: team["abbr"] for team in TEAMS}

# Abbreviation to team ID mapping
ABBR_TO_TEAM_ID = {team["abbr"]: team["teamId"] for team in TEAMS}

# League mappings
AL_TEAMS = [team for team in TEAMS if team["league"] == "AL"]
NL_TEAMS = [team for team in TEAMS if team["league"] == "NL"]
