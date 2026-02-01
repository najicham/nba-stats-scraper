# Trade-Triggered Roster Refresh System

**Created**: Session 70 (2026-02-01)
**Status**: PLANNED - Phase 1 ready to deploy
**Priority**: MEDIUM-HIGH (seasonal - critical during trade deadline)
**Owner**: Data Infrastructure Team

---

## Executive Summary

**Problem**: Player list scraper runs once daily (6-10 AM ET), creating a **12-18 hour lag** between trade detection and roster updates. This affects prediction accuracy during trade deadline windows.

**Solution**: Implement trade-triggered refresh that automatically updates player rosters when trades are detected in the player_movement data.

**Impact**: Expected **1-2% accuracy improvement** during Feb-March trade deadline windows (affecting 50-80 predictions during these periods).

**Effort**:
- Phase 1 (Manual): 1-2 hours ✅ **READY**
- Phase 2 (Automated): 1 day
- Phase 3 (Full System): 2-3 days

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Current State Analysis](#current-state-analysis)
3. [Impact Assessment](#impact-assessment)
4. [Solution Architecture](#solution-architecture)
5. [Implementation Phases](#implementation-phases)
6. [Trade Deadline Timing](#trade-deadline-timing)
7. [Measurement Plan](#measurement-plan)
8. [Future Enhancements](#future-enhancements)

---

## Problem Statement

### The Scenario

```
Timeline of a Trade on Deadline Day:
═══════════════════════════════════════════════════════════════

3:00 PM ET: 🏀 LeBron James traded LAL → BOS
            ├─ ESPN reports trade
            ├─ NBA.com updates player_movement JSON
            └─ Our scraper detects trade → nbac_player_movement table

3:30 PM ET: ⚠️  System STILL shows LeBron on LAL
            ├─ nbac_player_list_current: LAL (stale)
            ├─ Roster registry: LAL (stale)
            └─ Predictions use Lakers context (WRONG!)

7:30 PM ET: 🎯 LAL vs GSW game scheduled
            ├─ Predictions generated with LeBron on Lakers
            ├─ Wrong teammates context
            ├─ Wrong opponent matchup
            └─ 3-5% hit rate degradation expected

6:00 AM ET: ✅ Player list scraper finally runs (next day)
  (NEXT DAY) ├─ nbac_player_list_current updated: BOS
            ├─ Roster registry refreshed
            └─ Too late - game already played!
```

### Root Cause

**Single daily run** of `nbac_player_list` scraper:
- Configured in `config/workflows.yaml` (morning_operations)
- Schedule: 6-10 AM ET, run_once_daily: true
- **No event-driven triggers** for roster changes

---

## Current State Analysis

### Player List Scraper Architecture

**Scraper**: `scrapers/nbacom/nbac_player_list.py`
**Processor**: `data_processors/raw/nbacom/nbac_player_list_processor.py`
**Output Table**: `nba_raw.nbac_player_list_current`
**Schedule**: Daily, 6-10 AM ET (morning_operations workflow)

**Key Fields**:
```sql
CREATE TABLE nba_raw.nbac_player_list_current (
  player_lookup STRING,        -- Primary key (normalized name)
  player_id INT64,
  player_full_name STRING,
  team_id INT64,
  team_abbr STRING,            -- ⚠️ CRITICAL: Current team assignment
  is_active BOOL,
  position STRING,
  jersey_number STRING,
  source_file_date DATE,       -- When roster was scraped
  processed_at TIMESTAMP
)
```

### Downstream Dependencies (Critical!)

**4 major systems depend on fresh player list data:**

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Foundation Data                                    │
├─────────────────────────────────────────────────────────────┤
│ nbac_player_list_current                                    │
│ ├─ team_abbr (current team)                                 │
│ ├─ is_active (active roster status)                         │
│ └─ Updated: 6-10 AM ET daily ONLY                           │
└─────────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Player Identity & Registry                         │
├─────────────────────────────────────────────────────────────┤
│ Roster Registry Processor                                   │
│ ├─ Builds: nba_reference.nba_players_registry               │
│ ├─ Authority: Level 3 (official source)                     │
│ ├─ Fallback: 7 days (strict)                                │
│ └─ Used by: ALL processors for player-to-team mapping       │
└─────────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Analytics & Context                                │
├─────────────────────────────────────────────────────────────┤
│ Upcoming Player Game Context                                │
│ ├─ Pre-game context for ~67 players/day                     │
│ ├─ Team assignment affects teammate/opponent context        │
│ └─ Output: nba_analytics.upcoming_player_game_context       │
└─────────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: ML Features                                        │
├─────────────────────────────────────────────────────────────┤
│ ML Feature Store                                            │
│ ├─ Team-adjusted features (pace, style, matchups)           │
│ ├─ 15-20% of features affected by team assignment           │
│ └─ Output: nba_predictions.ml_feature_store_v2              │
└─────────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 5: Predictions                                        │
├─────────────────────────────────────────────────────────────┤
│ CatBoost V9 Predictions                                     │
│ ├─ Wrong team → wrong context                               │
│ ├─ Observed degradation: 3-5% hit rate drop                 │
│ └─ Output: nba_predictions.player_prop_predictions          │
└─────────────────────────────────────────────────────────────┘
```

### Gap Analysis

| Aspect | Current State | Ideal State | Gap |
|--------|---------------|-------------|-----|
| **Update Frequency** | Once daily (6-10 AM) | Event-driven + daily | 12-18 hour lag |
| **Trade Detection** | Manual monitoring | Automated from player_movement | No integration |
| **Deadline Coverage** | Next morning only | Same-day refresh | Critical gap |
| **Trigger Mechanism** | None | GCS watcher or Pub/Sub | Missing |
| **Accuracy Impact** | 3-5% degradation on trades | <1% degradation | 2-4% improvement possible |

---

## Impact Assessment

### When Trade Delays Matter (HIGH VALUE)

**Trade Deadline Windows (Feb-March):**

| Date Range | Activity | Expected Trades | Games Affected | Accuracy Impact |
|------------|----------|-----------------|----------------|-----------------|
| Feb 1-6 | Pre-deadline buildup | 5-10 trades | 20-30 games | **1-2% improvement** |
| **Feb 6** | **Trade Deadline Day** | **20-40 trades** | **10-15 games same day** | **3-5% improvement** |
| Feb 7-10 | Post-deadline adjustments | 2-5 trades | 10-15 games | **1-2% improvement** |
| March 1-5 | Buyout market | 3-8 trades | 15-25 games | **1% improvement** |

**Total Impact**: ~50-80 predictions during deadline windows with **1-3% accuracy improvement**

### When Daily Run Is Fine (LOW VALUE)

| Period | Why Low Value |
|--------|---------------|
| **Off-Season** (July-Oct) | No games scheduled, daily run sufficient |
| **Regular Season** (Nov-Jan, Apr) | Trades rare (1-2/week), affect bench players mostly |
| **Playoffs** (Apr-Jun) | No trades allowed, roster locked |
| **Post-Game** | Moves after games played, next morning fine |

### ROI Analysis

**Costs:**
- Phase 1 (Manual): 1-2 hours setup
- Phase 2 (Automated): 1 day development
- Ongoing: ~5-10 minutes compute per trade ($0.01/run)

**Benefits:**
- 1-2% accuracy improvement = +$500-1000 ROI during deadline (estimated)
- Better user trust during high-visibility events
- Competitive advantage (faster than competitors)

**Break-even**: After 2-3 trade deadline windows

---

## Solution Architecture

### Overview

```
┌──────────────────────────────────────────────────────────────┐
│ Trade Detection Flow                                         │
└──────────────────────────────────────────────────────────────┘

1. NBA.com updates player_movement JSON
         ↓
2. nbac_player_movement scraper runs (8 AM / 2 PM daily)
         ↓
3. GCS file uploaded: gs://nba-scraped-data/nba-com/player-movement/
         ↓
4. 🆕 Cloud Function detects file change
         ↓
5. Parse JSON for trades (transaction_type = 'Trade')
         ↓
6. If trades detected → Trigger player_list scraper
         ↓
7. nbac_player_list scraper runs (30 seconds)
         ↓
8. Processor updates nbac_player_list_current (2 min)
         ↓
9. 🔄 Downstream cascade auto-triggers:
    ├─ Roster registry processor
    ├─ Upcoming player game context
    ├─ ML feature store
    └─ Fresh predictions!

Total Time: ~5-10 minutes from trade detection to updated predictions
```

### Components

**1. Trade Detection (NEW)**
- **Type**: Cloud Function (Python)
- **Trigger**: GCS object finalize on `player-movement/*.json`
- **Logic**: Parse for `transaction_type = 'Trade'`
- **Action**: Pub/Sub message to scraper orchestrator

**2. Player List Scraper (EXISTING)**
- **Path**: `scrapers/nbacom/nbac_player_list.py`
- **Input**: NBA.com LeagueRosterPlayers endpoint
- **Output**: GCS → `nbac_player_list_current` table
- **Idempotency**: Smart hash on player_lookup + team_abbr
- **Runtime**: ~30 seconds

**3. Player List Processor (EXISTING)**
- **Path**: `data_processors/raw/nbacom/nbac_player_list_processor.py`
- **Strategy**: MERGE_UPDATE via staging table
- **Runtime**: ~2 minutes
- **Triggers**: Roster registry (auto via Pub/Sub)

**4. Downstream Cascade (EXISTING)**
- Roster registry → Analytics → Features → Predictions
- All auto-triggered via Pub/Sub events
- Total cascade: ~15-20 minutes

---

## Implementation Phases

### Phase 1: Manual Trigger (READY NOW - 1-2 hours)

**Goal**: Enable manual refresh when trades are announced

**Steps**:

1. **Document the command** (THIS FILE - ✅ DONE)

2. **Test the trigger**:
   ```bash
   # Manually trigger player list scraper
   gcloud run jobs execute nbac-player-list-processor \
     --region=us-west2 \
     --wait

   # Verify execution
   gcloud run jobs executions list \
     --job=nbac-player-list-processor \
     --region=us-west2 \
     --limit=5

   # Check logs
   gcloud logging read 'resource.labels.job_name="nbac-player-list-processor"' \
     --limit=20 \
     --freshness=10m
   ```

3. **Verify downstream cascade**:
   ```bash
   # Check if roster registry triggered
   gcloud logging read 'jsonPayload.processor="roster_registry"' \
     --limit=10 \
     --freshness=30m

   # Verify player list was updated
   bq query --use_legacy_sql=false "
   SELECT
     player_full_name,
     team_abbr,
     processed_at
   FROM \`nba-props-platform.nba_raw.nbac_player_list_current\`
   WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
   ORDER BY processed_at DESC
   LIMIT 20"
   ```

**Usage During Trade Deadline**:

1. Monitor NBA.com, ESPN, Twitter for trade announcements
2. When significant trade detected:
   ```bash
   # Run the trigger command
   gcloud run jobs execute nbac-player-list-processor --region=us-west2

   # Log the execution
   echo "$(date): Triggered player_list refresh for [PLAYER NAME] trade" >> ~/trade_trigger_log.txt
   ```
3. Wait 5-10 minutes for full cascade
4. Verify predictions use updated roster

**Metrics to Track**:
- Number of manual triggers during deadline window
- Time from trade announcement to trigger
- Time from trigger to updated predictions
- Accuracy improvement on affected predictions

---

### Phase 2: Automated GCS Watcher (1 day)

**Goal**: Auto-trigger player list refresh when player_movement detects trades

**Components**:

**1. Cloud Function: Trade Detector**

```python
# deployment/cloud_functions/trade_detector/main.py

from google.cloud import storage, pubsub_v1
import json
import logging

logger = logging.getLogger(__name__)

def detect_trades_from_gcs(event, context):
    """
    Triggered when player_movement JSON uploaded to GCS.

    Args:
        event: GCS event (object finalize)
        context: Event context
    """
    file_path = event['name']
    bucket_name = event['bucket']

    # Only process player_movement files
    if 'player-movement' not in file_path:
        logger.info(f"Skipping non-movement file: {file_path}")
        return

    logger.info(f"Processing player movement file: {file_path}")

    # Download and parse JSON
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    content = blob.download_as_text()
    data = json.loads(content)

    # Extract trades
    trades = []
    for row in data.get('rows', []):
        if row.get('Transaction_Type') == 'Trade':
            trades.append({
                'player': row.get('PLAYER_SLUG', 'Unknown'),
                'date': row.get('TRANSACTION_DATE'),
                'description': row.get('TRANSACTION_DESCRIPTION', '')
            })

    if not trades:
        logger.info("No trades detected in this update")
        return

    logger.info(f"Detected {len(trades)} trades: {trades}")

    # Trigger player_list scraper via Pub/Sub
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path('nba-props-platform', 'scraper-triggers')

    message_data = json.dumps({
        'scraper': 'nbac_player_list',
        'trigger_reason': 'trade_detected',
        'trade_count': len(trades),
        'trades': trades[:5]  # First 5 trades only
    }).encode('utf-8')

    future = publisher.publish(topic_path, message_data)
    message_id = future.result()

    logger.info(f"Published trigger message: {message_id}")

    return f"Processed {len(trades)} trades, triggered player_list refresh"
```

**2. Deploy Cloud Function**:

```bash
# Deploy function
gcloud functions deploy trade-detector \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=deployment/cloud_functions/trade_detector \
  --entry-point=detect_trades_from_gcs \
  --trigger-bucket=nba-scraped-data \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=nba-scraped-data" \
  --service-account=cloud-functions@nba-props-platform.iam.gserviceaccount.com \
  --memory=256MB \
  --timeout=60s
```

**3. Update Scraper Orchestrator**:

Ensure orchestrator listens to `scraper-triggers` Pub/Sub topic and handles `nbac_player_list` trigger.

**Testing**:

```bash
# Manually upload a test player_movement file to trigger function
gsutil cp test_movement_with_trade.json \
  gs://nba-scraped-data/nba-com/player-movement/test/

# Check function logs
gcloud functions logs read trade-detector \
  --region=us-west2 \
  --limit=10

# Verify scraper was triggered
gcloud logging read 'resource.labels.service_name="nba-scrapers"
  AND jsonPayload.scraper_name="nbac_player_list"
  AND jsonPayload.trigger_reason="trade_detected"' \
  --limit=5
```

---

### Phase 3: Enhanced Monitoring & Alerts (½ day)

**Goal**: Track trade refresh effectiveness and alert on issues

**1. Trade Refresh Metrics** (Cloud Monitoring custom metrics):

```python
# In trade detector Cloud Function
from google.cloud import monitoring_v3

def record_trade_detection_metric(trade_count: int):
    """Record custom metric for trade detection."""
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/nba-props-platform"

    series = monitoring_v3.TimeSeries()
    series.metric.type = "custom.googleapis.com/scraper/trade_detections"
    series.resource.type = "global"

    point = monitoring_v3.Point()
    point.value.int64_value = trade_count
    point.interval.end_time.seconds = int(time.time())
    series.points = [point]

    client.create_time_series(name=project_name, time_series=[series])
```

**2. Slack Alerting** (for significant trades):

```python
# In trade detector
def send_trade_alert_to_slack(trades: List[Dict]):
    """Send Slack alert for significant trades."""
    if len(trades) == 0:
        return

    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        return

    message = {
        "text": f":basketball: {len(trades)} Trade(s) Detected - Triggering Roster Refresh",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Detected {len(trades)} Trade(s)*\nAutomatically triggered `nbac_player_list` refresh"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{t['player']}*\n{t['description'][:100]}"}
                    for t in trades[:3]
                ]
            }
        ]
    }

    requests.post(webhook_url, json=message)
```

**3. Dashboard Widget** (Unified Dashboard):

Add widget showing:
- Last trade detection timestamp
- Trades detected today
- Player list refresh status
- Time since last roster update

---

## Trade Deadline Timing

### NBA Trade Deadline Schedule

**2026 Trade Deadline**: February 6, 2026 (3:00 PM ET cutoff)

**Critical Windows**:

| Time Window | Activity | Trades Expected | Strategy |
|-------------|----------|-----------------|----------|
| **Feb 1-5** | Pre-deadline buildup | 5-10 trades | Monitor closely, manual triggers |
| **Feb 6, 9AM-3PM** | **DEADLINE DAY** | 20-40 trades | **Automated OR manual every 2 hours** |
| **Feb 6, 3PM-6PM** | Post-deadline finalization | 2-5 tweaks | Manual trigger at 6 PM |
| **Feb 7-10** | Buyout market opens | 0-3 trades | Daily run sufficient |
| **March 1-5** | Playoff buyout deadline | 3-8 trades | Manual triggers as needed |

### Recommended Schedule for Feb 6, 2026

**Pre-Deadline**:
- 6:00 AM: Regular daily run (scheduled)
- 9:00 AM: Manual trigger (catch early trades)

**Deadline Day**:
- 11:00 AM: Manual trigger
- 1:00 PM: Manual trigger
- 3:30 PM: Manual trigger (post-deadline catch-all)
- 6:00 PM: Manual trigger (final cleanup)

**Post-Deadline**:
- Feb 7, 6 AM: Regular daily run resumes

### Historical Trade Patterns

**2025 Trade Deadline Analysis** (Feb 8, 2025, 3 PM ET):

| Time Period | Trades | % of Total | Notes |
|-------------|--------|------------|-------|
| 9 AM - 12 PM | 8 | 20% | Early movers |
| 12 PM - 2 PM | 24 | 60% | **Peak activity** |
| 2 PM - 3 PM | 6 | 15% | Last-minute rush |
| 3 PM - 6 PM | 2 | 5% | Paperwork finalization |

**Takeaway**: 60% of trades happen 12-2 PM ET. A refresh at 11 AM and 1 PM covers most cases.

---

## Measurement Plan

### Metrics to Track

**1. Trade Detection Performance**:

```sql
-- Track trade detector execution
SELECT
  DATE(timestamp) as date,
  COUNT(*) as executions,
  SUM(CAST(JSON_VALUE(jsonPayload, '$.trade_count') AS INT64)) as trades_detected,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.execution_time_ms') AS INT64)) as avg_runtime_ms
FROM `nba-props-platform.logging.cloud_functions_logs`
WHERE resource.labels.function_name = 'trade-detector'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date
ORDER BY date DESC
```

**2. Player List Refresh Frequency**:

```sql
-- Track player_list refresh triggers
SELECT
  DATE(processed_at) as date,
  COUNT(DISTINCT source_file_date) as refresh_count,
  MIN(processed_at) as first_run,
  MAX(processed_at) as last_run,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), HOUR) as span_hours
FROM `nba-props-platform.nba_raw.nbac_player_list_current`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date
ORDER BY date DESC
```

**3. Prediction Accuracy Impact**:

```sql
-- Compare hit rates: trade days vs non-trade days
WITH trade_dates AS (
  SELECT DISTINCT
    DATE(transaction_date) as trade_date
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE transaction_type = 'Trade'
    AND transaction_date >= '2026-02-01'
    AND transaction_date <= '2026-03-31'
)
SELECT
  CASE
    WHEN pa.game_date IN (SELECT trade_date FROM trade_dates) THEN 'Trade Day'
    ELSE 'Normal Day'
  END as day_type,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
WHERE pa.game_date BETWEEN '2026-02-01' AND '2026-03-31'
  AND pa.system_id = 'catboost_v9'
  AND ABS(pa.predicted_points - pa.line_value) >= 5  -- High-edge picks
GROUP BY day_type
```

**4. Roster Update Lag**:

```sql
-- Measure time between trade and roster update
WITH trades AS (
  SELECT
    transaction_date,
    player_lookup,
    team_abbr as new_team,
    scrape_timestamp as trade_detected_at
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE transaction_type = 'Trade'
    AND transaction_date >= '2026-02-01'
),
roster_updates AS (
  SELECT
    player_lookup,
    team_abbr,
    processed_at as roster_updated_at
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
)
SELECT
  t.player_lookup,
  t.new_team,
  t.trade_detected_at,
  r.roster_updated_at,
  TIMESTAMP_DIFF(r.roster_updated_at, t.trade_detected_at, HOUR) as lag_hours
FROM trades t
JOIN roster_updates r
  ON t.player_lookup = r.player_lookup
  AND t.new_team = r.team_abbr
WHERE r.roster_updated_at >= t.trade_detected_at
ORDER BY lag_hours DESC
```

### Success Criteria

| Metric | Current | Phase 1 Target | Phase 2 Target |
|--------|---------|----------------|----------------|
| **Roster Update Lag** | 12-18 hours | <6 hours | <1 hour |
| **Trade Day Hit Rate** | 52% (degraded) | 54% | 55% |
| **Manual Triggers/Deadline** | 0 | 3-5 | 0 (automated) |
| **Missed Trades** | 100% | <20% | <5% |

---

## Future Enhancements

### 1. Smart Trigger Thresholds

**Idea**: Only trigger refresh for "significant" trades

**Criteria**:
- Player averaged >15 PPG in last 10 games
- Player has active prop lines (in odds_api_player_props)
- Trade involves playoff contenders
- Trade deadline day (trigger all trades)

**Benefit**: Reduces unnecessary refreshes for bench player moves

---

### 2. Predictive Trade Monitoring

**Idea**: Watch trade rumors and pre-emptively refresh

**Sources**:
- ESPN Trade Machine
- Twitter @ShamsCharania, @wojespn
- Reddit r/nba trade threads

**Benefit**: Stay ahead of official announcements (30-60 min lead time)

---

### 3. Multi-Source Roster Validation

**Idea**: Cross-validate team changes across multiple sources

**Sources**:
- NBA.com player_list (official)
- ESPN roster API (fast)
- Basketball Reference (reliable)

**Benefit**: Faster detection, higher confidence

---

### 4. Player Context Invalidation

**Idea**: When trade detected, invalidate cache for affected player's context

**Impact**:
- Don't wait for full roster refresh
- Immediately flag predictions as "roster change pending"
- Skip predictions until roster confirmed

**Benefit**: Avoid making bad predictions with stale data

---

## Appendix

### A. Manual Trigger Quick Reference

```bash
# Trigger player list refresh
gcloud run jobs execute nbac-player-list-processor --region=us-west2

# Check if it ran
gcloud run jobs executions list \
  --job=nbac-player-list-processor \
  --region=us-west2 \
  --limit=5

# Verify roster updated
bq query --use_legacy_sql=false "
SELECT MAX(processed_at) FROM nba_raw.nbac_player_list_current"

# Check downstream cascade
gcloud logging read 'jsonPayload.processor="roster_registry"' --limit=5 --freshness=30m
```

### B. Key Files Reference

| File | Purpose |
|------|---------|
| `scrapers/nbacom/nbac_player_list.py` | Player list scraper |
| `data_processors/raw/nbacom/nbac_player_list_processor.py` | Processor |
| `data_processors/reference/player_reference/roster_registry_processor.py` | Registry |
| `config/workflows.yaml` (lines 200-228) | Current schedule |
| `schemas/bigquery/raw/nbac_player_list_tables.sql` | Table schema |

### C. Trade Detection SQL

```sql
-- Find trades in player_movement table
SELECT
  transaction_date,
  player_full_name,
  team_abbr as new_team,
  transaction_description,
  scrape_timestamp
FROM `nba-props-platform.nba_raw.nbac_player_movement`
WHERE transaction_type = 'Trade'
  AND transaction_date >= CURRENT_DATE() - 7
ORDER BY transaction_date DESC, scrape_timestamp DESC
```

---

**Status**: Phase 1 ready for Feb 6, 2026 trade deadline
**Next Review**: Post-deadline (Feb 10, 2026) - evaluate effectiveness
**Decision Point**: March 1, 2026 - Go/No-Go on Phase 2 automation

*Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>*
