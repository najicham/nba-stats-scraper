# BigDataBall Play-by-Play Data Monitor

**Status**: 📋 TODO
**Priority**: P1 - High
**Estimated Effort**: 2-3 hours

---

## Problem Statement

BigDataBall releases play-by-play (PBP) data at **unpredictable times** after games complete:
- Sometimes 2-6 hours after game ends
- Sometimes not until the next day
- No notification when data is available

This creates issues:
1. Phase 3 analytics processors may run before PBP data is available
2. Shot zone analysis is incomplete without PBP data
3. No visibility into which games are missing PBP data
4. Manual checking required to know when to reprocess

---

## Current Data Flow

```
Game Ends (11 PM ET)
        │
        ▼
Gamebook Available (~30 min)  ────► Phase 2 scrapers run
        │
        ▼
Phase 3 Analytics triggered   ────► May run WITHOUT PBP data!
        │
        ▼
BigDataBall PBP Available (????)
        │
        ▼
❌ No trigger to reprocess Phase 3
```

---

## Proposed Solution

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                BIGDATABALL PBP MONITOR                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AVAILABILITY CHECKER (Cloud Scheduler - every 30 min)   │   │
│  │                                                           │   │
│  │  1. Get yesterday's games from schedule                  │   │
│  │  2. Query BigDataBall for available games                │   │
│  │  3. Identify missing games                               │   │
│  │  4. Update data_gaps table                               │   │
│  │  5. Alert if gap > 6 hours                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AUTO-RETRY TRIGGER                                       │   │
│  │                                                           │   │
│  │  When new BDB data detected:                             │   │
│  │  1. Publish to nba-phase3-analytics-trigger              │   │
│  │  2. Specify processors needing PBP data                  │   │
│  │  3. Mark gap as 'resolved'                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

1. **BDB Availability Checker** (`bin/monitoring/bdb_pbp_monitor.py`)
   - Runs every 30 minutes via Cloud Scheduler
   - Checks which games have BDB PBP data
   - Tracks gaps in `nba_orchestration.data_gaps`

2. **Data Gaps Table** (`nba_orchestration.data_gaps`)
   - Tracks all missing data by source
   - Records when gaps are detected and resolved
   - Supports auto-retry logic

3. **Auto-Retry Trigger**
   - When BDB data appears, triggers Phase 3 reprocessing
   - Only runs processors that need PBP data
   - Prevents duplicate processing

---

## Implementation Plan

### Step 1: Create Data Gaps Table

```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.data_gaps` (
    -- Identification
    gap_id STRING NOT NULL,           -- UUID
    game_date DATE NOT NULL,
    game_id STRING,
    source STRING NOT NULL,           -- 'bigdataball_pbp', 'gamebook', etc.

    -- Timing
    game_end_time TIMESTAMP,          -- When game ended
    expected_by TIMESTAMP,            -- When we expected data
    detected_at TIMESTAMP NOT NULL,   -- When gap was first detected
    last_checked_at TIMESTAMP,        -- Last availability check
    resolved_at TIMESTAMP,            -- When data appeared

    -- Status
    status STRING NOT NULL,           -- 'open', 'resolved', 'manual_review'
    severity STRING,                  -- 'warning' (6h), 'critical' (24h)

    -- Retry tracking
    auto_retry_triggered BOOL DEFAULT FALSE,
    auto_retry_at TIMESTAMP,
    retry_count INT64 DEFAULT 0,

    -- Metadata
    notes STRING
)
PARTITION BY game_date
OPTIONS (description = 'Tracks missing data across all sources');
```

### Step 2: Create BDB PBP Monitor Script

```python
#!/usr/bin/env python3
"""
BigDataBall Play-by-Play Monitor

Checks for missing BDB PBP data and triggers reprocessing when available.

Schedule: Every 30 minutes via Cloud Scheduler
"""

import logging
from datetime import date, datetime, timedelta, timezone
from google.cloud import bigquery, pubsub_v1

class BDBPBPMonitor:

    def __init__(self):
        self.bq_client = bigquery.Client()
        self.publisher = pubsub_v1.PublisherClient()

    def get_expected_games(self, game_date: date) -> list:
        """Get games that should have BDB data."""
        query = f"""
        SELECT game_id, home_team_abbr, away_team_abbr, game_status
        FROM nba_raw.v_nbac_schedule_latest
        WHERE game_date = '{game_date}'
          AND game_status = 'Final'
        """
        return list(self.bq_client.query(query).result())

    def get_available_bdb_games(self, game_date: date) -> set:
        """Get games that have BDB PBP data."""
        query = f"""
        SELECT DISTINCT game_id
        FROM nba_raw.bigdataball_play_by_play
        WHERE game_date = '{game_date}'
        """
        return {row.game_id for row in self.bq_client.query(query).result()}

    def check_and_update_gaps(self, game_date: date):
        """Check for missing BDB data and update gaps table."""
        expected = self.get_expected_games(game_date)
        available = self.get_available_bdb_games(game_date)

        for game in expected:
            if game.game_id not in available:
                self._record_gap(game_date, game.game_id)
            else:
                self._resolve_gap(game_date, game.game_id)

    def _record_gap(self, game_date, game_id):
        """Record or update a data gap."""
        # Check if gap already exists
        # If not, create new gap record
        # If exists, update last_checked_at and severity
        pass

    def _resolve_gap(self, game_date, game_id):
        """Mark gap as resolved and trigger reprocessing."""
        # Update gap status to 'resolved'
        # Trigger Phase 3 reprocessing for this game
        pass

    def trigger_reprocessing(self, game_date, game_ids):
        """Trigger Phase 3 reprocessing for specific games."""
        # Publish to nba-phase3-analytics-trigger
        # Include game_ids and processor filter
        pass
```

### Step 3: Create Cloud Scheduler Job

```yaml
Job: bdb-pbp-availability-check
Schedule: */30 * * * *  # Every 30 minutes
Target: Cloud Function or Cloud Run endpoint
Payload:
  check_date: "yesterday"
```

### Step 4: Add Alerting

**Alert Conditions:**
- Gap detected for >6 hours → Warning to #nba-alerts
- Gap detected for >24 hours → Critical to #app-error-alerts
- Gap resolved → Info log only

**Alert Format:**
```
:warning: BigDataBall PBP Data Gap

*Date:* 2026-01-27
*Games Missing:* 3 of 7

*Missing Games:*
• LAL @ BOS (game ended 8h ago)
• MIA @ NYK (game ended 7h ago)
• GSW @ DAL (game ended 6h ago)

*Status:* Monitoring - will auto-retry when available
```

### Step 5: Integrate with Phase 3

**Option A: Delay Phase 3 until BDB available**
- Pro: Cleaner, single processing
- Con: Delays all analytics

**Option B: Process twice (recommended)**
- First pass: Without BDB PBP data (basic stats)
- Second pass: With BDB PBP data (shot zones)
- Pro: Faster initial results
- Con: More processing

---

## Timeline

| Day | Task |
|-----|------|
| Day 1 | Create data_gaps table, implement monitor script |
| Day 1 | Test with yesterday's data |
| Day 2 | Add auto-retry trigger |
| Day 2 | Add Slack alerting |
| Day 3 | Deploy Cloud Scheduler job |
| Day 3 | Monitor for 24 hours |

---

## Success Criteria

- [ ] All BDB PBP gaps detected within 30 minutes
- [ ] Auto-retry triggered when data becomes available
- [ ] Alert sent for gaps >6 hours
- [ ] No manual intervention needed for delayed BDB data
- [ ] Phase 3 reprocessing happens automatically

---

## Related Files

- `bin/monitoring/bdb_pbp_monitor.py` (to create)
- `schemas/bigquery/nba_orchestration/data_gaps.sql` (to create)
- `orchestration/cloud_functions/bdb_availability_check/` (to create)

---

## Notes

- BDB typically releases data 2-6 hours after games
- Weekend games may be delayed until Monday
- All-Star break has different timing
- Playoffs may have faster turnaround
