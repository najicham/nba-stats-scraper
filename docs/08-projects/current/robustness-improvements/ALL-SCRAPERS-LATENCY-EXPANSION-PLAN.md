# All Scrapers Latency Resolution - Expansion Plan
**Date:** January 22, 2026
**Status:** Ready for Implementation
**Priority:** P1 - Expand to All 33 NBA Scrapers

---

## Executive Summary

We've successfully deployed latency monitoring and resolution for BDL. This plan expands the same patterns to all 33 NBA scrapers, organized by priority and data criticality.

**What's Already Done:**
- ✅ BDL box scores - Availability logger integrated
- ✅ Daily scraper availability monitor - Deployed and running
- ✅ BigQuery monitoring views - All sources (BDL, NBAC, OddsAPI)
- ✅ Monitoring dashboard queries - Ready to use

**This Expansion Covers:**
- 33 NBA scrapers across 6 data sources
- Per-game availability tracking for critical scrapers
- Completeness validation for all game-level scrapers
- Automated retry queue for missing data

---

## Scraper Inventory (33 Total)

### Priority Tier 1: Critical Game Data (7 scrapers)
**Required for player analytics and predictions**

| Scraper | Source | Purpose | Current State |
|---------|--------|---------|---------------|
| `bdl_box_scores` | BDL | Player box scores | ✅ Logger integrated |
| `bdl_player_box_scores` | BDL | Player stats | 🔄 Next to implement |
| `nbac_gamebook` | NBAC | Official box scores | 🔄 High priority |
| `nbac_play_by_play` | NBAC | Play-by-play data | 🔄 High priority |
| `odds_events` | OddsAPI | Game events/lines | 🔄 Medium priority |
| `odds_game_lines` | OddsAPI | Betting lines | 🔄 Medium priority |
| `espn_boxscore` | ESPN | Backup box scores | ⚠️ Stale (June 2025) |

### Priority Tier 2: Player Props (4 scrapers)
**Required for player prop predictions**

| Scraper | Source | Purpose | Current State |
|---------|--------|---------|---------------|
| `odds_player_props` | OddsAPI | Player props | 🔄 Next |
| `bettingpros_player_props` | BettingPros | Props comparison | 🔄 Next |
| `espn_scoreboard` | ESPN | Live scores | ⚠️ Stale |
| `espn_roster` | ESPN | Roster data | ⚠️ Stale |

### Priority Tier 3: Supplementary Data (13 scrapers)
**Enhance predictions but not critical**

**NBAC Scrapers (10):**
- `nbac_schedule` - Game schedule (source of truth)
- `nbac_player_boxscores` - Alternative box scores
- `nbac_team_boxscores` - Team stats
- `nbac_scoreboard` - Live game data
- `nbac_standings` - Team standings
- `nbac_injury_report` - Player injuries
- `nbac_referee_assignments` - Officials
- `nbac_roster` - Team rosters
- `nbac_player_profiles` - Player bio
- `nbac_coaches` - Coaching staff

**BDL Scrapers (3):**
- `bdl_games` - Game metadata
- `bdl_teams` - Team info
- `bdl_players` - Player info

### Priority Tier 4: Alternative/Discovery Sources (9 scrapers)
**Optional or backup data sources**

**OddsAPI (5):**
- `odds_historical_events` - Historical odds
- `odds_historical_lines` - Historical betting lines
- `odds_historical_props` - Historical props
- `odds_sports` - Sports catalog
- `odds_bookmakers` - Bookmaker info

**BigDataBall (2):**
- `bigdataball_discovery` - Data discovery
- `bigdataball_pbp` - Play-by-play

**Basketball Reference (1):**
- `bbref_season_roster` - Season rosters

**BettingPros (1):**
- `bettingpros_events` - Event metadata

---

## Implementation Strategy

### Phase 1: Critical Game Data (Week 1-2)

**Goal:** Expand BDL pattern to NBAC and OddsAPI for game-level scrapers

#### 1.1 NBAC Gamebook Availability Logger ⏰ 3 hours

**Create:** `shared/utils/nbac_availability_logger.py`

```python
"""
NBAC Game Availability Logger

Tracks which games NBA.com gamebook API returned on each scrape attempt.
Similar to BDL logger but adapted for NBAC data structure.
"""

from typing import List, Dict
from google.cloud import bigquery
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)


def log_nbac_game_availability(
    game_date: str,
    execution_id: str,
    gamebook_data: List[Dict],
    workflow: str = "unknown"
):
    """
    Log NBAC gamebook availability for each game.

    Args:
        game_date: Date being scraped (YYYY-MM-DD)
        execution_id: Scraper run ID
        gamebook_data: List of gamebook entries from NBAC
        workflow: Which workflow triggered this

    Creates one row per expected game in bdl_game_scrape_attempts table.
    """
    client = bigquery.Client()

    # Get expected games from schedule
    expected_games = _get_expected_games_from_schedule(game_date, client)

    # Build set of games returned by NBAC
    returned_games = set()
    for entry in gamebook_data:
        try:
            home_team = entry.get('home_team_abbreviation')
            away_team = entry.get('away_team_abbreviation')
            if home_team and away_team:
                returned_games.add((home_team, away_team))
        except Exception as e:
            logger.warning(f"Failed to parse game from gamebook entry: {e}")

    # Log each expected game
    rows_to_insert = []
    for game in expected_games:
        was_available = (game['home_team'], game['away_team']) in returned_games
        player_count = None  # Could count from gamebook data if needed

        row = {
            'scrape_timestamp': datetime.now(timezone.utc).isoformat(),
            'execution_id': execution_id,
            'workflow': workflow,
            'game_date': game_date,
            'home_team': game['home_team'],
            'away_team': game['away_team'],
            'was_available': was_available,
            'player_count': player_count,
            'game_status': 'Final',  # NBAC only returns final games
            'was_expected': True,
            'expected_start_time': game['game_start_time'].isoformat() if game['game_start_time'] else None,
            'estimated_end_time': (
                game['game_start_time'] + timedelta(hours=2.5)
            ).isoformat() if game['game_start_time'] else None,
            'is_west_coast': game['is_west_coast']
        }
        rows_to_insert.append(row)

    # Insert to BigQuery (using NBAC table)
    if rows_to_insert:
        table_id = "nba-props-platform.nba_orchestration.nbac_game_scrape_attempts"
        try:
            errors = client.insert_rows_json(table_id, rows_to_insert)
            if not errors:
                logger.info(f"Logged {len(rows_to_insert)} NBAC game availability records for {game_date}")
            else:
                logger.error(f"Failed to insert NBAC availability: {errors}")
        except Exception as e:
            logger.error(f"Failed to log NBAC game availability: {e}", exc_info=True)


def _get_expected_games_from_schedule(game_date: str, client: bigquery.Client) -> List[Dict]:
    """Query schedule to get expected games for date."""
    query = """
    SELECT
      home_team,
      away_team,
      game_date_est as game_start_time,
      arena_timezone IN ('America/Los_Angeles', 'America/Phoenix') as is_west_coast
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_date = @game_date
      AND season_year = 2025
      AND game_status = 3
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        results = client.query(query, job_config=job_config).result()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Failed to query schedule: {e}")
        return []
```

**Deploy BigQuery Table:**
```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.nbac_game_scrape_attempts` (
  scrape_timestamp TIMESTAMP NOT NULL,
  execution_id STRING NOT NULL,
  workflow STRING,
  game_date DATE NOT NULL,
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,
  was_available BOOL NOT NULL,
  gamebook_present BOOL,  -- NBAC-specific
  play_by_play_present BOOL,  -- NBAC-specific
  player_count INT64,
  game_status STRING,
  was_expected BOOL DEFAULT TRUE,
  expected_start_time TIMESTAMP,
  estimated_end_time TIMESTAMP,
  is_west_coast BOOL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(scrape_timestamp)
CLUSTER BY game_date, home_team, was_available;
```

**Integrate into:**
- `scrapers/nbac/nbac_gamebook.py`
- `scrapers/nbac/nbac_play_by_play.py`

#### 1.2 OddsAPI Availability Logger ⏰ 3 hours

Similar to NBAC but adapted for OddsAPI structure:

**Key Differences:**
- OddsAPI has different completion criteria (events vs games)
- Track: `odds_count`, `bookmaker_count`, `props_available`
- Alert only if no odds for games > 2 hours after start

**Files to Create:**
- `shared/utils/oddsapi_availability_logger.py`
- `schemas/bigquery/nba_orchestration/oddsapi_game_scrape_attempts.sql`

**Integrate into:**
- `scrapers/oddsapi/odds_events.py`
- `scrapers/oddsapi/odds_game_lines.py`

#### 1.3 Completeness Validation for Critical Scrapers ⏰ 4 hours

**Expand the validator from Phase 2 to support multiple sources:**

```python
# In shared/validation/scraper_completeness_validator.py

SOURCE_TABLES = {
    'BDL_BOX_SCORES': 'nba_raw.bdl_player_boxscores',
    'BDL_PLAYER_BOX_SCORES': 'nba_raw.bdl_player_boxscores',
    'NBAC_GAMEBOOK': 'nba_raw.nbac_gamebook_player_stats',
    'NBAC_PLAY_BY_PLAY': 'nba_raw.nbac_play_by_play',
    'ODDS_EVENTS': 'nba_raw.oddsapi_events',
    'ODDS_GAME_LINES': 'nba_raw.oddsapi_game_lines',
}

# Add validate_completeness calls to each scraper's transform_data()
```

---

### Phase 2: Player Props & Supplementary (Week 3-4)

#### 2.1 Player Props Completeness Validation ⏰ 2 hours

**Different from game-level:**
- Not all players have props every game
- Check: "Did we get props for the stars?"
- Baseline: Historical average prop count per game

**Create:** `shared/validation/player_props_validator.py`

```python
def validate_player_props_completeness(
    game_date: str,
    props_returned: int,
    source: str = 'ODDS_PLAYER_PROPS'
):
    """
    Validate player props completeness.

    Unlike game-level validation, props vary by:
    - Player popularity
    - Bookmaker coverage
    - Game importance

    Strategy: Compare to historical baseline
    """
    # Get historical average for this day of week
    historical_avg = _get_historical_props_average(game_date)

    # Alert if significantly below average (< 70%)
    if props_returned < historical_avg * 0.7:
        notify_warning(
            title=f"{source} - Low Props Coverage",
            message=f"Only {props_returned} props vs {historical_avg} historical avg",
            details={
                'game_date': game_date,
                'props_returned': props_returned,
                'historical_avg': historical_avg,
                'completeness_pct': (props_returned / historical_avg * 100)
            }
        )
```

**Integrate into:**
- `scrapers/oddsapi/odds_player_props.py`
- `scrapers/bettingpros/bettingpros_player_props.py`

#### 2.2 NBAC Schedule Monitoring ⏰ 1 hour

**Special case:** Schedule is source of truth

- Monitor: Daily updates arriving on time
- Alert: If schedule not updated by 6 AM ET
- Critical: Schedule staleness detection

**Create:** `orchestration/cloud_functions/schedule_freshness_monitor/`

---

### Phase 3: Discovery & Alternative Sources (Week 5+)

#### 3.1 Discovery Mode Scrapers

**Scrapers with discovery mode:**
- `nbac_injury_report` - 12 attempts/day until found
- `nbac_referee_assignments` - 12 attempts/day until found

**Monitoring Strategy:**
- Track: How many attempts before data found?
- Alert: If > 24 hours without data (unusual)
- Dashboard: Discovery success rate over time

#### 3.2 ESPN Scraper Revival ⏰ 4 hours

**ESPN scrapers are stale (last ran June 2025)**

**Actions:**
1. Test ESPN scrapers with current data
2. Fix any API changes
3. Add availability logging
4. Deploy as backup to BDL

**Priority:** Medium (ESPN is backup only)

---

## Unified Monitoring Dashboard

### Create Master Dashboard View

```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_all_scrapers_health` AS

WITH scraper_status AS (
  -- Combine execution logs from all scrapers
  SELECT
    scraper_name,
    DATE(triggered_at) as run_date,
    MAX(triggered_at) as last_run_at,
    COUNTIF(status = 'success') as success_count,
    COUNTIF(status = 'failed') as failed_count,
    COUNTIF(status = 'no_data') as no_data_count,
    AVG(duration_seconds) as avg_duration_sec
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY scraper_name, run_date
),

game_data_scrapers AS (
  -- Critical game-level scrapers
  SELECT
    'GAME_DATA' as category,
    scraper_name,
    run_date,
    last_run_at,
    success_count,
    failed_count,
    CASE
      WHEN scraper_name LIKE 'bdl%' THEN 'BDL'
      WHEN scraper_name LIKE 'nbac%' THEN 'NBAC'
      WHEN scraper_name LIKE 'odds%' THEN 'OddsAPI'
      WHEN scraper_name LIKE 'espn%' THEN 'ESPN'
      ELSE 'Other'
    END as source,
    CASE
      WHEN success_count > 0 THEN '✅'
      WHEN failed_count > 0 THEN '❌'
      WHEN no_data_count > 0 THEN '⚠️'
      ELSE '⏸️'
    END as status_icon
  FROM scraper_status
  WHERE scraper_name IN (
    'bdl_box_scores', 'bdl_player_box_scores',
    'nbac_gamebook', 'nbac_play_by_play',
    'odds_events', 'odds_game_lines',
    'espn_boxscore'
  )
),

props_scrapers AS (
  -- Player props scrapers
  SELECT
    'PLAYER_PROPS' as category,
    scraper_name,
    run_date,
    last_run_at,
    success_count,
    failed_count,
    CASE
      WHEN scraper_name LIKE 'odds%' THEN 'OddsAPI'
      WHEN scraper_name LIKE 'bettingpros%' THEN 'BettingPros'
      ELSE 'Other'
    END as source,
    CASE
      WHEN success_count > 0 THEN '✅'
      WHEN failed_count > 0 THEN '❌'
      ELSE '⚠️'
    END as status_icon
  FROM scraper_status
  WHERE scraper_name IN (
    'odds_player_props',
    'bettingpros_player_props'
  )
),

supplementary_scrapers AS (
  -- All other scrapers
  SELECT
    'SUPPLEMENTARY' as category,
    scraper_name,
    run_date,
    last_run_at,
    success_count,
    failed_count,
    CASE
      WHEN scraper_name LIKE 'bdl%' THEN 'BDL'
      WHEN scraper_name LIKE 'nbac%' THEN 'NBAC'
      WHEN scraper_name LIKE 'odds%' THEN 'OddsAPI'
      ELSE 'Other'
    END as source,
    CASE
      WHEN success_count > 0 THEN '✅'
      WHEN failed_count > 0 THEN '❌'
      ELSE '⏸️'
    END as status_icon
  FROM scraper_status
  WHERE scraper_name NOT IN (
    'bdl_box_scores', 'bdl_player_box_scores',
    'nbac_gamebook', 'nbac_play_by_play',
    'odds_events', 'odds_game_lines', 'espn_boxscore',
    'odds_player_props', 'bettingpros_player_props'
  )
)

-- Combine all categories
SELECT * FROM game_data_scrapers
UNION ALL
SELECT * FROM props_scrapers
UNION ALL
SELECT * FROM supplementary_scrapers

ORDER BY category, source, scraper_name, run_date DESC;
```

---

## Implementation Timeline

### Week 1: BDL Complete (DONE ✅)
- Day 1-2: Deploy monitor, BDL logger, dashboard
- Day 3-5: Testing and refinement

### Week 2: NBAC & OddsAPI
- Day 1-2: NBAC availability logger + integration
- Day 3-4: OddsAPI availability logger + integration
- Day 5: Completeness validation for all critical scrapers

### Week 3: Props & Supplementary
- Day 1-2: Player props validation
- Day 3-4: Schedule freshness monitoring
- Day 5: Discovery mode monitoring

### Week 4: ESPN & Finalization
- Day 1-2: ESPN scraper revival
- Day 3-4: Unified dashboard deployment
- Day 5: Documentation and handoff

**Total: 4 weeks, ~80 hours**

---

## Success Metrics

### Per-Scraper Targets

| Scraper Category | Detection Time | Missing Rate | Recovery |
|------------------|----------------|--------------|----------|
| **Game Data** | < 10 min | < 1% | 90%+ auto |
| **Player Props** | < 30 min | < 5% | 80%+ auto |
| **Supplementary** | < 2 hours | < 10% | 70%+ auto |

### Overall Pipeline Health

**Before Expansion:**
- BDL only monitored
- 17% missing game rate
- Manual recovery only

**After Expansion:**
- All 33 scrapers monitored
- < 1% missing rate across all critical scrapers
- 85%+ automatic recovery
- < 15 min average detection time

---

## Priority Order for Implementation

1. **This Week:** Complete BDL (✅ DONE)
2. **Next Week:** NBAC gamebook + play-by-play
3. **Week 3:** OddsAPI events + game lines
4. **Week 4:** Player props + schedule monitoring
5. **Backlog:** ESPN revival + discovery mode

---

## Files to Create

### Python Utilities
- `shared/utils/nbac_availability_logger.py`
- `shared/utils/oddsapi_availability_logger.py`
- `shared/validation/player_props_validator.py`
- `shared/validation/schedule_freshness_validator.py`

### BigQuery Schemas
- `schemas/bigquery/nba_orchestration/nbac_game_scrape_attempts.sql`
- `schemas/bigquery/nba_orchestration/oddsapi_game_scrape_attempts.sql`
- `schemas/bigquery/nba_orchestration/v_all_scrapers_health.sql`

### Cloud Functions
- `orchestration/cloud_functions/schedule_freshness_monitor/`
- Update existing: `scraper_availability_monitor/` (expand to all scrapers)

### Monitoring Queries
- `monitoring/all_scrapers_dashboard.sql`
- `monitoring/props_completeness_dashboard.sql`

---

**Document Created:** January 22, 2026
**Owner:** Data Engineering Team
**Status:** Ready for Implementation
**Next Steps:** Begin NBAC integration (Week 2)
