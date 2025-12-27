# Live Box Scores Pipeline Design

**Created:** 2025-12-27
**Status:** Implementation in progress
**Purpose:** Enable historical tracking of in-game player stats for challenge grading and analytics

---

## Overview

The current live scores architecture bypasses BigQuery entirely, calling the BDL API directly and writing to GCS. This design adds proper database persistence to enable:

1. Historical analysis (score progression during games)
2. "Time to over" calculations (when did player hit the line?)
3. Post-game analysis without losing in-game data
4. Debugging and auditing of live grading decisions

---

## Architecture Comparison

### Current Architecture (Stateless)
```
Cloud Scheduler (*/3 min)
    ↓
live-export Cloud Function
    ↓
BDL API (/box_scores/live) → LiveScoresExporter → GCS
                                                   ↓
                                          /live/latest.json
                                          (overwritten each poll)
```

**Issues:**
- No historical data retention
- Cannot analyze score progression
- Debugging live grading is difficult

### New Architecture (With Persistence)
```
Cloud Scheduler (*/3 min during games)
    ↓
┌─────────────────────────────────────────────────────┐
│              nba-phase1-scrapers                     │
│  bdl_live_box_scores.py scraper                     │
│      ↓                                               │
│  GCS: ball-dont-lie/live-boxscores/{date}/{ts}.json │
└─────────────────────────────────────────────────────┘
    ↓ (Pub/Sub)
┌─────────────────────────────────────────────────────┐
│              nba-phase2-raw-processors              │
│  BdlLiveBoxscoresProcessor                          │
│      ↓                                               │
│  BigQuery: nba_raw.bdl_live_boxscores               │
│  (append-only, one row per player per poll)         │
└─────────────────────────────────────────────────────┘
    ↓ (or parallel)
┌─────────────────────────────────────────────────────┐
│              live-export Cloud Function             │
│  LiveScoresExporter (unchanged - direct API call)   │
│      ↓                                               │
│  GCS: /live/latest.json (for frontend)              │
└─────────────────────────────────────────────────────┘
```

---

## BigQuery Schema Design

### Table: `nba_raw.bdl_live_boxscores`

**Strategy:** Append-only snapshots. Each poll creates new rows.

**Partitioning:** By `game_date` (DATE)
**Clustering:** By `game_id`, `player_lookup`, `poll_timestamp`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.bdl_live_boxscores` (
    -- Poll metadata (CRITICAL for time-series analysis)
    poll_timestamp TIMESTAMP NOT NULL,    -- When this snapshot was taken
    poll_id STRING NOT NULL,              -- e.g., "20251227T213000Z"

    -- Game identification
    game_id STRING NOT NULL,              -- BDL game ID (e.g., "18447237")
    game_date DATE NOT NULL,              -- Game date for partitioning

    -- Game state at poll time
    game_status STRING,                   -- "scheduled" | "in_progress" | "final"
    period INT64,                         -- 1, 2, 3, 4, or 5+ for OT
    time_remaining STRING,                -- "5:42", "12:00", "Final", etc.
    is_halftime BOOLEAN,                  -- True if between Q2 and Q3

    -- Team context
    home_team_abbr STRING NOT NULL,
    away_team_abbr STRING NOT NULL,
    home_score INT64,
    away_score INT64,

    -- Player identification
    bdl_player_id INT64,                  -- BDL's player ID
    player_lookup STRING NOT NULL,        -- Normalized name for joining
    player_full_name STRING,              -- Display name
    team_abbr STRING NOT NULL,            -- Player's team

    -- Player stats at poll time
    minutes STRING,                       -- "28:30" format
    minutes_decimal FLOAT64,              -- 28.5 for easier calculations
    points INT64,
    rebounds INT64,
    offensive_rebounds INT64,
    defensive_rebounds INT64,
    assists INT64,
    steals INT64,
    blocks INT64,
    turnovers INT64,
    personal_fouls INT64,

    -- Shooting stats
    field_goals_made INT64,
    field_goals_attempted INT64,
    three_pointers_made INT64,
    three_pointers_attempted INT64,
    free_throws_made INT64,
    free_throws_attempted INT64,

    -- Processing metadata
    source_file_path STRING,
    processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_id, player_lookup, poll_timestamp
OPTIONS (
    description = 'Live in-game box score snapshots from BallDontLie API. Append-only - each poll creates new rows.',
    labels = [("pipeline_phase", "raw"), ("data_source", "balldontlie"), ("update_frequency", "live")]
);
```

### Key Design Decisions

1. **Append-only**: No updates or deletes during live games. Each poll = new rows.
   - Enables time-series queries
   - Avoids streaming buffer conflicts
   - Simple to reason about

2. **poll_timestamp as required**: This is the time dimension for analysis.

3. **Separate from bdl_player_boxscores**: That table is for FINAL game stats.
   This table is for in-progress snapshots.

4. **minutes_decimal**: Pre-computed for easier "time to over" queries.

5. **BDL game_id format**: Using BDL's native ID (e.g., "18447237") not our
   generated format, since this comes directly from the BDL API.

---

## Sample Queries

### When did player first hit 20 points?
```sql
SELECT
    player_lookup,
    player_full_name,
    MIN(poll_timestamp) as first_hit_20,
    MIN_BY(time_remaining, poll_timestamp) as game_clock_when_hit
FROM `nba_raw.bdl_live_boxscores`
WHERE game_date = '2025-12-27'
  AND player_lookup = 'lebronjames'
  AND points >= 20
GROUP BY player_lookup, player_full_name
```

### Score progression for a player
```sql
SELECT
    poll_timestamp,
    time_remaining,
    period,
    points,
    points - LAG(points) OVER (ORDER BY poll_timestamp) as points_in_interval
FROM `nba_raw.bdl_live_boxscores`
WHERE game_date = '2025-12-27'
  AND player_lookup = 'lebronjames'
  AND game_id = '18447237'
ORDER BY poll_timestamp
```

### Game score at halftime
```sql
SELECT game_id, home_team_abbr, away_team_abbr, home_score, away_score
FROM `nba_raw.bdl_live_boxscores`
WHERE game_date = '2025-12-27'
  AND (is_halftime = TRUE OR (period = 2 AND time_remaining = '0:00'))
QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY poll_timestamp) = 1
```

---

## Data Volume Estimates

**Per game night (5-10 games):**
- ~150 players per night
- ~40 polls per night (3-hour window @ 3 min intervals)
- = ~6,000 rows per night

**Per season:**
- ~180 game nights
- = ~1.08M rows per season

**Storage:** ~50MB/season compressed (very manageable)

---

## GCS Path Template

Add to `gcs_path_builder.py`:

```python
"bdl_live_box_scores": "ball-dont-lie/live-boxscores/%(date)s/%(timestamp)s.json",
```

---

## Processor Registry Entry

Add to `main_processor_service.py`:

```python
'ball-dont-lie/live-boxscores': ('balldontlie.bdl_live_boxscores_processor', 'BdlLiveBoxscoresProcessor'),
```

---

## Scheduler Configuration

**New scheduler job:** `bdl-live-boxscores-scraper`

```bash
# Every 3 minutes during game windows (7 PM - 1 AM ET)
gcloud scheduler jobs create http bdl-live-boxscores-evening \
    --location=us-west2 \
    --schedule="*/3 19-23 * * *" \
    --time-zone="America/New_York" \
    --uri="https://nba-phase1-scrapers-xxx.run.app/scrape/bdl_live_box_scores" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{}' \
    --attempt-deadline=120s \
    --description="BDL live box scores scraper during evening games"

gcloud scheduler jobs create http bdl-live-boxscores-late \
    --location=us-west2 \
    --schedule="*/3 0-1 * * *" \
    --time-zone="America/New_York" \
    --uri="https://nba-phase1-scrapers-xxx.run.app/scrape/bdl_live_box_scores" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{}' \
    --attempt-deadline=120s \
    --description="BDL live box scores scraper during late-night games"
```

---

## Implementation Checklist

- [ ] Add GCS path template to `gcs_path_builder.py`
- [ ] Create BigQuery table `nba_raw.bdl_live_boxscores`
- [ ] Create `bdl_live_boxscores_processor.py`
- [ ] Register processor in `main_processor_service.py`
- [ ] Test processor locally
- [ ] Deploy Phase 2 service
- [ ] Create scheduler jobs
- [ ] Verify end-to-end flow

---

## Backwards Compatibility

The existing `live-export` Cloud Function and `LiveScoresExporter` continue unchanged.
This is an **additive** enhancement that runs in parallel.

The frontend continues reading `/live/latest.json` from GCS for real-time grading.
BigQuery data is for historical analysis and debugging.

---

## Future Enhancements

1. **Analytics views**: Pre-computed "time to over" for each player
2. **Alerts**: Notify when player is close to hitting line
3. **Historical comparison**: Compare live progression to historical patterns
4. **Grafana dashboards**: Real-time game monitoring
