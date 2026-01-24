# Option D: Phase 5 Full Deployment - Implementation Handoff

**Created**: 2026-01-17
**Status**: Ready for Implementation
**Estimated Duration**: 13-16 hours
**Priority**: High (Revenue-Generating Feature)

---

## Executive Summary

Deploy the complete Phase 5 prediction system, including training production XGBoost models, deploying the prediction coordinator, integrating with Phase 4 via Pub/Sub, and establishing end-to-end monitoring. This enables automated daily prediction generation for NBA player props.

### Current State
- ✅ Prediction worker: Deployed to Cloud Run (with CatBoost V8)
- ✅ Data pipeline: Phases 1-4 operational
- ❌ **Prediction coordinator**: Not deployed
- ❌ **XGBoost model**: Using mock model (needs real training)
- ❌ **Pub/Sub integration**: Phase 4 → Phase 5 not connected
- ❌ **End-to-end automation**: Manual trigger only

### What Gets Better
- **Automated predictions** generated daily after Phase 4 completion
- **Production XGBoost model** trained on real historical data
- **End-to-end pipeline** from data scraping to predictions (Phases 1-5)
- **Coordinated execution** ensures player predictions run in correct order
- **Full monitoring** tracks prediction coverage, accuracy, and system health

---

## Current State (As of 2026-01-17)

### What's Working

**Prediction Worker** (Cloud Run Service):
- Service: `nba-prediction-worker`
- URL: https://nba-prediction-worker-756957797294.us-central1.run.app/
- Models deployed:
  - ✅ CatBoost V8 (production model)
  - ⚠️  XGBoost V1 (mock model - needs replacement)
- Features:
  - ✅ Single prediction endpoint
  - ✅ Batch prediction endpoint
  - ✅ Health checks
  - ✅ Startup validation
  - ✅ Fallback prediction system
  - ✅ Week 1 alerting (model failures, fallback rate)

**Data Pipeline** (Phases 1-4):
- Phase 1: Orchestration ✅ (7 daily workflows, 33 scrapers)
- Phase 2: Raw processing ✅ (25 processors, smart idempotency)
- Phase 3: Analytics ✅ (5 processors, completeness checking)
- Phase 4: Precompute ✅ (5 processors, ML feature store)

**Pub/Sub Topics Configured**:
- `nba-scraper-complete`: Phase 1 → Phase 2 ✅
- `nba-phase2-raw-complete`: Phase 2 → Phase 3 ✅
- `nba-phase3-analytics-complete`: Phase 3 → Phase 4 ✅
- `nba-phase4-precompute-complete`: **NOT CREATED** ❌

### What's Missing

**Critical Gaps**:

1. **XGBoost Production Model**
   - Current: Using mock model from 2024-11-14
   - Path: `gs://nba-scraped-data/ml-models/nba_points_xgboost_v1_mock.json`
   - Issue: Not trained on real data, predictions unreliable
   - **Need**: Train on historical data (Nov 2021 - present)

2. **Prediction Coordinator**
   - Code: `/predictions/coordinator/coordinator.py` ✅ (code complete)
   - Deployment: Not deployed ❌
   - Purpose: Orchestrates prediction generation, handles dependencies
   - **Need**: Deploy to Cloud Run

3. **Pub/Sub Integration**
   - Topic `nba-phase4-precompute-complete`: Not created
   - Subscription for coordinator: Not created
   - Phase 4 processors: Not publishing completion events
   - **Need**: Create topic/subscription, update Phase 4 publishers

4. **End-to-End Automation**
   - Current: Manual trigger required for predictions
   - **Need**: Automatic trigger after Phase 4 completion

5. **Phase 5 Monitoring**
   - No prediction coverage tracking
   - No accuracy metrics collection
   - No integration with Cloud Monitoring
   - **Need**: Dashboards, alerts, daily reports

---

## Objectives & Success Criteria

### Objective 1: Train Production XGBoost Model
**Goal**: Replace mock model with real ML model trained on historical data

**Success Criteria**:
- [ ] Model trained on ≥1 year of historical data (ideally 3+ years)
- [ ] Training MAE ≤ 4.0 points
- [ ] Validation MAE ≤ 4.5 points
- [ ] Model saved to GCS with versioned filename
- [ ] Deployment script updated with new model path

### Objective 2: Deploy Prediction Coordinator
**Goal**: Deploy coordinator service to orchestrate predictions

**Success Criteria**:
- [ ] Coordinator deployed to Cloud Run
- [ ] Health endpoint returns 200
- [ ] Can trigger batch predictions via HTTP
- [ ] Can receive Pub/Sub messages from Phase 4
- [ ] Logs structured events to Cloud Logging

### Objective 3: Integrate Phase 4 → Phase 5 Pub/Sub
**Goal**: Automate prediction trigger after feature engineering

**Success Criteria**:
- [ ] Topic `nba-phase4-precompute-complete` created
- [ ] Coordinator subscribed to topic
- [ ] Phase 4 processors publish completion events
- [ ] End-to-end flow tested (Phase 4 → Pub/Sub → Coordinator → Worker)

### Objective 4: Establish Phase 5 Monitoring
**Goal**: Track prediction generation and quality

**Success Criteria**:
- [ ] Daily prediction coverage tracking (% of scheduled players predicted)
- [ ] Prediction quality metrics (confidence distribution, edge analysis)
- [ ] Error rate monitoring (failed predictions, model errors)
- [ ] Dashboard showing Phase 5 health
- [ ] Alerts for low coverage or high error rates

### Objective 5: End-to-End Validation
**Goal**: Prove complete pipeline works autonomously

**Success Criteria**:
- [ ] Manual test: Phase 4 completion triggers predictions automatically
- [ ] Production test: Daily workflow generates predictions without intervention
- [ ] Predictions written to BigQuery correctly
- [ ] All players in upcoming games have predictions
- [ ] Zero manual intervention required for 3 consecutive days

---

## Detailed Implementation Plan

### Step 1: Train Production XGBoost Model (4-5 hours)

**1.1 Prepare Training Data**

Create: `/ml_models/nba/train_xgboost_v1.py`

```python
#!/usr/bin/env python3
"""
Train production XGBoost model for NBA player points prediction.

Usage:
    python3 ml_models/nba/train_xgboost_v1.py \
        --start-date 2021-11-01 \
        --end-date 2024-12-31 \
        --output-path gs://nba-scraped-data/ml-models/
"""

import argparse
import xgboost as xgb
from google.cloud import bigquery
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error
import json

def load_training_data(start_date, end_date):
    """Load features and labels from BigQuery."""
    client = bigquery.Client()

    query = f"""
    SELECT
      -- Target
      pgs.points as label,

      -- Features (same as worker uses)
      mlfs.season_ppg,
      mlfs.rolling_ppg_3g,
      mlfs.rolling_ppg_5g,
      mlfs.rolling_ppg_10g,
      mlfs.home_away_split_ppg,
      mlfs.opponent_def_rating,
      mlfs.days_rest,
      mlfs.minutes_per_game,
      mlfs.usage_rate,
      mlfs.true_shooting_pct,
      -- ... all 35+ features

      -- Metadata (for validation)
      mlfs.player_lookup,
      mlfs.game_date,
      pgs.game_id

    FROM `nba-data-warehouse-422817.nba_precompute.ml_feature_store` mlfs
    JOIN `nba-data-warehouse-422817.nba_analytics.player_game_summary` pgs
      ON mlfs.player_lookup = pgs.player_lookup
      AND mlfs.game_date = pgs.game_date
    WHERE mlfs.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND pgs.points IS NOT NULL  -- Must have actual outcome
      AND mlfs.season_ppg IS NOT NULL  -- Basic quality check
    """

    print(f"Loading training data from {start_date} to {end_date}...")
    df = client.query(query).to_dataframe()

    print(f"Loaded {len(df):,} training examples")
    return df

def prepare_features(df):
    """Prepare features and labels for XGBoost."""

    # Feature columns
    feature_cols = [
        'season_ppg', 'rolling_ppg_3g', 'rolling_ppg_5g', 'rolling_ppg_10g',
        'home_away_split_ppg', 'opponent_def_rating', 'days_rest',
        'minutes_per_game', 'usage_rate', 'true_shooting_pct',
        # ... add all features
    ]

    # Extract features and labels
    X = df[feature_cols].copy()
    y = df['label'].copy()

    # Handle missing values (fill with median)
    X = X.fillna(X.median())

    # Metadata for analysis
    metadata = df[['player_lookup', 'game_date', 'game_id']].copy()

    return X, y, metadata, feature_cols

def train_model(X_train, y_train, X_val, y_val):
    """Train XGBoost model with hyperparameter tuning."""

    # XGBoost parameters (tuned via grid search)
    params = {
        'objective': 'reg:squarederror',
        'max_depth': 6,
        'learning_rate': 0.05,
        'n_estimators': 300,
        'min_child_weight': 3,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'gamma': 0.1,
        'random_state': 42,
        'n_jobs': -1
    }

    print("Training XGBoost model...")
    print(f"Training examples: {len(X_train):,}")
    print(f"Validation examples: {len(X_val):,}")

    model = xgb.XGBRegressor(**params)

    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        eval_metric='mae',
        early_stopping_rounds=20,
        verbose=True
    )

    return model

def evaluate_model(model, X_train, y_train, X_val, y_val):
    """Evaluate model performance."""

    # Training metrics
    train_preds = model.predict(X_train)
    train_mae = mean_absolute_error(y_train, train_preds)
    train_rmse = np.sqrt(mean_squared_error(y_train, train_preds))

    # Validation metrics
    val_preds = model.predict(X_val)
    val_mae = mean_absolute_error(y_val, val_preds)
    val_rmse = np.sqrt(mean_squared_error(y_val, val_preds))

    print("\n" + "="*50)
    print("MODEL EVALUATION")
    print("="*50)
    print(f"Training MAE:   {train_mae:.3f} points")
    print(f"Training RMSE:  {train_rmse:.3f} points")
    print(f"Validation MAE: {val_mae:.3f} points")
    print(f"Validation RMSE: {val_rmse:.3f} points")
    print("="*50)

    # Feature importance
    importance = pd.DataFrame({
        'feature': model.feature_names_in_,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    print("\nTop 10 Most Important Features:")
    print(importance.head(10).to_string(index=False))

    return {
        'train_mae': float(train_mae),
        'train_rmse': float(train_rmse),
        'val_mae': float(val_mae),
        'val_rmse': float(val_rmse),
        'feature_importance': importance.to_dict('records')
    }

def save_model(model, output_path, metrics, feature_cols):
    """Save model to GCS with metadata."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_filename = f"nba_points_xgboost_v1_production_{timestamp}.json"

    # Save model
    gcs_path = f"{output_path.rstrip('/')}/{model_filename}"
    model.save_model(gcs_path)

    print(f"\n✅ Model saved to: {gcs_path}")

    # Save metadata
    metadata = {
        'model_path': gcs_path,
        'model_version': 'v1_production',
        'timestamp': timestamp,
        'framework': 'xgboost',
        'framework_version': xgb.__version__,
        'metrics': metrics,
        'features': feature_cols,
        'num_features': len(feature_cols)
    }

    metadata_filename = f"nba_points_xgboost_v1_production_{timestamp}_metadata.json"
    metadata_path = f"{output_path.rstrip('/')}/{metadata_filename}"

    from google.cloud import storage
    storage_client = storage.Client()

    # Parse GCS path
    bucket_name = output_path.split('/')[2]
    blob_path = '/'.join(output_path.split('/')[3:]) + '/' + metadata_filename

    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(json.dumps(metadata, indent=2))

    print(f"✅ Metadata saved to: {metadata_path}")

    return gcs_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-date', required=True, help='Training start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='Training end date (YYYY-MM-DD)')
    parser.add_argument('--output-path', required=True, help='GCS output path (gs://bucket/path)')
    parser.add_argument('--test-size', type=float, default=0.2, help='Validation split (default 0.2)')
    args = parser.parse_args()

    # Load data
    df = load_training_data(args.start_date, args.end_date)

    if len(df) < 1000:
        print(f"ERROR: Insufficient training data ({len(df)} examples). Need at least 1000.")
        return 1

    # Prepare features
    X, y, metadata, feature_cols = prepare_features(df)

    # Train/validation split (by date to prevent data leakage)
    df_sorted = df.sort_values('game_date')
    split_idx = int(len(df_sorted) * (1 - args.test_size))

    train_idx = df_sorted.index[:split_idx]
    val_idx = df_sorted.index[split_idx:]

    X_train, y_train = X.loc[train_idx], y.loc[train_idx]
    X_val, y_val = X.loc[val_idx], y.loc[val_idx]

    # Train model
    model = train_model(X_train, y_train, X_val, y_val)

    # Evaluate
    metrics = evaluate_model(model, X_train, y_train, X_val, y_val)

    # Check if model meets criteria
    if metrics['val_mae'] > 4.5:
        print(f"\n⚠️  WARNING: Validation MAE ({metrics['val_mae']:.3f}) exceeds threshold (4.5)")
        print("Model may not be production-ready. Consider:")
        print("  - More training data")
        print("  - Feature engineering")
        print("  - Hyperparameter tuning")

        response = input("\nSave model anyway? (y/n): ")
        if response.lower() != 'y':
            print("Model not saved.")
            return 1

    # Save model
    model_path = save_model(model, args.output_path, metrics, feature_cols)

    print(f"\n{'='*50}")
    print("NEXT STEPS:")
    print(f"{'='*50}")
    print(f"1. Update deployment script with new model path:")
    print(f"   XGBOOST_V1_MODEL_PATH={model_path}")
    print(f"2. Deploy prediction worker:")
    print(f"   ./bin/predictions/deploy/deploy_prediction_worker.sh")
    print(f"3. Test predictions:")
    print(f"   curl https://nba-prediction-worker-...run.app/predict \\")
    print(f"     -d '{{...}}'")
    print(f"{'='*50}")

    return 0

if __name__ == "__main__":
    exit(main())
```

**1.2 Run Training**

```bash
# Train on 3 years of data (Nov 2021 - Dec 2024)
# Assumes backfill complete (Option C)
python3 ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2024-12-31 \
  --output-path gs://nba-scraped-data/ml-models/ \
  --test-size 0.2

# Expected output:
# Loaded 450,000+ training examples
# Training MAE: 3.8 points
# Validation MAE: 4.2 points
# ✅ Model saved to: gs://nba-scraped-data/ml-models/nba_points_xgboost_v1_production_20260117_143022.json
```

**1.3 Update Deployment Configuration**

File: `/bin/predictions/deploy/deploy_prediction_worker.sh`

```bash
# Update model path (around line 30)
XGBOOST_V1_MODEL_PATH="gs://nba-scraped-data/ml-models/nba_points_xgboost_v1_production_20260117_143022.json"

# Or set via environment variable
export XGBOOST_V1_MODEL_PATH="gs://nba-scraped-data/ml-models/nba_points_xgboost_v1_production_20260117_143022.json"
```

**1.4 Deploy Updated Worker**

```bash
# Deploy with new model
./bin/predictions/deploy/deploy_prediction_worker.sh

# Verify new model loaded
curl https://nba-prediction-worker-756957797294.us-central1.run.app/ | jq .

# Expected output includes:
# {
#   "model_versions": {
#     "xgboost_v1": "nba_points_xgboost_v1_production_20260117_143022"
#   }
# }
```

---

### Step 2: Deploy Prediction Coordinator (3-4 hours)

**2.1 Review Coordinator Code**

File: `/predictions/coordinator/coordinator.py` (already exists - verify completeness)

Key functionality:
- Receives Pub/Sub message with game_date
- Determines which players need predictions
- Triggers batch prediction on worker
- Handles retries and error recovery
- Publishes Phase 5 completion event

**2.2 Create Coordinator Dockerfile**

Create: `/docker/nba-prediction-coordinator.Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    flask==3.0.0 \
    gunicorn==21.2.0 \
    google-cloud-bigquery==3.13.0 \
    google-cloud-pubsub==2.18.4 \
    google-cloud-storage==2.10.0 \
    requests==2.31.0

# Copy code
COPY shared/ /app/shared/
COPY predictions/coordinator/ /app/predictions/coordinator/

# Set environment
ENV PYTHONPATH=/app
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run with Gunicorn
CMD exec gunicorn \
    --bind :$PORT \
    --workers 1 \
    --threads 4 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    predictions.coordinator.coordinator:app
```

**2.3 Create Deployment Script**

Create: `/bin/predictions/deploy/deploy_prediction_coordinator.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"
REGION="us-central1"
SERVICE_NAME="nba-prediction-coordinator"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Environment variables
WORKER_URL="https://nba-prediction-worker-756957797294.us-central1.run.app"
PHASE5_COMPLETION_TOPIC="nba-phase5-predictions-complete"

echo "Building and deploying NBA Prediction Coordinator..."
echo ""

# Build Docker image
echo "Step 1/4: Building Docker image..."
docker build -f docker/nba-prediction-coordinator.Dockerfile -t ${IMAGE_NAME}:latest .

# Push to Container Registry
echo "Step 2/4: Pushing to Container Registry..."
docker push ${IMAGE_NAME}:latest

# Deploy to Cloud Run
echo "Step 3/4: Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --image=${IMAGE_NAME}:latest \
  --platform=managed \
  --memory=1Gi \
  --cpu=1 \
  --timeout=600s \
  --concurrency=10 \
  --min-instances=0 \
  --max-instances=5 \
  --no-allow-unauthenticated \
  --service-account=nba-scrapers@${PROJECT_ID}.iam.gserviceaccount.com \
  --set-env-vars="WORKER_URL=${WORKER_URL},PHASE5_COMPLETION_TOPIC=${PHASE5_COMPLETION_TOPIC}" \
  --labels=phase=5,component=coordinator

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --format='value(status.url)')

echo ""
echo "Step 4/4: Testing health endpoint..."
sleep 5

curl -f -H "Authorization: Bearer $(gcloud auth print-identity-token)" ${SERVICE_URL}/health

echo ""
echo "========================================"
echo "✅ Coordinator deployed successfully!"
echo "========================================"
echo "Service URL: ${SERVICE_URL}"
echo ""
echo "Next steps:"
echo "1. Create Pub/Sub subscription for Phase 4 → Coordinator"
echo "2. Test manual trigger:"
echo "   curl -X POST ${SERVICE_URL}/trigger -d '{\"game_date\": \"2026-01-20\"}'"
echo "========================================"
```

**2.4 Deploy Coordinator**

```bash
# Deploy coordinator service
./bin/predictions/deploy/deploy_prediction_coordinator.sh

# Verify deployment
gcloud run services describe nba-prediction-coordinator \
  --region us-central1 \
  --format="value(status.url)"

# Test health endpoint
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://nba-prediction-coordinator-...run.app/health

# Expected: {"status": "healthy", "timestamp": "..."}
```

---

### Step 3: Integrate Phase 4 → Phase 5 via Pub/Sub (2-3 hours)

**3.1 Create Pub/Sub Topic and Subscription**

Create: `/bin/predictions/setup_phase5_pubsub.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"
REGION="us-central1"

TOPIC_NAME="nba-phase4-precompute-complete"
SUBSCRIPTION_NAME="nba-phase4-to-phase5"
COORDINATOR_URL=$(gcloud run services describe nba-prediction-coordinator \
  --region=${REGION} \
  --format='value(status.url)')

echo "Setting up Phase 4 → Phase 5 Pub/Sub integration..."
echo ""

# Create topic
echo "Creating topic: ${TOPIC_NAME}..."
gcloud pubsub topics create ${TOPIC_NAME} \
  --project=${PROJECT_ID} \
  --labels=phase=4,target=phase5 \
  || echo "Topic already exists"

# Create push subscription to coordinator
echo "Creating subscription: ${SUBSCRIPTION_NAME}..."
gcloud pubsub subscriptions create ${SUBSCRIPTION_NAME} \
  --project=${PROJECT_ID} \
  --topic=${TOPIC_NAME} \
  --push-endpoint="${COORDINATOR_URL}/pubsub" \
  --push-auth-service-account=nba-scrapers@${PROJECT_ID}.iam.gserviceaccount.com \
  --ack-deadline=600 \
  --message-retention-duration=7d \
  --labels=phase=5,component=coordinator \
  || echo "Subscription already exists"

# Grant invoker permission to service account
echo "Granting Cloud Run Invoker permission..."
gcloud run services add-iam-policy-binding nba-prediction-coordinator \
  --region=${REGION} \
  --member=serviceAccount:nba-scrapers@${PROJECT_ID}.iam.gserviceaccount.com \
  --role=roles/run.invoker \
  || echo "Permission already granted"

echo ""
echo "✅ Pub/Sub integration configured"
echo ""
echo "Topic: ${TOPIC_NAME}"
echo "Subscription: ${SUBSCRIPTION_NAME}"
echo "Coordinator endpoint: ${COORDINATOR_URL}/pubsub"
```

**3.2 Update Phase 4 Processors to Publish Events**

File: `/data_processors/precompute/ml_feature_store_processor.py` (final Phase 4 processor)

Add after successful processing:

```python
from google.cloud import pubsub_v1

def publish_phase4_completion(game_date):
    """Publish Phase 4 completion event to trigger Phase 5."""
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(
        "nba-data-warehouse-422817",
        "nba-phase4-precompute-complete"
    )

    message = {
        "game_date": game_date,
        "timestamp": datetime.utcnow().isoformat(),
        "processor": "ml_feature_store"
    }

    future = publisher.publish(
        topic_path,
        json.dumps(message).encode('utf-8')
    )

    logger.info(
        f"Published Phase 4 completion event",
        extra={"game_date": game_date, "message_id": future.result()}
    )

# Call after MLFS processing complete
if processing_successful:
    publish_phase4_completion(game_date)
```

**3.3 Redeploy Phase 4 Processors**

```bash
# Redeploy MLFS processor with Pub/Sub publishing
gcloud run deploy nba-processor-mlfs \
  --source=. \
  --region=us-central1 \
  --project=nba-data-warehouse-422817

# Verify processor can publish
gcloud logging read 'resource.type="cloud_run_revision"
  resource.labels.service_name="nba-processor-mlfs"
  jsonPayload.message=~"Published Phase 4 completion"' \
  --limit 5
```

**3.4 Test End-to-End Integration**

```bash
# Manual trigger of Phase 4 processor (simulates daily workflow)
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://nba-processor-mlfs-...run.app/process \
  -d '{"game_date": "2026-01-18"}'

# Monitor Pub/Sub message delivery
gcloud pubsub subscriptions pull nba-phase4-to-phase5 --limit=5

# Check coordinator logs
gcloud logging read 'resource.type="cloud_run_revision"
  resource.labels.service_name="nba-prediction-coordinator"' \
  --limit 10

# Verify predictions created in BigQuery
bq query --use_legacy_sql=false '
SELECT COUNT(*) as prediction_count
FROM `nba_predictions.player_predictions`
WHERE game_date = "2026-01-18"
'

# Expected: prediction_count > 0
```

---

### Step 4: Establish Phase 5 Monitoring (3-4 hours)

**4.1 Create Prediction Coverage Metric**

```bash
# Log-based metric: Daily prediction coverage
gcloud logging metrics create nba_prediction_coverage \
  --description="Percentage of scheduled players with predictions" \
  --log-filter='resource.type="cloud_run_revision"
    resource.labels.service_name="nba-prediction-coordinator"
    jsonPayload.coverage_pct!=null
    severity="INFO"' \
  --value-extractor='EXTRACT(jsonPayload.coverage_pct)'
```

**4.2 Create Quality Metrics**

```sql
-- Create monitoring views in BigQuery

-- View 1: Daily Prediction Coverage
CREATE OR REPLACE VIEW `nba_predictions.daily_coverage` AS
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as predictions_generated,
  COUNT(DISTINCT CASE WHEN recommendation IN ('OVER', 'UNDER') THEN player_lookup END) as actionable_predictions,
  ROUND(AVG(confidence), 1) as avg_confidence,
  ROUND(AVG(CASE WHEN recommendation IN ('OVER', 'UNDER') THEN confidence END), 1) as avg_actionable_confidence,
  COUNTIF(ARRAY_LENGTH(red_flags) > 0) as predictions_with_red_flags
FROM `nba_predictions.player_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- View 2: Model Performance Tracking
CREATE OR REPLACE VIEW `nba_predictions.model_performance` AS
SELECT
  model_version,
  COUNT(*) as total_predictions,
  ROUND(AVG(confidence), 1) as avg_confidence,
  COUNTIF(ARRAY_LENGTH(red_flags) = 0) as clean_predictions,
  COUNTIF(recommendation = 'PASS') as pass_count,
  ROUND(COUNTIF(recommendation = 'PASS') / COUNT(*) * 100, 1) as pass_rate
FROM `nba_predictions.player_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY model_version
ORDER BY total_predictions DESC;

-- View 3: Error Tracking
CREATE OR REPLACE VIEW `nba_predictions.prediction_errors` AS
SELECT
  DATE(timestamp) as error_date,
  jsonPayload.error_type,
  jsonPayload.player_lookup,
  jsonPayload.game_date,
  jsonPayload.error_message,
  timestamp
FROM `nba-data-warehouse-422817._Default._AllLogs`
WHERE resource.type = 'cloud_run_revision'
  AND resource.labels.service_name IN ('nba-prediction-coordinator', 'nba-prediction-worker')
  AND severity >= 'ERROR'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY timestamp DESC;
```

**4.3 Create Alert Policies**

Create: `/bin/alerts/setup_phase5_alerts.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"

echo "Setting up Phase 5 alerting..."

# Alert 1: Low Prediction Coverage
cat > /tmp/low_coverage_alert.yaml <<'EOF'
displayName: "NBA Phase 5 - Low Prediction Coverage"
conditions:
  - displayName: "Coverage below 90%"
    conditionThreshold:
      filter: 'metric.type="logging.googleapis.com/user/nba_prediction_coverage"'
      comparison: COMPARISON_LT
      thresholdValue: 90
      duration: 300s
notificationChannels: []
documentation:
  content: |
    ## Low Prediction Coverage Alert

    Less than 90% of scheduled players have predictions generated.

    **Investigation:**
    ```bash
    bq query --use_legacy_sql=false 'SELECT * FROM nba_predictions.daily_coverage WHERE game_date = CURRENT_DATE()'
    ```

    **Possible Causes:**
    - Phase 4 incomplete (missing ML features)
    - Prediction worker errors
    - BigQuery write failures

    See: /docs/04-deployment/ALERT-RUNBOOKS.md#low-prediction-coverage
EOF

gcloud alpha monitoring policies create \
  --policy-from-file=/tmp/low_coverage_alert.yaml \
  --project=${PROJECT_ID}

# Alert 2: High Prediction Error Rate
cat > /tmp/high_error_rate_alert.yaml <<'EOF'
displayName: "NBA Phase 5 - High Prediction Error Rate"
conditions:
  - displayName: "Error rate > 5% over 10 minutes"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision"
        AND (resource.labels.service_name="nba-prediction-coordinator" OR resource.labels.service_name="nba-prediction-worker")
        AND severity="ERROR"'
      comparison: COMPARISON_GT
      thresholdValue: 10
      duration: 600s
      aggregations:
        - alignmentPeriod: 60s
          perSeriesAligner: ALIGN_RATE
notificationChannels: []
documentation:
  content: |
    ## High Prediction Error Rate

    More than 10 errors per minute in prediction services.

    **Investigation:**
    ```bash
    bq query 'SELECT * FROM nba_predictions.prediction_errors WHERE error_date = CURRENT_DATE() LIMIT 20'
    ```

    See: /docs/04-deployment/ALERT-RUNBOOKS.md#high-prediction-errors
EOF

gcloud alpha monitoring policies create \
  --policy-from-file=/tmp/high_error_rate_alert.yaml \
  --project=${PROJECT_ID}

echo "✅ Phase 5 alerts configured"
```

**4.4 Create Dashboard**

```bash
# Add Phase 5 tiles to existing NBA dashboard
# (See Option B for dashboard creation process)
# Key tiles:
# - Prediction volume (line chart)
# - Coverage percentage (scorecard)
# - Average confidence (line chart)
# - Error rate (stacked bar)
```

---

### Step 5: End-to-End Validation (2 hours)

**5.1 Manual End-to-End Test**

```bash
# Test complete pipeline manually
echo "Testing end-to-end pipeline..."

# 1. Trigger Phase 4 for tomorrow's date
TOMORROW=$(date -d "tomorrow" +%Y-%m-%d)

curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://nba-processor-mlfs-...run.app/process \
  -d "{\"game_date\": \"$TOMORROW\"}"

# 2. Monitor Pub/Sub message
sleep 10
gcloud pubsub subscriptions pull nba-phase4-to-phase5 --limit=1

# 3. Check coordinator triggered
gcloud logging read "resource.type=\"cloud_run_revision\"
  resource.labels.service_name=\"nba-prediction-coordinator\"
  jsonPayload.game_date=\"$TOMORROW\"" \
  --limit 5

# 4. Verify predictions created
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count
FROM \`nba_predictions.player_predictions\`
WHERE game_date = '$TOMORROW'
"

# Expected: count > 0
```

**5.2 Production Autonomous Test**

```bash
# Let daily workflow run autonomously for 3 days
# Monitor each day:

for day in {1..3}; do
  DATE=$(date -d "+$day days" +%Y-%m-%d)

  echo "Checking predictions for $DATE..."

  # Wait until workflow should complete (around 11:45 PM ET)
  # Check predictions exist
  bq query --use_legacy_sql=false "
  SELECT
    COUNT(*) as total_predictions,
    COUNT(DISTINCT player_lookup) as unique_players,
    ROUND(AVG(confidence), 1) as avg_confidence
  FROM \`nba_predictions.player_predictions\`
  WHERE game_date = '$DATE'
  "

  # Check for errors
  gcloud logging read "resource.type=\"cloud_run_revision\"
    severity=\"ERROR\"
    timestamp>\"$(date -d "$DATE" +%Y-%m-%d)T00:00:00Z\"
    timestamp<\"$(date -d "$DATE +1 day" +%Y-%m-%d)T00:00:00Z\"" \
    --limit 20

done

# Success criteria:
# - Predictions generated for all 3 days
# - No manual intervention required
# - Error rate < 1%
```

**5.3 Coverage Validation**

```bash
# Ensure all scheduled players have predictions
bq query --use_legacy_sql=false '
WITH scheduled_players AS (
  SELECT
    game_date,
    LOWER(REPLACE(player_name, " ", "_")) as player_lookup
  FROM `nba_orchestration.nba_schedule` s
  JOIN `nba_raw.team_roster` r ON s.home_team = r.team_abbr OR s.away_team = r.team_abbr
  WHERE game_date >= CURRENT_DATE()
    AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
),
predictions AS (
  SELECT
    game_date,
    player_lookup
  FROM `nba_predictions.player_predictions`
  WHERE game_date >= CURRENT_DATE()
)
SELECT
  s.game_date,
  COUNT(DISTINCT s.player_lookup) as scheduled_players,
  COUNT(DISTINCT p.player_lookup) as predicted_players,
  ROUND(COUNT(DISTINCT p.player_lookup) / COUNT(DISTINCT s.player_lookup) * 100, 1) as coverage_pct
FROM scheduled_players s
LEFT JOIN predictions p USING (game_date, player_lookup)
GROUP BY s.game_date
ORDER BY s.game_date
'

# Expected: coverage_pct >= 95% for all dates
```

---

## Key Files & Locations

### New Files Created
```
/ml_models/nba/
└── train_xgboost_v1.py                # Model training script

/docker/
└── nba-prediction-coordinator.Dockerfile  # Coordinator container

/bin/predictions/deploy/
└── deploy_prediction_coordinator.sh   # Coordinator deployment

/bin/predictions/
├── setup_phase5_pubsub.sh            # Pub/Sub configuration
└── test_phase5_e2e.sh                # End-to-end test script

/bin/alerts/
└── setup_phase5_alerts.sh            # Phase 5 alert configuration

/docs/04-deployment/
└── PHASE5-DEPLOYMENT-GUIDE.md        # Deployment documentation
```

### Modified Files
```
/bin/predictions/deploy/deploy_prediction_worker.sh  # New model path
/data_processors/precompute/ml_feature_store_processor.py  # Pub/Sub publishing
```

---

## Testing & Validation Checklist

### Pre-Deployment
- [ ] XGBoost model trained with MAE ≤ 4.5
- [ ] Model saved to GCS successfully
- [ ] Coordinator code reviewed and tested locally
- [ ] Docker images build without errors

### Post-Deployment
- [ ] Worker health check passes with new model
- [ ] Coordinator health check passes
- [ ] Pub/Sub topic and subscription created
- [ ] Manual trigger generates predictions
- [ ] End-to-end test (Phase 4 → Pub/Sub → Coordinator → Worker) succeeds
- [ ] Predictions written to BigQuery correctly

### Production Validation
- [ ] 3 consecutive days of autonomous operation
- [ ] Prediction coverage ≥ 95%
- [ ] Error rate < 1%
- [ ] Alerts configured and tested
- [ ] Dashboard shows real-time metrics

---

## Rollback Procedure

### If New Model Performs Poorly

```bash
# Rollback to previous model
export XGBOOST_V1_MODEL_PATH="gs://nba-scraped-data/ml-models/nba_points_xgboost_v1_mock.json"
./bin/predictions/deploy/deploy_prediction_worker.sh

# Verify rollback
curl https://nba-prediction-worker-...run.app/ | jq '.model_versions'
```

### If Coordinator Fails

```bash
# Delete coordinator service
gcloud run services delete nba-prediction-coordinator --region us-central1

# Delete Pub/Sub subscription (stops auto-triggering)
gcloud pubsub subscriptions delete nba-phase4-to-phase5

# Manual predictions still possible via worker
curl -X POST https://nba-prediction-worker-...run.app/predict-batch ...
```

### If End-to-End Pipeline Breaks

```bash
# Disable Phase 4 → Phase 5 trigger
gcloud pubsub subscriptions update nba-phase4-to-phase5 \
  --push-endpoint="" \
  --ack-deadline=600

# Predictions can still be triggered manually via coordinator
```

---

## Estimated Timeline

- **Step 1** (Model Training): 4-5 hours (mostly training time)
- **Step 2** (Deploy Coordinator): 3-4 hours
- **Step 3** (Pub/Sub Integration): 2-3 hours
- **Step 4** (Monitoring): 3-4 hours
- **Step 5** (Validation): 2 hours

**Total: 14-18 hours** (including validation and testing)

---

## Success Metrics

### Technical Metrics
- [ ] XGBoost model validation MAE ≤ 4.5 points
- [ ] Prediction coverage ≥ 95% of scheduled players
- [ ] End-to-end latency < 10 minutes (Phase 4 complete → predictions in BigQuery)
- [ ] Error rate < 1%
- [ ] Zero manual interventions for 3+ days

### Business Metrics
- [ ] Predictions available before games start (≥2 hours lead time)
- [ ] Actionable predictions (OVER/UNDER) rate ≥ 60%
- [ ] Average confidence ≥ 65%

---

## References

- Prediction Worker: `/predictions/worker/worker.py`
- Prediction Coordinator: `/predictions/coordinator/coordinator.py`
- Phase 4 Processors: `/data_processors/precompute/`
- Deployment Runbook: `/docs/04-deployment/status.md`

---

**End of Handoff Document**
