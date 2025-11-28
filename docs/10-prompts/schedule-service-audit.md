# Schedule Service Audit: Scrapers & Processors

**Purpose:** Systematically review all scrapers and processors to ensure proper game type handling using the `NBAScheduleService`.

**Background:** During a backfill operation, we discovered that the `nbac_player_boxscore` scraper was failing on All-Star games because:
1. The NBA.com API requires different `season_type` values for different game types
2. All-Star games use non-NBA team codes (e.g., "DRT" for Team Durant, "LBN" for Team LeBron)
3. Processors failed when trying to validate/load these non-standard team codes

**Solution Pattern Implemented:**
- Scraper: Use `NBAScheduleService.get_season_type_for_date()` to detect game type
- Scraper: Skip All-Star games (not useful for prop predictions)
- Processor: Check game type before processing, skip All-Star silently
- Processor: Validate team codes and alert only for non-All-Star games with invalid teams

---

## Task: Audit All Scrapers and Processors

### 1. Review Each NBA.com Scraper

For each scraper in `scrapers/nbacom/`:

```
nbac_player_boxscore.py    ✅ FIXED - uses schedule service, skips All-Star
nbac_team_boxscore.py      ⬜ Review - game_id based, may need All-Star detection
nbac_play_by_play.py       ⬜ Review - game_id based
nbac_gamebook_pdf.py       ⬜ Review - game_id based
nbac_scoreboard_v2.py      ⬜ Review - daily scoreboard
nbac_schedule_api.py       ⬜ Review - schedule data (All-Star games are valid here)
nbac_schedule_cdn.py       ⬜ Review - schedule data
nbac_injury_report.py      ⬜ Review - not game-specific
nbac_player_list.py        ⬜ Review - not game-specific
nbac_player_movement.py    ⬜ Review - not game-specific
nbac_referee_assignments.py ⬜ Review - game-specific, check if All-Star refs matter
nbac_roster.py             ⬜ Review - not game-specific
```

**Questions to answer for each scraper:**
1. Does it use a `season_type` parameter in the API call?
2. Does it scrape by date range or by specific game_id?
3. Could it encounter All-Star games?
4. Should All-Star games be skipped or handled differently?

### 2. Review Each Processor

For each processor in `data_processors/raw/nbacom/`:

```
nbac_player_boxscore_processor.py  ✅ FIXED - checks game type, validates teams
nbac_team_boxscore_processor.py    ⬜ Review - needs team validation
nbac_play_by_play_processor.py     ⬜ Review - needs team validation
nbac_gamebook_processor.py         ⬜ Review - needs team validation
nbac_scoreboard_v2_processor.py    ⬜ Review
nbac_schedule_processor.py         ⬜ Review - All-Star games valid in schedule
nbac_injury_report_processor.py    ⬜ Review
nbac_player_list_processor.py      ⬜ Review
nbac_player_movement_processor.py  ⬜ Review
nbac_referee_processor.py          ⬜ Review
```

**Questions to answer for each processor:**
1. Does it validate team codes against a list of valid NBA teams?
2. Could it receive All-Star game data?
3. Does it need to check game type before processing?
4. Should it alert on invalid team codes (only for non-All-Star games)?

### 3. Review Other Data Sources

Check if similar issues could exist in other scrapers:

```
scrapers/espn/espn_game_boxscore.py     ⬜ Review
scrapers/balldontlie/*.py               ⬜ Review
scrapers/pbpstats/*.py                  ⬜ Review
```

---

## Implementation Pattern

### For Scrapers (if they use season_type or date-based scraping):

```python
from shared.utils.schedule import NBAScheduleService

class MyScraper(ScraperBase):
    _schedule_service: Optional[NBAScheduleService] = None

    @classmethod
    def _get_schedule_service(cls) -> NBAScheduleService:
        if cls._schedule_service is None:
            cls._schedule_service = NBAScheduleService()
        return cls._schedule_service

    def set_additional_opts(self) -> None:
        # ... existing code ...

        # Auto-detect season type
        if not self.opts.get("season_type"):
            game_date = self._format_date(self.opts["gamedate"])
            self.opts["season_type"] = self._get_schedule_service().get_season_type_for_date(game_date)

        # Skip All-Star games if not useful
        if self.opts.get("season_type") == "All Star":
            raise DownloadDataException(f"Skipping All-Star game - not useful for predictions")
```

### For Processors (team validation with game type awareness):

```python
from shared.utils.schedule import NBAScheduleService

class MyProcessor(ProcessorBase):
    VALID_NBA_TEAMS = {
        'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }

    def __init__(self):
        super().__init__()
        self.schedule_service = NBAScheduleService()

    def transform_data(self) -> None:
        game_date = self._extract_game_date()

        # Check game type - skip All-Star games
        if game_date:
            season_type = self.schedule_service.get_season_type_for_date(game_date)
            if season_type == "All Star":
                logging.info(f"Skipping All-Star game for {game_date}")
                self.transformed_data = []
                return

        # Process data, validate teams...
        for row in data:
            team_code = row.get('team_abbr')
            if team_code not in self.VALID_NBA_TEAMS:
                # Only alert for non-All-Star games
                if season_type != "All Star":
                    notify_warning(...)
                continue
```

---

## Schedule Service API Reference

```python
from shared.utils.schedule import NBAScheduleService

schedule = NBAScheduleService()

# Get NBA.com API season_type for a date
season_type = schedule.get_season_type_for_date('2024-02-18')
# Returns: "All Star", "PlayIn", "Playoffs", "Regular Season", "Pre Season"

# Check if games exist on a date
has_games = schedule.has_games_on_date('2024-01-15')

# Get game count
count = schedule.get_game_count('2024-01-15')

# Get detailed game info
games = schedule.get_games_for_date('2024-01-15')
for game in games:
    print(game.game_type)  # 'regular_season', 'playoff', 'play_in', 'all_star_special', 'preseason'
```

---

## Files Modified (Reference)

**Schedule Service (already exists):**
- `shared/utils/schedule/service.py` - Added `get_season_type_for_date()`
- `shared/utils/schedule/database_reader.py` - Added `get_nba_api_season_type()`

**Fixed Scraper:**
- `scrapers/nbacom/nbac_player_boxscore.py` - Uses schedule service, skips All-Star

**Fixed Processor:**
- `data_processors/raw/nbacom/nbac_player_boxscore_processor.py` - Checks game type, validates teams

---

## Acceptance Criteria

- [ ] All scrapers reviewed for season_type handling
- [ ] All processors reviewed for team code validation
- [ ] Scrapers that encounter All-Star games either skip or handle correctly
- [ ] Processors check game type before alerting on invalid team codes
- [ ] No email floods from expected All-Star data
- [ ] Documentation updated with any new patterns discovered

---

## Notes

- All-Star games are NOT useful for player prop predictions (exhibition, non-NBA teams)
- Play-In Tournament games ARE useful (real NBA games, need "PlayIn" season_type)
- Emirates NBA Cup games are regular season games (no special handling needed)
- Preseason games may or may not be useful depending on use case
