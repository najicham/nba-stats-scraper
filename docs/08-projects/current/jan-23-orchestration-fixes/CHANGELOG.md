# Changelog - January 23, 2026 Orchestration Fixes

## [2026-01-23] - Critical Bug Fixes

### Fixed

#### orchestration/parameter_resolver.py
- **YESTERDAY_TARGET_WORKFLOWS**: Added `post_game_window_2b` and `morning_recovery` to the list of workflows that should target yesterday's games instead of today's
- **complex_resolvers**: Added `oddsa_events` resolver to provide `sport` and `game_date` parameters
- **_resolve_odds_events()**: New method that returns `{'sport': 'basketball_nba', 'game_date': context['execution_date']}`

#### data_processors/precompute/ml_feature_store/feature_extractor.py
- **_batch_extract_last_10_games()**: Fixed critical bug where `total_games_available` was incorrectly limited to 60-day window
  - Changed from single query with window function to CTE-based approach
  - First CTE counts ALL historical games (no date limit) for accurate bootstrap detection
  - Second CTE retrieves last 10 games with 60-day window for efficiency
  - This fixes 80% failure rate in spot check validation

#### bin/monitoring/fix_stale_schedule.py
- **find_stale_games()**: Fixed query to use correct column names
  - `start_time_et` → `time_slot`
  - `home_team_abbr` → `home_team_tricode`
  - `away_team_abbr` → `away_team_tricode`
- **fix_stale_games()**: Fixed UPDATE query to include partition filter
  - Added grouping by game_date for partition-safe updates
  - Now updates both `game_status` and `game_status_text` for consistency

### Data Fixes Applied
- Fixed 3 games from 2026-01-22 with inconsistent `game_status_text` (was "In Progress", now "Final")
- Fixed 1 game from 2026-01-08 stuck in "Scheduled" status (now "Final")

### Impact
- Scraper parameter resolution errors should be eliminated for `oddsa_events`, `espn_team_roster_api`, `nbac_team_boxscore`
- Feature store historical completeness will be accurate for future runs
- Stale schedule data can now be automatically fixed

### Requires Follow-up
- Feature store backfill for dates 2026-01-01 to 2026-01-22 to fix existing incorrect records
- Consider scheduling `fix_stale_schedule.py` as automated job
