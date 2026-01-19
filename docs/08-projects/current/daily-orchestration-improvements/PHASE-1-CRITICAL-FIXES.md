# Phase 1: Critical Fixes - Implementation Guide

**Status:** 🟡 In Progress
**Start Date:** January 18, 2026
**Target Completion:** January 25, 2026
**Estimated Effort:** 16 hours
**Priority:** P0 - Critical

---

## 📋 Overview

Phase 1 addresses the most critical orchestration failures that cause complete pipeline blockage or data loss. These fixes provide immediate value by preventing the January 18, 2026 all-or-nothing blocking issue and the January 17, 2026 race condition.

---

## ✅ Task 1: Deploy Health Endpoints to Production

**Status:** ⚪ Not Started
**Effort:** 4 hours
**Priority:** P0

### Context
Health endpoints were implemented in Session 111-112 and deployed to staging in Session 114. All 6 services have health endpoint code integrated but production services have not been redeployed with the new endpoints.

### Services to Deploy
1. `prediction-coordinator` - Already deployed to staging
2. `mlb-prediction-worker` - Already deployed to staging
3. `prediction-worker` (NBA) - Already deployed to staging
4. `nba-admin-dashboard` - Already deployed to staging
5. `analytics-processor` - Already deployed to staging
6. `precompute-processor` - Already deployed to staging

### Health Endpoints Provided
- `GET /health` - Liveness probe (<100ms response)
- `GET /ready` - Readiness probe with dependency checks (<5s response)
- `GET /health/deep` - Backward compatibility alias

### Implementation Steps

#### 1.1 Pre-Deployment Validation (30 min)
```bash
# Verify staging health endpoints are working
for service in prediction-coordinator mlb-prediction-worker prediction-worker nba-admin-dashboard analytics-processor precompute-processor; do
    echo "Checking $service..."
    curl -s "https://staging---${service}-f7p3g7f6ya-wl.a.run.app/health" | jq '.status'
    curl -s "https://staging---${service}-f7p3g7f6ya-wl.a.run.app/ready" | jq '.status'
done
```

**Expected Output:**
- `/health` → `{"status": "healthy"}`
- `/ready` → `{"status": "ready"}` or `{"status": "degraded"}` with details

#### 1.2 Production Deployment Using Canary Script (3 hours)

Use the canary deployment script from Session 112:

```bash
# Deploy each service with canary rollout
cd /home/naji/code/nba-stats-scraper

# Service 1: Prediction Coordinator
./bin/deploy/canary_deploy.sh prediction-coordinator \
  --image gcr.io/nba-props-platform/prediction-coordinator:staging-20260118-220835 \
  --monitoring-duration 60

# Service 2: MLB Prediction Worker
./bin/deploy/canary_deploy.sh mlb-prediction-worker \
  --image gcr.io/nba-props-platform/mlb-prediction-worker:staging-20260118-221835 \
  --monitoring-duration 60

# Service 3: NBA Prediction Worker
./bin/deploy/canary_deploy.sh prediction-worker \
  --image gcr.io/nba-props-platform/prediction-worker:staging-20260118-222945 \
  --monitoring-duration 60

# Service 4: Admin Dashboard
./bin/deploy/canary_deploy.sh nba-admin-dashboard \
  --image gcr.io/nba-props-platform/nba-admin-dashboard:staging-20260118-223811 \
  --monitoring-duration 60

# Service 5: Analytics Processor
./bin/deploy/canary_deploy.sh analytics-processor \
  --image gcr.io/nba-props-platform/analytics-processor:staging-20260118-224738 \
  --monitoring-duration 60

# Service 6: Precompute Processor
./bin/deploy/canary_deploy.sh precompute-processor \
  --image gcr.io/nba-props-platform/precompute-processor:staging-20260118-225508 \
  --monitoring-duration 60
```

**Canary Rollout Flow:**
1. Deploy to 5% traffic
2. Run smoke tests (includes `/health` and `/ready` checks)
3. Monitor for 60 seconds
4. If healthy → scale to 50%
5. Monitor for 60 seconds
6. If healthy → scale to 100%
7. If unhealthy at any stage → automatic rollback

#### 1.3 Configure Cloud Run Health Probes (30 min)

For each service, configure native Cloud Run health checks:

```bash
# Update each service with liveness and startup probes
for service in prediction-coordinator mlb-prediction-worker prediction-worker nba-admin-dashboard analytics-processor precompute-processor; do
    gcloud run services update $service \
      --region=us-west2 \
      --platform=managed \
      --project=nba-props-platform \
      --set-liveness-check path=/health,initial-delay=10,period=10,timeout=3,failure-threshold=3 \
      --set-startup-check path=/ready,initial-delay=0,period=5,timeout=10,failure-threshold=12
done
```

**Probe Configuration:**
- **Liveness Probe**: Checks if service is alive (kills unhealthy containers)
  - Path: `/health`
  - Initial delay: 10s
  - Period: 10s
  - Timeout: 3s
  - Failure threshold: 3 (30 seconds of failures triggers restart)

- **Startup Probe**: Checks if service is ready to receive traffic
  - Path: `/ready`
  - Initial delay: 0s
  - Period: 5s
  - Timeout: 10s
  - Failure threshold: 12 (allows 60 seconds for startup)

#### 1.4 Post-Deployment Validation (1 hour)

```bash
# Test production health endpoints
for service in prediction-coordinator mlb-prediction-worker prediction-worker nba-admin-dashboard analytics-processor precompute-processor; do
    echo "=== Testing $service ==="

    # Get production URL
    url=$(gcloud run services describe $service \
      --region=us-west2 \
      --project=nba-props-platform \
      --format='value(status.url)')

    # Test health endpoints
    echo "Health: $(curl -s $url/health | jq -r '.status')"
    echo "Ready: $(curl -s $url/ready | jq -r '.status')"
    echo ""
done
```

**Success Criteria:**
- All services return 200 OK for `/health`
- All services return 200 OK for `/ready` (may show "degraded" with warnings)
- Cloud Run shows services as healthy in console
- No error spikes in Cloud Logging

### Rollback Plan
If any service shows issues:
```bash
# Rollback to previous revision
gcloud run services update-traffic $SERVICE_NAME \
  --region=us-west2 \
  --project=nba-props-platform \
  --to-revisions PREVIOUS_REVISION=100
```

### Documentation Updates
- [ ] Update `docs/01-architecture/services/` with health endpoint URLs
- [ ] Update runbook with health check verification steps
- [ ] Document Cloud Run probe configuration

---

## ✅ Task 2: Add Pre-Flight Health Checks to Phase 3→4 Orchestrator

**Status:** ⚪ Not Started
**Effort:** 2 hours
**Priority:** P0

### Context
The Phase 3→4 orchestrator currently triggers Phase 4 processors immediately when all Phase 3 processors complete. This doesn't verify that Phase 4 services are healthy and ready to process data, leading to failures like the January 18 Firestore ImportError.

### File to Modify
`orchestration/cloud_functions/phase3_to_phase4/main.py`

### Current Code Pattern
```python
# Line ~95 in main.py
if completed_count >= EXPECTED_PROCESSORS:
    logger.info(f"All {EXPECTED_PROCESSORS} Phase 3 processors complete. Triggering Phase 4.")

    # Publish trigger message
    publish_to_pubsub(
        project_id=project_id,
        topic_name="nba-phase4-trigger",
        message=message_data
    )
```

### Enhanced Code with Health Checks

```python
import requests
from typing import Dict, Any

def check_service_health(service_url: str, timeout: int = 5) -> Dict[str, Any]:
    """
    Check if a service is healthy and ready to process requests.

    Args:
        service_url: Base URL of the service
        timeout: Request timeout in seconds

    Returns:
        Dict with status and details
    """
    try:
        response = requests.get(
            f"{service_url}/ready",
            timeout=timeout
        )
        response.raise_for_status()
        health_data = response.json()

        return {
            "healthy": health_data.get("status") in ["ready", "degraded"],
            "status": health_data.get("status"),
            "details": health_data
        }
    except Exception as e:
        logger.error(f"Health check failed for {service_url}: {e}")
        return {
            "healthy": False,
            "status": "unreachable",
            "error": str(e)
        }

def trigger_phase4_with_health_check(
    project_id: str,
    game_date: str,
    message_data: Dict[str, Any],
    entities_changed: set
):
    """
    Trigger Phase 4 only if downstream services are healthy.

    If services are unhealthy, schedule a retry in 5 minutes.
    """
    # Get Phase 4 service URLs from environment or config
    phase4_services = [
        os.getenv("ANALYTICS_PROCESSOR_URL"),
        os.getenv("PRECOMPUTE_PROCESSOR_URL")
    ]

    # Check health of all Phase 4 services
    all_healthy = True
    health_status = {}

    for service_url in phase4_services:
        if not service_url:
            continue

        service_name = service_url.split('/')[-1]
        health = check_service_health(service_url)
        health_status[service_name] = health

        if not health["healthy"]:
            all_healthy = False
            logger.warning(
                f"Phase 4 service {service_name} not ready: {health['status']}"
            )

    if all_healthy:
        # All services healthy - trigger Phase 4
        logger.info("All Phase 4 services healthy. Triggering Phase 4.")
        publish_to_pubsub(
            project_id=project_id,
            topic_name="nba-phase4-trigger",
            message=message_data
        )

        # Update Firestore with trigger timestamp
        update_firestore_trigger_status(
            game_date=game_date,
            triggered=True,
            health_checks=health_status
        )
    else:
        # Services unhealthy - schedule retry
        logger.warning(
            f"Phase 4 services not ready. Scheduling retry in 5 minutes. "
            f"Health status: {health_status}"
        )

        # Schedule retry via Cloud Tasks or Pub/Sub with delay
        schedule_phase4_retry(
            game_date=game_date,
            message_data=message_data,
            delay_seconds=300  # 5 minutes
        )

        # Send alert to on-call
        send_alert(
            severity="warning",
            message=f"Phase 4 trigger delayed - services not ready for {game_date}",
            details=health_status
        )

# Update main handler
if completed_count >= expected_processors:
    trigger_phase4_with_health_check(
        project_id=project_id,
        game_date=game_date,
        message_data=message_data,
        entities_changed=entities_changed
    )
```

### Environment Variables to Add

Add to Cloud Function configuration:
```bash
ANALYTICS_PROCESSOR_URL=https://analytics-processor-f7p3g7f6ya-wl.a.run.app
PRECOMPUTE_PROCESSOR_URL=https://precompute-processor-f7p3g7f6ya-wl.a.run.app
HEALTH_CHECK_TIMEOUT=5
RETRY_DELAY_SECONDS=300
```

### Testing

1. **Unit Test**: Mock health check responses
```python
def test_trigger_with_healthy_services():
    # Mock requests.get to return healthy status
    # Verify publish_to_pubsub is called
    pass

def test_trigger_with_unhealthy_services():
    # Mock requests.get to return unhealthy status
    # Verify retry is scheduled
    pass
```

2. **Integration Test**: Deploy to staging and test
```bash
# Manually trigger Phase 3→4 orchestrator
# Temporarily stop Phase 4 service to simulate unhealthy state
# Verify orchestrator schedules retry instead of triggering
```

### Deployment

```bash
cd orchestration/cloud_functions/phase3_to_phase4

# Deploy updated function
gcloud functions deploy phase3_to_phase4 \
  --region=us-west2 \
  --runtime=python311 \
  --trigger-topic=nba-phase3-analytics-complete \
  --entry-point=phase3_to_phase4_handler \
  --set-env-vars ANALYTICS_PROCESSOR_URL=https://analytics-processor-f7p3g7f6ya-wl.a.run.app,PRECOMPUTE_PROCESSOR_URL=https://precompute-processor-f7p3g7f6ya-wl.a.run.app \
  --project=nba-props-platform
```

---

## ✅ Task 3: Add Pre-Flight Health Checks to Phase 4→5 Orchestrator

**Status:** ⚪ Not Started
**Effort:** 2 hours
**Priority:** P0

### Context
Similar to Task 2, but for Phase 4→5 transition. This orchestrator triggers the Prediction Coordinator, which is critical for revenue (predictions must be ready before game time).

### File to Modify
`orchestration/cloud_functions/phase4_to_phase5/main.py`

### Current Code Pattern
```python
# After data freshness validation (R-006)
if all_data_fresh:
    trigger_prediction_coordinator(
        coordinator_url=coordinator_url,
        game_date=game_date,
        correlation_id=correlation_id
    )
```

### Enhanced Code
```python
def trigger_coordinator_with_health_check(
    coordinator_url: str,
    game_date: str,
    correlation_id: str
):
    """
    Trigger Prediction Coordinator only if it's healthy and ready.
    """
    # Check coordinator health
    health = check_service_health(coordinator_url)

    if not health["healthy"]:
        logger.warning(
            f"Prediction Coordinator not ready: {health['status']}. "
            f"Scheduling retry in 5 minutes."
        )

        schedule_coordinator_retry(
            game_date=game_date,
            correlation_id=correlation_id,
            delay_seconds=300
        )

        send_alert(
            severity="critical",  # High severity - affects revenue
            message=f"Prediction Coordinator not ready for {game_date}",
            details=health
        )
        return

    # Coordinator is healthy - trigger predictions
    logger.info("Prediction Coordinator healthy. Triggering Phase 5.")

    response = requests.post(
        f"{coordinator_url}/start",
        json={
            "game_date": game_date,
            "correlation_id": correlation_id,
            "mode": "batch"
        },
        timeout=30
    )

    response.raise_for_status()
    logger.info(f"Phase 5 triggered successfully: {response.json()}")
```

### Environment Variables
```bash
PREDICTION_COORDINATOR_URL=https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app
```

---

## ✅ Task 4: Implement Mode-Aware Orchestration

**Status:** ⚪ Not Started
**Effort:** 4 hours
**Priority:** P0

### Context
The Phase 3→4 orchestrator currently expects all 5 processors to complete regardless of whether it's overnight mode (processing yesterday's games) or same-day mode (processing today/tomorrow's games). This mismatch causes pipeline blocking.

### Modes Explained

**Overnight Mode** (runs 6:00 AM - 8:00 AM ET):
- Processing: Yesterday's completed games
- Expected processors: ALL 5
  1. `player_game_summary` (historical)
  2. `team_defense_game_summary` (historical)
  3. `team_offense_game_summary` (historical)
  4. `upcoming_player_game_context` (for today)
  5. `upcoming_team_game_context` (for today)

**Same-Day Mode** (runs 10:30 AM ET):
- Processing: Today's upcoming games
- Expected processors: 1-2
  1. `upcoming_player_game_context` (critical)
  2. `upcoming_team_game_context` (optional)

**Tomorrow Mode** (runs 5:00 PM ET):
- Processing: Tomorrow's games
- Expected processors: 1-2
  1. `upcoming_player_game_context` (critical)
  2. `upcoming_team_game_context` (optional)

### Mode Detection Logic

Add to `orchestration/cloud_functions/phase3_to_phase4/main.py`:

```python
from datetime import datetime, timedelta
import pytz

def detect_orchestration_mode(
    game_date: str,
    current_time: datetime = None
) -> str:
    """
    Detect orchestration mode based on game_date and current time.

    Args:
        game_date: Target game date (YYYY-MM-DD)
        current_time: Current timestamp (defaults to now in ET)

    Returns:
        Mode: 'overnight', 'same_day', or 'tomorrow'
    """
    if current_time is None:
        et_tz = pytz.timezone('America/New_York')
        current_time = datetime.now(et_tz)

    game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
    current_date = current_time.date()

    # Determine mode based on date relationship
    if game_dt < current_date:
        return 'overnight'  # Processing yesterday's games
    elif game_dt == current_date:
        return 'same_day'  # Processing today's games
    else:
        return 'tomorrow'  # Processing tomorrow's games

def get_expected_processors_for_mode(mode: str) -> tuple:
    """
    Get expected processor list based on orchestration mode.

    Returns:
        Tuple of (expected_count, critical_processors, optional_processors)
    """
    if mode == 'overnight':
        return (
            5,  # Expected count
            {   # Critical processors
                'player_game_summary',
                'upcoming_player_game_context'
            },
            {   # Optional processors
                'team_defense_game_summary',
                'team_offense_game_summary',
                'upcoming_team_game_context'
            }
        )
    elif mode in ['same_day', 'tomorrow']:
        return (
            1,  # Expected count
            {   # Critical processors
                'upcoming_player_game_context'
            },
            {   # Optional processors
                'upcoming_team_game_context'
            }
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")

# Update main handler
def phase3_to_phase4_handler(event, context):
    """Enhanced handler with mode detection."""
    # ... existing setup code ...

    # Detect mode
    mode = detect_orchestration_mode(game_date)
    logger.info(f"Detected orchestration mode: {mode} for game_date={game_date}")

    # Get expected processors for this mode
    expected_count, critical_processors, optional_processors = \
        get_expected_processors_for_mode(mode)

    # Check completion
    completed_set = set(completion_data.keys())
    critical_complete = critical_processors.issubset(completed_set)
    total_complete = len(completed_set)

    logger.info(
        f"Completion status: {total_complete}/{expected_count} total, "
        f"critical={'yes' if critical_complete else 'NO'}"
    )

    # Decision logic
    should_trigger = False
    trigger_reason = None

    if total_complete >= expected_count and critical_complete:
        # All expected processors complete
        should_trigger = True
        trigger_reason = "all_complete"
    elif critical_complete and total_complete >= (expected_count * 0.6):
        # Critical processors + 60% of total
        should_trigger = True
        trigger_reason = "critical_plus_majority"
    else:
        logger.info(
            f"Not triggering Phase 4: critical_complete={critical_complete}, "
            f"total={total_complete}, expected={expected_count}"
        )
        return

    # Trigger with health checks
    if should_trigger:
        logger.info(f"Triggering Phase 4 (reason: {trigger_reason})")
        trigger_phase4_with_health_check(
            project_id=project_id,
            game_date=game_date,
            message_data={
                **message_data,
                "mode": mode,
                "trigger_reason": trigger_reason
            },
            entities_changed=entities_changed
        )
```

### Configuration Update

Add to `predictions/coordinator/shared/config/orchestration_config.py`:

```python
class ModeAwareConfig:
    """Configuration for mode-aware orchestration."""

    OVERNIGHT_MODE = {
        "expected_processors": 5,
        "critical": ["player_game_summary", "upcoming_player_game_context"],
        "optional": ["team_defense_game_summary", "team_offense_game_summary", "upcoming_team_game_context"],
        "majority_threshold": 0.8  # 80% of expected
    }

    SAME_DAY_MODE = {
        "expected_processors": 1,
        "critical": ["upcoming_player_game_context"],
        "optional": ["upcoming_team_game_context"],
        "majority_threshold": 1.0  # Must have critical
    }

    TOMORROW_MODE = {
        "expected_processors": 1,
        "critical": ["upcoming_player_game_context"],
        "optional": ["upcoming_team_game_context"],
        "majority_threshold": 1.0  # Must have critical
    }
```

### Testing

```python
def test_overnight_mode_detection():
    # Game date is yesterday
    mode = detect_orchestration_mode('2026-01-17')
    assert mode == 'overnight'

def test_same_day_mode_detection():
    # Game date is today
    mode = detect_orchestration_mode(datetime.now().strftime('%Y-%m-%d'))
    assert mode == 'same_day'

def test_tomorrow_mode_detection():
    # Game date is tomorrow
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    mode = detect_orchestration_mode(tomorrow)
    assert mode == 'tomorrow'

def test_expected_processors_overnight():
    count, critical, optional = get_expected_processors_for_mode('overnight')
    assert count == 5
    assert 'player_game_summary' in critical

def test_triggering_with_critical_only():
    # Simulate: only critical processors complete
    # Should trigger if critical + 60% of total
    pass
```

---

## ✅ Task 5: Create Automated Daily Health Check Scheduler

**Status:** ⚪ Not Started
**Effort:** 4 hours
**Priority:** P1

### Context
Currently, daily health checks are performed manually using `bin/orchestration/quick_health_check.sh`. This should be automated to run at 8:00 AM ET daily and send a summary to Slack.

### Implementation

#### 5.1 Create Enhanced Health Check Script

Create new file: `bin/orchestration/automated_daily_health_check.sh`

```bash
#!/bin/bash
# Automated daily health check with service health verification
# Runs at 8:00 AM ET via Cloud Scheduler

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL}"  # From Secret Manager

echo "=== Daily Health Check: $(date) ==="

# 1. Check pipeline execution status
echo "Checking pipeline execution..."
python3 bin/orchestration/quick_health_check.py --json > /tmp/pipeline_health.json

# 2. Check service health endpoints
echo "Checking service health endpoints..."

SERVICES=(
    "prediction-coordinator"
    "mlb-prediction-worker"
    "prediction-worker"
    "nba-admin-dashboard"
    "analytics-processor"
    "precompute-processor"
)

SERVICE_HEALTH=()

for service in "${SERVICES[@]}"; do
    url=$(gcloud run services describe "$service" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.url)')

    if [ -z "$url" ]; then
        echo "⚠️  $service: URL not found"
        SERVICE_HEALTH+=("$service: unreachable")
        continue
    fi

    # Check /ready endpoint
    status=$(curl -s -w "%{http_code}" -o /tmp/health_response.json "$url/ready" || echo "000")

    if [ "$status" == "200" ]; then
        ready_status=$(jq -r '.status' /tmp/health_response.json)
        echo "✅ $service: $ready_status"
        SERVICE_HEALTH+=("$service: $ready_status")
    else
        echo "❌ $service: HTTP $status"
        SERVICE_HEALTH+=("$service: failed ($status)")
    fi
done

# 3. Check yesterday's grading completeness
echo "Checking yesterday's grading..."
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

grading_query="
SELECT
    COUNT(*) as graded_count,
    COUNT(*) * 100.0 / (SELECT COUNT(*) FROM nba_predictions.v8_predictions WHERE game_date = '$YESTERDAY') as coverage_pct
FROM nba_predictions.v8_predictions
WHERE game_date = '$YESTERDAY'
AND actual_result IS NOT NULL
"

grading_result=$(bq query --format=json --use_legacy_sql=false "$grading_query")
grading_count=$(echo "$grading_result" | jq -r '.[0].graded_count')
grading_coverage=$(echo "$grading_result" | jq -r '.[0].coverage_pct')

echo "Grading: $grading_count predictions graded ($grading_coverage%)"

# 4. Check today's prediction readiness
echo "Checking today's predictions..."
TODAY=$(date +%Y-%m-%d)

prediction_query="
SELECT COUNT(*) as prediction_count
FROM nba_predictions.v8_predictions
WHERE game_date = '$TODAY'
"

prediction_result=$(bq query --format=json --use_legacy_sql=false "$prediction_query")
prediction_count=$(echo "$prediction_result" | jq -r '.[0].prediction_count')

echo "Today's predictions: $prediction_count"

# 5. Determine overall health
OVERALL_HEALTH="✅ HEALTHY"
ALERT_LEVEL="info"

if (( $(echo "$grading_coverage < 95" | bc -l) )); then
    OVERALL_HEALTH="⚠️  DEGRADED"
    ALERT_LEVEL="warning"
fi

if [ "$prediction_count" -lt "100" ]; then
    OVERALL_HEALTH="❌ UNHEALTHY"
    ALERT_LEVEL="critical"
fi

# 6. Send Slack notification
cat > /tmp/slack_message.json <<EOF
{
    "text": "Daily Health Check - $(date +%Y-%m-%d)",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🏥 Daily Health Check: $OVERALL_HEALTH"
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "*Yesterday's Grading*\n$grading_count predictions ($grading_coverage%)"
                },
                {
                    "type": "mrkdwn",
                    "text": "*Today's Predictions*\n$prediction_count ready"
                }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Service Health:*\n$(printf '%s\n' "${SERVICE_HEALTH[@]}" | sed 's/^/• /')"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Automated check at $(date +%H:%M) ET | <https://console.cloud.google.com/run?project=$PROJECT_ID|Cloud Run Console>"
                }
            ]
        }
    ]
}
EOF

curl -X POST -H 'Content-type: application/json' \
    --data @/tmp/slack_message.json \
    "$SLACK_WEBHOOK_URL"

echo "Health check complete: $OVERALL_HEALTH"
```

#### 5.2 Create Cloud Scheduler Job

```bash
# Create Cloud Scheduler job for daily health check
gcloud scheduler jobs create http daily-health-check \
    --location=us-west2 \
    --schedule="0 8 * * * America/New_York" \
    --uri="https://cloud-function-url/daily-health-check" \
    --http-method=POST \
    --oidc-service-account-email=orchestration@nba-props-platform.iam.gserviceaccount.com \
    --time-zone="America/New_York" \
    --description="Automated daily health check at 8 AM ET"
```

#### 5.3 Create Cloud Function to Run Check

Create `orchestration/cloud_functions/daily_health_check/main.py`:

```python
import subprocess
import logging
from flask import Request

logger = logging.getLogger(__name__)

def daily_health_check_handler(request: Request):
    """
    Cloud Function to run automated daily health check.
    Triggered by Cloud Scheduler at 8:00 AM ET.
    """
    logger.info("Starting automated daily health check")

    try:
        # Run health check script
        result = subprocess.run(
            ["/bin/bash", "bin/orchestration/automated_daily_health_check.sh"],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes max
        )

        if result.returncode == 0:
            logger.info(f"Health check completed successfully:\n{result.stdout}")
            return {"status": "success", "output": result.stdout}, 200
        else:
            logger.error(f"Health check failed:\n{result.stderr}")
            return {"status": "error", "error": result.stderr}, 500

    except subprocess.TimeoutExpired:
        logger.error("Health check timed out after 5 minutes")
        return {"status": "error", "error": "Timeout"}, 500
    except Exception as e:
        logger.error(f"Health check exception: {e}")
        return {"status": "error", "error": str(e)}, 500
```

#### 5.4 Testing

```bash
# Test script locally
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
bash bin/orchestration/automated_daily_health_check.sh

# Test Cloud Function
gcloud functions call daily-health-check \
    --region=us-west2 \
    --project=nba-props-platform
```

---

## 📊 Success Criteria

All Phase 1 tasks complete when:

- [ ] All 6 services have health endpoints responding in production
- [ ] Cloud Run health probes configured for all services
- [ ] Phase 3→4 orchestrator validates downstream health before triggering
- [ ] Phase 4→5 orchestrator validates coordinator health before triggering
- [ ] Mode detection logic deployed and tested (overnight/same-day/tomorrow)
- [ ] Daily health check running automatically at 8 AM ET with Slack notifications
- [ ] Zero pipeline blockages due to all-or-nothing completion
- [ ] Zero service trigger failures due to unhealthy downstream services

---

## 📝 Rollback Plan

If Phase 1 changes cause issues:

1. **Health Endpoint Deployment**: Rollback individual services to previous revision
2. **Orchestrator Changes**: Disable health checks via environment variable
3. **Mode-Aware Logic**: Fall back to hardcoded expected_count=5
4. **Daily Check**: Pause Cloud Scheduler job

---

## 🔄 Next Phase

Upon Phase 1 completion, proceed to **Phase 2: Data Validation** which adds:
- Data freshness validation to Phase 2→3 and Phase 3→4
- Game completeness health checks
- Missing overnight schedulers

---

**Last Updated:** January 18, 2026
