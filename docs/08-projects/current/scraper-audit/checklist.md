# Scraper Audit Checklist

**Project:** GCS Scraper Data Completeness Audit
**Started:** 2025-11-25
**Updated:** 2025-11-25
**Status:** In Progress

---

## Backfill Tasks

### Priority 1: CRITICAL (Blocks Phase 3)

- [ ] **GetNbaComTeamBoxscore** - 5,299 games needed
  - [x] Export game_ids from nbac_schedule (done: `game_ids_to_scrape.csv`)
  - [x] Create scraper backfill job (done: `nbac_team_boxscore_scraper_backfill.py`)
  - [ ] Run backfill script
  - [ ] Verify completeness

**Location:** `backfill_jobs/scrapers/nbac_team_boxscore/`

**To run:**
```bash
# Dry run first
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --dry-run --limit=100

# Full backfill (estimated ~88 minutes for 5,299 games at 1s rate limit)
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

# By season
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --season=2024
```

### Priority 2: HIGH (Important for predictions)

- [ ] **GetOddsApiHistoricalGameLines** - ~104 dates missing (playoffs)
  - [x] Backfill script exists: `odds_api_lines_scraper_backfill.py`
  - [ ] Verify if API supports playoff dates
  - [ ] Backfill if possible

**Location:** `backfill_jobs/scrapers/odds_api_lines/`

**To run:**
```bash
# Dry run
python backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
  --dry-run --limit=10

# Full backfill
python backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
  --seasons=2021,2022,2023,2024
```

### Priority 3: MEDIUM (Enrichment)

- [ ] **GetNbaComPlayerBoxscore** - 840 dates needed
  - [x] Create scraper backfill job (done: `nbac_player_boxscore_scraper_backfill.py`)
  - [x] Export game dates (done: `game_dates_to_scrape.csv`)
  - [ ] Run backfill script
  - [ ] Verify completeness

**Location:** `backfill_jobs/scrapers/nbac_player_boxscore/`

**To run:**
```bash
python backfill_jobs/scrapers/nbac_player_boxscore/nbac_player_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

---

- [ ] **GetNbaComPlayByPlay** - 5,299 games needed
  - [x] Create scraper backfill job (done: `nbac_play_by_play_scraper_backfill.py`)
  - [x] Export game_ids (done: `game_ids_to_scrape.csv`)
  - [ ] Run backfill script
  - [ ] Verify completeness

**Location:** `backfill_jobs/scrapers/nbac_play_by_play/`

**To run:**
```bash
python backfill_jobs/scrapers/nbac_play_by_play/nbac_play_by_play_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

---

- [ ] **BdlStandingsScraper** - 3 seasons missing (2021, 2022, 2023)
  - [x] Create scraper backfill job (done: `bdl_standings_scraper_backfill.py`)
  - [ ] Run backfill script
  - [ ] Verify completeness

**Location:** `backfill_jobs/scrapers/bdl_standings/`

**To run:**
```bash
python backfill_jobs/scrapers/bdl_standings/bdl_standings_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

### Priority 4: LOW (Backups)

- [ ] **GetEspnBoxscore** - 5,299 games needed (backup only)
  - [x] Create scraper backfill job (done: `espn_game_boxscore_scraper_backfill.py`)
  - [x] Export game_ids (done: `game_ids_to_scrape.csv`)
  - [ ] Run backfill script
  - [ ] Verify completeness

**Location:** `backfill_jobs/scrapers/espn_game_boxscore/`

**To run:**
```bash
python backfill_jobs/scrapers/espn_game_boxscore/espn_game_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

---

## Backfill Scripts Summary

| Scraper | Script Location | Data File | Status |
|---------|-----------------|-----------|--------|
| GetNbaComTeamBoxscore | `backfill_jobs/scrapers/nbac_team_boxscore/` | `game_ids_to_scrape.csv` | ✅ Ready |
| GetOddsApiHistoricalGameLines | `backfill_jobs/scrapers/odds_api_lines/` | (uses Schedule Service) | ✅ Ready |
| GetNbaComPlayerBoxscore | `backfill_jobs/scrapers/nbac_player_boxscore/` | `game_dates_to_scrape.csv` | ✅ Ready |
| GetNbaComPlayByPlay | `backfill_jobs/scrapers/nbac_play_by_play/` | `game_ids_to_scrape.csv` | ✅ Ready |
| BdlStandingsScraper | `backfill_jobs/scrapers/bdl_standings/` | (hardcoded seasons) | ✅ Ready |
| GetEspnBoxscore | `backfill_jobs/scrapers/espn_game_boxscore/` | `game_ids_to_scrape.csv` | ✅ Ready |

---

## Verification Complete

### Per-Date Scrapers (verified against 853 expected dates)

- [x] BdlBoxScoresScraper - 893 dates ✓
- [x] GetNbaComGamebooks - 888 dates ✓
- [x] GetNbaComInjuryReport - 922 dates ✓
- [x] GetEspnScoreboard - 1,343 dates ✓
- [x] GetBettingProEvents - 878 dates ✓
- [x] GetBettingProPlayerProps - 865 dates ✓
- [x] GetOddsApiHistoricalEvents - 848 dates ✓
- [x] GetOddsApiHistoricalEventOdds - 447 dates ✓ (May 2023+ only)

### Per-Season Scrapers

- [x] GetNbaComScheduleApi - 6 seasons ✓
- [x] GetNbaComPlayerMovement - 6 years ✓
- [x] BasketballRefSeasonRoster - 120 files (30 teams × 4 seasons) ✓

### Per-Game File Counts (verified samples match expected)

- [x] GetNbaComGamebooks - file counts match game counts per date ✓
- [x] BigDataBallPbpScraper - folder counts match game counts per date ✓

---

## Notes

- BigDataBall missing 6 All-Star weekend dates (expected - no regular games)
- OddsAPI game-lines missing ~104 playoff dates (likely API limitation)
- Per-game scrapers need game_id list from nbac_schedule for backfill
- All backfill scripts created 2025-11-25
