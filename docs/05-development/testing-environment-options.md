# Testing & Staging Environment Options for NBA Stats Scraper Orchestrators

**Created:** February 12, 2026
**Session:** 206
**Purpose:** Evaluate options for safely testing orchestrator changes (IAM fixes, Cloud Function logic) without affecting production
**Status:** Research Complete - Recommendations Ready

## Executive Summary

After investigating GCP infrastructure, existing test frameworks, and industry best practices, we recommend a **Hybrid Multi-Layer Approach** combining:

1. **Local Emulator Testing** (immediate, $0 cost) - For unit tests and simple trigger verification
2. **Dataset-Prefix Staging** (low cost, ~$50-100/month) - For full pipeline integration testing
3. **Separate Staging Project** (high cost, duplicates production) - For critical changes before production

This document provides implementation guides for each option.

---

## 1. Option A: Local Emulator Testing (Recommended for Quick Iteration)

### Overview
Run Cloud Functions, Pub/Sub, and Firestore locally using emulators for fast, cost-free testing of orchestrator logic.

### Capabilities
| Component | Supported | Notes |
|-----------|-----------|-------|
| Cloud Functions code | ✅ Yes | Via Functions Framework |
| Pub/Sub triggers | ✅ Yes | Full emulation available |
| Firestore state | ✅ Yes | Full emulation available |
| Cloud Run HTTP | ✅ Yes | Test CloudRun-triggered endpoints |
| BigQuery | ❌ No | Cannot emulate - use local dataset prefix |
| Orchestrator IAM | ⚠️ Partial | Can test invoke logic, not actual IAM |

### Pros
- **Cost:** Free (local development only)
- **Speed:** Sub-second function execution vs 5-10s in cloud
- **Safety:** Fully isolated from production
- **Development Velocity:** Instant feedback loop
- **Debugging:** Full IDE/debugger support

### Cons
- **Limitations:** Cannot test actual IAM enforcement (needs staging environment)
- **Setup Time:** 30-45 minutes initial configuration
- **Maintenance:** Emulators must be kept in sync with GCP SDK updates
- **Not for IAM validation:** This is critical - you CANNOT test IAM actually working with emulators

### Implementation Guide

#### 1.1 Install Required Tools

```bash
# Install Google Cloud SDK (if not already installed)
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Initialize
gcloud init

# Install emulators
gcloud components install cloud-firestore-emulator pubsub-emulator

# Verify
gcloud beta emulators firestore start --help
gcloud beta emulators pubsub start --help
```

#### 1.2 Create Docker Compose Configuration

Create `.emulator/docker-compose.yml` for easy startup:

```yaml
version: '3.8'
services:
  pubsub:
    image: google/cloud-sdk:emulator
    ports:
      - "8085:8085"
    environment:
      - PUBSUB_PROJECT_ID=test-project
    entrypoint: /bin/bash -c "gcloud beta emulators pubsub start --host-port=0.0.0.0:8085"

  firestore:
    image: google/cloud-sdk:emulator
    ports:
      - "8080:8080"
    environment:
      - FIRESTORE_PROJECT_ID=test-project
    entrypoint: /bin/bash -c "gcloud beta emulators firestore start --host-port=0.0.0.0:8080"
```

#### 1.3 Setup Test Helper Script

Create `bin/testing/start-emulators.sh`:

```bash
#!/bin/bash
set -e

echo "Starting GCP emulators..."

# Start Pub/Sub emulator
gcloud beta emulators pubsub start &
PUBSUB_PID=$!
sleep 2

# Start Firestore emulator
gcloud beta emulators firestore start &
FIRESTORE_PID=$!
sleep 2

export PUBSUB_EMULATOR_HOST=localhost:8085
export FIRESTORE_EMULATOR_HOST=localhost:8080
export GOOGLE_CLOUD_PROJECT=test-project

echo "Emulators started:"
echo "  Pub/Sub: $PUBSUB_EMULATOR_HOST"
echo "  Firestore: $FIRESTORE_EMULATOR_HOST"
echo ""
echo "To stop: kill $PUBSUB_PID $FIRESTORE_PID"
```

#### 1.4 Write Orchestrator Unit Tests

Example: `tests/unit/orchestration/test_phase3_to_phase4_orchestrator_local.py`

```python
"""Test phase3_to_phase4 orchestrator logic with emulators"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from google.cloud import firestore
from google.cloud import pubsub_v1

@pytest.fixture
def firestore_client():
    """Use emulator Firestore client"""
    os.environ['FIRESTORE_EMULATOR_HOST'] = 'localhost:8080'
    return firestore.Client(project='test-project')

@pytest.fixture
def pubsub_client():
    """Use emulator Pub/Sub client"""
    os.environ['PUBSUB_EMULATOR_HOST'] = 'localhost:8085'
    return pubsub_v1.PublisherClient()

class TestPhase3To4OrchestratorLogic:
    """Test orchestrator state tracking and trigger logic"""

    def test_completeness_check_all_processors_complete(self, firestore_client):
        """Test that all processors completing triggers next phase"""
        # Set up test state
        doc = firestore_client.collection('phase3_completion').document('2026-02-11')
        doc.set({
            'processor_1': {'completed_at': '2026-02-11T10:30:00Z'},
            'processor_2': {'completed_at': '2026-02-11T10:31:00Z'},
            'processor_3': {'completed_at': '2026-02-11T10:32:00Z'},
        })

        # Simulate orchestrator logic
        doc_data = doc.get().to_dict()
        required = ['processor_1', 'processor_2', 'processor_3']
        all_complete = all(p in doc_data for p in required)

        assert all_complete is True

    def test_partial_completion_does_not_trigger(self, firestore_client):
        """Test that partial completion doesn't trigger"""
        doc = firestore_client.collection('phase3_completion').document('2026-02-11')
        doc.set({
            'processor_1': {'completed_at': '2026-02-11T10:30:00Z'},
            'processor_2': {'completed_at': '2026-02-11T10:31:00Z'},
            # processor_3 missing
        })

        doc_data = doc.get().to_dict()
        required = ['processor_1', 'processor_2', 'processor_3']
        all_complete = all(p in doc_data for p in required)

        assert all_complete is False
```

#### 1.5 Run Tests Against Emulators

```bash
# Start emulators in background
./bin/testing/start-emulators.sh &
EMULATOR_PID=$!

# Run tests
PYTHONPATH=. pytest tests/unit/orchestration/ -v

# Cleanup
kill $EMULATOR_PID
```

### Cost Analysis
- **Monthly Cost:** $0 (local-only, no cloud resources)
- **Setup Effort:** 30-45 minutes (one-time)
- **Best For:** Fast development iteration, unit testing, logic verification

### Limitations for Orchestrator Testing
⚠️ **Critical:** This option CANNOT test IAM validation because:
- Emulator Pub/Sub doesn't enforce actual IAM roles
- Firestore emulator doesn't check authentication
- Service account invoke permissions must be tested in actual GCP environment

**Verdict:** Use for unit tests, but MUST use staging environment for IAM fix validation.

---

## 2. Option B: Dataset-Prefix Staging (Recommended for Integration Testing)

### Overview
Use test datasets (`test_nba_analytics`, `test_nba_predictions`, etc.) in the production GCP project, reusing production Cloud Run services and Cloud Functions. This replicates the full pipeline on test data.

### Capabilities
| Component | Supported | Notes |
|-----------|-----------|-------|
| Cloud Functions | ✅ Yes | Reuses production |
| Pub/Sub | ✅ Yes | Test topics in production |
| Firestore | ✅ Yes | Orchestrator state tracking |
| BigQuery | ✅ Yes | Separate test datasets |
| Full pipeline | ✅ Yes | Phase 1-6 with test data |
| IAM testing | ✅ Yes | Uses real service accounts |

### Pros
- **Cost:** ~$50-100/month (query + storage on test datasets)
- **Completeness:** Tests entire pipeline including Pub/Sub, Cloud Functions, Firestore
- **IAM Testing:** Real service accounts used - can validate IAM fixes
- **Reuses Infrastructure:** No new services to deploy
- **Dataset Prefix Support:** Already partially implemented in codebase
- **Easy Cleanup:** Test datasets auto-expire in 7 days

### Cons
- **Code Changes:** Processors need DATASET_PREFIX support (partially done)
- **Message Pollution:** Test Pub/Sub messages in production environment
- **Query Costs:** Every test run incurs BigQuery costs
- **Staleness:** Can't guarantee test datasets stay in sync with production schema

### Implementation Guide

#### 2.1 Enable Dataset Prefix Support

Add environment variable support to all processors:

**File:** `data_processors/raw/processor_base.py`

```python
import os

# Add at module level
DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')
RAW_DATASET = f"{DATASET_PREFIX}nba_raw"
SOURCE_DATASET = f"{DATASET_PREFIX}nba_source"

# Update queries to use these variables
class RawProcessorBase:
    def __init__(self):
        self.raw_dataset = RAW_DATASET
        self.source_dataset = SOURCE_DATASET
```

**Similar updates needed for:**
- `data_processors/analytics/analytics_base.py` → `ANALYTICS_DATASET`
- `data_processors/precompute/precompute_base.py` → `PRECOMPUTE_DATASET`
- `predictions/worker/data_loaders.py` → `PREDICTIONS_DATASET`, `ANALYTICS_DATASET`

#### 2.2 Create Test Dataset Setup Script

Create `bin/testing/setup_staging_datasets.sh`:

```bash
#!/bin/bash
set -e

PROJECT_ID=${1:-nba-props-platform}
PREFIX=${2:-test_}

echo "Setting up test datasets with prefix: $PREFIX"

for dataset in nba_raw nba_analytics nba_predictions nba_precompute; do
    echo "Creating $PREFIX$dataset..."
    bq mk --dataset \
        --project_id=$PROJECT_ID \
        --default_table_expiration=604800 \
        --description="Test dataset - auto-expires in 7 days" \
        "$PREFIX$dataset" 2>/dev/null || echo "Dataset already exists"
done

echo "Test datasets ready"
echo ""
echo "To use these datasets:"
echo "  DATASET_PREFIX=$PREFIX gcloud run deploy [service]"
```

#### 2.3 Create Test Data Snapshot Script

Copy small sample of production data to test datasets:

```bash
#!/bin/bash
# bin/testing/seed_staging_data.sh

PROJECT_ID=nba-props-platform
PREFIX=test_
SAMPLE_DATE=${1:-2026-02-01}

echo "Seeding test datasets from $SAMPLE_DATE..."

# Copy nba_raw tables
for table in nbac_schedule nbac_play_by_play nbac_gamebook_player_stats; do
    echo "Copying $table..."
    bq query --project_id=$PROJECT_ID --nouse_legacy_sql \
        "CREATE OR REPLACE TABLE ${PREFIX}nba_raw.$table AS
         SELECT * FROM nba_raw.$table
         WHERE DATE(created_at) = '$SAMPLE_DATE'
         LIMIT 1000"
done

echo "Test data seeded"
```

#### 2.4 Create Test Deployment Script

Create `bin/testing/deploy_staging.sh`:

```bash
#!/bin/bash
set -e

SERVICE=${1:-prediction-worker}
PREFIX=${2:-test_}
PROJECT_ID="nba-props-platform"

echo "Deploying $SERVICE to staging with prefix: $PREFIX"

# Deploy Cloud Function with test prefix
if [[ "$SERVICE" == "phase"*"-orchestrator" ]]; then
    gcloud functions deploy "$SERVICE-staging" \
        --gen2 \
        --runtime=python311 \
        --region=us-west2 \
        --source=orchestration/cloud_functions/${SERVICE#phase*-to-phase*-} \
        --entry-point=main \
        --trigger-topic=test_nba-phase-trigger \
        --update-env-vars="DATASET_PREFIX=$PREFIX" \
        --project=$PROJECT_ID
else
    # For Cloud Run services
    gcloud run deploy "$SERVICE-staging" \
        --source="./${SERVICE%%-*}/$SERVICE" \
        --region=us-west2 \
        --platform=managed \
        --update-env-vars="DATASET_PREFIX=$PREFIX,GCS_PREFIX=test/" \
        --project=$PROJECT_ID
fi

echo "Deployment complete"
```

#### 2.5 Run Integration Tests

```bash
# Setup test datasets (one-time)
./bin/testing/setup_staging_datasets.sh

# Seed with test data
./bin/testing/seed_staging_data.sh 2026-02-10

# Deploy orchestrator with test prefix
DATASET_PREFIX=test_ ./bin/testing/deploy_staging.sh phase3-to-phase4-orchestrator

# Trigger processing (manual test)
curl https://phase3-to-phase4-orchestrator-staging-XXXXX.run.app/orchestrate \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"game_date":"2026-02-10"}'

# Validate results
bq query "SELECT COUNT(*) FROM test_nba_analytics.player_game_summary WHERE game_date='2026-02-10'"

# Cleanup (optional - datasets auto-expire in 7 days)
bq rm -r -d test_nba_analytics test_nba_predictions test_nba_raw test_nba_precompute
```

### Cost Analysis
| Component | Cost | Notes |
|-----------|------|-------|
| BigQuery Storage | ~$10-20/month | 100-200 GB test data |
| BigQuery Queries | ~$30-50/month | Test run queries |
| Cloud Run | ~$10/month | Service invocations |
| Pub/Sub | ~$5/month | Test messages |
| **Total** | **~$50-100/month** | With 10+ test runs per month |

### Timeline
- **Setup:** 2-3 hours (enable prefix support, create scripts)
- **Per Test Run:** 5-10 minutes (deploy, run, validate)
- **Iteration Speed:** Fast (datasets persist, reuse infrastructure)

### When to Use
✅ Testing orchestrator changes with IAM validation
✅ Full pipeline integration tests
✅ Performance testing
✅ Data quality validation

---

## 3. Option C: Separate Staging Project (Maximum Safety)

### Overview
Create a completely separate GCP project (`nba-props-platform-staging`) that mirrors production configuration. Provides complete isolation and full IAM testing capability.

### Capabilities
| Component | Supported | Notes |
|-----------|-----------|-------|
| Everything | ✅ Yes | Full production replica |
| IAM Testing | ✅ Yes | Separate service accounts, full testing |
| Data Isolation | ✅ Yes | No production data access |
| Deployment Testing | ✅ Yes | Test Cloud Build triggers |

### Pros
- **Safety:** Complete isolation from production
- **Realism:** 100% production replica, tests everything
- **Regression Testing:** Safe place to test breaking changes
- **Audit Trail:** Separate billing, clear resource tracking
- **Team Training:** Safe sandbox for operations team

### Cons
- **Cost:** Duplicates production (high variable costs)
- **Complexity:** Must synchronize infrastructure, service accounts, configs
- **Maintenance:** Keep staging configs in sync with production
- **Time to Setup:** 4-6 hours for initial setup
- **Monthly Cost:** $2000-5000+ depending on test volume

### Implementation Guide

#### 3.1 Create Staging Project

```bash
# Create project
gcloud projects create nba-props-platform-staging \
    --name="NBA Props Platform - Staging" \
    --folder=FOLDER_ID

PROJECT_ID=nba-props-platform-staging

# Enable APIs
gcloud services enable \
    bigquery.googleapis.com \
    cloudfunctions.googleapis.com \
    cloudscheduler.googleapis.com \
    firestore.googleapis.com \
    pubsub.googleapis.com \
    run.googleapis.com \
    --project=$PROJECT_ID

# Create service account
gcloud iam service-accounts create nba-orchestrator \
    --display-name="NBA Orchestrator - Staging" \
    --project=$PROJECT_ID
```

#### 3.2 Set Up BigQuery Datasets

```bash
# Mirror production schema
for dataset in nba_raw nba_analytics nba_predictions nba_precompute nba_orchestration; do
    bq mk --dataset \
        --project_id=$PROJECT_ID \
        $dataset
done

# Copy production schemas (no data)
bq show --schema --format=json nba-props-platform:nba_analytics.player_game_summary | \
    bq mk --table nba-props-platform-staging:nba_analytics.player_game_summary -
```

#### 3.3 Deploy Services to Staging

```bash
# Configure gcloud for staging project
gcloud config set project nba-props-platform-staging

# Deploy orchestrator
./bin/orchestrators/deploy_phase3_to_phase4.sh

# Deploy Cloud Run services
./bin/deploy-service.sh prediction-worker
```

### Cost Analysis
| Component | Production Cost | Staging Cost |
|-----------|--------|---|
| BigQuery | $500/month | $500/month |
| Cloud Functions | $100/month | $100/month |
| Cloud Run | $200/month | $200/month |
| Pub/Sub | $50/month | $50/month |
| Firestore | $100/month | $100/month |
| **Total** | **$950/month** | **$950/month** |

**Recommendation:** Only for critical orchestrator changes or major refactoring.

---

## Comparison Matrix

| Criteria | Local Emulators | Dataset Prefix | Separate Project |
|----------|---|---|---|
| **Setup Time** | 30-45 min | 2-3 hours | 4-6 hours |
| **Monthly Cost** | $0 | $50-100 | $2000-5000 |
| **IAM Testing** | ❌ No | ✅ Yes | ✅ Yes |
| **Full Pipeline** | ❌ Partial | ✅ Yes | ✅ Yes |
| **Iteration Speed** | ⚡ Fast | ⚡⚡ Medium | 🐌 Slow |
| **Data Isolation** | ✅ Yes | ⚠️ Shared project | ✅ Yes |
| **Development** | ✅ Best | ✅ Good | ⚠️ Heavy |
| **Pre-prod Testing** | ⚠️ Limited | ✅ Good | ✅ Best |

---

## Recommended Workflow

### For Orchestrator IAM Fixes (Session 205-206)

1. **Phase 1: Local Development** (Hours 0-1)
   - Write unit tests using local emulators
   - Test orchestrator state logic, completeness checks
   - Verify message publishing logic

   ```bash
   ./bin/testing/start-emulators.sh &
   PYTHONPATH=. pytest tests/unit/orchestration/ -v
   ```

2. **Phase 2: Staging Integration Test** (Hours 1-3)
   - Deploy to staging with dataset prefix
   - Run full orchestrator flow with real Pub/Sub, Firestore
   - **Validate IAM fixes are working**

   ```bash
   # Setup staging
   ./bin/testing/setup_staging_datasets.sh

   # Deploy with test prefix
   DATASET_PREFIX=test_ ./bin/testing/deploy_staging.sh phase3-to-phase4-orchestrator

   # Test IAM validation
   PYTHONPATH=. pytest tests/integration/test_orchestrator_deployment.py -v
   ```

3. **Phase 3: Production Deployment** (Minutes to Hours)
   - Auto-deploy via Cloud Build on git push
   - Monitor first 24 hours with metrics

---

## Quick Start: Set Up Option B (Recommended)

```bash
# 1. Create test datasets
./bin/testing/setup_staging_datasets.sh

# 2. Seed with sample data
./bin/testing/seed_staging_data.sh 2026-02-10

# 3. Deploy orchestrator with test prefix
DATASET_PREFIX=test_ \
gcloud functions deploy phase3-to-phase4-orchestrator-staging \
    --gen2 \
    --runtime=python311 \
    --region=us-west2 \
    --source=orchestration/cloud_functions/phase3_to_phase4 \
    --entry-point=orchestrate_phase3_to_phase4 \
    --trigger-topic=test_nba-phase3-analytics-complete \
    --update-env-vars=DATASET_PREFIX=test_

# 4. Run integration tests
PYTHONPATH=. pytest tests/integration/test_orchestrator_deployment.py -v
```

---

## Related Documentation

- **Session 205 Handoff:** `docs/09-handoff/2026-02-12-SESSION-205-HANDOFF.md` - IAM permission fix
- **Session 206 Handoff:** `docs/09-handoff/2026-02-12-SESSION-206-HANDOFF.md` - Testing infrastructure
- **Unit Tests:** `tests/unit/validation/test_orchestrator_iam_check.py`
- **Integration Tests:** `tests/integration/test_orchestrator_deployment.py`
- **CLAUDE.md:** Health checks and deployment procedures

---

## References

Testing and emulation:
- [Testing apps locally with the emulator | Pub/Sub | Google Cloud](https://docs.cloud.google.com/pubsub/docs/emulator)
- [Firebase Local Emulator Suite](https://firebase.google.com/docs/emulator-suite)
- [Use Firestore emulator locally](https://docs.cloud.google.com/firestore/native/docs/emulator)
- [Local functions development | Cloud Run](https://cloud.google.com/functions/docs/functions-framework)

Cost analysis:
- [BigQuery Pricing](https://cloud.google.com/bigquery/pricing)
- [Cloud Functions Pricing](https://cloud.google.com/functions/pricing)

---

**Document Created:** Session 206 (February 12, 2026)
**Next Steps:** Implement Option B (Dataset-Prefix Staging) for orchestrator IAM testing
