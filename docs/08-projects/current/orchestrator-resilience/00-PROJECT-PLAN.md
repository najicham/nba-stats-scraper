# Orchestrator Health Monitoring & Resilience

**Project Lead:** Session 199
**Date:** 2026-02-11
**Status:** Planning - Awaiting Opus Review
**Priority:** P0 CRITICAL

## Executive Summary

**Problem:** Phase 2→3 orchestrator failure (Session 198) went undetected for 3 days, blocking all downstream data flow. All 6 Phase 2 processors completed successfully, but orchestrator never set `_triggered=True` in Firestore. No alerts fired.

**Impact:** 3-day data gap (Feb 9-11), zero predictions generated, manual intervention required.

**Proposed Solution:** Multi-layer detection and prevention system to catch orchestrator failures in 15 minutes instead of 3 days, plus root cause prevention to make failures impossible.

**Estimated Effort:** 90 minutes total implementation
**Risk Reduction:** 96x faster detection (3 days → 15 minutes)

---

## Problem Analysis

### What Happened (Session 198)

```
Timeline:
- Feb 9-11: All Phase 2 processors complete successfully (6/6)
- Firestore shows: processors_complete=6, _triggered=False
- No Slack alerts fired
- Phase 3-6 blocked (no analytics, no predictions, no data flow)
- Discovery: Feb 11 during manual investigation (3 days later)
- Resolution: Manual Cloud Scheduler trigger
```

### Why Existing Safeguards Failed

The Phase 2→3 orchestrator has **extensive** error handling and alerting:
- ✅ `send_orchestration_error_alert()` - Catches unexpected exceptions
- ✅ `send_data_freshness_alert()` - Missing raw data
- ✅ `send_validation_warning_alert()` - Validation failures
- ✅ `send_completion_deadline_alert()` - Deadline exceeded

**But none of these fired!** This means:
1. Orchestrator received processor completions
2. Updated Firestore with processor status
3. Never reached the code that sets `_triggered=True`
4. Failed silently without throwing catchable exception

### Root Cause Hypotheses

1. **Cloud Function timeout (540s)** - Function killed before reaching trigger code
2. **Firestore transaction deadlock** - Transaction failed silently, no exception thrown
3. **Exception + alert failure** - Caught exception but Slack alert also failed
4. **Logic bug** - Edge case where `should_trigger` evaluated to False despite 6/6 complete
5. **Resource exhaustion** - Memory/CPU limits hit, function terminated

**Critical gap:** No logging checkpoints between "received completion" and "set _triggered=True", so we can't diagnose root cause.

---

## Current Detection Landscape

| Layer | Detection Time | What It Checks | Coverage |
|-------|----------------|----------------|----------|
| Orchestrator internal alerts | Real-time | Exceptions, validation, deadlines | ❌ **Didn't fire** |
| Deployment drift alerter | 2 hours | Service deployment status | ❌ **Not orchestrator logic** |
| Pipeline canary queries | 30 minutes | Phase data completeness | ❌ **Missing orchestrator trigger check** |
| Auto-batch cleanup | 15 minutes | Stalled prediction batches | ❌ **Downstream symptom, not root cause** |
| `/validate-daily` skill | 24 hours | Firestore `_triggered` status | ✅ **Just added (Session 199)** |

**Detection gap:** Real-time alerts failed, next check is 24 hours later.

---

## Proposed Solutions

### Solution 1: Enhanced Orchestrator Logging (P0 - CRITICAL)

**Objective:** Add visibility into orchestrator execution to enable post-mortem diagnosis and real-time monitoring.

**Changes to `orchestration/cloud_functions/phase2_to_phase3/main.py`:**

#### 1A. Checkpoint Logging

Add log statements at critical decision points:

```python
# Line ~878 - BEFORE transaction
logger.info(
    f"CHECKPOINT_PRE_TRANSACTION: processor={processor_name}, "
    f"game_date={game_date}, correlation_id={correlation_id}"
)

# Line ~893 - AFTER transaction
logger.info(
    f"CHECKPOINT_POST_TRANSACTION: should_trigger={should_trigger}, "
    f"deadline_exceeded={deadline_exceeded}, game_date={game_date}"
)

# Line ~962 - WHEN triggering
logger.info(
    f"CHECKPOINT_TRIGGER_SET: All {EXPECTED_PROCESSOR_COUNT} processors complete, "
    f"_triggered=True written to Firestore, game_date={game_date}"
)

# Line ~1090 - Still waiting
logger.info(
    f"CHECKPOINT_WAITING: Registered {processor_name}, "
    f"completed={completed_count}/{EXPECTED_PROCESSOR_COUNT}, game_date={game_date}"
)
```

**Benefit:** Enables diagnosis of future failures. Logs show exactly where execution stopped.

#### 1B. Dual-Write Trigger Status to BigQuery

Write `_triggered` status to BigQuery for monitoring (don't rely solely on Firestore):

```python
# After Firestore transaction succeeds (line ~993)
if should_trigger:
    # Existing Firestore write...

    # ALSO write to BigQuery for monitoring
    try:
        bq_client = get_bigquery_client()
        table_id = f"{PROJECT_ID}.nba_orchestration.orchestrator_triggers"

        row = {
            'phase_name': 'phase2_to_phase3',
            'game_date': game_date,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
            'trigger_reason': 'all_complete',
            'completed_processors': list(EXPECTED_PROCESSOR_SET),
            'processor_count': EXPECTED_PROCESSOR_COUNT,
            'correlation_id': correlation_id
        }

        errors = bq_client.insert_rows_json(table_id, [row])
        if errors:
            logger.error(f"Failed to write trigger status to BQ: {errors}")
        else:
            logger.info(f"✅ Trigger status logged to BigQuery: {game_date}")
    except Exception as e:
        # Non-blocking - log but don't fail orchestration
        logger.error(f"BigQuery trigger logging failed: {e}", exc_info=True)
```

**New table schema:**
```sql
CREATE TABLE nba_orchestration.orchestrator_triggers (
    phase_name STRING NOT NULL,
    game_date DATE NOT NULL,
    triggered_at TIMESTAMP NOT NULL,
    trigger_reason STRING,
    completed_processors ARRAY<STRING>,
    processor_count INT64,
    correlation_id STRING,
    metadata JSON
)
PARTITION BY game_date
CLUSTER BY phase_name, trigger_reason;
```

**Benefit:**
- Pipeline canaries can query BigQuery (easier than Firestore)
- Provides backup if Firestore fails
- Historical audit trail

#### 1C. Timeout Warning System

Add signal handler to warn before Cloud Function timeout (540s limit):

```python
# At start of orchestrate_phase2_to_phase3() (line ~816)
import signal

def timeout_warning_handler(signum, frame):
    """Warn when approaching Cloud Function timeout limit"""
    logger.error(
        f"⚠️  TIMEOUT WARNING: Orchestrator approaching 540s Cloud Function limit! "
        f"Function may terminate before completing. game_date={game_date if 'game_date' in locals() else 'unknown'}"
    )

    # Send critical alert
    if SLACK_WEBHOOK_URL:
        try:
            payload = {
                "text": f"🚨 Phase 2→3 Orchestrator Timeout Warning",
                "blocks": [{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Orchestrator approaching 540s timeout!*\n"
                                f"Game Date: {game_date if 'game_date' in locals() else 'unknown'}\n"
                                f"This may indicate a stuck transaction or resource issue."
                    }
                }]
            }
            requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send timeout warning alert: {e}")

# Set alarm for 8 minutes (480s) - 1 minute before 9-minute Cloud Function timeout
signal.signal(signal.SIGALRM, timeout_warning_handler)
signal.alarm(480)
```

**Benefit:** Catches timeout scenarios before function is killed.

#### 1D. Firestore Transaction Visibility

Add detailed logging inside the transaction:

```python
# In update_completion_atomic() function (line ~1142)
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, completion_data):
    """..."""
    logger.info(f"TRANSACTION_START: processor={processor_name}")

    # Read current state
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}
    logger.info(f"TRANSACTION_READ: doc_exists={doc_snapshot.exists}, keys={list(current.keys())}")

    # ... existing logic ...

    completed_count = len([k for k in current.keys() if not k.startswith('_')])
    logger.info(f"TRANSACTION_COUNT: completed={completed_count}/{EXPECTED_PROCESSOR_COUNT}")

    if completed_count >= EXPECTED_PROCESSOR_COUNT and not current.get('_triggered'):
        logger.info(f"TRANSACTION_TRIGGERING: Setting _triggered=True for {doc_ref.path}")
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        # ... rest of trigger logic ...

    logger.info(f"TRANSACTION_COMPLETE: should_trigger={should_trigger}")
    return (should_trigger, deadline_exceeded)
```

**Benefit:** Visibility into transaction execution. Can see if transaction completes but returns wrong value.

**Effort:** 20 minutes
**Risk:** Low (logging only, no logic changes)
**Priority:** 🔥 **DO FIRST**

---

### Solution 2: Pipeline Canary Orchestrator Check (30-min detection)

**Objective:** Add orchestrator trigger status check to existing pipeline canary system (runs every 30 minutes).

**Changes to `bin/monitoring/pipeline_canary_queries.py`:**

#### 2A. Add Firestore Check Function

```python
from google.cloud import firestore
from datetime import datetime, timedelta

def check_orchestrator_triggers(game_date: str) -> Tuple[bool, Dict, Optional[str]]:
    """
    Check if orchestrators triggered successfully for game_date.

    Args:
        game_date: Date to check (YYYY-MM-DD)

    Returns:
        (passed, metrics, error_message)
    """
    try:
        db = firestore.Client(project=PROJECT_ID)
        issues = []

        # Check Phase 2→3 (yesterday's data)
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        doc = db.collection('phase2_completion').document(yesterday).get()

        if doc.exists:
            data = doc.to_dict()
            processors = len([k for k in data.keys() if not k.startswith('_')])
            triggered = data.get('_triggered', False)

            if processors >= 5 and not triggered:
                issues.append(f"Phase 2→3 ({yesterday}): {processors}/6 complete but NOT TRIGGERED")

        # Check Phase 3→4 (today's processing date)
        today = datetime.now().strftime('%Y-%m-%d')
        doc = db.collection('phase3_completion').document(today).get()

        if doc.exists:
            data = doc.to_dict()
            processors = len([k for k in data.keys() if not k.startswith('_')])
            triggered = data.get('_triggered', False)

            if processors >= 5 and not triggered:
                issues.append(f"Phase 3→4 ({today}): {processors}/5 complete but NOT TRIGGERED")

        if issues:
            return (False, {'issues': issues}, '\n'.join(issues))

        return (True, {'phase2_triggered': True, 'phase3_triggered': True}, None)

    except Exception as e:
        logger.error(f"Failed to check orchestrator triggers: {e}", exc_info=True)
        return (False, {}, f"Firestore check failed: {e}")
```

#### 2B. Integrate into Canary Runner

```python
def run_all_canaries():
    """Run all canary checks"""
    client = bigquery.Client()
    failures = []

    # Run BigQuery-based canaries
    for check in CANARY_CHECKS:
        passed, metrics, error = run_canary_query(client, check)
        if not passed:
            failures.append({
                'name': check.name,
                'phase': check.phase,
                'error': error,
                'metrics': metrics
            })

    # Run Firestore-based orchestrator check (NEW)
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    passed, metrics, error = check_orchestrator_triggers(yesterday)
    if not passed:
        failures.append({
            'name': 'Orchestrator Trigger Status',
            'phase': 'orchestrator_health',
            'error': error,
            'metrics': metrics
        })

    # Send alerts if failures
    if failures:
        send_canary_failures_alert(failures)
```

**Alternative: Use BigQuery Instead of Firestore**

If we implement Solution 1B (dual-write to BigQuery), we can query BigQuery instead:

```python
CanaryCheck(
    name="Orchestrator - Phase 2→3 Trigger",
    phase="orchestrator_p2_p3",
    query="""
    WITH expected_triggers AS (
        -- Find dates where Phase 2 should have triggered
        SELECT DISTINCT game_date
        FROM `nba-props-platform.nba_orchestration.phase_completions`
        WHERE phase = 'phase2'
          AND game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
          AND completed_processor_count >= 5
    ),
    actual_triggers AS (
        -- Find dates where orchestrator actually triggered
        SELECT DISTINCT game_date
        FROM `nba-props-platform.nba_orchestration.orchestrator_triggers`
        WHERE phase_name = 'phase2_to_phase3'
          AND game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    )
    SELECT
        COUNTIF(a.game_date IS NULL) as missing_triggers,
        STRING_AGG(CAST(e.game_date AS STRING), ', ') as missing_dates
    FROM expected_triggers e
    LEFT JOIN actual_triggers a USING (game_date)
    """,
    thresholds={
        'missing_triggers': {'max': 0}  # FAIL if any expected triggers missing
    },
    description="Validates Phase 2→3 orchestrator triggered when processors complete"
)
```

**Effort:** 30 minutes (20 min for Firestore version, 10 min if using BigQuery)
**Risk:** Low (adds to existing system)
**Priority:** 🔥 **DO SECOND**

---

### Solution 3: Dedicated Orchestrator Health Monitor (15-min detection)

**Objective:** Create dedicated monitoring script that checks orchestrator health every 15 minutes and can auto-heal stuck orchestrators.

**New file: `bin/monitoring/orchestrator_health_monitor.py`**

```python
#!/usr/bin/env python3
"""
Orchestrator Health Monitor (Session 199)

Checks orchestrator trigger status every 15 minutes.
Detects stuck orchestrators where processors complete but _triggered=False.
Can optionally auto-trigger stuck orchestrators.

Usage:
    python bin/monitoring/orchestrator_health_monitor.py
    python bin/monitoring/orchestrator_health_monitor.py --auto-heal

Sends alerts to #orchestrator-alerts when issues detected.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import firestore
from shared.utils.slack_alerts import send_slack_alert

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
ENABLE_AUTO_HEAL = os.environ.get('ENABLE_ORCHESTRATOR_AUTO_HEAL', 'false').lower() == 'true'


class OrchestratorHealthMonitor:
    """Monitors orchestrator health and detects stuck triggers"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.db = firestore.Client(project=project_id)

    def check_phase2_to_phase3(self, game_date: str) -> Dict:
        """Check Phase 2→3 orchestrator trigger status"""
        doc = self.db.collection('phase2_completion').document(game_date).get()

        if not doc.exists:
            return {
                'status': 'no_data',
                'game_date': game_date,
                'phase': 'phase2_to_phase3'
            }

        data = doc.to_dict()
        processors_complete = len([k for k in data.keys() if not k.startswith('_')])
        triggered = data.get('_triggered', False)
        trigger_reason = data.get('_trigger_reason', 'N/A')

        # STUCK: processors complete but not triggered
        if processors_complete >= 5 and not triggered:
            return {
                'status': 'stuck',
                'game_date': game_date,
                'phase': 'phase2_to_phase3',
                'processors_complete': processors_complete,
                'expected_processors': 6,
                'triggered': triggered,
                'heal_command': f"gcloud scheduler jobs run same-day-phase3 --location=us-west2"
            }

        # HEALTHY: triggered successfully
        if triggered:
            return {
                'status': 'healthy',
                'game_date': game_date,
                'phase': 'phase2_to_phase3',
                'processors_complete': processors_complete,
                'triggered': triggered,
                'trigger_reason': trigger_reason
            }

        # WAITING: processors still completing
        return {
            'status': 'waiting',
            'game_date': game_date,
            'phase': 'phase2_to_phase3',
            'processors_complete': processors_complete,
            'expected_processors': 6
        }

    def check_phase3_to_phase4(self, processing_date: str) -> Dict:
        """Check Phase 3→4 orchestrator trigger status"""
        doc = self.db.collection('phase3_completion').document(processing_date).get()

        if not doc.exists:
            return {
                'status': 'no_data',
                'game_date': processing_date,
                'phase': 'phase3_to_phase4'
            }

        data = doc.to_dict()
        processors_complete = len([k for k in data.keys() if not k.startswith('_')])
        triggered = data.get('_triggered', False)

        if processors_complete >= 5 and not triggered:
            return {
                'status': 'stuck',
                'game_date': processing_date,
                'phase': 'phase3_to_phase4',
                'processors_complete': processors_complete,
                'expected_processors': 5,
                'triggered': triggered,
                'heal_command': f"gcloud scheduler jobs run phase3-to-phase4 --location=us-west2"
            }

        if triggered:
            return {
                'status': 'healthy',
                'game_date': processing_date,
                'phase': 'phase3_to_phase4',
                'processors_complete': processors_complete,
                'triggered': triggered
            }

        return {
            'status': 'waiting',
            'game_date': processing_date,
            'phase': 'phase3_to_phase4',
            'processors_complete': processors_complete,
            'expected_processors': 5
        }

    def check_all_orchestrators(self) -> List[Dict]:
        """Check all orchestrators and return issues"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')

        issues = []

        # Check Phase 2→3 (yesterday's data)
        result = self.check_phase2_to_phase3(yesterday)
        if result['status'] == 'stuck':
            issues.append(result)
            logger.error(
                f"🔴 STUCK: {result['phase']} orchestrator for {yesterday} - "
                f"{result['processors_complete']}/{result['expected_processors']} complete but NOT TRIGGERED"
            )
        elif result['status'] == 'healthy':
            logger.info(f"✅ {result['phase']} orchestrator triggered successfully for {yesterday}")

        # Check Phase 3→4 (today's processing date)
        result = self.check_phase3_to_phase4(today)
        if result['status'] == 'stuck':
            issues.append(result)
            logger.error(
                f"🔴 STUCK: {result['phase']} orchestrator for {today} - "
                f"{result['processors_complete']}/{result['expected_processors']} complete but NOT TRIGGERED"
            )
        elif result['status'] == 'healthy':
            logger.info(f"✅ {result['phase']} orchestrator triggered successfully for {today}")

        return issues

    def send_alert(self, issues: List[Dict]):
        """Send Slack alert for stuck orchestrators"""
        if not SLACK_WEBHOOK_URL:
            logger.warning("SLACK_WEBHOOK_URL not configured, skipping alert")
            return

        issue_details = []
        for issue in issues:
            issue_details.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{issue['phase']}*\n"
                        f"Date: `{issue['game_date']}`\n"
                        f"Status: {issue['processors_complete']}/{issue['expected_processors']} processors complete, *NOT TRIGGERED*\n"
                        f"Action: `{issue['heal_command']}`"
                    )
                }
            })

        payload = {
            "attachments": [{
                "color": "#FF0000",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🚨 Orchestrator Health Check FAILED",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{len(issues)} orchestrator(s) stuck!* Processors complete but orchestrator never triggered."
                        }
                    }
                ] + issue_details + [
                    {
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": f"🤖 Auto-heal: {'Enabled' if ENABLE_AUTO_HEAL else 'Disabled'} | Detected: {datetime.now().isoformat()}"
                        }]
                    }
                ]
            }]
        }

        try:
            import requests
            response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Alert sent successfully for {len(issues)} stuck orchestrator(s)")
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}", exc_info=True)

    def auto_heal(self, issues: List[Dict]):
        """Auto-trigger stuck orchestrators (if enabled)"""
        if not ENABLE_AUTO_HEAL:
            logger.info("Auto-heal disabled, skipping auto-trigger")
            return

        import subprocess

        for issue in issues:
            logger.warning(f"🤖 AUTO-HEALING: Triggering {issue['phase']} for {issue['game_date']}")

            try:
                # Extract job name from command
                # Example: "gcloud scheduler jobs run same-day-phase3 --location=us-west2"
                parts = issue['heal_command'].split()
                job_name_idx = parts.index('run') + 1
                job_name = parts[job_name_idx]
                location = 'us-west2'

                # Trigger via gcloud
                result = subprocess.run(
                    ['gcloud', 'scheduler', 'jobs', 'run', job_name, f'--location={location}'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    logger.info(f"✅ Auto-heal successful: {job_name} triggered")

                    # Log healing event to Firestore for audit trail
                    self.db.collection('orchestrator_healing_events').add({
                        'phase': issue['phase'],
                        'game_date': issue['game_date'],
                        'healed_at': firestore.SERVER_TIMESTAMP,
                        'trigger_command': issue['heal_command'],
                        'status': 'success',
                        'processors_complete': issue['processors_complete'],
                        'expected_processors': issue['expected_processors']
                    })
                else:
                    logger.error(f"❌ Auto-heal failed: {result.stderr}")

            except Exception as e:
                logger.error(f"Failed to auto-heal {issue['phase']}: {e}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description='Monitor orchestrator health')
    parser.add_argument('--auto-heal', action='store_true', help='Auto-trigger stuck orchestrators')
    args = parser.parse_args()

    # Override env var if --auto-heal flag provided
    if args.auto_heal:
        global ENABLE_AUTO_HEAL
        ENABLE_AUTO_HEAL = True

    logger.info("Starting orchestrator health check...")

    monitor = OrchestratorHealthMonitor(PROJECT_ID)
    issues = monitor.check_all_orchestrators()

    if issues:
        logger.error(f"🔴 CRITICAL: {len(issues)} stuck orchestrator(s) detected!")
        monitor.send_alert(issues)

        if ENABLE_AUTO_HEAL:
            monitor.auto_heal(issues)

        sys.exit(1)
    else:
        logger.info("✅ All orchestrators healthy")
        sys.exit(0)


if __name__ == '__main__':
    main()
```

**Cloud Scheduler Setup:**

```bash
# Deploy as Cloud Function (optional)
gcloud functions deploy orchestrator-health-monitor \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-env-vars="PROJECT_ID=nba-props-platform,ENABLE_ORCHESTRATOR_AUTO_HEAL=false"

# Create Cloud Scheduler job (runs every 15 minutes)
gcloud scheduler jobs create http orchestrator-health-monitor \
  --schedule="*/15 * * * *" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/orchestrator-health-monitor" \
  --http-method=GET \
  --oidc-service-account-email="cloud-scheduler@nba-props-platform.iam.gserviceaccount.com" \
  --location=us-west2 \
  --description="Monitor orchestrator health every 15 minutes (Session 199)"
```

**Or run directly via Cloud Scheduler (simpler):**

```bash
# Schedule direct Python execution every 15 minutes
gcloud scheduler jobs create http orchestrator-health-monitor \
  --schedule="*/15 * * * *" \
  --uri="https://us-west2-run.googleapis.com/scripts/orchestrator-health-monitor" \
  --http-method=POST \
  --location=us-west2
```

**Effort:** 45 minutes (30 min script + 15 min deployment/testing)
**Risk:** Low (separate monitoring layer, doesn't touch orchestrator code)
**Priority:** ⭐ **DO THIRD**

---

### Solution 4: Orchestrator Self-Healing (Future Enhancement)

**Objective:** Make orchestrators self-monitoring with built-in deadman switches.

**Concept:** Add expiration timestamps to Firestore that external monitors can check:

```python
# When all processors complete, set expected trigger deadline
current['_trigger_deadline'] = firestore.SERVER_TIMESTAMP + timedelta(minutes=5)

# External monitor checks:
if now() > _trigger_deadline and _triggered == False:
    # Orchestrator should have triggered by now but didn't
    alert("Orchestrator missed trigger deadline!")
    auto_trigger()
```

**Effort:** 60 minutes
**Risk:** Medium (modifies orchestrator logic)
**Priority:** 📅 **Future - After monitoring layers proven**

---

## Implementation Plan

### Phase 1: Visibility (Week 1)

**Goal:** Make orchestrator failures visible and diagnosable

| Task | Effort | Owner | Files |
|------|--------|-------|-------|
| Enhanced orchestrator logging | 20 min | Agent | `orchestration/cloud_functions/phase2_to_phase3/main.py` |
| BigQuery dual-write | 15 min | Agent | Same + create `orchestrator_triggers` table |
| Timeout warning system | 10 min | Agent | Same |
| Deploy orchestrator | 5 min | Agent | Cloud Functions deploy |

**Total: 50 minutes**

### Phase 2: Detection (Week 1)

**Goal:** Catch stuck orchestrators in 15-30 minutes

| Task | Effort | Owner | Files |
|------|--------|-------|-------|
| Pipeline canary orchestrator check | 30 min | Agent | `bin/monitoring/pipeline_canary_queries.py` |
| Dedicated health monitor | 45 min | Agent | `bin/monitoring/orchestrator_health_monitor.py` |
| Cloud Scheduler setup | 10 min | Agent | GCP config |

**Total: 85 minutes**

### Phase 3: Validation (Week 1)

**Goal:** Test and verify all layers work

| Task | Effort | Owner |
|------|--------|-------|
| Simulate stuck orchestrator | 15 min | Agent |
| Verify canary alerts | 10 min | Agent |
| Verify dedicated monitor alerts | 10 min | Agent |
| Test auto-heal (dry run) | 10 min | Agent |
| Document runbook | 15 min | Agent |

**Total: 60 minutes**

---

## Success Criteria

### Immediate (Post-Implementation)

- [ ] Enhanced logging deployed to Phase 2→3 orchestrator
- [ ] `orchestrator_triggers` BigQuery table created
- [ ] Pipeline canary includes orchestrator trigger check
- [ ] Dedicated health monitor deployed and scheduled (15-min intervals)
- [ ] All monitors tested with simulated stuck orchestrator

### 30 Days (Operational)

- [ ] Zero orchestrator failures go undetected >30 minutes
- [ ] Mean time to detection (MTTD) < 30 minutes for orchestrator failures
- [ ] Mean time to resolution (MTTR) < 2 hours for orchestrator failures
- [ ] Auto-heal successfully triggers 100% of stuck orchestrators (if enabled)

### 90 Days (Prevention)

- [ ] Root cause of Session 198 failure identified via enhanced logging
- [ ] Orchestrator failure rate < 1 per month
- [ ] Zero 24+ hour data gaps due to orchestrator failures

---

## Risk Assessment

### Implementation Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Logging overhead increases orchestrator latency | Low | Use async logging, minimal string formatting |
| BigQuery dual-write fails | Low | Non-blocking, logs error but doesn't fail orchestration |
| False positive alerts | Medium | Tune thresholds (processors >= 5 vs >= 6) |
| Auto-heal triggers incorrectly | High | **Disable by default**, require explicit enable flag |
| Timeout warning triggers too early | Low | Set at 8 minutes (plenty of buffer before 9-min limit) |

### Operational Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Alert fatigue from too many monitors | Medium | Consolidate alerts to single Slack channel |
| Auto-heal masks underlying issues | High | **Log all healing events**, track healing frequency, alert if >3 per week |
| Monitors add Cloud costs | Low | 15-min interval = 96 invocations/day × $0.0000004 = negligible |

---

## Rollback Plan

### If Logging Changes Cause Issues

```bash
# Revert orchestrator to previous version
gcloud functions deploy phase2-to-phase3-orchestrator \
  --gen2 --runtime=python311 --region=us-west2 \
  --source=. --entry-point=orchestrate_phase2_to_phase3 \
  --trigger-topic=nba-phase2-raw-complete \
  --set-env-vars="COMMIT_SHA=<previous-commit-sha>"
```

### If Monitors Cause Alert Fatigue

```bash
# Disable Cloud Scheduler jobs temporarily
gcloud scheduler jobs pause orchestrator-health-monitor --location=us-west2

# Or adjust frequency to run less often
gcloud scheduler jobs update orchestrator-health-monitor \
  --schedule="*/30 * * * *" \  # Every 30 min instead of 15
  --location=us-west2
```

### If Auto-Heal Triggers Incorrectly

```bash
# Disable auto-heal immediately
gcloud functions deploy orchestrator-health-monitor \
  --update-env-vars="ENABLE_ORCHESTRATOR_AUTO_HEAL=false"
```

---

## Open Questions for Opus Review

1. **Auto-heal default setting:** Should auto-heal be enabled by default or opt-in?
   - Recommendation: Start disabled, enable after 2 weeks of successful manual healing

2. **Alert threshold:** Use processors >= 5 or >= 6 for triggering alerts?
   - Recommendation: >= 5 for early warning, but only alert if stuck >30 minutes

3. **Monitor frequency:** 15 minutes or 30 minutes for dedicated health monitor?
   - Recommendation: 15 minutes for critical orchestrators (2→3), 30 minutes for others

4. **BigQuery vs Firestore:** Should pipeline canaries check BigQuery (after dual-write) or Firestore directly?
   - Recommendation: Firestore initially (simpler), migrate to BigQuery after dual-write proven

5. **Scope:** Apply to all orchestrators (2→3, 3→4, 4→5) or just Phase 2→3 initially?
   - Recommendation: Start with 2→3 (highest impact), roll out to others after validation

6. **Healing audit:** How long to keep orchestrator healing events in Firestore?
   - Recommendation: 90 days in Firestore, permanent in BigQuery

---

## Appendix A: Session 198 Timeline

```
Feb 9, 6:00 AM ET:
- Phase 1 scrapers run for Feb 9 games
- Phase 2 processors complete successfully (6/6)
- Phase 2→3 orchestrator receives completions
- Firestore shows: processors_complete=6, _triggered=False
- ❌ No Phase 3 trigger
- ❌ No alerts

Feb 9-11 (72 hours):
- Phase 3-6 blocked
- Zero predictions generated
- Zero analytics processed
- Frontend shows stale data

Feb 11, 7:00 AM ET:
- User notices missing predictions
- Manual investigation discovers stuck orchestrator
- Manual trigger via Cloud Scheduler resolves issue
- Data gap: 3 full days
```

**Cost of failure:** 72 hours of zero predictions, manual intervention required

**Proposed improvement:** 15-minute detection = 48x faster response time

---

## Appendix B: Related Documentation

- Session 198 handoff: `docs/09-handoff/2026-02-11-SESSION-198-HANDOFF.md`
- Session 199 handoff: `docs/09-handoff/2026-02-11-SESSION-199-HANDOFF.md`
- Orchestrator health guide: `docs/02-operations/ORCHESTRATOR-HEALTH.md`
- Daily validation skill: `.claude/skills/validate-daily/SKILL.md`

---

## Approval

**Reviewed by:** [Opus name]
**Approval date:** [Date]
**Status:** [ ] Approved [ ] Rejected [ ] Needs Changes
**Comments:**

---

**Next Steps After Approval:**
1. Create task list for implementation
2. Implement Phase 1 (Visibility)
3. Test enhanced logging
4. Implement Phase 2 (Detection)
5. Run full validation suite
6. Deploy to production
7. Monitor for 1 week
8. Create final handoff document
