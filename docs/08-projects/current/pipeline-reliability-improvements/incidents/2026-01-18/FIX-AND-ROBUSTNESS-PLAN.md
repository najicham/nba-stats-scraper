# Fix and Robustness Plan: 2026-01-18 Incident Recovery

**Created:** January 18, 2026
**Status:** Ready for Implementation
**Timeline:** Immediate (P0) → 4 Weeks (Long-term)
**Goals:** Fix immediate issues + Prevent future occurrences + Build self-healing capabilities

---

## Table of Contents

1. [Immediate Fixes (Today)](#immediate-fixes-today)
2. [Short-Term Improvements (This Week)](#short-term-improvements-this-week)
3. [Medium-Term Robustness (Week 2-3)](#medium-term-robustness-week-2-3)
4. [Long-Term Self-Healing (Week 4+)](#long-term-self-healing-week-4)
5. [Testing & Validation Strategy](#testing--validation-strategy)
6. [Success Metrics](#success-metrics)
7. [Rollback Plans](#rollback-plans)

---

## Immediate Fixes (Today)

**Goal:** Restore full operational capability within 2 hours

### Fix 1: Firestore Dependency (5 minutes) - CRITICAL

**Problem:** Worker crashes due to missing `google-cloud-firestore` dependency

**Files:**
- `/home/naji/code/nba-stats-scraper/predictions/worker/requirements.txt`

**Implementation:**
```bash
cd /home/naji/code/nba-stats-scraper

# Add dependency
cat >> predictions/worker/requirements.txt << 'EOF'
google-cloud-firestore==2.14.0
EOF

# Commit
git add predictions/worker/requirements.txt
git commit -m "fix(predictions): Add missing google-cloud-firestore dependency for distributed lock

- Fixes ImportError at worker.py:556
- Distributed lock feature from Session 92 requires Firestore
- Already present in coordinator, now added to worker
- Prevents Pub/Sub retry storms during grading"

# Deploy
cd predictions/worker
gcloud run deploy prediction-worker \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform \
  --platform=managed \
  --timeout=3600
```

**Verification:**
```bash
# Check deployment status
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="value(status.url)"

# Monitor logs for successful Firestore import
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND severity>=WARNING' \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)"

# Verify no ImportError
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND textPayload:"ImportError"' \
  --limit=5
```

**Success Criteria:**
- ✅ Worker deploys successfully
- ✅ No ImportError in logs
- ✅ Distributed lock initializes correctly
- ✅ Next grading cycle completes without errors

**Rollback:**
```bash
# Revert to previous revision
gcloud run services update-traffic prediction-worker \
  --to-revisions=PREVIOUS=100 \
  --region=us-west2
```

---

### Fix 2: Dependency Audit (30 minutes) - HIGH PRIORITY

**Problem:** Missing dependencies may exist in other services

**Goal:** Identify all dependency mismatches across services

**Script:**
```bash
cd /home/naji/code/nba-stats-scraper

# Create dependency audit script
cat > scripts/audit_dependencies.sh << 'EOF'
#!/bin/bash
# Dependency Audit Script
# Scans all services for missing dependencies

echo "=== Dependency Audit ==="
echo ""

# Services to check
SERVICES=(
  "predictions/coordinator"
  "predictions/worker"
  "data_processors/phase2"
  "data_processors/phase3"
  "data_processors/phase4"
  "orchestration/cloud_functions/phase3_to_phase4"
  "orchestration/cloud_functions/phase4_to_phase5"
)

# Common imports to check
IMPORTS=(
  "google.cloud.firestore:google-cloud-firestore"
  "google.cloud.bigquery:google-cloud-bigquery"
  "google.cloud.storage:google-cloud-storage"
  "google.cloud.secretmanager:google-cloud-secret-manager"
  "google.cloud.pubsub:google-cloud-pubsub"
)

for service in "${SERVICES[@]}"; do
  echo "Checking $service..."

  if [ ! -f "$service/requirements.txt" ]; then
    echo "  ⚠️  No requirements.txt found"
    continue
  fi

  for import in "${IMPORTS[@]}"; do
    IFS=':' read -r module package <<< "$import"

    # Check if module is imported in code
    if grep -r "from $module import\|import $module" "$service"/*.py &> /dev/null; then
      # Check if package is in requirements.txt
      if ! grep -q "$package" "$service/requirements.txt"; then
        echo "  ❌ MISSING: $package (used but not in requirements.txt)"
      fi
    fi
  done

  echo ""
done

echo "=== Audit Complete ==="
EOF

chmod +x scripts/audit_dependencies.sh
./scripts/audit_dependencies.sh
```

**Action Items Based on Audit:**
1. Add missing dependencies to requirements.txt
2. Deploy affected services
3. Verify no import errors

**Prevention:**
Create pre-commit hook to validate dependencies:
```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# Validate dependencies before commit

# Run dependency audit on changed files
changed_files=$(git diff --cached --name-only | grep requirements.txt)

if [ -n "$changed_files" ]; then
  echo "Validating dependencies..."
  ./scripts/audit_dependencies.sh

  if [ $? -ne 0 ]; then
    echo "❌ Dependency validation failed"
    exit 1
  fi
fi
EOF

chmod +x .git/hooks/pre-commit
```

---

### Fix 3: Investigate Grading Accuracy (30 minutes) - HIGH PRIORITY

**Problem:** 18.75% accuracy (9/48 correct) - need to determine if system regression or expected variance

**Investigation Queries:**

**Query 1: Full accuracy breakdown by system**
```sql
-- Save to: monitoring/queries/grading_accuracy_investigation.sql

WITH grading_stats AS (
  SELECT
    game_date,
    system_id,
    COUNT(*) as total_predictions,
    SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) as correct,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 2) as accuracy_pct,
    ROUND(AVG(absolute_error), 2) as mae,
    MIN(graded_at) as first_graded,
    MAX(graded_at) as last_graded
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date = '2026-01-18'
    AND recommendation IN ('OVER', 'UNDER')
    AND graded_at IS NOT NULL
  GROUP BY game_date, system_id
),
historical_avg AS (
  SELECT
    system_id,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 2) as historical_accuracy,
    ROUND(AVG(absolute_error), 2) as historical_mae
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date BETWEEN DATE_SUB('2026-01-18', INTERVAL 14 DAY) AND DATE_SUB('2026-01-18', INTERVAL 1 DAY)
    AND recommendation IN ('OVER', 'UNDER')
    AND graded_at IS NOT NULL
  GROUP BY system_id
)
SELECT
  g.system_id,
  g.total_predictions,
  g.correct,
  g.accuracy_pct as today_accuracy,
  h.historical_accuracy as avg_14d_accuracy,
  ROUND(g.accuracy_pct - h.historical_accuracy, 2) as accuracy_delta,
  g.mae as today_mae,
  h.historical_mae as avg_14d_mae,
  ROUND(g.mae - h.historical_mae, 2) as mae_delta,
  g.first_graded,
  g.last_graded,
  CASE
    WHEN g.accuracy_pct < h.historical_accuracy - 10 THEN '🚨 REGRESSION'
    WHEN g.accuracy_pct < h.historical_accuracy - 5 THEN '⚠️ DEGRADED'
    WHEN g.total_predictions < 40 THEN '⚠️ SMALL SAMPLE'
    ELSE '✅ NORMAL'
  END as status
FROM grading_stats g
LEFT JOIN historical_avg h ON g.system_id = h.system_id
ORDER BY accuracy_delta ASC;
```

**Query 2: Check prediction timing and data freshness**
```sql
-- Check if predictions were made with stale data
WITH prediction_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_prediction,
    MAX(created_at) as last_prediction,
    COUNT(*) as total_predictions,
    COUNT(DISTINCT player_lookup) as unique_players
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = '2026-01-18'
    AND is_active = TRUE
  GROUP BY game_date
),
phase3_timing AS (
  SELECT
    DATE(started_at) as game_date,
    MAX(started_at) as last_phase3_run
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name IN ('upcoming_player_game_context', 'upcoming_team_game_context')
    AND DATE(started_at) >= '2026-01-17'
  GROUP BY DATE(started_at)
)
SELECT
  p.game_date,
  p.first_prediction,
  p.last_prediction,
  ph3.last_phase3_run,
  TIMESTAMP_DIFF(p.first_prediction, ph3.last_phase3_run, HOUR) as hours_after_phase3,
  p.total_predictions,
  p.unique_players,
  CASE
    WHEN TIMESTAMP_DIFF(p.first_prediction, ph3.last_phase3_run, HOUR) > 24 THEN '🚨 STALE DATA'
    WHEN TIMESTAMP_DIFF(p.first_prediction, ph3.last_phase3_run, HOUR) > 12 THEN '⚠️ OLD DATA'
    ELSE '✅ FRESH'
  END as data_freshness
FROM prediction_timing p
LEFT JOIN phase3_timing ph3 ON p.game_date = ph3.game_date;
```

**Query 3: Check if Firestore error corrupted grading**
```sql
-- Compare grading records vs prediction records
SELECT
  'Predictions Created' as source,
  COUNT(*) as count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-01-18'
  AND is_active = TRUE

UNION ALL

SELECT
  'Grading Records' as source,
  COUNT(*) as count
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = '2026-01-18'
  AND graded_at IS NOT NULL;
```

**Decision Matrix Based on Results:**

| Scenario | Action |
|----------|--------|
| Accuracy delta < -10% AND all systems affected | 🚨 System regression - investigate model drift |
| Accuracy delta < -10% AND single system | ⚠️ System-specific issue - retrain model |
| Small sample size (<40 predictions) | ✅ Expected variance - no action |
| Data staleness >12 hours | 🚨 Phase 3 timing issue - fix scheduler |
| Grading count << prediction count | 🚨 Firestore error corrupted writes - regrade |

---

### Fix 4: Add Emergency Monitoring (30 minutes) - HIGH PRIORITY

**Goal:** Get immediate visibility into orchestration health

**Quick Dashboard Query:**
```bash
# Create daily health check script
cat > scripts/daily_orchestration_check.sh << 'EOF'
#!/bin/bash
# Daily Orchestration Health Check
# Run every morning to validate overnight runs

echo "=== Daily Orchestration Health Check ==="
echo "Date: $(date)"
echo ""

# Check 1: Predictions created
echo "1. Predictions Generated:"
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  MAX(created_at) as last_created
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
  AND is_active = TRUE
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 3"

# Check 2: Phase 3 completion
echo ""
echo "2. Phase 3 Processor Completion:"
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  MAX(started_at) as last_run,
  CASE
    WHEN MAX(started_at) > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) THEN '✅'
    ELSE '❌'
  END as status
FROM nba_reference.processor_run_history
WHERE processor_name IN (
  'player_game_summary',
  'team_defense_game_summary',
  'team_offense_game_summary',
  'upcoming_player_game_context',
  'upcoming_team_game_context'
)
GROUP BY processor_name
ORDER BY last_run DESC"

# Check 3: Grading completion
echo ""
echo "3. Grading Status:"
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as accuracy_pct,
  ROUND(AVG(absolute_error), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  AND graded_at IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC"

# Check 4: Recent errors
echo ""
echo "4. Recent Errors (last 2 hours):"
gcloud logging read 'severity>=ERROR' \
  --limit=10 \
  --format="table(timestamp,resource.labels.service_name,textPayload)" \
  --freshness=2h

echo ""
echo "=== Health Check Complete ==="
EOF

chmod +x scripts/daily_orchestration_check.sh

# Run immediately
./scripts/daily_orchestration_check.sh
```

**Set up cron for automatic checks:**
```bash
# Add to crontab to run daily at 9 AM ET
crontab -l > /tmp/crontab.bak
echo "0 9 * * * cd /home/naji/code/nba-stats-scraper && ./scripts/daily_orchestration_check.sh | mail -s 'Daily Orchestration Report' your-email@example.com" >> /tmp/crontab.bak
crontab /tmp/crontab.bak
```

---

## Short-Term Improvements (This Week)

**Goal:** Prevent recurrence of today's issues within 7 days

### Improvement 1: Critical-Path Orchestration (4 hours)

**Problem:** Phase 4 blocked by incomplete Phase 3 (all-or-nothing requirement)

**Solution:** Implement critical-processor-only trigger

**Files:**
- `/home/naji/code/nba-stats-scraper/shared/config/orchestration_config.py`
- `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/phase3_to_phase4/main.py`

**Implementation:**

```python
# orchestration_config.py

PHASE3_TO_PHASE4_CONFIG = {
    'trigger_mode': 'critical_only',

    # MUST complete for pipeline to proceed
    'critical_processors': [
        'upcoming_player_game_context',  # Required for predictions
        'upcoming_team_game_context',    # Required for predictions
    ],

    # Can fail without blocking pipeline
    'optional_processors': [
        'player_game_summary',        # Historical analytics
        'team_defense_game_summary',  # Historical analytics
        'team_offense_game_summary',  # Historical analytics
    ],

    # Alert if optional processors fail
    'alert_on_optional_failure': True,

    # Maximum wait time for critical processors
    'max_wait_minutes': 60,

    # Retry configuration
    'retry_config': {
        'max_attempts': 3,
        'backoff_multiplier': 2,
        'initial_delay_minutes': 5,
    }
}
```

```python
# phase3_to_phase4/main.py

from shared.config.orchestration_config import PHASE3_TO_PHASE4_CONFIG
from google.cloud import firestore
import logging

def check_phase3_completion(game_date: str) -> dict:
    """
    Check Phase 3 completion status with critical-path logic.

    Returns:
        {
            'ready_for_phase4': bool,
            'critical_complete': bool,
            'optional_complete': bool,
            'missing_critical': list,
            'missing_optional': list,
            'alert_required': bool
        }
    """
    db = firestore.Client()
    doc_ref = db.collection('phase3_completion').document(game_date)
    doc = doc_ref.get()

    if not doc.exists:
        return {
            'ready_for_phase4': False,
            'critical_complete': False,
            'optional_complete': False,
            'missing_critical': PHASE3_TO_PHASE4_CONFIG['critical_processors'],
            'missing_optional': PHASE3_TO_PHASE4_CONFIG['optional_processors'],
            'alert_required': True
        }

    data = doc.to_dict()
    completed = data.get('completed_processors', [])

    # Check critical processors
    missing_critical = [
        p for p in PHASE3_TO_PHASE4_CONFIG['critical_processors']
        if p not in completed
    ]

    # Check optional processors
    missing_optional = [
        p for p in PHASE3_TO_PHASE4_CONFIG['optional_processors']
        if p not in completed
    ]

    critical_complete = len(missing_critical) == 0
    optional_complete = len(missing_optional) == 0

    # Alert if optional processors failed
    alert_required = (
        not optional_complete and
        PHASE3_TO_PHASE4_CONFIG['alert_on_optional_failure']
    )

    return {
        'ready_for_phase4': critical_complete,
        'critical_complete': critical_complete,
        'optional_complete': optional_complete,
        'missing_critical': missing_critical,
        'missing_optional': missing_optional,
        'alert_required': alert_required
    }

def trigger_phase4_if_ready(request):
    """Cloud Function entry point."""
    game_date = request.get_json().get('game_date')

    status = check_phase3_completion(game_date)

    if status['ready_for_phase4']:
        logging.info(f"✅ Phase 3 critical processors complete for {game_date}")

        if not status['optional_complete']:
            logging.warning(
                f"⚠️ Optional processors incomplete: {status['missing_optional']}"
            )
            # Send alert
            send_alert(
                severity='warning',
                message=f"Phase 3 optional processors incomplete for {game_date}",
                details=status
            )

        # Trigger Phase 4
        trigger_phase4(game_date)
        return {'status': 'triggered', 'details': status}, 200

    else:
        logging.error(
            f"❌ Phase 3 critical processors incomplete: {status['missing_critical']}"
        )
        # Send alert
        send_alert(
            severity='error',
            message=f"Phase 3 critical processors failed for {game_date}",
            details=status
        )
        return {'status': 'blocked', 'details': status}, 200
```

**Testing:**
```bash
# Test with mock Firestore data
python -m pytest tests/orchestration/test_phase3_to_phase4.py -v

# Integration test
cd orchestration/cloud_functions/phase3_to_phase4
gcloud functions deploy phase3-to-phase4-trigger \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=. \
  --entry-point=trigger_phase4_if_ready \
  --trigger-topic=nba-phase3-complete

# Test invocation
gcloud pubsub topics publish nba-phase3-complete \
  --message='{"game_date": "2026-01-19"}'
```

**Rollback:**
```bash
# Revert to all_complete mode
git revert <commit-hash>
gcloud functions deploy phase3-to-phase4-trigger --source=.
```

---

### Improvement 2: Phase 3 Retry Logic (4 hours)

**Problem:** Phase 3 creates insufficient records when betting lines unavailable

**Solution:** Detect low-record scenarios and retry after delay

**Files:**
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/upcoming_player_game_context.py`
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/processor_base.py`

**Implementation:**

```python
# processor_base.py

from datetime import datetime, timedelta
from google.cloud import pubsub_v1
import logging

class ProcessorBase:
    """Base class for all processors with retry logic."""

    def __init__(self):
        self.publisher = pubsub_v1.PublisherClient()
        self.project_id = 'nba-props-platform'

    def check_record_completeness(
        self,
        records_created: int,
        expected_records: int,
        min_threshold: float = 0.5
    ) -> dict:
        """
        Check if created records meet minimum threshold.

        Args:
            records_created: Number of records created
            expected_records: Expected number of records
            min_threshold: Minimum acceptable ratio (default 50%)

        Returns:
            {
                'sufficient': bool,
                'ratio': float,
                'should_retry': bool,
                'reason': str
            }
        """
        if expected_records == 0:
            return {
                'sufficient': True,
                'ratio': 0.0,
                'should_retry': False,
                'reason': 'No records expected (no games scheduled)'
            }

        ratio = records_created / expected_records
        sufficient = ratio >= min_threshold

        return {
            'sufficient': sufficient,
            'ratio': ratio,
            'should_retry': not sufficient,
            'reason': f'Created {records_created}/{expected_records} ({ratio:.1%})'
        }

    def schedule_retry(
        self,
        processor_name: str,
        game_date: str,
        delay_minutes: int = 30,
        attempt: int = 1,
        max_attempts: int = 3
    ):
        """
        Schedule retry via Pub/Sub with delay.

        Uses Pub/Sub scheduled publish for retry after delay.
        """
        if attempt >= max_attempts:
            logging.error(
                f"Max retry attempts ({max_attempts}) reached for {processor_name}"
            )
            self.send_alert(
                severity='error',
                message=f"{processor_name} failed after {max_attempts} attempts",
                details={'game_date': game_date, 'attempt': attempt}
            )
            return

        retry_topic = f'projects/{self.project_id}/topics/processor-retry'
        retry_time = datetime.now() + timedelta(minutes=delay_minutes)

        message_data = {
            'processor_name': processor_name,
            'game_date': game_date,
            'attempt': attempt + 1,
            'scheduled_time': retry_time.isoformat()
        }

        # Publish with delivery time
        future = self.publisher.publish(
            retry_topic,
            data=str(message_data).encode('utf-8'),
            # Note: Cloud Pub/Sub doesn't support scheduled delivery natively
            # Use Cloud Tasks or Cloud Scheduler for delayed execution
        )

        logging.info(
            f"Scheduled retry #{attempt + 1} for {processor_name} "
            f"in {delay_minutes} minutes"
        )
```

```python
# upcoming_player_game_context.py

class UpcomingPlayerGameContextProcessor(ProcessorBase):
    """Process upcoming player game context with retry logic."""

    def run(self, game_date: str, attempt: int = 1):
        """Run processor with completeness check."""

        # Get expected record count
        expected_records = self.get_expected_record_count(game_date)

        # Run processing
        records_created = self.process_data(game_date)

        # Check completeness
        completeness = self.check_record_completeness(
            records_created=records_created,
            expected_records=expected_records,
            min_threshold=0.5  # Require 50% of expected records
        )

        if completeness['sufficient']:
            logging.info(
                f"✅ Created {records_created} records ({completeness['ratio']:.1%})"
            )
            # Mark complete in Firestore
            self.mark_complete(game_date)

        else:
            logging.warning(
                f"⚠️ Only created {records_created}/{expected_records} "
                f"({completeness['ratio']:.1%})"
            )

            # Schedule retry
            self.schedule_retry(
                processor_name='upcoming_player_game_context',
                game_date=game_date,
                delay_minutes=30,
                attempt=attempt
            )

            # Send alert
            self.send_alert(
                severity='warning',
                message=f"Phase 3 low record count, retry #{attempt} scheduled",
                details={
                    'game_date': game_date,
                    'records_created': records_created,
                    'expected_records': expected_records,
                    'ratio': completeness['ratio'],
                    'retry_in_minutes': 30
                }
            )

    def get_expected_record_count(self, game_date: str) -> int:
        """Query schedule to get expected number of records."""
        query = f"""
        SELECT COUNT(DISTINCT player_id) as expected_players
        FROM `nba-props-platform.nba_reference.game_schedule`
        WHERE game_date = '{game_date}'
        """

        result = self.bq_client.query(query).result()
        row = next(result, None)

        if row:
            # Approximately 10 players per team, 2 teams per game
            return row.expected_players * 10 if row.expected_players else 0
        return 0
```

**Cloud Task Setup for Delayed Retry:**
```bash
# Create Cloud Task queue for processor retries
gcloud tasks queues create processor-retry \
  --location=us-west2 \
  --max-attempts=3 \
  --max-backoff=1h

# Create Cloud Function to handle retry tasks
cat > orchestration/cloud_functions/processor_retry/main.py << 'EOF'
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import json
from datetime import datetime, timedelta

def schedule_processor_retry(request):
    """Schedule delayed processor retry via Cloud Tasks."""

    data = request.get_json()
    processor_name = data['processor_name']
    game_date = data['game_date']
    attempt = data['attempt']
    delay_minutes = data.get('delay_minutes', 30)

    # Create Cloud Tasks client
    client = tasks_v2.CloudTasksClient()
    project = 'nba-props-platform'
    location = 'us-west2'
    queue = 'processor-retry'

    parent = client.queue_path(project, location, queue)

    # Calculate schedule time
    schedule_time = datetime.now() + timedelta(minutes=delay_minutes)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(schedule_time)

    # Create task
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': f'https://us-west2-{project}.cloudfunctions.net/run-processor',
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'processor_name': processor_name,
                'game_date': game_date,
                'attempt': attempt
            }).encode()
        },
        'schedule_time': timestamp
    }

    response = client.create_task(request={'parent': parent, 'task': task})

    return {
        'status': 'scheduled',
        'task_name': response.name,
        'schedule_time': schedule_time.isoformat()
    }, 200
EOF

# Deploy
gcloud functions deploy schedule-processor-retry \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/processor_retry \
  --entry-point=schedule_processor_retry \
  --trigger-http \
  --allow-unauthenticated
```

**Testing:**
```bash
# Test retry logic
python -m pytest tests/data_processors/test_retry_logic.py -v

# Integration test - trigger with low data scenario
bq query --use_legacy_sql=false "
DELETE FROM nba_reference.betting_lines
WHERE game_date = '2026-01-20' AND line_type = 'player_props'"

# Run processor - should trigger retry
python data_processors/analytics/upcoming_player_game_context.py --game-date=2026-01-20

# Check Cloud Tasks queue
gcloud tasks list --queue=processor-retry --location=us-west2
```

---

### Improvement 3: Comprehensive Alerting (4 hours)

**Problem:** No automated alerts for orchestration failures

**Solution:** Implement email/Slack alerting for critical issues

**Files:**
- `/home/naji/code/nba-stats-scraper/shared/alerting/alert_manager.py` (new)
- `/home/naji/code/nba-stats-scraper/shared/alerting/alert_config.py` (new)

**See detailed alerting implementation in existing docs:**
- `docs/08-projects/current/email-alerting/INTEGRATION-PLAN.md`

**Quick Implementation:**

```python
# shared/alerting/alert_manager.py

from google.cloud import secretmanager
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from enum import Enum

class AlertSeverity(Enum):
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'

class AlertManager:
    """Centralized alert management."""

    def __init__(self):
        self.project_id = 'nba-props-platform'
        self.smtp_config = self._get_smtp_config()

    def _get_smtp_config(self) -> dict:
        """Retrieve SMTP configuration from Secret Manager."""
        client = secretmanager.SecretManagerServiceClient()

        secrets = {
            'host': 'smtp-host',
            'port': 'smtp-port',
            'username': 'smtp-username',
            'password': 'smtp-password',
            'from_email': 'smtp-from-email'
        }

        config = {}
        for key, secret_name in secrets.items():
            name = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            config[key] = response.payload.data.decode('UTF-8')

        return config

    def send_alert(
        self,
        severity: AlertSeverity,
        message: str,
        details: dict = None,
        component: str = None
    ):
        """
        Send alert via email.

        Args:
            severity: Alert severity level
            message: Short alert message
            details: Additional context dict
            component: Component name (e.g., 'phase3', 'predictions')
        """
        subject = f"[{severity.value.upper()}] {component or 'Orchestration'}: {message}"

        # Build email body
        body = f"""
NBA Props Platform Alert

Severity: {severity.value.upper()}
Component: {component or 'Unknown'}
Message: {message}
Time: {datetime.now().isoformat()}

Details:
{json.dumps(details, indent=2) if details else 'None'}

---
This is an automated alert from NBA Props Platform orchestration system.
"""

        # Send email
        try:
            msg = MIMEMultipart()
            msg['From'] = self.smtp_config['from_email']
            msg['To'] = self.smtp_config.get('alert_email', self.smtp_config['from_email'])
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(self.smtp_config['host'], int(self.smtp_config['port'])) as server:
                server.starttls()
                server.login(self.smtp_config['username'], self.smtp_config['password'])
                server.send_message(msg)

            logging.info(f"Alert sent: {subject}")

        except Exception as e:
            logging.error(f"Failed to send alert: {e}")
```

**Alert Configuration:**

```python
# shared/alerting/alert_config.py

ALERT_RULES = {
    # Phase 3 Alerts
    'phase3_completion_low': {
        'threshold': 0.8,  # Alert if <80% processors complete
        'severity': 'warning',
        'message_template': 'Phase 3 completion {ratio:.1%} below threshold'
    },

    'phase3_data_stale': {
        'threshold_hours': 2,
        'severity': 'error',
        'message_template': 'Phase 3 data is {hours} hours old'
    },

    # Phase 4 Alerts
    'phase4_not_triggered': {
        'threshold_minutes': 30,
        'severity': 'error',
        'message_template': 'Phase 4 not triggered {minutes} min after Phase 3'
    },

    # Grading Alerts
    'grading_accuracy_low': {
        'threshold': 0.30,  # Alert if <30% accuracy
        'severity': 'error',
        'message_template': 'Grading accuracy {accuracy:.1%} below threshold'
    },

    # Prediction Alerts
    'prediction_volume_low': {
        'threshold': 200,
        'severity': 'error',
        'message_template': 'Only {count} predictions created (expected 280+)'
    },

    # Worker Alerts
    'worker_errors_high': {
        'threshold': 5,
        'window_minutes': 5,
        'severity': 'critical',
        'message_template': '{count} worker errors in {window} minutes'
    }
}
```

**Cloud Monitoring Alert Policies:**

```bash
# Create alerting policies in Cloud Monitoring
cat > orchestration/monitoring/create_alerts.sh << 'EOF'
#!/bin/bash

PROJECT_ID="nba-props-platform"
EMAIL="your-email@example.com"

# Alert 1: Worker Errors
gcloud alpha monitoring policies create \
  --notification-channels="projects/${PROJECT_ID}/notificationChannels/EMAIL_CHANNEL_ID" \
  --display-name="Prediction Worker Errors" \
  --condition-display-name="Error rate > 5 in 5 min" \
  --condition-threshold-value=5 \
  --condition-threshold-duration=300s \
  --condition-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-worker"
    AND severity="ERROR"'

# Alert 2: Phase 3 Processor Failures
gcloud alpha monitoring policies create \
  --notification-channels="projects/${PROJECT_ID}/notificationChannels/EMAIL_CHANNEL_ID" \
  --display-name="Phase 3 Processor Failures" \
  --condition-display-name="Processor failed" \
  --condition-filter='resource.type="cloud_run_revision"
    AND logName=~".*phase3.*"
    AND textPayload=~".*FAILED.*"'

echo "Alert policies created successfully"
EOF

chmod +x orchestration/monitoring/create_alerts.sh
./orchestration/monitoring/create_alerts.sh
```

---

## Medium-Term Robustness (Week 2-3)

### Week 2: Monitoring Dashboard (12 hours)

**Goal:** Comprehensive visibility into orchestration health

**Components:**
1. **Phase Completion Dashboard**
   - Processor-level success rates
   - Completion timing metrics
   - Data freshness indicators

2. **Prediction Health Dashboard**
   - Prediction volume trends
   - Accuracy by system
   - Grading coverage

3. **System Performance Dashboard**
   - End-to-end latency
   - Resource utilization
   - Cost tracking

**Implementation:** See `docs/08-projects/current/pipeline-reliability-improvements/monitoring/FAILURE-TRACKING-DESIGN.md`

---

### Week 3: Event-Driven Architecture (16 hours)

**Goal:** Replace fixed schedules with data-availability-driven triggers

**Key Changes:**
1. **Data Availability Signals**
   - Betting lines API publishes completion event
   - Schedule updates trigger re-evaluation
   - Injury reports trigger context refresh

2. **Completion-Based Triggers**
   - Phase 3 processors publish completion to Pub/Sub
   - Phase 4 subscribes and triggers when ready
   - No fixed time dependencies

3. **State Management**
   - Firestore orchestration state
   - Atomic transaction protection
   - Race condition prevention

**Implementation:** See `docs/08-projects/current/pipeline-reliability-improvements/plans/EVENT-DRIVEN-ORCHESTRATION-DESIGN.md`

---

## Long-Term Self-Healing (Week 4+)

### Week 4: Auto-Recovery Mechanisms (20 hours)

**Goal:** System automatically recovers from transient failures

**Capabilities:**
1. **Intelligent Retry Logic**
   - Exponential backoff
   - Circuit breaker patterns
   - Max retry limits

2. **Fallback Data Sources**
   - Multi-source scraper fallback
   - Primary → secondary → tertiary
   - Auto-recovery when primary restored

3. **Self-Diagnosis**
   - Automated root cause analysis
   - Suggested fixes in alerts
   - Auto-remediation for known issues

**Implementation:** See `docs/08-projects/current/pipeline-reliability-improvements/self-healing/README.md`

---

## Testing & Validation Strategy

### Unit Testing
```bash
# Run all tests
pytest tests/ -v --cov=. --cov-report=html

# Test specific components
pytest tests/orchestration/ -v
pytest tests/data_processors/ -v
pytest tests/predictions/ -v
```

### Integration Testing
```bash
# End-to-end orchestration test
python tests/integration/test_full_pipeline.py --game-date=2026-01-20

# Phase transition tests
python tests/integration/test_phase_transitions.py
```

### Production Validation
```bash
# Canary deployment
gcloud run services update <service> \
  --region=us-west2 \
  --traffic=<new-revision>=10,<old-revision>=90

# Monitor for 1 hour
./scripts/monitor_deployment.sh <service> --duration=60

# Full rollout if successful
gcloud run services update <service> \
  --region=us-west2 \
  --traffic=<new-revision>=100
```

---

## Success Metrics

### Immediate (Week 1)
- ✅ Zero Firestore import errors
- ✅ Grading accuracy within historical range (±5%)
- ✅ Phase 3 completion rate >90%
- ✅ Phase 4 triggered within 15 minutes of Phase 3

### Short-Term (Week 2-3)
- ✅ Alerts configured for all critical failures
- ✅ Dashboard visibility into all phases
- ✅ Retry logic reducing manual interventions by 80%
- ✅ Event-driven triggers eliminating timing issues

### Long-Term (Month 2+)
- ✅ Self-healing recovery rate >95%
- ✅ Manual interventions <1 per week
- ✅ Mean time to recovery <15 minutes
- ✅ Zero production incidents from known causes

---

## Rollback Plans

### Per-Component Rollback

**Firestore Dependency Fix:**
```bash
git revert <commit-hash>
cd predictions/worker
gcloud run deploy prediction-worker --source=.
```

**Critical-Path Orchestration:**
```bash
# Revert to all_complete mode
git revert <commit-hash>
cd orchestration/cloud_functions/phase3_to_phase4
gcloud functions deploy phase3-to-phase4-trigger --source=.
```

**Retry Logic:**
```bash
# Disable retry feature flag
gcloud run services update processor-runner \
  --update-env-vars=ENABLE_RETRY=false
```

### Full Rollback
```bash
# Rollback all changes
git revert HEAD~<number-of-commits>
git push

# Redeploy all services
./bin/deploy_all.sh --revision=stable
```

---

## Next Steps

**Today:**
1. ✅ Deploy Firestore dependency fix
2. ✅ Run grading accuracy investigation
3. ✅ Set up daily health check script

**This Week:**
1. Implement critical-path orchestration
2. Add Phase 3 retry logic
3. Configure comprehensive alerting

**Next 2 Weeks:**
1. Build monitoring dashboards
2. Migrate to event-driven architecture
3. Implement self-healing capabilities

---

**Document Created:** January 18, 2026
**Last Updated:** January 18, 2026
**Status:** Ready for Implementation
**Owner:** DevOps/Platform Team
