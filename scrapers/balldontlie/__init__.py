# scrapers/balldontlie/__init__.py
from datetime import date

_TODAY = date.today().isoformat()

BDL_SCRAPER_MATRIX = {
    "bdl_active_players":         [],
    "bdl_advanced_stats":         ["--dates", _TODAY],
    "bdl_box_scores":             ["--date", _TODAY],
    "bdl_game_detail":            ["--gameId", "18444564"],
    "bdl_game_stats":             ["--date", _TODAY],
    "bdl_games":                  ["--startDate", _TODAY, "--endDate", _TODAY],
    "bdl_injuries":               [],
    "bdl_leaders":                ["--stat", "points"],
    "bdl_live_box_scores":        ["--date", _TODAY],
    "bdl_odds":                   ["--date", _TODAY],
    "bdl_player_detail":          ["--playerId", "237"],            # LeBron :)
    "bdl_players":                ["--search", "curry"],
    "bdl_season_averages":        ["--season", "2024"],
    "bdl_standings":              [],
    "bdl_team_detail":            ["--teamId", "14"],               # LAC
    "bdl_teams":                  [],
}
