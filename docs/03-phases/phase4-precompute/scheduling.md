# Phase 4 Scheduling Strategy

**File:** `docs/processors/06-phase4-scheduling-strategy.md`
**Created:** 2025-11-15 15:45 PST
**Last Updated:** 2025-11-25
**Purpose:** Cloud Scheduler and dependency orchestration for Phase 4 precompute processors
**Status:** ✅ Deployed & operational
**Audience:** Engineers deploying Phase 4 orchestration infrastructure

**Related Docs:**
- **Operations:** See `05-phase4-operations-guide.md` for processor specifications
- **Troubleshooting:** See `07-phase4-troubleshooting.md` for failure recovery
- **ML Feature Store:** See `08-phase4-ml-feature-store-deepdive.md` for 4-way dependency details
- **Phase 3 Comparison:** See `03-phase3-scheduling-strategy.md` for simpler orchestration

---

## Table of Contents

1. [Overview](#overview)
2. [The 4-Way Dependency Challenge](#four-way-dependency)
3. [Dependency Management Strategies](#dependency-strategies)
4. [Pub/Sub Topic Configuration](#pubsub-topic-configuration)
5. [Cloud Scheduler Configuration](#cloud-scheduler-configuration)
6. [Deployment Steps](#deployment-steps)

---

## Overview

### Scheduling Approach

Phase 4 uses **sequential with parallelization** strategy:

**Time-Based Start (Cloud Scheduler):**
- Single trigger at 11:00 PM ET (phase4-start)
- Starts P1 + P2 in parallel
- Predictable, easy to monitor

**Event-Driven Continuation (Pub/Sub):**
- P1 + P2 completion triggers P3 + P4
- P3 + P4 completion triggers P5
- Adapts to variable processing times
- More responsive than fixed delays

### Complexity vs Phase 3

**Phase 3:**
- Simple: 2 parallel sets + 2 sequential
- Max 2-way dependency (team + player context)
- 3 Cloud Scheduler jobs

**Phase 4:**
- Complex: 3 dependency levels with parallelization
- **4-way dependency** (P5 waits for ALL 4 upstream)
- Multi-dependency triggers (P3 waits for P1 AND P2)
- 1 Cloud Scheduler job + complex Pub/Sub orchestration

### Recommended Implementation Path

**Phase 1 (Week 1-2): Time-Based with Validation**
- Use Cloud Scheduler with staggered times
- Add dependency checks at processor start
- Simplest to set up and debug

**Phase 2 (Week 3-4): Hybrid (Time + Events)**
- Keep time-based start (11 PM)
- Add Pub/Sub for P3/P4 triggers
- Cloud Function for P5 (wait for all 4)

**Phase 3 (Month 2+): Cloud Workflows**
- Full orchestration via Workflows
- Native dependency management
- Best long-term solution

---

## The 4-Way Dependency Challenge

### The Problem

**ML Feature Store (P5) waits for ALL 4 upstream processors:**

```
P1: team_defense_zone_analysis
P2: player_shot_zone_analysis
P3: player_composite_factors
P4: player_daily_cache
        ↓
   ALL 4 must complete
        ↓
P5: ml_feature_store_v2
```

**Challenges:**
- Events may arrive in any order
- Events may be duplicated (retries)
- Events may be delayed (slow processors)
- One event may never arrive (processor failed)
- Need atomic "all complete" check

### Dependency Graph

```
┌─────────────────────────────────────────────────────────────┐
│                    phase4-start (11 PM)                     │
│                            │                                 │
│            ┌───────────────┴───────────────┐                │
│            ↓                               ↓                 │
│  ┌──────────────────┐          ┌──────────────────┐        │
│  │ P1: team_defense │          │ P2: player_shot  │        │
│  │    (2 min)       │          │    (8 min)       │        │
│  └──────────────────┘          └──────────────────┘        │
│            │                               │                 │
│            │ team-defense-complete         │ player-shot-   │
│            │                               │ zone-complete   │
│            └───────────────┬───────────────┘                │
│                            ↓                                 │
│                   DEPENDENCY CHECK                           │
│                 (Wait for BOTH P1 + P2)                     │
│                            │                                 │
│            ┌───────────────┴───────────────┐                │
│            ↓                               ↓                 │
│  ┌──────────────────┐          ┌──────────────────┐        │
│  │ P3: composite    │          │ P4: daily_cache  │        │
│  │    (15 min)      │          │    (10 min)      │        │
│  └──────────────────┘          └──────────────────┘        │
│            │                               │                 │
│            │ composite-complete            │ cache-complete  │
│            └───────────────┬───────────────┘                │
│                            ↓                                 │
│                   DEPENDENCY CHECK                           │
│                (Wait for ALL 4: P1+P2+P3+P4)                │
│                            │                                 │
│                            ↓                                 │
│              ┌──────────────────────────┐                    │
│              │ P5: ml_feature_store_v2  │                    │
│              │        (2 min)           │                    │
│              └──────────────────────────┘                    │
│                            │                                 │
│                            ↓                                 │
│                    phase4-complete                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Dependency Management Strategies

### Strategy 1: Cloud Function with Firestore State (Recommended for Hybrid)

**Architecture:**

```
Each P1-P4 processor → Publishes completion event → Cloud Function
                                                         ↓
                                           Stores in Firestore
                                                         ↓
                                           Checks if all 4 present
                                                         ↓
                                           Triggers P5 if complete
```

**Implementation:**

```python
# Cloud Function: phase4_completion_tracker
# Triggered by: team-defense-complete, player-shot-zone-complete,
#               player-composite-complete, player-daily-cache-complete

import firebase_admin
from firebase_admin import firestore
from google.cloud import pubsub_v1
import json
from datetime import datetime

# Initialize
db = firestore.client()
publisher = pubsub_v1.PublisherClient()

def track_completion(event, context):
    """
    Track Phase 4 processor completions and trigger P5 when all 4 complete.
    """
    # Parse message
    message_data = json.loads(event['data'])
    processor = message_data['processor']
    analysis_date = message_data['analysis_date']
    completed_at = message_data.get('completed_at', datetime.utcnow().isoformat())

    # Firestore document ID: {analysis_date}
    doc_ref = db.collection('phase4_completions').document(analysis_date)

    # Update processor completion status
    doc_ref.set({
        processor: {
            'completed_at': completed_at,
            'status': 'success',
            'rows_processed': message_data.get('rows_processed', 0)
        }
    }, merge=True)

    # Check if all 4 processors complete
    doc = doc_ref.get()
    if not doc.exists:
        print(f"Document {analysis_date} doesn't exist yet")
        return

    completions = doc.to_dict()
    required_processors = [
        'team_defense_zone_analysis',
        'player_shot_zone_analysis',
        'player_composite_factors',
        'player_daily_cache'
    ]

    all_complete = all(proc in completions for proc in required_processors)

    if all_complete:
        print(f"✅ All Phase 4 processors complete for {analysis_date}")

        # Trigger P5
        topic_path = publisher.topic_path('nba-props-platform', 'phase4-ml-feature-store-start')
        message = {
            'processor': 'ml_feature_store_v2',
            'phase': '4',
            'trigger_time': datetime.utcnow().isoformat(),
            'game_date': analysis_date,
            'dependencies_met': {
                'team_defense': True,
                'player_shot_zone': True,
                'player_composite': True,
                'player_daily_cache': True
            }
        }

        publisher.publish(topic_path, json.dumps(message).encode('utf-8'))
        print(f"🚀 Triggered ML Feature Store V2 for {analysis_date}")

        # Mark as triggered (prevent duplicates)
        doc_ref.set({
            'ml_feature_store_triggered': True,
            'triggered_at': datetime.utcnow().isoformat()
        }, merge=True)

    else:
        missing = [p for p in required_processors if p not in completions]
        print(f"⏳ Waiting for: {', '.join(missing)}")
```

**Deployment:**

```bash
# Deploy Cloud Function
gcloud functions deploy phase4_completion_tracker \
  --runtime python39 \
  --trigger-topic team-defense-complete \
  --trigger-topic player-shot-zone-complete \
  --trigger-topic player-composite-complete \
  --trigger-topic player-daily-cache-complete \
  --entry-point track_completion \
  --memory 256MB \
  --timeout 60s \
  --region us-central1 \
  --set-env-vars "GCP_PROJECT_ID=nba-props-platform"
```

**Pros:**
- ✅ Handles out-of-order events
- ✅ Prevents duplicate triggers (check triggered flag)
- ✅ Easy to debug (Firestore shows completion state)
- ✅ Can add timeout logic (alert if not complete after 60 min)

**Cons:**
- ❌ Additional service (Firestore) to maintain
- ❌ More complex than simple Pub/Sub
- ❌ Firestore costs (minimal, but not zero)

---

### Strategy 2: Cloud Workflows (Recommended for Production)

**Architecture:**

```yaml
# workflows/phase4_orchestration.yaml

main:
  steps:
    # Step 1: Trigger parallel set 1 (P1 + P2)
    - parallel_set_1:
        parallel:
          shared: [analysis_date]
          branches:
            - team_defense_branch:
                steps:
                  - call_team_defense:
                      call: http.post
                      args:
                        url: https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/phase4-team-defense:run
                        auth:
                          type: OIDC
                        body:
                          analysis_date: ${analysis_date}
                      result: team_defense_result
                  - log_team_defense:
                      call: sys.log
                      args:
                        text: ${"Team defense complete: " + string(team_defense_result.status)}

            - player_shot_zone_branch:
                steps:
                  - call_player_shot_zone:
                      call: http.post
                      args:
                        url: https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/phase4-player-shot-zone:run
                        auth:
                          type: OIDC
                        body:
                          analysis_date: ${analysis_date}
                      result: shot_zone_result
                  - log_player_shot_zone:
                      call: sys.log
                      args:
                        text: ${"Player shot zone complete: " + string(shot_zone_result.status)}

    # Step 2: P1 + P2 both complete, now trigger P3 + P4 in parallel
    - parallel_set_2:
        parallel:
          shared: [analysis_date]
          branches:
            - player_composite_branch:
                steps:
                  - call_player_composite:
                      call: http.post
                      args:
                        url: https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/phase4-player-composite:run
                        auth:
                          type: OIDC
                        body:
                          game_date: ${analysis_date}
                      result: composite_result

            - player_daily_cache_branch:
                steps:
                  - call_player_daily_cache:
                      call: http.post
                      args:
                        url: https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/phase4-player-daily-cache:run
                        auth:
                          type: OIDC
                        body:
                          cache_date: ${analysis_date}
                      result: cache_result

    # Step 3: All P1-P4 complete, trigger P5 (ML Feature Store)
    - ml_feature_store:
        call: http.post
        args:
          url: https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/phase4-ml-feature-store-v2:run
          auth:
            type: OIDC
          body:
            game_date: ${analysis_date}
            dependencies_met:
              team_defense: true
              player_shot_zone: true
              player_composite: true
              player_daily_cache: true
        result: ml_feature_store_result

    # Step 4: Publish phase4-complete event
    - publish_completion:
        call: googleapis.pubsub.v1.projects.topics.publish
        args:
          topic: projects/nba-props-platform/topics/phase4-complete
          messages:
            - data: ${base64.encode(json.encode({
                "phase": "4",
                "status": "complete",
                "analysis_date": analysis_date,
                "completed_at": text.now()
              }))}

    # Step 5: Return success
    - return_result:
        return:
          status: success
          analysis_date: ${analysis_date}
```

**Deployment:**

```bash
# Deploy Workflow
gcloud workflows deploy phase4-orchestration \
  --source=workflows/phase4_orchestration.yaml \
  --location=us-central1

# Trigger via Cloud Scheduler
gcloud scheduler jobs create http phase4-workflow-trigger \
  --schedule="0 23 * * *" \
  --time-zone="America/New_York" \
  --location=us-central1 \
  --uri="https://workflowexecutions.googleapis.com/v1/projects/nba-props-platform/locations/us-central1/workflows/phase4-orchestration/executions" \
  --http-method=POST \
  --oauth-service-account-email=cloud-scheduler@nba-props-platform.iam.gserviceaccount.com \
  --message-body='{"argument": "{\"analysis_date\": \"'$(date +%Y-%m-%d)'\"}"}'
```

**Pros:**
- ✅ Native GCP service (built for this use case)
- ✅ Visual DAG in console (easy to debug)
- ✅ Built-in retry/error handling
- ✅ Handles parallelization automatically
- ✅ No additional code to maintain

**Cons:**
- ❌ Learning curve (new service)
- ❌ Slightly more expensive than Pub/Sub
- ❌ Less flexible than custom code

---

### Strategy 3: Time-Based with Validation (Simplest)

**Architecture:**

```
11:00 PM → P1 + P2 start (Cloud Scheduler)
11:45 PM → P3 + P4 start (Cloud Scheduler, assumes P1+P2 done)
12:00 AM → P5 starts (Cloud Scheduler, assumes P1-P4 done)
              ↓
         P5 validates all dependencies present before processing
```

**Cloud Scheduler Configuration:**

```bash
# P1 + P2: 11:00 PM (parallel)
gcloud scheduler jobs create http phase4-team-defense \
  --schedule "0 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

gcloud scheduler jobs create http phase4-player-shot-zone \
  --schedule "0 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

# P3 + P4: 11:20 PM (after P1+P2 typically complete)
gcloud scheduler jobs create http phase4-player-composite \
  --schedule "20 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

gcloud scheduler jobs create http phase4-player-daily-cache \
  --schedule "20 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST

# P5: 11:45 PM (after all typically complete)
gcloud scheduler jobs create http phase4-ml-feature-store \
  --schedule "45 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://[CLOUD_RUN_JOB_URL]/trigger" \
  --http-method POST
```

**Dependency Validation (in processor code):**

```python
# In ml_feature_store_processor.py
def check_dependencies(self, analysis_date: date) -> bool:
    """
    Check if ALL 4 Phase 4 processors completed.
    Retry with exponential backoff if not ready.
    """
    team_defense_count = self._query_count(
        f"SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis "
        f"WHERE analysis_date = '{analysis_date}'"
    )

    player_shot_zone_count = self._query_count(
        f"SELECT COUNT(*) FROM nba_precompute.player_shot_zone_analysis "
        f"WHERE analysis_date = '{analysis_date}'"
    )

    player_composite_count = self._query_count(
        f"SELECT COUNT(*) FROM nba_precompute.player_composite_factors "
        f"WHERE game_date = '{analysis_date}'"
    )

    player_daily_cache_count = self._query_count(
        f"SELECT COUNT(*) FROM nba_precompute.player_daily_cache "
        f"WHERE cache_date = '{analysis_date}'"
    )

    if (team_defense_count < 20 or
        player_shot_zone_count < 100 or
        player_composite_count < 100 or
        player_daily_cache_count < 100):

        # Not ready, retry with backoff
        retry_count = self.opts.get('retry_count', 0)
        if retry_count < 3:
            wait_seconds = 2 ** retry_count * 60  # 1, 2, 4 minutes
            logger.warning(f"Dependencies not ready, retrying in {wait_seconds}s")
            time.sleep(wait_seconds)
            self.opts['retry_count'] = retry_count + 1
            return self.check_dependencies(analysis_date)
        else:
            raise ValueError("Phase 4 dependencies not ready after 3 retries")

    return True
```

**Pros:**
- ✅ Simplest to implement (no extra services)
- ✅ Easy to understand (fixed schedule)
- ✅ Self-healing (retry if dependencies not ready)

**Cons:**
- ❌ Fixed timing (doesn't adapt if P1-P4 slow)
- ❌ Potential race conditions
- ❌ More retries = more cost

---

### Recommendation: Hybrid Approach

**Week 1-2 (Initial Launch):** Use Strategy 3 (Time-Based)
- Simpler to debug during launch
- Easier to intervene manually if issues
- Good enough for validation

**Week 3+ (Production Stable):** Migrate to Strategy 2 (Cloud Workflows)
- More robust for long-term operations
- Better handling of variable processing times
- Professional-grade orchestration

**Future (If Needed):** Add Strategy 1 (Cloud Function)
- If Workflows doesn't meet needs
- If need more custom logic
- If need finer-grained control

---

## Pub/Sub Topic Configuration

### Topic Naming Convention

| Topic | Purpose | Publisher | Subscribers |
|-------|---------|-----------|-------------|
| `phase4-start` | Triggers parallel set 1 (P1 + P2) | Cloud Scheduler | P1 + P2 |
| `phase4-team-defense-complete` | P1 completion event | P1 processor | Cloud Function OR P3 |
| `phase4-player-shot-zone-complete` | P2 completion event | P2 processor | Cloud Function OR P3 + P4 |
| `phase4-player-composite-complete` | P3 completion event | P3 processor | Cloud Function |
| `phase4-player-daily-cache-complete` | P4 completion event | P4 processor | Cloud Function |
| `phase4-ml-feature-store-start` | Triggers P5 after all 4 complete | Cloud Function | P5 processor |
| `phase4-complete` | All Phase 4 complete | P5 processor | Phase 5 systems |

### Creating Topics

```bash
#!/bin/bash
# create_phase4_topics.sh

PROJECT_ID="nba-props-platform"

# Create all Phase 4 topics
gcloud pubsub topics create phase4-start --project=$PROJECT_ID
gcloud pubsub topics create phase4-team-defense-complete --project=$PROJECT_ID
gcloud pubsub topics create phase4-player-shot-zone-complete --project=$PROJECT_ID
gcloud pubsub topics create phase4-player-composite-complete --project=$PROJECT_ID
gcloud pubsub topics create phase4-player-daily-cache-complete --project=$PROJECT_ID
gcloud pubsub topics create phase4-ml-feature-store-start --project=$PROJECT_ID
gcloud pubsub topics create phase4-complete --project=$PROJECT_ID

# Create dead letter queues
gcloud pubsub topics create phase4-team-defense-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase4-player-shot-zone-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase4-player-composite-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase4-player-daily-cache-dlq --project=$PROJECT_ID
gcloud pubsub topics create phase4-ml-feature-store-dlq --project=$PROJECT_ID

echo "✅ All Phase 4 Pub/Sub topics created"
```

### Creating Subscriptions

```bash
#!/bin/bash
# create_phase4_subscriptions.sh

PROJECT_ID="nba-props-platform"

# P1: Team defense
gcloud pubsub subscriptions create phase4-team-defense-sub \
  --topic phase4-start \
  --ack-deadline 600 \
  --message-retention-duration 1h \
  --dead-letter-topic phase4-team-defense-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

# P2: Player shot zones
gcloud pubsub subscriptions create phase4-player-shot-zone-sub \
  --topic phase4-start \
  --ack-deadline 1200 \
  --message-retention-duration 1h \
  --dead-letter-topic phase4-player-shot-zone-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

# P3: Player composite (if using Pub/Sub trigger, not Cloud Function)
gcloud pubsub subscriptions create phase4-player-composite-sub \
  --topic phase4-team-defense-complete \
  --ack-deadline 1500 \
  --message-retention-duration 1h \
  --dead-letter-topic phase4-player-composite-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

# P4: Player daily cache
gcloud pubsub subscriptions create phase4-player-daily-cache-sub \
  --topic phase4-player-shot-zone-complete \
  --ack-deadline 1200 \
  --message-retention-duration 1h \
  --dead-letter-topic phase4-player-daily-cache-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

# P5: ML feature store (if using Pub/Sub trigger, not Cloud Function)
gcloud pubsub subscriptions create phase4-ml-feature-store-sub \
  --topic phase4-ml-feature-store-start \
  --ack-deadline 600 \
  --message-retention-duration 1h \
  --dead-letter-topic phase4-ml-feature-store-dlq \
  --max-delivery-attempts 3 \
  --project=$PROJECT_ID

echo "✅ All Phase 4 Pub/Sub subscriptions created"
```

---

## Cloud Scheduler Configuration

### Primary Trigger (11:00 PM ET)

```bash
#!/bin/bash
# Create Cloud Scheduler job for Phase 4 start

gcloud scheduler jobs create pubsub phase4-nightly-trigger \
  --schedule "0 23 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic phase4-start \
  --message-body '{
    "processor": "phase4_start",
    "phase": "4",
    "analysis_date": "'$(date +%Y-%m-%d)'"
  }' \
  --project=nba-props-platform

echo "✅ Phase 4 Cloud Scheduler job created"
```

**Verify:**

```bash
# List scheduler jobs
gcloud scheduler jobs list --location=us-central1 | grep phase4

# Test manual trigger
gcloud scheduler jobs run phase4-nightly-trigger --location=us-central1
```

---

## Deployment Steps

### Step 1: Create Pub/Sub Infrastructure

```bash
# Run topic creation script
./create_phase4_topics.sh

# Verify topics created
gcloud pubsub topics list --project=nba-props-platform | grep phase4

# Run subscription creation script
./create_phase4_subscriptions.sh

# Verify subscriptions created
gcloud pubsub subscriptions list --project=nba-props-platform | grep phase4
```

---

### Step 2: Deploy Cloud Run Jobs

**Note:** This assumes you have Docker images built for each processor.

```bash
#!/bin/bash
# deploy_phase4_processors.sh

PROJECT_ID="nba-props-platform"
REGION="us-central1"

# P1: Team defense
gcloud run jobs create phase4-team-defense-zone-analysis \
  --image gcr.io/$PROJECT_ID/team-defense-zone-analysis:latest \
  --region $REGION \
  --memory 1Gi \
  --cpu 1 \
  --timeout 10m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# P2: Player shot zones
gcloud run jobs create phase4-player-shot-zone-analysis \
  --image gcr.io/$PROJECT_ID/player-shot-zone-analysis:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 20m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# P3: Player composite
gcloud run jobs create phase4-player-composite-factors \
  --image gcr.io/$PROJECT_ID/player-composite-factors:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 25m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# P4: Player daily cache
gcloud run jobs create phase4-player-daily-cache \
  --image gcr.io/$PROJECT_ID/player-daily-cache:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 20m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

# P5: ML feature store
gcloud run jobs create phase4-ml-feature-store-v2 \
  --image gcr.io/$PROJECT_ID/ml-feature-store-v2:latest \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 10m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
  --project=$PROJECT_ID

echo "✅ All Phase 4 Cloud Run jobs deployed"
```

---

### Step 3: Deploy Dependency Management (Choose One)

**Option A: Cloud Function (for Hybrid approach)**

```bash
# Deploy completion tracker function
gcloud functions deploy phase4_completion_tracker \
  --runtime python39 \
  --trigger-topic team-defense-complete \
  --trigger-topic player-shot-zone-complete \
  --trigger-topic player-composite-complete \
  --trigger-topic player-daily-cache-complete \
  --entry-point track_completion \
  --memory 256MB \
  --timeout 60s \
  --region us-central1 \
  --set-env-vars "GCP_PROJECT_ID=nba-props-platform"
```

**Option B: Cloud Workflows (for Production)**

```bash
# Deploy workflow
gcloud workflows deploy phase4-orchestration \
  --source=workflows/phase4_orchestration.yaml \
  --location=us-central1
```

**Option C: Time-Based (for Initial Launch)**

```bash
# Create staggered Cloud Scheduler jobs (see Strategy 3 above)
# No additional deployment needed beyond Step 2
```

---

### Step 4: Create Cloud Scheduler Job

```bash
# Create nightly trigger (11 PM)
gcloud scheduler jobs create pubsub phase4-nightly-trigger \
  --schedule "0 23 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --topic phase4-start \
  --message-body '{"processor":"phase4_start","phase":"4","analysis_date":"'$(date +%Y-%m-%d)'"}' \
  --project=nba-props-platform

# Verify job created
gcloud scheduler jobs list --location=us-central1 | grep phase4
```

---

### Step 5: Test End-to-End

```bash
# Test manual trigger
gcloud scheduler jobs run phase4-nightly-trigger --location=us-central1

# Monitor progress
watch -n 5 'gcloud run jobs executions list --job=phase4-team-defense-zone-analysis --region=us-central1 --limit=1'

# Check results after ~30 min
bq query --use_legacy_sql=false "
SELECT
  'team_defense' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()
-- Repeat for all 5 processors
"
```

---

## Related Documentation

**Operations:**
- `05-phase4-operations-guide.md` - Processor specifications and success criteria

**Troubleshooting:**
- `07-phase4-troubleshooting.md` - Failure recovery and manual triggers

**ML Feature Store:**
- `08-phase4-ml-feature-store-deepdive.md` - 4-way dependency deep-dive

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub testing

---

**Last Updated:** 2025-11-15 15:45 PST
**Status:** 🚧 Draft (awaiting deployment)
**Next Review:** After Phase 4 deployment
