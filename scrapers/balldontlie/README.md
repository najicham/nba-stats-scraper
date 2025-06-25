
# Docs

Player Boxscore
https://docs.balldontlie.io/#get-all-stats



# Testing Order

Testing order (fastest failure first)

bdl_teams – option‑free sanity

bdl_active_players – big payload, gzip trigger

bdl_standings – option‑free, pagination

bdl_games --startDate … – date params

bdl_odds --date … – date param, join check

bdl_game_detail --gameId …

bdl_player_detail --playerId …

bdl_season_averages --season 2024

bdl_leaders --stat points

bdl_box_scores / bdl_game_stats / bdl_advanced_stats --date …

bdl_live_box_scores --date …

bdl_injuries – may return empty list

Forgot about
bdl_game_stats
bdl_advanced_stats
bdl_team_detail


python tools/fixtures/capture.py bdl_player_detail --debug --playerId 237
python tools/fixtures/capture.py bdl_leaders --debug --statType reb --season 2024
python tools/fixtures/capture.py bdl_season_averages --debug --playerIds 237,115,140 --season 2024
python tools/fixtures/capture.py bdl_box_scores --debug --date 2025-06-21

python tools/fixtures/capture.py bdl_injuries --debug --teamId 2

python tools/fixtures/capture.py bdl_season_averages --debug --playerIds 237,115,140 --season 2024



