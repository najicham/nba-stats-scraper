# Phase 3 Scheduling Strategy

**File:** `docs/processors/03-phase3-scheduling-strategy.md`
**Created:** 2025-11-15 14:45 PST
**Last Updated:** 2025-11-25
**Purpose:** Cloud Scheduler and Pub/Sub configuration for Phase 3 analytics processors
**Status:** ✅ Deployed & operational
**Audience:** Engineers deploying Phase 3 orchestration infrastructure

**Related Docs:**
- **Operations:** See `02-phase3-operations-guide.md` for processor specifications
- **Troubleshooting:** See `04-phase3-troubleshooting.md` for failure recovery
- **Phase 1:** See `docs/orchestration/01-how-it-works.md` for Phase 1 scheduler comparison

---

## Table of Contents

1. [Overview](#overview)
2. [Pub/Sub Topic Configuration](#pubsub-topic-configuration)
3. [Cloud Scheduler Jobs](#cloud-scheduler-jobs)
4. [Event Payload Structure](#event-payload-structure)
5. [Implementation Strategies](#implementation-strategies)
6. [Deployment Steps](#deployment-steps)

---

## Overview

### Scheduling Approach

Phase 3 uses a **hybrid scheduling strategy**:

**Time-Based (Cloud Scheduler):**
- Historical processors: Fixed daily schedule (2:30 AM ET)
- Upcoming contexts: Multiple daily runs (6 AM, 12 PM, 5 PM ET)
- Predictable, easy to monitor
- ✅ **Recommended for initial deployment**

**Event-Driven (Pub/Sub):**
- Responds to upstream events (props-updated, injuries-updated)
- Enables real-time updates when data changes
- More complex, but more responsive
- 🔄 **Add after time-based is stable**

### Recommended Implementation Path

**Phase 1 (Week 1): Time-Based Only**
- Use Cloud Scheduler with fixed times
- Simplest to set up and debug
- Covers 95% of use cases

**Phase 2 (Week 2-3): Add Event-Driven**
- Add Pub/Sub triggers for props updates
- Keep time-based as fallback
- Best of both worlds

**Phase 3 (Month 2+): Full Event-Driven**
- All processors triggered by events
- Minimal fixed schedules (only fallbacks)
- Most responsive system

---

## Pub/Sub Topic Configuration

### Topic Naming Convention

**Note:** Following architecture pattern from `docs/01-architecture/pipeline-design.md`

| Topic | Purpose | Publisher | Subscribers |
|-------|---------|-----------|-------------|
| `nba-raw-data-complete` | Phase 2 raw data loaded | Phase 2 processors | All Phase 3 processors |
| `phase3-start` | **Time-based fallback only** | Cloud Scheduler (backup) | P1 + P2 + P3 historical |
| `phase3-player-game-summary-complete` | Historical player data ready | player_game_summary | (none - for monitoring) |
| `phase3-team-offense-complete` | Historical team offense ready | team_offense_game_summary | (none - for monitoring) |
| `phase3-team-defense-complete` | Historical team defense ready | team_defense_game_summary | (none - for monitoring) |
| `phase3-historical-complete` | All 3 historical processors done | Aggregator function | (future Phase 4) |
| `props-updated` | New prop data available | Odds API scrapers | Team + player context |
| `schedule-updated` | Schedule changes | Schedule scrapers | Team context |
| `injuries-updated` | Injury report updated | Injury scrapers | Team context |
| `team-context-updated` | Team context refreshed | upcoming_team_game_context | Player context |
| `nba-analytics-complete` | Phase 3 analytics ready | Phase 3 processors | Phase 4 processors |

**Primary Pattern (Event-Driven):**
- Phase 2 publishes to `nba-raw-data-complete` when data loads
- Phase 3 processors subscribe and check dependencies
- Each processor decides to run or skip based on dependency check

**Fallback Pattern (Time-Based):**
- Cloud Scheduler publishes to `phase3-start` at fixed times (2:30 AM)
- Use during initial deployment or if event-driven fails
- Can run alongside event-driven (idempotency prevents duplicates)

### Creating Topics

```bash
#!/bin/bash
# create_phase3_topics.sh

PROJECT_ID="nba-props-platform"

# Primary event-driven topic (Phase 2 → Phase 3)
gcloud pubsub topics create nba-raw-data-complete --project=$PROJECT_ID

# Time-based fallback topic (Cloud Scheduler → Phase 3)
gcloud pubsub topics create phase3-start --project=$PROJECT_ID
gcloud pubsub topics create phase3-player-game-summary-complete --project=$PROJECT_ID
gcloud pubsub topics create phase3-team-offense-complete --project=$PROJECT_ID
gcloud pubsub topics create phase3-team-defense-complete --project=$PROJECT_ID
gcloud pubsub topics create phase3-historical-complete --project=$PROJECT_ID
gcloud pubsub topics create props-updated --project=$PROJECT_ID
gcloud pubsub topics create schedule-updated --project=$PROJECT_ID
gcloud pubsub topics create injuries-updated --project=$PROJECT_ID
gcloud pubsub topics create team-context-updated --project=$PROJECT_ID
gcloud pubsub topics create phase3-complete --project=$PROJECT_ID

# Create dead letter queues
gcloud pubsub topics create phase3-player-game-summary-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase3-team-offense-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase3-team-defense-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase3-upcoming-team-context-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase3-upcoming-player-context-dlq --project=$PROJECT_ID

echo "✅ All Phase 3 Pub/Sub topics created"
```

### Creating Subscriptions

**Note:** Phase 3 uses push subscriptions to Cloud Run analytics service

```bash
#!/bin/bash
# create_phase3_subscriptions.sh

PROJECT_ID="nba-props-platform"
ANALYTICS_SERVICE_URL="https://nba-analytics-processors-xxx.run.app"

# PRIMARY: Event-driven subscriptions (Phase 2 → Phase 3)
# All Phase 3 processors listen to nba-raw-data-complete
gcloud pubsub subscriptions create phase3-analytics-event-driven-sub \
  --topic nba-raw-data-complete \
  --push-endpoint="${ANALYTICS_SERVICE_URL}/process" \
  --ack-deadline 900 \
  --message-retention-duration 1h \
  --dead-letter-topic phase3-analytics-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

# FALLBACK: Time-based subscriptions (Cloud Scheduler → Phase 3)
# For initial deployment or when event-driven unavailable
gcloud pubsub subscriptions create phase3-analytics-time-based-sub \
  --topic phase3-start \
  --push-endpoint="${ANALYTICS_SERVICE_URL}/process" \
  --ack-deadline 900 \
  --message-retention-duration 1h \
  --dead-letter-topic phase3-analytics-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

# Upcoming contexts (multiple triggers)
gcloud pubsub subscriptions create phase3-upcoming-team-context-sub \
  --topic props-updated \
  --ack-deadline 1500 \
  --message-retention-duration 1h \
  --dead-letter-topic phase3-upcoming-team-context-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create phase3-upcoming-player-context-sub \
  --topic props-updated \
  --ack-deadline 1800 \
  --message-retention-duration 1h \
  --dead-letter-topic phase3-upcoming-player-context-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

echo "✅ All Phase 3 Pub/Sub subscriptions created"
```

**Subscription Parameters:**

| Parameter | Value | Reasoning |
|-----------|-------|-----------|
| **ack-deadline** | 900-1800s (15-30 min) | Processors can take 5-15s, need buffer for retries |
| **message-retention** | 1h | Messages expire after 1 hour if not processed |
| **max-delivery-attempts** | 3 | Try 3 times before sending to DLQ |
| **dead-letter-topic** | processor-specific DLQ | Failed messages go to separate DLQ for investigation |

---

## Cloud Scheduler Jobs

### Historical Processors (Daily Morning - Single Run)

**Job Name:** `phase3-historical-nightly`
**Schedule:** `0 2 * * *` (2:00 AM ET daily)
**Purpose:** Trigger all 3 historical processors in parallel

```bash
#!/bin/bash
# Create historical nightly job

PROJECT_ID="nba-props-platform"
REGION="us-central1"

gcloud scheduler jobs create pubsub phase3-historical-nightly \
  --schedule "0 2 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic phase3-start \
  --message-body '{
    "trigger": "nightly_historical",
    "phase": "3",
    "trigger_time": "AUTO_TIMESTAMP",
    "start_date": "AUTO_YESTERDAY",
    "end_date": "AUTO_YESTERDAY",
    "source": "cloud-scheduler"
  }' \
  --project=$PROJECT_ID

echo "✅ Historical nightly job created"
```

**Note:** `AUTO_TIMESTAMP` and `AUTO_YESTERDAY` are placeholders. In practice, you'd use:
- `trigger_time`: Current timestamp at execution
- `start_date`/`end_date`: Yesterday's date (CURRENT_DATE - 1)

---

### Upcoming Team Context (Multiple Daily Runs)

**Morning Run (6:00 AM ET):**
```bash
gcloud scheduler jobs create pubsub phase3-team-context-morning \
  --schedule "0 6 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic props-updated \
  --message-body '{
    "event_type": "scheduled_update",
    "trigger_time": "AUTO_TIMESTAMP",
    "game_date": "AUTO_TODAY",
    "run_type": "morning"
  }' \
  --project=nba-props-platform
```

**Midday Run (12:00 PM ET):**
```bash
gcloud scheduler jobs create pubsub phase3-team-context-midday \
  --schedule "0 12 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic props-updated \
  --message-body '{
    "event_type": "scheduled_update",
    "trigger_time": "AUTO_TIMESTAMP",
    "game_date": "AUTO_TODAY",
    "run_type": "midday"
  }' \
  --project=nba-props-platform
```

**Pre-Game Run (5:00 PM ET):**
```bash
gcloud scheduler jobs create pubsub phase3-team-context-pregame \
  --schedule "0 17 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic props-updated \
  --message-body '{
    "event_type": "scheduled_update",
    "trigger_time": "AUTO_TIMESTAMP",
    "game_date": "AUTO_TODAY",
    "run_type": "pregame"
  }' \
  --project=nba-props-platform
```

---

### Upcoming Player Context (Multiple Daily Runs)

**Morning Run (6:30 AM ET - after team context):**
```bash
gcloud scheduler jobs create pubsub phase3-player-context-morning \
  --schedule "30 6 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic props-updated \
  --message-body '{
    "event_type": "scheduled_update",
    "trigger_time": "AUTO_TIMESTAMP",
    "game_date": "AUTO_TODAY",
    "run_type": "morning"
  }' \
  --project=nba-props-platform
```

**Pre-Game Run (6:00 PM ET):**
```bash
gcloud scheduler jobs create pubsub phase3-player-context-pregame \
  --schedule "0 18 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic props-updated \
  --message-body '{
    "event_type": "scheduled_update",
    "trigger_time": "AUTO_TIMESTAMP",
    "game_date": "AUTO_TODAY",
    "run_type": "pregame"
  }' \
  --project=nba-props-platform
```

---

### Complete Scheduler Job Setup Script

```bash
#!/bin/bash
# setup_phase3_scheduler.sh

PROJECT_ID="nba-props-platform"
REGION="us-central1"

echo "Creating Phase 3 Cloud Scheduler jobs..."

# 1. Historical processors (2:00 AM ET daily)
gcloud scheduler jobs create pubsub phase3-historical-nightly \
  --schedule "0 2 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic phase3-start \
  --message-body '{"trigger":"nightly_historical","phase":"3"}' \
  --project=$PROJECT_ID

# 2. Team context - morning (6:00 AM ET)
gcloud scheduler jobs create pubsub phase3-team-context-morning \
  --schedule "0 6 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic props-updated \
  --message-body '{"event_type":"scheduled_update","run_type":"morning"}' \
  --project=$PROJECT_ID

# 3. Team context - midday (12:00 PM ET)
gcloud scheduler jobs create pubsub phase3-team-context-midday \
  --schedule "0 12 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic props-updated \
  --message-body '{"event_type":"scheduled_update","run_type":"midday"}' \
  --project=$PROJECT_ID

# 4. Team context - pregame (5:00 PM ET)
gcloud scheduler jobs create pubsub phase3-team-context-pregame \
  --schedule "0 17 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic props-updated \
  --message-body '{"event_type":"scheduled_update","run_type":"pregame"}' \
  --project=$PROJECT_ID

# 5. Player context - morning (6:30 AM ET)
gcloud scheduler jobs create pubsub phase3-player-context-morning \
  --schedule "30 6 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic props-updated \
  --message-body '{"event_type":"scheduled_update","run_type":"morning"}' \
  --project=$PROJECT_ID

# 6. Player context - pregame (6:00 PM ET)
gcloud scheduler jobs create pubsub phase3-player-context-pregame \
  --schedule "0 18 * * *" \
  --time-zone "America/New_York" \
  --location $REGION \
  --topic props-updated \
  --message-body '{"event_type":"scheduled_update","run_type":"pregame"}' \
  --project=$PROJECT_ID

echo "✅ All Phase 3 Cloud Scheduler jobs created"
echo ""
echo "Verify with:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID | grep phase3"
```

---

## Event Payload Structure

### Standard Phase 3 Event

```json
{
  "processor": "player_game_summary",
  "phase": "3",
  "trigger_time": "2025-01-15T02:30:00Z",
  "start_date": "2025-01-14",
  "end_date": "2025-01-14",
  "source": "cloud-scheduler",
  "retry_count": 0
}
```

**Fields:**
- `processor`: Which processor to run
- `phase`: Always "3" for Phase 3
- `trigger_time`: When event was published (ISO 8601 UTC)
- `start_date`: Start date for processing (YYYY-MM-DD)
- `end_date`: End date for processing (YYYY-MM-DD)
- `source`: Where event came from (cloud-scheduler, pubsub, manual)
- `retry_count`: How many times this has been retried (0 = first attempt)

### Completion Event

```json
{
  "processor": "player_game_summary",
  "phase": "3",
  "status": "success",
  "completed_at": "2025-01-15T02:33:15Z",
  "duration_seconds": 4,
  "rows_processed": 452,
  "next_processor": "none",
  "date_processed": "2025-01-14"
}
```

**Fields:**
- `status`: success | partial | failure
- `completed_at`: Timestamp of completion
- `duration_seconds`: How long processor took
- `rows_processed`: Number of records created/updated
- `next_processor`: Downstream processor to trigger (or "none")
- `date_processed`: Date of data that was processed

### Props Updated Event

```json
{
  "event_type": "props_updated",
  "trigger_time": "2025-01-15T06:00:00Z",
  "game_date": "2025-01-15",
  "player_count": 178,
  "source": "odds-api-scraper",
  "trigger_processors": [
    "upcoming_team_game_context",
    "upcoming_player_game_context"
  ]
}
```

**Fields:**
- `event_type`: Type of event (props_updated, schedule_updated, injuries_updated)
- `trigger_time`: When event occurred
- `game_date`: Which game date was updated
- `player_count`: How many players have props
- `source`: Which scraper published this
- `trigger_processors`: List of processors that should respond

---

## Implementation Strategies

### Strategy 1: Time-Based Only (Simplest)

**Pros:**
- ✅ Easiest to set up and debug
- ✅ Predictable timing
- ✅ No Pub/Sub complexity
- ✅ Works for 95% of use cases

**Cons:**
- ❌ Fixed timing (doesn't adapt to upstream delays)
- ❌ No event-driven updates
- ❌ Can't respond to intraday data changes

**Setup:**
```bash
# Historical at 2:30 AM (all 3 with same schedule)
gcloud scheduler jobs create http phase3-player-game-summary \
  --schedule "30 2 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

gcloud scheduler jobs create http phase3-team-offense \
  --schedule "30 2 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

gcloud scheduler jobs create http phase3-team-defense \
  --schedule "30 2 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

# Upcoming processors at 6 AM (team first, player 30 min later)
gcloud scheduler jobs create http phase3-team-context-morning \
  --schedule "0 6 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

gcloud scheduler jobs create http phase3-player-context-morning \
  --schedule "30 6 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST
```

**✅ Recommended for initial deployment (Week 1-2)**

---

### Strategy 2: Hybrid (Time-Based + Event-Driven)

**Pros:**
- ✅ Reliable time-based baseline
- ✅ Event-driven for intraday updates
- ✅ Best of both worlds
- ✅ Gradual complexity increase

**Cons:**
- ⚠️ Need to manage both systems
- ⚠️ Duplicate runs possible (need deduplication)

**Setup:**
```bash
# Time-based for guaranteed runs (6 AM, 12 PM, 5 PM)
# PLUS
# Event-driven for responsive updates (when props change)

# Both trigger the same processors
# Processors handle deduplication via:
#   DELETE existing date range → INSERT new records
```

**✅ Recommended for production (Month 1+)**

---

### Strategy 3: Full Event-Driven (Most Complex)

**Pros:**
- ✅ Most responsive to changes
- ✅ Minimal wasted processing
- ✅ Adapts to upstream delays

**Cons:**
- ❌ Complex to set up and debug
- ❌ Harder to predict timing
- ❌ Need robust fallback mechanisms

**Setup:**
- All processors triggered by Pub/Sub
- Time-based only as fallback (if events fail)
- Requires comprehensive monitoring

**🔄 Recommended for mature system (Month 3+)**

---

## Deployment Steps

### Step 1: Create Pub/Sub Infrastructure

```bash
# Run topic creation script
./create_phase3_topics.sh

# Verify topics created
gcloud pubsub topics list --project=nba-props-platform | grep phase3

# Run subscription creation script
./create_phase3_subscriptions.sh

# Verify subscriptions created
gcloud pubsub subscriptions list --project=nba-props-platform | grep phase3
```

---

### Step 2: Deploy Cloud Run Jobs

**Note:** This assumes you have Docker images built for each processor.

```bash
#!/bin/bash
# deploy_phase3_processors.sh

PROJECT_ID="nba-props-platform"
REGION="us-central1"

# Deploy player game summary
gcloud run jobs create phase3-player-game-summary \
  --image gcr.io/$PROJECT_ID/player-game-summary:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 15m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# Deploy team offense
gcloud run jobs create phase3-team-offense-game-summary \
  --image gcr.io/$PROJECT_ID/team-offense-game-summary:latest \
  --region $REGION \
  --memory 1Gi \
  --cpu 1 \
  --timeout 15m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# Deploy team defense
gcloud run jobs create phase3-team-defense-game-summary \
  --image gcr.io/$PROJECT_ID/team-defense-game-summary:latest \
  --region $REGION \
  --memory 1Gi \
  --cpu 1 \
  --timeout 15m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# Deploy upcoming team context
gcloud run jobs create phase3-upcoming-team-game-context \
  --image gcr.io/$PROJECT_ID/upcoming-team-game-context:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 25m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# Deploy upcoming player context
gcloud run jobs create phase3-upcoming-player-game-context \
  --image gcr.io/$PROJECT_ID/upcoming-player-game-context:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 30m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

echo "✅ All Phase 3 Cloud Run jobs deployed"
```

---

### Step 3: Create Cloud Scheduler Jobs

```bash
# Run scheduler setup script
./setup_phase3_scheduler.sh

# Verify jobs created
gcloud scheduler jobs list --location=us-central1 | grep phase3
```

**Expected Output:**
```
phase3-historical-nightly    2 0 * * *  America/New_York  Enabled
phase3-team-context-morning  0 6 * * *  America/New_York  Enabled
phase3-team-context-midday   0 12 * * * America/New_York  Enabled
phase3-team-context-pregame  0 17 * * * America/New_York  Enabled
phase3-player-context-morning  30 6 * * *  America/New_York  Enabled
phase3-player-context-pregame  0 18 * * *  America/New_York  Enabled
```

---

### Step 4: Test Manual Triggers

```bash
# Test historical processor
gcloud scheduler jobs run phase3-historical-nightly --location=us-central1

# Wait 30 seconds, check BigQuery
bq query --use_legacy_sql=false "
SELECT COUNT(*) as rows
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = CURRENT_DATE() - 1
"

# Test upcoming context
gcloud scheduler jobs run phase3-team-context-morning --location=us-central1

# Wait 30 seconds, check BigQuery
bq query --use_legacy_sql=false "
SELECT COUNT(*) as rows
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date = CURRENT_DATE()
"
```

---

### Step 5: Monitor First Runs

**Next Morning (after 2:30 AM):**
```bash
# Check historical processors ran
gcloud run jobs executions list \
  --job=phase3-player-game-summary \
  --region=us-central1 \
  --limit=5
```

**Query BigQuery for results:**
```sql
-- Overall status check
SELECT
  'player_game_summary' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'upcoming_team_game_context',
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE();
```

---

## Related Documentation

**Operations:**
- `02-phase3-operations-guide.md` - Processor specifications and success criteria

**Troubleshooting:**
- `04-phase3-troubleshooting.md` - Failure recovery and manual trigger procedures

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub testing

**Phase 1 Comparison:**
- `docs/orchestration/01-how-it-works.md` - Phase 1 scheduler (different approach)

---

**Last Updated:** 2025-11-15 14:45 PST
**Status:** 🚧 Draft (awaiting deployment)
**Next Review:** After Phase 3 deployment
