# Evening Analytics Processing - Implementation Plan

**Created**: February 2, 2026
**Session**: 72, 73
**Status**: Phase 1 COMPLETE, Phase 1.5 COMPLETE

---

## Goals

1. **Reduce processing delay** from 6-18 hours to 1-3 hours (Phase 1)
2. **Enable real-time processing** when games complete (Phase 2)
3. **Support same-night signal validation** and grading

---

## Phase 1: Scheduled Evening Triggers (Quick Win)

### Overview

Add 3 new Cloud Scheduler jobs to process analytics in the evening, catching games as they complete throughout the night.

### New Scheduler Jobs

| Job Name | Schedule | Time (ET) | Purpose |
|----------|----------|-----------|---------|
| `evening-analytics-6pm-et` | `0 18 * * 0,6` | 6 PM Sat/Sun | Weekend matinees |
| `evening-analytics-10pm-et` | `0 22 * * *` | 10 PM Daily | Early evening games |
| `evening-analytics-1am-et` | `0 1 * * *` | 1 AM Daily | West Coast games |

### Implementation

```bash
# 1. Weekend afternoon trigger (catches 1 PM, 3:30 PM starts)
gcloud scheduler jobs create http evening-analytics-6pm-et \
  --location=us-west2 \
  --schedule="0 18 * * 0,6" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"start_date":"TODAY","end_date":"TODAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
  --oidc-service-account-email="phase3-invoker@nba-props-platform.iam.gserviceaccount.com"

# 2. Evening trigger (catches 7 PM starts)
gcloud scheduler jobs create http evening-analytics-10pm-et \
  --location=us-west2 \
  --schedule="0 22 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"start_date":"TODAY","end_date":"TODAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
  --oidc-service-account-email="phase3-invoker@nba-props-platform.iam.gserviceaccount.com"

# 3. Late night trigger (catches 10 PM starts, uses YESTERDAY since it's after midnight)
gcloud scheduler jobs create http evening-analytics-1am-et \
  --location=us-west2 \
  --schedule="0 1 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"start_date":"YESTERDAY","end_date":"YESTERDAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
  --oidc-service-account-email="phase3-invoker@nba-props-platform.iam.gserviceaccount.com"
```

### Expected Impact

| Game Start | Game End | New Processing | Delay |
|------------|----------|----------------|-------|
| 1:00 PM | ~3:30 PM | 6:00 PM | **2.5 hours** |
| 3:30 PM | ~6:00 PM | 6:00 PM | **0 hours** (caught immediately) |
| 7:00 PM | ~9:30 PM | 10:00 PM | **0.5 hours** |
| 10:00 PM | ~12:30 AM | 1:00 AM | **0.5 hours** |

### Verification

After implementation, verify jobs are running:

```bash
# List evening jobs
gcloud scheduler jobs list --location=us-west2 | grep evening

# Check recent executions
gcloud scheduler jobs describe evening-analytics-10pm-et --location=us-west2

# Verify player_game_summary updates
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records, MAX(processed_at) as last_update
FROM nba_analytics.player_game_summary
WHERE game_date = CURRENT_DATE()
GROUP BY game_date"
```

---

## Phase 1.5: Boxscore Fallback (IMPLEMENTED - Session 73)

### Problem Discovered

Phase 1 schedulers weren't working because `PlayerGameSummaryProcessor` requires `nbac_gamebook_player_stats` as its primary data source, but gamebook data only becomes available the next morning (from PDF parsing).

### Solution Implemented

Added `nbac_player_boxscores` as a fallback source when gamebook isn't available.

**How it works:**
1. Processor checks `nbac_gamebook_player_stats` first (PRIMARY)
2. If empty, checks `nbac_player_boxscores` where `game_status = 'Final'` (FALLBACK)
3. Uses `_use_boxscore_fallback` flag to switch extraction query
4. `primary_source_used` column tracks which source was used

**Key Code Changes:**
- `USE_NBAC_BOXSCORES_FALLBACK = True` flag in processor
- Modified `_check_source_data_available()` to check both sources
- Added `nbac_boxscore_data` CTE to extraction query

**Data Quality:**
- Boxscores have 100% match on points with gamebook
- Missing from boxscores: `player_status`, `dnp_reason` (injury info)
- Gamebook can still enrich data when it runs in the morning

### Verification

```sql
-- Check which source was used
SELECT game_date, COUNT(*) as records,
  COUNTIF(primary_source_used = 'nbac_boxscores') as from_boxscores,
  COUNTIF(primary_source_used = 'nbac_gamebook') as from_gamebook
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date ORDER BY game_date DESC
```

### Result

Feb 1, 2026: Successfully processed 148 records from 7 games using boxscore fallback at 12:13 AM ET (same night as games).

---

## Phase 2: Event-Driven Game Completion Detection

### Overview

Build a system that detects when games complete and triggers analytics processing in real-time.

### Architecture Options

#### Option A: Poll Schedule Table

```
Cloud Scheduler (every 5 min during game hours)
    ↓
Cloud Function: check_game_completion
    ↓
Query: SELECT game_id FROM schedule WHERE game_status = 3 AND NOT processed
    ↓
For each new Final game → Trigger Phase 3 for that game_date
    ↓
Mark game as processed in tracking table
```

**Pros**: Simple, uses existing data
**Cons**: 5-minute latency, polling overhead

#### Option B: Boxscore Scraper Triggers Completion

```
bdl-live-boxscores scraper runs every 3 min
    ↓
Detects game_status = 3 in response
    ↓
Publishes to: nba-game-complete topic
    ↓
Cloud Function triggers Phase 3
```

**Pros**: Real-time, leverages existing scraping
**Cons**: Couples scraping with orchestration

#### Option C: Dedicated Game Monitor Service

```
Cloud Run Service: game-completion-monitor
    ↓
Subscribes to live game updates (NBA API websocket or polling)
    ↓
Detects Final status
    ↓
Publishes completion event
    ↓
Phase 3 triggered via Pub/Sub
```

**Pros**: Dedicated responsibility, cleanest separation
**Cons**: New service to maintain

### Recommended: Option A (Polling)

Start with polling because:
1. Simplest to implement
2. Uses existing infrastructure
3. 5-minute latency is acceptable
4. Can upgrade to Option B/C later if needed

---

## Game Completion Detection: Investigation Needed

### Key Question: How Fast Does NBA.com Update game_status?

We need to measure the latency between:
1. Game actually ends (final buzzer)
2. `game_status = 3` appears in NBA.com API

### Investigation Plan

```sql
-- Create tracking table for game completion timing
CREATE TABLE IF NOT EXISTS nba_orchestration.game_completion_timing (
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  scheduled_start_time TIMESTAMP,

  -- Detection timestamps
  first_seen_final TIMESTAMP,      -- When we first saw game_status = 3
  boxscore_complete_at TIMESTAMP,  -- When full boxscore was available

  -- External reference (manual entry for calibration)
  actual_game_end_time TIMESTAMP,  -- From ESPN/other source

  -- Calculated latencies
  detection_latency_minutes INT64,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
```

### Potential Alternative Sources

If NBA.com is slow to update, consider:

| Source | Update Speed | Reliability | Notes |
|--------|--------------|-------------|-------|
| NBA.com Schedule API | Unknown | High | Current source |
| ESPN API | Fast (~1 min) | High | May need scraper |
| BallDontLie API | Medium | Medium | Already integrated |
| Sports Radar | Real-time | High | Paid API |
| TheScore | Fast | Medium | May need scraper |

### Measurement Script

```python
# Script to measure NBA.com game_status latency
# Run during games to collect timing data

import time
from datetime import datetime
import requests

def check_game_status(game_id):
    """Poll NBA.com for game status."""
    url = f"https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    resp = requests.get(url)
    data = resp.json()

    for game in data.get('scoreboard', {}).get('games', []):
        if game['gameId'] == game_id:
            return game['gameStatus'], game['gameStatusText']
    return None, None

def monitor_game_completion(game_id, check_interval=30):
    """Monitor a game until it completes, logging timestamps."""
    print(f"Monitoring game {game_id}...")

    while True:
        status, status_text = check_game_status(game_id)
        now = datetime.utcnow().isoformat()

        print(f"[{now}] Status: {status} - {status_text}")

        if status == 3:  # Final
            print(f"Game complete! First detected at {now}")
            return now

        time.sleep(check_interval)
```

---

## Phase 3: Automatic Grading Trigger

### Overview

Once `player_game_summary` is populated, automatically trigger grading.

### Current Flow (Manual)

```
player_game_summary populated
    ↓
[WAIT until next morning]
    ↓
Manual grading backfill or scheduled job
```

### Proposed Flow (Automatic)

```
player_game_summary populated
    ↓
Publishes: nba-phase3-analytics-complete (existing)
    ↓
New listener: grading-trigger-function
    ↓
Triggers grading for affected game_date
    ↓
prediction_accuracy table updated
```

### Implementation

```python
# Cloud Function: grading_trigger
def trigger_grading(event, context):
    """Trigger grading when Phase 3 completes."""
    import base64
    import json
    from google.cloud import run_v2

    message = json.loads(base64.b64decode(event['data']).decode())

    if message.get('processor_name') == 'PlayerGameSummaryProcessor':
        game_date = message.get('game_date')

        # Call grading service
        # ... implementation
```

---

## Implementation Timeline

### Week 1: Phase 1 (Scheduled Triggers)

- [ ] Create 3 evening scheduler jobs
- [ ] Test with manual triggers
- [ ] Verify player_game_summary populates
- [ ] Monitor for 3 days

### Week 2: Investigation

- [ ] Measure NBA.com game_status latency
- [ ] Evaluate alternative sources (ESPN, BDL)
- [ ] Document findings

### Week 3-4: Phase 2 (Event-Driven)

- [ ] Implement game completion polling function
- [ ] Create tracking table
- [ ] Deploy and test
- [ ] Compare to scheduled approach

### Week 5+: Phase 3 (Automatic Grading)

- [ ] Add grading trigger function
- [ ] Test end-to-end flow
- [ ] Document and handoff

---

## Success Metrics

| Metric | Before | Phase 1 Target | Phase 2 Target |
|--------|--------|----------------|----------------|
| Avg processing delay | 12 hours | 2 hours | 15 minutes |
| Weekend matinee delay | 15 hours | 3 hours | 15 minutes |
| Same-night grading | Never | Sometimes | Always |
| Signal validation delay | Next day | Same night | Real-time |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Incomplete boxscores | Bad analytics data | Check boxscore completeness before processing |
| Duplicate processing | Wasted resources | Idempotent processors, tracking table |
| API rate limits | Missed updates | Backoff, caching, fallback sources |
| Game postponements | Processing errors | Check game_status before processing |

---

## Files to Create/Modify

### Phase 1 (Schedulers)
- `bin/orchestrators/setup_evening_schedulers.sh` - New scheduler setup script

### Phase 2 (Event-Driven)
- `orchestration/cloud_functions/game_completion_monitor/` - New function
- `schemas/bigquery/orchestration/game_completion_timing.sql` - Tracking table

### Phase 3 (Grading)
- `orchestration/cloud_functions/grading_trigger/` - New function

---

## Related Documentation

- [Current State Analysis](./CURRENT-STATE-ANALYSIS.md)
- [Orchestration Architecture](../../01-architecture/orchestration/)
- [Phase 3 Analytics](../../03-phases/phase3-analytics/)
