# Phase 4→5 Timeout Fix Plan

**Date:** January 12, 2026
**Status:** IMPLEMENTED - Ready for deployment
**Priority:** P0-ORCH-2
**Risk:** HIGH - Pipeline can get stuck indefinitely

**Implementation Completed:**
- Fix 1: HTTP error handling updated (line 505 no longer raises)
- Fix 2: `phase4_timeout_check` function created with deployment script

---

## Current State Analysis

### What Exists

The Phase 4→5 orchestrator (`orchestration/cloud_functions/phase4_to_phase5/main.py`) already has timeout logic at lines 288-312:

```python
MAX_WAIT_HOURS = 4  # Line 51
MAX_WAIT_SECONDS = MAX_WAIT_HOURS * 3600  # Line 52

# Lines 288-312: Timeout check
if wait_seconds > MAX_WAIT_SECONDS:
    logger.warning(f"TIMEOUT: Waited {wait_seconds/3600:.1f} hours...")
    current['_trigger_reason'] = 'timeout'
    return (True, 'timeout', missing_processors)
```

### Two Issues Identified

1. **HTTP call raises on failure (line 427)**
   - When `trigger_prediction_coordinator()` fails, it raises an exception
   - This crashes the Cloud Function
   - Pub/Sub retries the message, but state is already updated in Firestore
   - Can cause duplicate triggers or stuck state

2. **Timeout only checked on processor completion**
   - Timeout logic runs only when a processor completion message arrives
   - If ALL Phase 4 processors fail (no messages), timeout never fires
   - Pipeline stays stuck indefinitely

---

## Proposed Fix

### Fix 1: Graceful HTTP Failure Handling

**File:** `orchestration/cloud_functions/phase4_to_phase5/main.py`
**Lines:** 382-427

**Change:** Don't raise exception on HTTP failure

```python
def trigger_prediction_coordinator(game_date: str, correlation_id: str) -> bool:
    """
    Trigger the prediction coordinator via HTTP.

    Returns True if successful, False otherwise.
    Does NOT raise exceptions - failures are logged but not propagated.
    """
    try:
        url = f"{PREDICTION_COORDINATOR_URL}/start"
        payload = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'phase4_orchestrator'
        }

        # Get identity token for Cloud Run authentication
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token
            auth_req = google.auth.transport.requests.Request()
            id_token = google.oauth2.id_token.fetch_id_token(auth_req, PREDICTION_COORDINATOR_URL)
            headers = {
                'Authorization': f'Bearer {id_token}',
                'Content-Type': 'application/json'
            }
        except Exception as e:
            logger.warning(f"Could not get ID token: {e}, trying without auth")
            headers = {'Content-Type': 'application/json'}

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            logger.info(f"Successfully triggered prediction coordinator for {game_date}")
            return True
        else:
            logger.warning(
                f"Prediction coordinator returned {response.status_code}: {response.text[:200]}"
            )
            return False

    except requests.Timeout:
        logger.warning(f"Timeout triggering prediction coordinator for {game_date} (30s)")
        return False
    except Exception as e:
        logger.error(f"Error triggering prediction coordinator: {e}")
        # Don't raise - Pub/Sub message sent, self-heal will catch it
        return False
```

### Fix 2: Scheduled Timeout Check Job

**Problem:** If no processors complete, timeout never fires.

**Solution:** Add a Cloud Scheduler job that periodically checks for stale Phase 4 states.

**New File:** `orchestration/cloud_functions/phase4_timeout_check/main.py`

```python
"""
Phase 4 Timeout Check

Cloud Scheduler job that runs every 30 minutes to check for stuck Phase 4 states.
If a game_date has Phase 4 started but not triggered for > 4 hours, force trigger.
"""

import functions_framework
from datetime import datetime, timezone, timedelta
from google.cloud import firestore

MAX_WAIT_HOURS = 4
db = firestore.Client()

@functions_framework.http
def check_phase4_timeouts(request):
    """Check for stuck Phase 4 states and force trigger if needed."""
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()

    triggered_count = 0

    for game_date in [today, yesterday]:
        doc_ref = db.collection('phase4_completion').document(game_date)
        doc = doc_ref.get()

        if not doc.exists:
            continue

        data = doc.to_dict()

        # Already triggered - skip
        if data.get('_triggered'):
            continue

        # Check timeout
        first_completion_str = data.get('_first_completion_at')
        if first_completion_str:
            first_completion = datetime.fromisoformat(
                first_completion_str.replace('Z', '+00:00')
            )
            wait_hours = (now - first_completion).total_seconds() / 3600

            if wait_hours > MAX_WAIT_HOURS:
                # Force trigger
                trigger_phase5_for_stale_date(game_date, data)
                triggered_count += 1

    return {'triggered': triggered_count}
```

**Cloud Scheduler Configuration:**
```yaml
name: phase4-timeout-check
schedule: "*/30 * * * *"  # Every 30 minutes
time_zone: America/New_York
target:
  uri: https://phase4-timeout-check-xxx.run.app
```

---

## Implementation Steps

### Step 1: Update HTTP Error Handling (Low Risk)

1. Edit `orchestration/cloud_functions/phase4_to_phase5/main.py`
2. Change line 427 from `raise` to `return False`
3. Update function return type to `bool`
4. Deploy to Cloud Functions

**Testing:**
- Trigger with coordinator URL set to invalid
- Verify function doesn't crash
- Verify Firestore state is preserved

### Step 2: Add Timeout Check Job (Medium Risk)

1. Create `orchestration/cloud_functions/phase4_timeout_check/main.py`
2. Deploy to Cloud Functions
3. Add Cloud Scheduler job
4. Test with manually-created stale Firestore doc

**Testing:**
- Create test doc with old `_first_completion_at`
- Run function manually
- Verify it triggers Phase 5

---

## Affected Files

| File | Change |
|------|--------|
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Don't raise on HTTP failure |
| `orchestration/cloud_functions/phase4_timeout_check/main.py` | NEW - Scheduled timeout check |

---

## Deployment Order

1. Deploy Fix 1 (HTTP error handling) first - safe, no behavior change for happy path
2. Test Fix 1 in production for 1 day
3. Deploy Fix 2 (scheduled timeout check)
4. Monitor Cloud Scheduler logs for triggered timeouts

---

## Rollback Plan

**Fix 1:** Revert to previous version - simple redeploy
**Fix 2:** Disable Cloud Scheduler job, no code change needed

---

## Verification

After deployment, verify:

1. Cloud Function logs show "Successfully triggered" or graceful failures
2. No Cloud Function crashes on coordinator HTTP errors
3. Timeout check job runs every 30 minutes
4. Stale Phase 4 states get triggered after 4 hours

---

## Related Documentation

- Handoff: `docs/09-handoff/2026-01-12-SESSION-14-COMPLETE-HANDOFF.md`
- Master TODO: `docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md`

---

*Created: January 12, 2026*
*Status: Ready for Implementation*
