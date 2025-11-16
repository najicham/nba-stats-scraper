# Phase 5 Deployment Guide - Complete

**File:** `docs/predictions/operations/01-deployment-guide.md`
**Created:** 2025-11-09 14:30 PST
**Last Updated:** 2025-11-15 19:45 PST
**Purpose:** Complete deployment guide for Phase 5 prediction system - coordinator, worker, ML models, monitoring
**Status:** ✅ Production Ready - Comprehensive deployment reference

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture Pattern](#architecture-pattern)
3. [Coordinator Service](#coordinator-service)
4. [Worker Service](#worker-service)
5. [ML Model Deployment](#ml-models)
6. [Pub/Sub Topics](#pubsub-topics)
7. [Daily Processing Scale](#daily-scale)
8. [Cost Analysis & Optimization](#cost-analysis)
9. [Critical Dependencies](#dependencies)
10. [Success Criteria](#success-criteria)
11. [Complete Deployment Guide](#deployment-guide)
12. [Monitoring & Alerting](#monitoring)
13. [Related Documentation](#related-docs)

---

## 🎯 Overview {#overview}

### Phase 5 Mission

Generate accurate NBA player points predictions for ~450 players daily using 5 prediction systems:
- **Moving Average** - Simple baseline using recent averages
- **Zone Matchup** - Shot zone analysis vs opponent defense
- **Similarity** - Similar games pattern matching
- **XGBoost** - Machine learning model
- **Ensemble** - Weighted combination of all systems

Predictions generated at multiple prop lines (±2 points from opening) to cover typical line movement.

### Timing Window

| Attribute | Value |
|-----------|-------|
| **Start** | 6:15 AM ET (after Phase 4 features cached) |
| **End** | 6:20 AM ET (target), 6:30 AM ET (hard deadline) |
| **Duration** | 2-5 minutes (with parallelization) |
| **Critical Deadline** | Website must have predictions by 6:30 AM ET |

### Execution Strategy

- **Coordinator-Worker Pattern:** Single coordinator fans out to auto-scaling workers
- **Event-Driven:** Pub/Sub messaging for scalability and fault tolerance
- **Parallel Processing:** 20 workers × 5 threads = 100 concurrent player predictions
- **Multiple Lines:** Generate 5 line predictions per player (testing mode) or 1 line (production)
- **Dependency Validation:** Check Phase 4 completion before starting

---

## 🏗️ Architecture Pattern {#architecture-pattern}

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 5 ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────┘

              Cloud Scheduler (6:15 AM daily)
                          ↓
            ┌─────────────────────────┐
            │   COORDINATOR           │
            │  (Cloud Run Job)        │
            │                         │
            │  1. Check Phase 4       │
            │  2. Query players       │
            │  3. Query lines         │
            │  4. Fan out work        │
            └─────────────────────────┘
                          ↓
            Pub/Sub: "prediction-request"
            (450 messages, one per player)
                          ↓
      ┌───────────────────┴───────────────────┐
      ↓                                       ↓
┌─────────────────┐                  ┌─────────────────┐
│  WORKER 1-20    │       ...        │  WORKER 1-20    │
│ (Cloud Run)     │                  │ (Cloud Run)     │
│                 │                  │                 │
│ 5 threads each  │                  │ 5 threads each  │
│ Process players │                  │ Process players │
│ in parallel     │                  │ in parallel     │
└─────────────────┘                  └─────────────────┘
      ↓                                       ↓
      └───────────────────┬───────────────────┘
                          ↓
            BigQuery: player_prop_predictions
            (11,250 predictions written)
                          ↓
            Pub/Sub: "prediction-ready"
                          ↓
                  Phase 6 Publishing
```

---

## 📡 Coordinator Service {#coordinator-service}

### Service Overview

| Attribute | Value |
|-----------|-------|
| **Cloud Run Job Name** | `phase5-prediction-coordinator` |
| **Trigger Type** | Cloud Scheduler (scheduled HTTP trigger) |
| **Trigger Schedule** | 6:15 AM ET daily |
| **Expected Duration** | 1-2 minutes (typical) |
| **Max Duration** | 10 minutes (timeout alert) |

### Trigger Payload

```json
{
  "processor": "prediction_coordinator",
  "phase": "5",
  "trigger_time": "2025-11-07T06:15:00Z",
  "game_date": "2025-11-07"
}
```

### Dependencies

| Type | Description |
|------|-------------|
| **Upstream (CRITICAL)** | Phase 4: `ml_feature_store_v2` (MUST have features ready) |
| **Upstream (CRITICAL)** | Phase 3: `upcoming_player_game_context` (player schedule) |
| **Upstream (Important)** | Phase 2: `player_props` (opening prop lines) |
| **Downstream** | Workers: Fans out to 20 worker instances |

### Processing Details

| Attribute | Value |
|-----------|-------|
| **Volume** | 450 players with games today |
| **Strategy** | Query players → Query lines → Calculate spreads → Publish 450 messages |
| **Output** | 450 Pub/Sub messages (one per player) |
| **Concurrency** | Single instance (orchestrator pattern) |

### Cloud Run Configuration

```bash
gcloud run jobs create phase5-prediction-coordinator \
  --image gcr.io/nba-props-platform/prediction-coordinator:latest \
  --region us-central1 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 10m \
  --max-retries 2 \
  --set-env-vars "GCP_PROJECT_ID=nba-props-platform,GAME_DATE={{GAME_DATE}}" \
  --execute-now
```

### Environment Variables

```bash
GCP_PROJECT_ID=nba-props-platform
BIGQUERY_DATASET=nba_predictions
PUBSUB_TOPIC=prediction-request
FEATURE_VERSION=v1_baseline_25
PRIMARY_BOOKMAKER=draftkings
LINE_SPREAD_RANGE=2.0  # ±2.0 from opening line
```

### Success Criteria

```sql
-- Verify coordinator published messages
SELECT
  COUNT(DISTINCT player_lookup) as players_queued,
  COUNT(*) as total_messages
FROM `nba-props-platform.nba_logs.pubsub_messages`
WHERE topic_name = 'prediction-request'
  AND DATE(publish_time) = CURRENT_DATE()
  AND publish_time >= TIMESTAMP('06:15:00');

-- Expected: ~450 players, 450 messages
```

### On Success
- **Action:** Publish 450 "prediction-request" messages to Pub/Sub
- **Duration:** ~30 seconds for fanout

### On Failure

| Action | Details |
|--------|---------|
| **Retry** | Up to 2 times (3 total attempts) |
| **Alert** | Slack + PagerDuty if all retries fail |
| **Block** | ALL Phase 5 prediction generation (no workers start) |
| **Impact** | 🔴 CRITICAL - No predictions for the day |
| **Timeout** | 10 minutes (kill job, send to DLQ) |

### Coordinator Output Format

Pub/Sub Message (One per Player):

```json
{
  "player_lookup": "lebron-james",
  "game_id": "20251107_LAL_GSW",
  "game_date": "2025-11-07",
  "opening_line": 25.5,
  "line_values": [23.5, 24.5, 25.5, 26.5, 27.5],
  "opponent_team_abbr": "GSW",
  "is_home": true,
  "feature_version": "v1_baseline_25"
}
```

---

## 👷 Worker Service {#worker-service}

### Service Overview

| Attribute | Value |
|-----------|-------|
| **Cloud Run Service Name** | `phase5-prediction-worker` |
| **Trigger Type** | Pub/Sub push subscription |
| **Trigger Topic** | `prediction-request` |
| **Expected Duration** | ~10 seconds per player |
| **Cold Start** | +30 seconds (first instance) |
| **Total Duration** | 2-5 minutes (450 players with 100 concurrent) |

### Dependencies

| Type | Description |
|------|-------------|
| **Upstream (CRITICAL)** | Coordinator: Receives "prediction-request" messages |
| **Upstream (CRITICAL)** | Phase 4: Reads `ml_feature_store_v2` for features |
| **Downstream** | BigQuery: Writes to `player_prop_predictions` |
| **Downstream** | Pub/Sub: Publishes "prediction-ready" events |

### Processing Details

| Attribute | Value |
|-----------|-------|
| **Volume** | 1 player per message |
| **Concurrency** | 5 threads per worker instance |
| **Auto-Scaling** | 0 → 20 instances based on queue depth |
| **Strategy** | Read features → Generate 25 predictions → Batch write |
| **Output** | 25 predictions per player (5 lines × 5 systems) |

### Cloud Run Configuration

```bash
gcloud run services create phase5-prediction-worker \
  --image gcr.io/nba-props-platform/prediction-worker:latest \
  --region us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 600s \
  --min-instances 0 \
  --max-instances 20 \
  --concurrency 5 \
  --set-env-vars "GCP_PROJECT_ID=nba-props-platform,THREAD_POOL_SIZE=5,FEATURE_VERSION=v1_baseline_25" \
  --no-allow-unauthenticated
```

### Key Configuration Rationale

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **memory** | 2Gi | XGBoost model + 5 threads |
| **cpu** | 2 | Parallel processing |
| **timeout** | 600s | 10 minutes per request (generous) |
| **min-instances** | 0 | Scale to zero when idle |
| **max-instances** | 20 | Max 20 workers |
| **concurrency** | 5 | 5 threads per worker (Cloud Run native) |

### Environment Variables

```bash
GCP_PROJECT_ID=nba-props-platform
THREAD_POOL_SIZE=5
BIGQUERY_PROJECT=nba-props-platform
PREDICTIONS_TABLE=nba_predictions.player_prop_predictions
FEATURE_VERSION=v1_baseline_25
ML_MODEL_PATH=gs://nba-props-models/xgboost/v1/model.pkl
```

### Pub/Sub Subscription

```bash
gcloud pubsub subscriptions create phase5-prediction-worker-sub \
  --topic prediction-request \
  --ack-deadline 600 \
  --message-retention-duration 1h \
  --dead-letter-topic prediction-worker-dlq \
  --max-delivery-attempts 3 \
  --push-endpoint https://prediction-worker-xxx.run.app/predict \
  --push-auth-service-account prediction-worker@nba-props-platform.iam.gserviceaccount.com
```

### Key Subscription Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **ack-deadline** | 600s | 10 minutes (match Cloud Run timeout) |
| **message-retention-duration** | 1h | Keep unprocessed messages for 1 hour |
| **max-delivery-attempts** | 3 | Retry failed messages 3 times |
| **push-endpoint** | Cloud Run worker URL | HTTP push to worker |

### Success Criteria

```sql
-- Verify workers wrote predictions for all players
SELECT
  COUNT(DISTINCT player_lookup) as players_with_predictions,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as systems_run
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND created_at >= TIMESTAMP('06:15:00');

-- Expected: 450 players, 11,250 predictions (450 × 5 lines × 5 systems), 5 systems
```

### On Success
- **Action:** Write 25 predictions per player to BigQuery
- **Action:** Publish "prediction-ready" event
- **Duration:** ~10 seconds per player

### On Failure

| Action | Details |
|--------|---------|
| **Retry** | Up to 3 times via Pub/Sub (automatic) |
| **Alert** | Slack if >10 players fail |
| **Impact** | 🟡 Partial failure acceptable (449/450 OK) |
| **Recovery** | Pub/Sub redelivers failed messages to other workers |
| **DLQ** | Failed messages move to dead letter queue after 3 attempts |
| **Timeout** | 10 minutes (Cloud Run kills long-running requests) |

### Worker Scaling Behavior

Auto-Scaling Logic:
```
Pub/Sub Queue Depth → Cloud Run Scaling
─────────────────────────────────────────
0 messages         → 0 instances (scale to zero)
1-5 messages       → 1 instance
6-50 messages      → 2-10 instances
51-100 messages    → 11-20 instances
100+ messages      → 20 instances (max)
```

Expected Scaling Pattern (6:16 AM):
```
6:16:00 - Coordinator publishes 450 messages
6:16:05 - Cloud Run scales: 0 → 5 instances (cold start)
6:16:30 - Cloud Run scales: 5 → 20 instances (full scale)
6:17:00 - Workers processing 100 players concurrently (20 × 5 threads)
6:18:00 - Queue depth: 350 → 250 → 150
6:19:00 - Queue depth: 150 → 50 → 0
6:19:30 - Workers complete last players
6:20:00 - Cloud Run scales: 20 → 0 instances (scale down)
```

---

## 🤖 ML Model Deployment {#ml-models}

### Model Overview

Phase 5 uses one primary ML model (XGBoost) with weekly retraining:

| Model | Purpose | Size | Load Time | Update Frequency |
|-------|---------|------|-----------|------------------|
| **XGBoost V1** | Player points prediction | ~5-10 MB | 2-3 seconds | Weekly (Monday 2 AM) |
| Moving Average | Baseline (rule-based, no model file) | N/A | Instant | N/A |
| Zone Matchup | Matchup analysis (rule-based) | N/A | Instant | N/A |
| Similarity | Pattern matching (rule-based) | N/A | Instant | N/A |
| Ensemble | Combination logic (rule-based) | N/A | Instant | N/A |

**Note:** Only XGBoost requires model file deployment. Other systems are rule-based.

---

### GCS Model Storage Structure

**Production bucket:** `gs://nba-models-production/`

```
gs://nba-models-production/
├── xgboost/
│   ├── v1.0_2024-11-15/               # Week 1 model
│   │   ├── model.json                 # XGBoost model file (5 MB)
│   │   ├── metadata.json              # Training stats, feature importance
│   │   ├── evaluation.json            # Validation metrics (MAE, R²)
│   │   └── training_log.txt           # Training configuration
│   │
│   ├── v1.1_2024-11-22/               # Week 2 retrain
│   │   ├── model.json
│   │   ├── metadata.json
│   │   ├── evaluation.json
│   │   └── training_log.txt
│   │
│   ├── v1.2_2024-11-29/               # Week 3 retrain
│   │   └── ... (same structure)
│   │
│   └── current -> v1.2_2024-11-29/    # Symlink to active model
│
└── mock/
    └── xgboost_mock_v1.json           # Mock model for testing
```

**IAM Permissions:**
```bash
# Grant worker service account read access to models
gsutil iam ch \
  serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com:objectViewer \
  gs://nba-models-production
```

---

### Model Metadata Format

**File:** `metadata.json` (stored with each model)

```json
{
  "model_version": "v1.2_2024-11-29",
  "model_type": "xgboost",
  "created_at": "2024-11-29T02:15:30Z",
  "training_data": {
    "start_date": "2022-10-01",
    "end_date": "2024-11-25",
    "total_games": 75382,
    "players": 450,
    "seasons": ["2022-23", "2023-24", "2024-25"]
  },
  "features": {
    "count": 25,
    "version": "v1_baseline_25",
    "feature_names": [
      "points_avg_last_5",
      "points_avg_last_10",
      "points_avg_season",
      "points_std_last_10",
      "minutes_avg_last_10",
      "fatigue_score",
      "shot_zone_mismatch_score",
      "pace_score",
      "usage_spike_score",
      "opponent_def_rating_last_15",
      "opponent_pace_last_15",
      "is_home",
      "days_rest",
      "back_to_back",
      "paint_rate_last_10",
      "mid_range_rate_last_10",
      "three_pt_rate_last_10",
      "assisted_rate_last_10",
      "team_pace_last_10",
      "team_off_rating_last_10",
      "usage_rate_last_10"
    ]
  },
  "performance": {
    "validation_mae": 3.2,
    "validation_r2": 0.72,
    "calibration_80pct": 4.1,
    "training_time_minutes": 12
  },
  "hyperparameters": {
    "max_depth": 6,
    "learning_rate": 0.1,
    "n_estimators": 100,
    "subsample": 0.8,
    "colsample_bytree": 0.8
  },
  "feature_importance": {
    "points_avg_last_5": 0.25,
    "points_avg_season": 0.18,
    "opponent_def_rating_last_15": 0.12,
    "fatigue_score": 0.08,
    "usage_rate_last_10": 0.07
    // ... top 5 shown
  }
}
```

---

### Model Loading Strategies

**Strategy 1: Startup Loading (Recommended)**

Load model once at worker startup (cold start), reuse across all requests.

**Pros:**
- Fast predictions (~5-10ms per player)
- No per-request latency
- Efficient memory usage

**Cons:**
- +30 second cold start time
- Model stays in memory (~5-10 MB per worker)

**Implementation:** `predictions/worker/worker.py:82-96`

```python
# Worker initialization (runs once at startup)
logger.info("Initializing prediction systems...")

# Load XGBoost model from GCS at startup
xgboost = XGBoostV1(model_path=os.environ.get('XGBOOST_MODEL_PATH'))

# Initialize other systems (no model files needed)
moving_average = MovingAverageBaseline()
zone_matchup = ZoneMatchupV1()
similarity = SimilarityBalancedV1()

# Initialize ensemble with base systems
ensemble = EnsembleV1(
    moving_average_system=moving_average,
    zone_matchup_system=zone_matchup,
    similarity_system=similarity,
    xgboost_system=xgboost
)

logger.info("All prediction systems initialized successfully")
```

**Strategy 2: On-Demand Loading (Not Recommended)**

Load model per request or lazily on first use.

**Pros:**
- Faster cold start (~5 seconds)

**Cons:**
- Slow first prediction (+3 seconds)
- Wasted time on every request if not cached properly

---

### Model Versioning & Registry

**Version Naming Convention:**
```
v{major}.{minor}_{date}

Examples:
- v1.0_2024-11-15  # Initial production model
- v1.1_2024-11-22  # Weekly retrain (same features)
- v2.0_2024-12-01  # Major update (new features: 25 → 47)
```

**Deployment Process:**

```bash
# 1. Train new model (weekly Monday 2 AM)
python predictions/training/train_xgboost.py \
    --training-data gs://nba-training-data/xgboost/training_latest.parquet \
    --output-model gs://nba-models-production/xgboost/v1.2_2024-11-29/model.json \
    --output-metadata gs://nba-models-production/xgboost/v1.2_2024-11-29/metadata.json

# 2. Validate model performance
python predictions/training/evaluate_model.py \
    --model gs://nba-models-production/xgboost/v1.2_2024-11-29/model.json \
    --validation-data gs://nba-training-data/xgboost/validation_latest.parquet \
    --threshold-mae 3.5

# 3. If validation passes, update "current" symlink
gsutil -m rm -r gs://nba-models-production/xgboost/current
gsutil -m cp -r gs://nba-models-production/xgboost/v1.2_2024-11-29 \
    gs://nba-models-production/xgboost/current

# 4. Update worker environment variable (triggers rolling restart)
gcloud run services update phase5-prediction-worker \
    --update-env-vars XGBOOST_MODEL_PATH=gs://nba-models-production/xgboost/v1.2_2024-11-29/model.json
```

**Automatic Rollback:**
```bash
# If new model performs poorly, rollback to previous version
gcloud run services update phase5-prediction-worker \
    --update-env-vars XGBOOST_MODEL_PATH=gs://nba-models-production/xgboost/v1.1_2024-11-22/model.json
```

---

### Weekly Retraining Process

**Schedule:** Monday 2:00 AM ET (during NBA off-day window)

**Automated Workflow:**

```
Monday 2:00 AM - Extract training data
  ├─ Query last 7 days: predictions + actual results
  ├─ Append to training dataset (incremental)
  └─ Save: gs://nba-training-data/xgboost/training_latest.parquet

Monday 2:05 AM - Train new model
  ├─ Load training data (3 seasons + last 90 days)
  ├─ Train XGBoost model (~10-15 minutes)
  └─ Save model + metadata to GCS

Monday 2:20 AM - Validate model
  ├─ Run on holdout set (last 2 weeks)
  ├─ Calculate MAE, R², calibration
  └─ Compare to current production model

Monday 2:25 AM - Deploy or reject
  ├─ If MAE < 3.5 points: Deploy new model
  │   └─ Update worker environment variable
  ├─ If MAE >= 3.5 points: Keep current model
  │   └─ Alert team for investigation
  └─ Log decision to monitoring dashboard

Monday 2:30 AM - Verify deployment
  ├─ Check worker logs for successful model load
  ├─ Run test predictions on 10 sample players
  └─ Monitor first hour of production predictions
```

**Cloud Scheduler Configuration:**

```bash
gcloud scheduler jobs create http xgboost-weekly-retrain \
    --schedule "0 2 * * 1" \
    --time-zone "America/New_York" \
    --uri "https://training-service-xxx.run.app/train-xgboost" \
    --http-method POST \
    --oidc-service-account-email training-service@nba-props-platform.iam.gserviceaccount.com \
    --message-body '{
      "model_type": "xgboost",
      "feature_version": "v1_baseline_25",
      "auto_deploy": true,
      "mae_threshold": 3.5
    }'
```

---

### Code Example: Model Loading in Worker

**File:** `predictions/worker/prediction_systems/xgboost_v1.py:204-249`

```python
def _load_model_from_gcs(self, model_path: str):
    """
    Load trained XGBoost model from Google Cloud Storage

    Args:
        model_path: GCS path (e.g., 'gs://bucket/models/xgboost_v1.json')

    Returns:
        Loaded XGBoost model
    """
    try:
        import xgboost as xgb
        from google.cloud import storage

        # Parse GCS path: gs://bucket/path/model.json
        if model_path.startswith('gs://'):
            parts = model_path.replace('gs://', '').split('/', 1)
            bucket_name = parts[0]
            blob_path = parts[1]
        else:
            raise ValueError(f"Invalid GCS path: {model_path}")

        # Download from GCS
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        # Save to local temp file
        local_path = '/tmp/xgboost_model.json'
        blob.download_to_filename(local_path)

        logger.info(f"Downloaded model from {model_path} to {local_path}")

        # Load model
        model = xgb.Booster()
        model.load_model(local_path)

        logger.info(f"Loaded XGBoost model successfully")
        return model

    except Exception as e:
        logger.error(f"Failed to load model from GCS: {e}")
        logger.warning("Falling back to mock model for testing")

        from predictions.shared.mock_xgboost_model import load_mock_model
        return load_mock_model(seed=42)
```

**Environment Variables for Worker:**

```bash
# Required
XGBOOST_MODEL_PATH=gs://nba-models-production/xgboost/v1.2_2024-11-29/model.json

# Optional (fallback to mock if not set)
XGBOOST_FALLBACK_TO_MOCK=true  # Use mock model if GCS load fails
```

---

### Mock Model for Testing

**Purpose:** Test deployment without trained model

**Location:** `gs://nba-models-production/mock/xgboost_mock_v1.json`

**Usage:**

```bash
# Deploy worker with mock model for testing
gcloud run services update phase5-prediction-worker \
    --update-env-vars XGBOOST_MODEL_PATH=gs://nba-models-production/mock/xgboost_mock_v1.json
```

**Mock Model Behavior:**
- Uses simple formula: `prediction = points_avg_season * (0.95 + random(0.1))`
- Adds realistic variance based on opponent defense
- Returns confidence = 70% for all predictions
- Marked with `model_type: 'mock'` in output

---

## 📨 Pub/Sub Topics {#pubsub-topics}

### Topic Naming Convention

| Topic | Purpose | Publisher | Subscriber |
|-------|---------|-----------|------------|
| `prediction-request` | Worker job requests | Coordinator | Workers (20 instances) |
| `prediction-ready` | Prediction completion events | Workers | Phase 6 Publishing |
| `prediction-worker-dlq` | Failed worker messages | Pub/Sub | Manual recovery |
| `precompute-complete` | Phase 4 completion (informational) | Phase 4 | (None - logging only) |

### Creating Topics

```bash
# Create all Phase 5 topics
gcloud pubsub topics create prediction-request
gcloud pubsub topics create prediction-ready
gcloud pubsub topics create prediction-worker-dlq

# Set IAM permissions
gcloud pubsub topics add-iam-policy-binding prediction-request \
  --member=serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher

gcloud pubsub topics add-iam-policy-binding prediction-request \
  --member=serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/pubsub.subscriber

gcloud pubsub topics add-iam-policy-binding prediction-ready \
  --member=serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher
```

### Event Payload Structures

**Event 1: "prediction-request" (Coordinator → Workers)**

```json
{
  "player_lookup": "lebron-james",
  "game_id": "20251107_LAL_GSW",
  "game_date": "2025-11-07",
  "opening_line": 25.5,
  "line_values": [23.5, 24.5, 25.5, 26.5, 27.5],
  "opponent_team_abbr": "GSW",
  "is_home": true,
  "feature_version": "v1_baseline_25",
  "retry_count": 0
}
```

**Event 2: "prediction-ready" (Workers → Phase 6)**

```json
{
  "player_lookup": "lebron-james",
  "game_id": "20251107_LAL_GSW",
  "game_date": "2025-11-07",
  "predictions_generated": 25,
  "lines_processed": 5,
  "systems_run": 5,
  "timestamp": "2025-11-07T06:18:15Z"
}
```

**Event 3: Failure Event (to DLQ)**

```json
{
  "player_lookup": "lebron-james",
  "game_id": "20251107_LAL_GSW",
  "status": "failed",
  "failed_at": "2025-11-07T06:20:00Z",
  "error": "Timeout after 600 seconds",
  "retry_count": 3,
  "original_message": { /* original prediction-request */ },
  "alert_sent": true
}
```

### Message Retention & DLQ

Configuration:
```bash
# prediction-request subscription (worker sub)
--ack-deadline 600                      # 10 minutes (match Cloud Run timeout)
--message-retention-duration 1h         # Keep unacked messages for 1 hour
--dead-letter-topic prediction-worker-dlq
--max-delivery-attempts 3               # Retry 3 times before DLQ
```

Dead Letter Queue Processing:
```sql
-- Query DLQ for failed predictions
SELECT
  JSON_EXTRACT_SCALAR(data, '$.player_lookup') as player_lookup,
  JSON_EXTRACT_SCALAR(data, '$.error') as error_message,
  JSON_EXTRACT_SCALAR(data, '$.retry_count') as retry_count,
  publish_time
FROM `nba-props-platform.nba_logs.pubsub_dlq_messages`
WHERE topic_name = 'prediction-worker-dlq'
  AND DATE(publish_time) = CURRENT_DATE()
ORDER BY publish_time DESC;
```

---

## 📊 Daily Processing Scale {#daily-scale}

### Phase 5 Input (from Phase 4 at 12:00 AM)

```
ml_feature_store_v2: 450 players × 25 features = 11,250 feature values
```

### Phase 5 Processing (6:15 AM)

```
├─ Coordinator: Query players + lines (~1-2 min)
├─ Workers: Process 450 players in parallel (~2-3 min)
│   └─ Per player: 5 lines × 5 systems = 25 predictions
└─ Total: 450 players × 5 lines × 5 systems = 11,250 predictions
```

### Phase 5 Output

```
├─ player_prop_predictions: 11,250 rows
└─ Duration: 2-5 minutes (target: <3 min)
```

### Daily Volume Analysis

**Per-Player Data Flow:**
- Input (Pub/Sub message): ~500 bytes JSON
- Features (BigQuery): ~2 KB (25 features + metadata)
- Historical Games (BigQuery): ~5 KB (30 games × ~170 bytes each)
- Predictions (BigQuery write): ~5 KB (5 systems × ~1 KB each)
- Completion Event (Pub/Sub): ~300 bytes JSON
- **Total per player:** ~12.8 KB

**Daily Volume:**

Single Line Mode (Production):
```
450 players × 12.8 KB = 5.76 MB input/output
450 players × 5 systems × 1 KB = 2.25 MB stored
```

Multi-Line Mode (Testing):
```
450 players × 5 lines × 12.8 KB = 28.8 MB input/output
450 players × 5 lines × 5 systems × 1 KB = 11.25 MB stored
```

---

## 💰 Cost Analysis & Optimization {#cost-analysis}

### Daily Cost Breakdown

**Phase 5 costs ~$60/day** (based on 450 players, 2-5 min processing time)

| Component | Daily Cost | Monthly Cost | Calculation |
|-----------|------------|--------------|-------------|
| **Coordinator (Cloud Run Job)** | $0.30 | $9 | 1 execution × 2 min × $0.0000024/vCPU-sec × 1 vCPU |
| **Workers (Cloud Run Service)** | $45.00 | $1,350 | 20 instances × 3 min avg × 2 vCPU × $0.0000024/vCPU-sec |
| **Pub/Sub Messages** | $2.50 | $75 | 450 requests + 450 ready + retries ×$0.40/million |
| **BigQuery Queries** | $5.00 | $150 | Features (450 × 2 KB) + Historical (450 × 5 KB) |
| **BigQuery Storage** | $0.20 | $6 | 11,250 predictions × 1 KB × $0.02/GB/month |
| **GCS Model Storage** | $0.10 | $3 | 10 MB model × 3 versions × $0.02/GB/month |
| **Cloud Logging** | $3.00 | $90 | Worker logs (20 workers × 5 threads × 450 players) |
| **Cloud Monitoring** | $3.90 | $117 | Custom metrics + dashboards |
| **TOTAL** | **$60.00** | **$1,800** | Annual: **$21,600** |

**Cost per prediction:** $60 ÷ 450 players = **$0.13 per player**

---

### Monthly/Yearly Projections

**Monthly Costs (30 days):**
```
Base daily cost: $60/day
Monthly total: $60 × 30 = $1,800/month
Off-season reduction (June-Sept): $1,800 × 0.3 = $540/month (67% reduction)
```

**Annual Costs:**
```
Regular season (Oct-May): 8 months × $1,800 = $14,400
Off-season (June-Sept): 4 months × $540 = $2,160
TOTAL ANNUAL: $16,560
```

**Cost Scenarios:**

| Scenario | Daily Volume | Daily Cost | Monthly Cost | Annual Cost |
|----------|--------------|------------|--------------|-------------|
| **Light Days** | 200 players | $30 | $900 | $10,800 |
| **Typical Days** | 450 players | $60 | $1,800 | $21,600 |
| **Heavy Days** | 600 players | $80 | $2,400 | $28,800 |
| **Playoffs** | 100 players | $15 | $450 | N/A (2 months) |

---

### Cost Optimization Strategies

#### Strategy 1: Reduce Worker Instances (15% savings)

**Current:** 20 max workers, 5 threads each = 100 concurrent
**Optimized:** 15 max workers, 7 threads each = 105 concurrent

```bash
gcloud run services update phase5-prediction-worker \
    --max-instances 15 \
    --concurrency 7
```

**Savings:** -5 instances × $2.25/day = **-$9/day (-15%)** = **-$270/month**

**Trade-off:** +30 seconds total processing time (2:30 min → 3:00 min)

---

#### Strategy 2: Optimize BigQuery Queries (20% savings)

**Current:** 450 separate queries for features + historical games
**Optimized:** Batch queries (50 players per query)

```python
# Before: One query per player
for player in players:
    features = load_features(player)  # 450 queries

# After: Batch query (50 players at once)
for batch in chunk(players, 50):
    features = load_features_batch(batch)  # 9 queries
```

**Savings:** 450 queries → 9 queries = **-$4/day (-20% BQ cost)** = **-$120/month**

**Implementation:** Modify `data_loaders.py` to support batch queries

---

#### Strategy 3: Cache ML Features in Redis (30% savings)

**Current:** Load features from BigQuery every prediction
**Optimized:** Cache features in Redis (6 AM), reuse all day

```python
# 6:15 AM - Load all features to Redis (one-time)
features_all = load_all_features_for_date(game_date)
redis.set(f'features:{game_date}', features_all, ex=86400)

# Workers: Read from Redis (instant)
features = redis.get(f'features:{game_date}:{player_lookup}')
```

**Savings:** 450 BQ queries → 1 BQ query = **-$4.50/day (-90% BQ cost)** = **-$135/month**

**Cost:** Redis: $30/month (Cloud Memorystore 1GB)
**Net Savings:** -$135 + $30 = **-$105/month**

**Trade-off:** +$30/month Redis, +5 min setup time at 6 AM

---

#### Strategy 4: Scale to Zero Faster (5% savings)

**Current:** Workers scale to zero after 10 min idle
**Optimized:** Workers scale to zero after 2 min idle

```bash
gcloud run services update phase5-prediction-worker \
    --min-instances 0 \
    --max-instances 20 \
    --no-traffic-timeout 120  # 2 minutes
```

**Savings:** Reduce idle time from 10 min → 2 min = **-$3/day (-5%)** = **-$90/month**

**Trade-off:** Occasional cold starts if predictions requested outside 6:15-6:30 AM window

---

#### Strategy 5: Use Spot/Preemptible Instances (N/A for Cloud Run)

**Note:** Cloud Run doesn't support spot instances, but we can optimize with:

**Alternative:** Reduce memory allocation if possible

```bash
# Current: 2 Gi memory
gcloud run services update phase5-prediction-worker \
    --memory 1.5Gi  # Reduce if XGBoost fits

# Test memory usage first:
# Expected: ~800 MB per worker (500 MB XGBoost + 300 MB overhead)
```

**Potential Savings:** 2 Gi → 1.5 Gi = **-25% memory cost** = **-$11/day** = **-$330/month**

**Risk:** Out of memory errors if model or concurrent load increases

---

### Cost Optimization Summary

| Strategy | Savings/Month | Effort | Risk | Recommendation |
|----------|---------------|--------|------|----------------|
| Reduce worker instances | -$270 | Low | Low | ✅ Implement Week 2 |
| Batch BigQuery queries | -$120 | Medium | Low | ✅ Implement Week 3 |
| Redis feature cache | -$105 net | High | Medium | ⚠️ Implement Month 2 |
| Scale to zero faster | -$90 | Low | Low | ✅ Implement Week 1 |
| Reduce memory | -$330 | Low | High | ❌ Monitor first, test carefully |

**Total Potential Savings:** -$585/month (-32% reduction)
**Optimized Monthly Cost:** $1,800 → $1,215/month

---

### Budget Alerts Setup

**Create budget alerts to monitor costs:**

```bash
# 1. Create budget ($2,000/month with 80% alert)
gcloud billing budgets create \
    --billing-account=BILLING_ACCOUNT_ID \
    --display-name="Phase 5 Predictions Budget" \
    --budget-amount=2000 \
    --threshold-rule=percent=80 \
    --threshold-rule=percent=100 \
    --all-updates-rule-pubsub-topic=projects/nba-props-platform/topics/budget-alerts

# 2. Set up alerts for daily spike (>$100/day)
gcloud alpha monitoring policies create \
    --notification-channels=CHANNEL_ID \
    --display-name="Phase 5 Daily Cost Spike" \
    --condition-display-name="Daily cost exceeds $100" \
    --condition-threshold-value=100 \
    --condition-threshold-duration=86400s
```

**Alert Thresholds:**

| Alert | Threshold | Action |
|-------|-----------|--------|
| **Daily budget** | >$80/day | Slack notification |
| **Weekly budget** | >$500/week | Email team + review |
| **Monthly budget** | >$1,800/month | PagerDuty + urgent review |
| **Sudden spike** | +50% vs yesterday | Investigate immediately |

---

### Cost Monitoring Queries

**Daily cost breakdown:**
```sql
-- Query GCP billing export
SELECT
  service.description,
  SUM(cost) as daily_cost,
  COUNT(*) as usage_count
FROM `nba-props-platform.billing.gcp_billing_export_v1_*`
WHERE DATE(usage_start_time) = CURRENT_DATE()
  AND project.id = 'nba-props-platform'
  AND (
    service.description LIKE '%Cloud Run%'
    OR service.description LIKE '%Pub/Sub%'
    OR service.description LIKE '%BigQuery%'
  )
GROUP BY service.description
ORDER BY daily_cost DESC;
```

**Weekly trend:**
```sql
-- Weekly cost trend (last 4 weeks)
SELECT
  DATE_TRUNC(DATE(usage_start_time), WEEK) as week,
  SUM(cost) as weekly_cost,
  AVG(cost) as avg_daily_cost
FROM `nba-props-platform.billing.gcp_billing_export_v1_*`
WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND project.id = 'nba-props-platform'
  AND service.description LIKE '%Phase 5%'
GROUP BY week
ORDER BY week DESC;
```

---

## 🔗 Critical Dependencies {#dependencies}

### Phase 5 Requires

✅ **Phase 4 complete by 12:15 AM** (features cached in `ml_feature_store_v2`)
✅ **Phase 3 upcoming context by 6:00 AM** (player game schedule)
✅ **Phase 2 prop lines by 6:00 AM** (opening lines from overnight scrape)

### If Any Dependency Fails

❌ **Phase 4 failure** → No predictions possible (CRITICAL)
⚠️ **Phase 3 failure** → Use previous day's context (degraded)
⚠️ **Phase 2 failure** → Use estimated lines from historical data (degraded)

---

## ✅ Success Criteria {#success-criteria}

### Coordinator Success

```sql
-- Verify coordinator published messages
SELECT
  COUNT(DISTINCT player_lookup) as players_queued,
  COUNT(*) as total_messages
FROM `nba-props-platform.nba_logs.pubsub_messages`
WHERE topic_name = 'prediction-request'
  AND DATE(publish_time) = CURRENT_DATE()
  AND publish_time >= TIMESTAMP('06:15:00');

-- Expected: ~450 players, 450 messages
```

### Worker Success

```sql
-- Verify workers wrote predictions for all players
SELECT
  COUNT(DISTINCT player_lookup) as players_with_predictions,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as systems_run
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND created_at >= TIMESTAMP('06:15:00');

-- Expected: 450 players, 11,250 predictions, 5 systems
```

### System Coverage

```sql
-- Check all 5 systems generated predictions
SELECT
  system_id,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as predictions,
  AVG(confidence_score) as avg_confidence
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
ORDER BY system_id;

-- Expected: 5 systems, each with 450 players, 2,250 predictions
```

### Feature Quality

```sql
-- Check feature quality feeding predictions
SELECT
  COUNT(*) as players,
  AVG(feature_quality_score) as avg_quality,
  MIN(feature_quality_score) as min_quality,
  COUNTIF(feature_quality_score < 70) as low_quality_count
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();

-- Expected: 450 players, avg 85+, min 70+, low_quality 0
```

---

## 🚀 Complete Deployment Guide {#deployment-guide}

### Pre-Deployment Checklist

**Infrastructure Prerequisites:**

- [ ] **GCP Project** set up with billing enabled
- [ ] **BigQuery datasets** created:
  - [ ] `nba_predictions` (for ml_feature_store_v2, player_prop_predictions)
  - [ ] `nba_precompute` (for Phase 4 outputs)
  - [ ] `nba_analytics` (for Phase 3 outputs)
- [ ] **GCS buckets** created:
  - [ ] `gs://nba-models-production/` (for XGBoost models)
  - [ ] `gs://nba-training-data/` (for model training data)
- [ ] **Service accounts** created:
  - [ ] `prediction-coordinator@nba-props-platform.iam.gserviceaccount.com`
  - [ ] `prediction-worker@nba-props-platform.iam.gserviceaccount.com`
  - [ ] `training-service@nba-props-platform.iam.gserviceaccount.com`

**Code Prerequisites:**

- [ ] **Phase 5 code** deployed to container registry:
  - [ ] Coordinator image: `gcr.io/nba-props-platform/prediction-coordinator:latest`
  - [ ] Worker image: `gcr.io/nba-props-platform/prediction-worker:latest`
- [ ] **Dependencies verified** in requirements.txt:
  - [ ] xgboost==2.0.0
  - [ ] google-cloud-bigquery>=3.0.0
  - [ ] google-cloud-pubsub>=2.0.0
  - [ ] google-cloud-storage>=2.0.0
  - [ ] flask>=2.0.0

**Configuration Prerequisites:**

- [ ] **Environment variables** prepared (see sections below)
- [ ] **ML model** trained or mock model ready:
  - [ ] XGBoost model uploaded to GCS
  - [ ] Metadata.json uploaded with model
  - [ ] Model path environment variable set

---

### Step-by-Step Deployment

#### Step 1: Create Pub/Sub Topics (5 minutes)

```bash
# Create topics
gcloud pubsub topics create prediction-request \
    --project nba-props-platform

gcloud pubsub topics create prediction-ready \
    --project nba-props-platform

gcloud pubsub topics create prediction-worker-dlq \
    --project nba-props-platform

# Verify topics created
gcloud pubsub topics list --project nba-props-platform | grep prediction
```

---

#### Step 2: Set Up IAM Roles (10 minutes)

```bash
# Coordinator: Can publish to prediction-request, read from BigQuery
gcloud projects add-iam-policy-binding nba-props-platform \
    --member=serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
    --role=roles/pubsub.publisher

gcloud projects add-iam-policy-binding nba-props-platform \
    --member=serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
    --role=roles/bigquery.dataViewer

# Worker: Can subscribe to prediction-request, write to BigQuery, publish to prediction-ready
gcloud projects add-iam-policy-binding nba-props-platform \
    --member=serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com \
    --role=roles/pubsub.subscriber

gcloud projects add-iam-policy-binding nba-props-platform \
    --member=serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com \
    --role=roles/pubsub.publisher

gcloud projects add-iam-policy-binding nba-props-platform \
    --member=serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com \
    --role=roles/bigquery.dataEditor

# Worker: Can read ML models from GCS
gsutil iam ch \
    serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com:objectViewer \
    gs://nba-models-production
```

---

#### Step 3: Deploy Coordinator Service (15 minutes)

**Option A: Deploy from source**

```bash
cd predictions/coordinator

gcloud run jobs create phase5-prediction-coordinator \
    --source . \
    --region us-central1 \
    --memory 1Gi \
    --cpu 1 \
    --timeout 10m \
    --max-retries 2 \
    --service-account prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
    --set-env-vars "GCP_PROJECT_ID=nba-props-platform,\
BIGQUERY_DATASET=nba_predictions,\
PUBSUB_TOPIC=prediction-request,\
FEATURE_VERSION=v1_baseline_25,\
PRIMARY_BOOKMAKER=draftkings,\
LINE_SPREAD_RANGE=2.0"
```

**Option B: Deploy from container image**

```bash
gcloud run jobs create phase5-prediction-coordinator \
    --image gcr.io/nba-props-platform/prediction-coordinator:latest \
    --region us-central1 \
    --memory 1Gi \
    --cpu 1 \
    --timeout 10m \
    --max-retries 2 \
    --service-account prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
    --set-env-vars "GCP_PROJECT_ID=nba-props-platform,\
BIGQUERY_DATASET=nba_predictions,\
PUBSUB_TOPIC=prediction-request,\
FEATURE_VERSION=v1_baseline_25,\
PRIMARY_BOOKMAKER=draftkings,\
LINE_SPREAD_RANGE=2.0"
```

**Verify deployment:**
```bash
gcloud run jobs describe phase5-prediction-coordinator --region us-central1
```

---

#### Step 4: Deploy Worker Service (15 minutes)

```bash
cd predictions/worker

gcloud run services create phase5-prediction-worker \
    --source . \
    --region us-central1 \
    --memory 2Gi \
    --cpu 2 \
    --timeout 600s \
    --min-instances 0 \
    --max-instances 20 \
    --concurrency 5 \
    --service-account prediction-worker@nba-props-platform.iam.gserviceaccount.com \
    --no-allow-unauthenticated \
    --set-env-vars "GCP_PROJECT_ID=nba-props-platform,\
THREAD_POOL_SIZE=5,\
BIGQUERY_PROJECT=nba-props-platform,\
PREDICTIONS_TABLE=nba_predictions.player_prop_predictions,\
FEATURE_VERSION=v1_baseline_25,\
XGBOOST_MODEL_PATH=gs://nba-models-production/xgboost/v1.0/model.json"
```

**Verify deployment:**
```bash
gcloud run services describe phase5-prediction-worker --region us-central1
```

---

#### Step 5: Create Pub/Sub Push Subscription (10 minutes)

```bash
# Get worker service URL
WORKER_URL=$(gcloud run services describe phase5-prediction-worker \
    --region us-central1 \
    --format="value(status.url)")

echo "Worker URL: $WORKER_URL"

# Create push subscription
gcloud pubsub subscriptions create phase5-prediction-worker-sub \
    --topic prediction-request \
    --ack-deadline 600 \
    --message-retention-duration 1h \
    --dead-letter-topic prediction-worker-dlq \
    --max-delivery-attempts 3 \
    --push-endpoint="${WORKER_URL}/predict" \
    --push-auth-service-account=prediction-worker@nba-props-platform.iam.gserviceaccount.com

# Verify subscription
gcloud pubsub subscriptions describe phase5-prediction-worker-sub
```

---

#### Step 6: Set Up Cloud Scheduler (10 minutes)

```bash
# Create daily trigger at 6:15 AM ET
gcloud scheduler jobs create http phase5-prediction-daily \
    --location us-central1 \
    --schedule "15 10 * * *" \
    --time-zone "America/New_York" \
    --uri "https://$(gcloud run jobs describe phase5-prediction-coordinator --region us-central1 --format='value(status.url)')/start" \
    --http-method POST \
    --oidc-service-account-email prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
    --message-body '{
      "processor": "prediction_coordinator",
      "phase": "5",
      "game_date": "auto"
    }'

# Verify scheduler job
gcloud scheduler jobs describe phase5-prediction-daily --location us-central1
```

---

### Post-Deployment Validation

#### Day 1: Initial Validation

**1. Test Coordinator Manually (5 minutes)**

```bash
# Run coordinator manually to test
gcloud run jobs execute phase5-prediction-coordinator \
    --region us-central1 \
    --wait

# Check execution logs
gcloud run jobs executions list \
    --job phase5-prediction-coordinator \
    --region us-central1 \
    --limit 1
```

**Expected Output:**
- Execution completes successfully
- 450 messages published to Pub/Sub
- No errors in logs

**2. Verify Pub/Sub Messages (2 minutes)**

```sql
-- Check prediction-request messages
SELECT COUNT(*) as message_count
FROM `nba-props-platform.nba_logs.pubsub_messages`
WHERE topic_name = 'prediction-request'
  AND DATE(publish_time) = CURRENT_DATE();
-- Expected: 450
```

**3. Verify Worker Processing (10 minutes)**

```bash
# Monitor worker logs in real-time
gcloud logging read "resource.type=cloud_run_revision \
    AND resource.labels.service_name=phase5-prediction-worker" \
    --limit 50 \
    --format json
```

**Expected Output:**
- Workers auto-scale from 0 → 20 instances
- Each worker processes ~22 players (450 / 20)
- No crashes or OOM errors

**4. Verify Predictions Written (5 minutes)**

```sql
-- Check predictions table
SELECT
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as systems
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE);
-- Expected: 450 players, 11,250 predictions, 5 systems
```

---

#### Week 1: Ongoing Monitoring

**Daily Health Checks (every morning 6:45 AM):**

- [ ] **Coordinator ran** - Check Cloud Scheduler execution logs
- [ ] **450 players processed** - Query BigQuery predictions table
- [ ] **All 5 systems ran** - Verify system_id counts
- [ ] **No DLQ messages** - Check dead letter queue is empty
- [ ] **Processing time < 5 min** - Check Cloud Run metrics

**Weekly Reviews (every Monday):**

- [ ] **Cost review** - Check GCP billing vs. budget
- [ ] **Performance review** - Check prediction latency p50/p95/p99
- [ ] **Error rate** - Check worker error rate < 1%
- [ ] **Model performance** - Check MAE, calibration metrics
- [ ] **Feature quality** - Check avg feature_quality_score >= 85

---

#### Month 1: Optimization & Tuning

**Week 1-2: Baseline Measurement**
- Collect cost metrics, performance metrics, prediction accuracy
- Establish baseline for future optimizations

**Week 3: Apply Quick Wins**
- Implement "Scale to zero faster" optimization
- Implement "Reduce worker instances" if processing time allows

**Week 4: Plan Long-Term Optimizations**
- Evaluate batch BigQuery queries implementation
- Plan Redis caching if needed
- Schedule model retraining pipeline deployment

---

## 📊 Monitoring & Alerting {#monitoring}

### Key Metrics to Monitor

**Cloud Run Metrics (Coordinator):**

| Metric | Threshold | Alert Level | Action |
|--------|-----------|-------------|--------|
| Execution count | < 1/day | P1 | Check Cloud Scheduler |
| Execution duration | > 10 min | P2 | Check query performance |
| Execution errors | > 0 | P1 | Review logs, retry manually |

**Cloud Run Metrics (Workers):**

| Metric | Threshold | Alert Level | Action |
|--------|-----------|-------------|--------|
| Request count | < 400/day | P1 | Check coordinator |
| Request latency p95 | > 30 sec | P2 | Check BigQuery |
| Error rate | > 5% | P1 | Review error logs |
| Instance count peak | > 20 | P2 | Check for runaway scaling |
| CPU utilization | > 90% | P2 | Consider +CPU or -concurrency |
| Memory utilization | > 85% | P1 | Risk of OOM, reduce concurrency |

**BigQuery Metrics:**

| Metric | Threshold | Alert Level | Action |
|--------|-----------|-------------|--------|
| Predictions written | < 10,000/day | P1 | Check workers |
| Feature quality avg | < 80 | P2 | Check Phase 4 |
| Query slots used | > 2000 | P2 | Optimize queries |

**Pub/Sub Metrics:**

| Metric | Threshold | Alert Level | Action |
|--------|-----------|-------------|--------|
| Unacked messages (prediction-request) | > 100 (after 10 min) | P2 | Workers may be down |
| DLQ messages | > 10 | P2 | Investigate failures |
| Subscription backlog | > 500 | P1 | Workers not scaling |

---

### Grafana Dashboard Configuration

**Panel 1: Daily Predictions Count**

```json
{
  "title": "Daily Predictions Count",
  "targets": [{
    "query": "SELECT COUNT(*) FROM `nba_predictions.player_prop_predictions` WHERE game_date = CURRENT_DATE()",
    "refId": "A"
  }],
  "thresholds": [
    { "value": 10000, "color": "green" },
    { "value": 5000, "color": "yellow" },
    { "value": 0, "color": "red" }
  ]
}
```

**Panel 2: Worker Processing Time**

```json
{
  "title": "Phase 5 Processing Time (6:15 AM - completion)",
  "targets": [{
    "query": "SELECT MAX(created_at) - MIN(created_at) as duration_minutes FROM `nba_predictions.player_prop_predictions` WHERE game_date = CURRENT_DATE()",
    "refId": "A"
  }],
  "thresholds": [
    { "value": 3, "color": "green" },
    { "value": 5, "color": "yellow" },
    { "value": 10, "color": "red" }
  ]
}
```

**Panel 3: System Coverage**

```json
{
  "title": "Prediction Systems Running",
  "targets": [{
    "query": "SELECT system_id, COUNT(DISTINCT player_lookup) as players FROM `nba_predictions.player_prop_predictions` WHERE game_date = CURRENT_DATE() GROUP BY system_id",
    "refId": "A"
  }]
}
```

---

### Alert Policies (Cloud Monitoring)

**Critical Alerts (PagerDuty):**

```bash
# Alert 1: Coordinator failed
gcloud alpha monitoring policies create \
    --notification-channels=$PAGERDUTY_CHANNEL \
    --display-name="Phase 5 Coordinator Failed" \
    --condition-display-name="Coordinator execution errors > 0" \
    --condition-threshold-value=1 \
    --condition-threshold-duration=60s

# Alert 2: Predictions count low
gcloud alpha monitoring policies create \
    --notification-channels=$PAGERDUTY_CHANNEL \
    --display-name="Phase 5 Low Predictions Count" \
    --condition-display-name="Daily predictions < 10000" \
    --condition-threshold-value=10000 \
    --condition-threshold-comparison=COMPARISON_LT \
    --condition-threshold-duration=3600s
```

**Warning Alerts (Slack):**

```bash
# Alert 3: High worker error rate
gcloud alpha monitoring policies create \
    --notification-channels=$SLACK_CHANNEL \
    --display-name="Phase 5 Worker Error Rate High" \
    --condition-display-name="Worker error rate > 5%" \
    --condition-threshold-value=0.05 \
    --condition-threshold-duration=300s

# Alert 4: Processing time slow
gcloud alpha monitoring policies create \
    --notification-channels=$SLACK_CHANNEL \
    --display-name="Phase 5 Processing Time Slow" \
    --condition-display-name="Processing duration > 5 min" \
    --condition-threshold-value=300 \
    --condition-threshold-duration=60s
```

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Documentation (Primary):**
- **🌟 Getting Started:** `../tutorials/01-getting-started.md` - Complete onboarding guide (READ FIRST!)
- **Scheduling Strategy:** `02-scheduling-strategy.md` - Cloud Scheduler, dependency management, retry strategy
- **Troubleshooting:** `03-troubleshooting.md` - Failure scenarios, incident response, manual operations
- **Worker Deep-Dive:** `04-worker-deepdive.md` - Model loading, concurrency, performance optimization
- **Data Sources:** `../data-sources/01-data-categorization.md` - How Phase 5 uses data
- **Architecture:** `../architecture/01-parallelization-strategy.md` - Scaling decisions

**Upstream Dependencies:**
- **Phase 4:** `docs/processors/05-phase4-operations-guide.md` - ML Feature Store (CRITICAL)
- **Phase 3:** `docs/processors/02-phase3-operations-guide.md` - Upcoming game context
- **Phase 2:** `docs/processors/01-phase2-operations-guide.md` - Raw data processing
- **Phase 1:** `docs/orchestration/` - Scraper orchestration

**Infrastructure:**
- **Pub/Sub:** `docs/infrastructure/` - Event infrastructure setup
- **Monitoring:** `docs/monitoring/01-grafana-monitoring-guide.md` - Grafana dashboards
- **Data Flow:** `docs/data-flow/` - Pipeline schemas and transformations

**Architecture:**
- **Event-Driven Pipeline:** `docs/architecture/04-event-driven-pipeline-architecture.md`
- **Implementation Status:** `docs/architecture/05-implementation-status-and-roadmap.md`
- **Integration Plan:** `docs/architecture/01-phase1-to-phase5-integration-plan.md`

**Processor Cards (Quick Reference):**
- **ML Feature Store:** `docs/processor-cards/phase4-ml-feature-store-v2.md` - Your input data
- **Real-Time Flow:** `docs/processor-cards/workflow-realtime-prediction-flow.md` - End-to-end workflow

---

**Last Updated:** 2025-11-15 19:45 PST
**Next Review:** After Phase 5 production deployment
**Status:** ✅ Production Ready - Comprehensive deployment reference
