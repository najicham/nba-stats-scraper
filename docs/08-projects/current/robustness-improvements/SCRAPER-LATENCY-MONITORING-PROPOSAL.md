# Scraper Latency Monitoring Proposal

**Created:** January 21, 2026
**Context:** BDL missing 17 games revealed need for systematic latency monitoring across ALL scrapers

---

## Problem Statement

We discovered 17+ games missing from BDL only through manual validation. We need:
1. **Early detection** - Know within hours, not days
2. **Latency measurement** - How long after game end does data appear?
3. **Cross-source comparison** - BDL vs NBAC vs ESPN vs OddsAPI
4. **Historical analysis** - Patterns over time

---

## Proposed Architecture

### 1. Central Schedule as Source of Truth

Use `nba_raw.nbac_schedule` as the authoritative list of games:
- `game_id` - Unique identifier
- `game_date_est` - Game start time
- `game_status` - 1=Scheduled, 2=In Progress, 3=Final
- `estimated_game_end` = `game_start + 2.5 hours`

### 2. Per-Scraper Availability Tables

Create a unified tracking table:

```sql
CREATE TABLE nba_monitoring.scraper_game_availability (
  game_date DATE NOT NULL,
  game_id STRING NOT NULL,
  matchup STRING,
  game_start_time TIMESTAMP,
  estimated_game_end TIMESTAMP,

  -- Per-scraper first-seen timestamps
  bdl_first_seen_at TIMESTAMP,
  nbac_first_seen_at TIMESTAMP,
  espn_first_seen_at TIMESTAMP,
  odds_api_first_seen_at TIMESTAMP,

  -- Latency calculations (minutes from estimated game end)
  bdl_latency_minutes INT64,
  nbac_latency_minutes INT64,
  espn_latency_minutes INT64,
  odds_api_latency_minutes INT64,

  -- Status flags
  is_west_coast BOOL,
  is_late_game BOOL,

  -- Overall status
  any_source_available BOOL,
  all_sources_available BOOL,
  missing_sources ARRAY<STRING>,

  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY game_id;
```

### 3. Latency Categories

```sql
CASE
  WHEN latency_minutes IS NULL THEN 'NEVER_AVAILABLE'
  WHEN latency_minutes < 0 THEN 'BEFORE_GAME_END'      -- Live data
  WHEN latency_minutes <= 30 THEN 'FAST'               -- < 30 min
  WHEN latency_minutes <= 60 THEN 'NORMAL'             -- 30-60 min
  WHEN latency_minutes <= 120 THEN 'SLOW'              -- 1-2 hours
  WHEN latency_minutes <= 360 THEN 'DELAYED'           -- 2-6 hours
  ELSE 'VERY_DELAYED'                                  -- 6+ hours
END AS latency_category
```

### 4. Expected Latency by Source

| Source | Expected Latency | Alert Threshold |
|--------|------------------|-----------------|
| NBAC (NBA.com) | < 30 min | 2 hours |
| BDL | < 2 hours | 6 hours |
| ESPN | < 1 hour | 4 hours |
| OddsAPI | Real-time (pre-game) | N/A |

---

## Implementation Plan

### Phase 1: Extend Current View (This Week)

Already done for BDL. Extend `v_bdl_game_availability` pattern to other sources:

```sql
-- Add NBAC latency to existing view
CREATE OR REPLACE VIEW nba_orchestration.v_game_availability_all_sources AS
WITH schedule AS (...),
bdl_first_seen AS (...),
nbac_first_seen AS (...),
espn_first_seen AS (...),
odds_first_seen AS (...)
SELECT
  s.*,
  -- BDL
  bdl.first_seen_at AS bdl_first_seen,
  TIMESTAMP_DIFF(bdl.first_seen_at, s.estimated_game_end, MINUTE) AS bdl_latency_min,
  -- NBAC
  nbac.first_seen_at AS nbac_first_seen,
  TIMESTAMP_DIFF(nbac.first_seen_at, s.estimated_game_end, MINUTE) AS nbac_latency_min,
  -- ESPN (if available)
  espn.first_seen_at AS espn_first_seen,
  -- etc.
FROM schedule s
LEFT JOIN bdl_first_seen bdl ON ...
LEFT JOIN nbac_first_seen nbac ON ...
LEFT JOIN espn_first_seen espn ON ...;
```

### Phase 2: Add Scraper-Level Logging (Next Week)

Modify each scraper to log which games it found:

```python
# In each scraper's transform_data():
from shared.utils.scraper_availability_logger import log_game_availability

# After successful scrape:
log_game_availability(
    scraper_name='bdl_box_scores',
    game_date=self.opts['date'],
    games_found=[g['game_id'] for g in self.data['games']],
    execution_id=self.run_id,
    scrape_timestamp=datetime.utcnow()
)
```

### Phase 3: Alerting (Week 3)

Add Cloud Function to check availability daily:

```python
def check_scraper_availability():
    """Run at 6 AM ET - check yesterday's games."""
    query = """
    SELECT game_date, matchup, missing_sources
    FROM nba_orchestration.v_game_availability_all_sources
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
      AND NOT all_sources_available
      AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), estimated_game_end, HOUR) > 8
    """
    missing = bq_client.query(query).result()

    if missing:
        send_slack_alert(
            title="Scraper Data Missing",
            games=list(missing),
            threshold="8 hours post-game"
        )
```

### Phase 4: Dashboard (Week 4)

Create Looker Studio dashboard showing:
- Daily coverage % by source
- Latency P50/P90/P95 trends
- West Coast vs East Coast comparison
- Source reliability over time

---

## Scrapers to Instrument

| Scraper | File | Priority |
|---------|------|----------|
| BDL Box Scores | `scrapers/balldontlie/bdl_box_scores.py` | ✅ Done (view exists) |
| BDL Games | `scrapers/balldontlie/bdl_games.py` | High |
| NBAC Gamebook | `scrapers/nba_com/nbac_gamebook.py` | High |
| ESPN Scoreboard | `scrapers/espn/espn_scoreboard.py` | Medium (currently stale) |
| OddsAPI Lines | `scrapers/odds_api/odds_api_game_lines.py` | Medium |
| OddsAPI Props | `scrapers/odds_api/odds_api_player_props.py` | Medium |
| BettingPros | `scrapers/bettingpros/` | Low |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Time to detect missing data | Days (manual) | < 8 hours (automated) |
| Latency visibility | None | Per-game, per-source |
| Cross-source comparison | None | Automated daily |
| Historical patterns | None | 30-day rolling dashboard |

---

## Quick Wins (Can Do Today)

1. ✅ BDL latency view deployed
2. Add NBAC latency to same view
3. Create daily summary query
4. Set up basic Slack alert for missing games

---

## Related Documents

- `ERROR-TRACKING-PROPOSAL.md` - Broader error tracking system
- `bdl_game_availability_tracking.sql` - Current BDL-specific views
- `2026-01-21-DATA-VALIDATION-REPORT.md` - Analysis that revealed this need
