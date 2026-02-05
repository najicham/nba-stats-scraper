# Multi-Session Deployment Coordination Evaluation

**Date**: 2026-02-05
**Author**: Claude Sonnet 4.5
**Status**: Evaluation

## Problem Statement

Multiple Claude Code chat sessions can deploy services simultaneously with no coordination mechanism. This leads to:

- **Confusion**: Users don't know which session deployed what
- **Conflicts**: Concurrent deployments to same service (rare but possible)
- **Opacity**: No visibility into active deployments across sessions
- **Wasted time**: Sessions may unknowingly duplicate deployment work

**Current State**: `check-active-deployments.sh` helps detect active builds but doesn't prevent conflicts.

## Constraint Analysis

### Key Constraints
1. **Claude Code sessions cannot share state** - Each session is isolated
2. **External storage required** - Must use GCP services (Firestore, BigQuery, Cloud Build API)
3. **User experience critical** - Cannot add excessive friction to deployments
4. **Failure resilience** - System must handle lock abandonment, crashes
5. **Cost sensitivity** - NBA stats project is cost-conscious

### Session Context
- Sessions typically last 1-4 hours
- Deployments take 3-8 minutes (build + verify)
- Most common: 1 session at a time, occasionally 2 concurrent sessions
- Deployment frequency: 2-5 per day during active development

## Approach Evaluation

### 1. Firestore Deployment Lock

**Mechanism**: Session claims exclusive lock in Firestore before deploying, releases after completion.

```python
# Pseudocode
def deploy_with_lock(service_name):
    lock_id = f"deploy_lock_{service_name}"
    lock_doc = firestore.collection('deployment_locks').document(lock_id)

    # Try to claim lock
    result = lock_doc.create({
        'session_id': get_session_id(),
        'claimed_at': datetime.utcnow(),
        'service': service_name,
        'ttl': datetime.utcnow() + timedelta(minutes=15)
    })

    if not result:
        # Lock exists - check if stale
        existing = lock_doc.get()
        if existing['ttl'] < datetime.utcnow():
            # Stale lock - claim it
            lock_doc.update({'session_id': get_session_id(), ...})
        else:
            raise DeploymentLockError(f"Service {service_name} is being deployed by another session")

    try:
        # Perform deployment
        deploy_service(service_name)
    finally:
        # Release lock
        lock_doc.delete()
```

#### Prevents/Detects Concurrent Deployments
- ✅ **Prevents**: Hard block on concurrent deployments to same service
- ✅ **Detects**: Immediate feedback if another session has lock
- ⚠️ **Limitation**: Different services can deploy concurrently (intended behavior)

#### User Experience
- ✅ **Pros**:
  - Clear error message: "Service X is being deployed by session Y"
  - Minimal friction for common case (no concurrent deployments)
  - No user action required when successful
- ❌ **Cons**:
  - Blocks deployment if lock held (user must wait or override)
  - Requires session identification (how to name sessions?)
  - Manual override needed if lock stuck

**Friction Score**: 2/10 (low - only adds delay in rare conflict case)

#### Implementation Complexity
- ✅ **Moderate** (3-4 hours)
  - Add lock acquisition to `deploy-service.sh`
  - Create lock collection with TTL index
  - Add stale lock cleanup logic
  - Test concurrent deployment scenarios

**Code Locations**:
- `bin/deploy-service.sh` - Add lock logic before Cloud Run deploy
- `shared/utils/deployment_lock.py` - Reusable lock manager
- Uses existing `shared/clients/firestore_pool.py`

#### Failure Modes
1. **Lock not released** (session crashes mid-deployment)
   - **Mitigation**: TTL (15 min) - lock auto-expires
   - **Recovery**: Automatic via TTL, or manual `delete_stale_locks.sh`

2. **TTL too short** (slow deployment exceeds 15 min)
   - **Mitigation**: Set TTL to 20 minutes, avg deployment is 5 min
   - **Recovery**: Lock automatically renews every 5 min (heartbeat)

3. **Firestore unavailable**
   - **Mitigation**: Fall back to deployment without lock (log warning)
   - **Recovery**: Firestore has 99.95% SLA

4. **Session ID collision** (two sessions claim same ID)
   - **Mitigation**: Use `session_id = f"{user}_{hostname}_{timestamp}_{random}"`
   - **Recovery**: Rare (UUID collision probability negligible)

**Resilience Score**: 8/10 (very resilient with TTL + fallback)

#### Cost
- **Firestore operations**:
  - Lock claim: 1 write
  - Lock release: 1 delete
  - Heartbeat (every 5 min): 0-3 writes per deployment
  - Total: ~5 operations per deployment
- **Cost**: $0.18/100k writes → ~$0.000009 per deployment
- **Storage**: Minimal (~10 active locks × 1 KB = 10 KB)

**Monthly Cost** (assuming 100 deployments/month): **$0.001** (negligible)

---

### 2. Slack Notification on Deploy Start/Finish

**Mechanism**: Send Slack message when deployment starts and completes.

```bash
# In deploy-service.sh
send_slack_notification "🚀 Deployment started: $SERVICE by session $SESSION_ID"
# ... perform deployment ...
send_slack_notification "✅ Deployment complete: $SERVICE ($DURATION)"
```

#### Prevents/Detects Concurrent Deployments
- ❌ **Prevents**: Does not prevent concurrent deployments
- ✅ **Detects**: Users see notifications and realize conflict
- ⚠️ **Limitation**: Detection is post-facto, no automatic coordination

#### User Experience
- ✅ **Pros**:
  - Zero friction - no blocking, just notifications
  - Good visibility across sessions
  - Useful for async awareness (other users see what's deploying)
- ❌ **Cons**:
  - Noise in Slack channel (100 deploys/month = 200 messages)
  - Requires manual coordination if conflicts occur
  - No protection against mistakes

**Friction Score**: 0/10 (zero friction)

#### Implementation Complexity
- ✅ **Very Low** (30 minutes)
  - Add 2 lines to `deploy-service.sh`
  - Use existing `shared/utils/slack_alerts.py`
  - No new infrastructure

**Code Locations**:
- `bin/deploy-service.sh` - Add notifications at start/end
- Uses existing `shared/utils/slack_alerts.py`

#### Failure Modes
1. **Slack webhook unavailable**
   - **Mitigation**: Silent failure, deployment continues
   - **Recovery**: No impact on deployment success

2. **Notification fatigue** (too many messages)
   - **Mitigation**: Use thread replies for multi-service deploys
   - **Recovery**: Users mute channel or filter notifications

**Resilience Score**: 10/10 (cannot fail in a way that breaks deployments)

#### Cost
- **Slack API**: Free (webhook calls)
- **Cloud egress**: Negligible (~1 KB per notification)

**Monthly Cost**: **$0** (free)

---

### 3. GitHub Deployment Tracking (via API)

**Mechanism**: Use GitHub Deployments API to track deployment status.

```bash
# Create deployment via gh CLI
gh api repos/OWNER/REPO/deployments \
  -f ref=$COMMIT_SHA \
  -f environment="production-$SERVICE" \
  -f description="Deploy $SERVICE from Claude session"

# Update deployment status
gh api repos/OWNER/REPO/deployments/$DEPLOY_ID/statuses \
  -f state=in_progress \
  -f description="Building and deploying"

gh api repos/OWNER/REPO/deployments/$DEPLOY_ID/statuses \
  -f state=success \
  -f description="Deployed to Cloud Run"
```

#### Prevents/Detects Concurrent Deployments
- ⚠️ **Prevents**: Can block if active deployment exists (custom logic)
- ✅ **Detects**: Query API for active deployments
- ✅ **Advantage**: Permanent audit trail in GitHub

#### User Experience
- ✅ **Pros**:
  - Visible in GitHub UI (deployments tab)
  - Integrates with PR checks and status badges
  - Audit trail for compliance/debugging
- ❌ **Cons**:
  - Requires GitHub auth in Cloud Run (add complexity)
  - GitHub API rate limits (5000 requests/hour)
  - Not real-time (polling required)

**Friction Score**: 3/10 (low but adds auth complexity)

#### Implementation Complexity
- ⚠️ **High** (1 day)
  - Install `gh` CLI in Cloud Run images
  - Configure GitHub auth (service account or PAT)
  - Add deployment tracking logic
  - Handle API failures gracefully
  - Update all 6 service Dockerfiles

**Code Locations**:
- `bin/deploy-service.sh` - Add GitHub API calls
- All Dockerfiles - Install `gh` CLI
- Secret Manager - Store GitHub PAT

#### Failure Modes
1. **GitHub API unavailable**
   - **Mitigation**: Fallback to deploy without tracking
   - **Recovery**: Deployment succeeds, just no tracking

2. **Rate limit exceeded**
   - **Mitigation**: Cache deployment status locally
   - **Recovery**: Wait for rate limit reset (hourly)

3. **Auth token expired**
   - **Mitigation**: Use GitHub App installation token (auto-refresh)
   - **Recovery**: Manual token rotation

**Resilience Score**: 6/10 (external dependency, rate limits)

#### Cost
- **GitHub API**: Free (within rate limits)
- **Secret Manager**: $0.06/secret/month (for PAT storage)

**Monthly Cost**: **$0.06**

---

### 4. Cloud Build Status Webhook to Shared Location

**Mechanism**: Cloud Build publishes status to Pub/Sub → Cloud Function → Firestore for shared visibility.

```python
# Cloud Function triggered by Cloud Build Pub/Sub
def on_build_status(event, context):
    build_id = event['data']['id']
    status = event['data']['status']
    service = parse_service_from_tags(event['data']['tags'])

    firestore.collection('build_status').document(build_id).set({
        'service': service,
        'status': status,
        'started_at': event['data']['createTime'],
        'session_id': event['data']['substitutions'].get('_SESSION_ID'),
        'updated_at': datetime.utcnow()
    })
```

#### Prevents/Detects Concurrent Deployments
- ✅ **Detects**: Query Firestore for in-progress builds
- ⚠️ **Prevents**: Requires combining with approach #1 (locks)
- ✅ **Advantage**: Passive monitoring, no active participation needed

#### User Experience
- ✅ **Pros**:
  - Zero friction for deployers
  - Real-time visibility via `check-active-deployments.sh`
  - Automatic tracking (no manual steps)
- ❌ **Cons**:
  - Doesn't prevent conflicts, only detects
  - Requires additional query to check status

**Friction Score**: 0/10 (zero friction)

#### Implementation Complexity
- ⚠️ **Moderate-High** (4-6 hours)
  - Create Cloud Function for Pub/Sub subscription
  - Subscribe to `cloud-builds` Pub/Sub topic
  - Add session ID to build tags
  - Create Firestore collection with TTL
  - Update `check-active-deployments.sh` to query Firestore

**Code Locations**:
- `cloud_functions/build_status_tracker/main.py` - New function
- `bin/deploy-service.sh` - Add session ID to build tags
- `bin/check-active-deployments.sh` - Query Firestore instead of gcloud

#### Failure Modes
1. **Cloud Function fails**
   - **Mitigation**: Pub/Sub retries up to 7 days
   - **Recovery**: Automatic retry, or manual Firestore update

2. **Firestore write fails**
   - **Mitigation**: Log error, don't crash function
   - **Recovery**: Status visible in Cloud Build console

3. **Pub/Sub subscription deleted**
   - **Mitigation**: Infrastructure-as-code (Terraform) recreates
   - **Recovery**: Redeploy Cloud Function

**Resilience Score**: 7/10 (resilient but adds moving parts)

#### Cost
- **Cloud Function**: $0.40/million invocations (100/month = $0.00004)
- **Pub/Sub**: $0.40/million messages (100/month = $0.00004)
- **Firestore**: 100 writes/month = $0.0002

**Monthly Cost**: **$0.0003** (negligible)

---

### 5. Session Registry in Firestore

**Mechanism**: Each Claude session registers itself on startup, updates heartbeat, deregisters on exit.

```python
# On session start
session_id = f"{user}_{timestamp}_{random}"
firestore.collection('active_sessions').document(session_id).set({
    'user': get_user(),
    'hostname': get_hostname(),
    'started_at': datetime.utcnow(),
    'last_heartbeat': datetime.utcnow(),
    'active_deployments': []
})

# During deployment
firestore.collection('active_sessions').document(session_id).update({
    'active_deployments': firestore.ArrayUnion([service_name])
})

# On session end
firestore.collection('active_sessions').document(session_id).delete()
```

#### Prevents/Detects Concurrent Deployments
- ✅ **Detects**: Query active sessions to see who's deploying what
- ⚠️ **Prevents**: Requires combining with approach #1 (locks)
- ✅ **Advantage**: Enables richer coordination (chat, handoff between sessions)

#### User Experience
- ✅ **Pros**:
  - Rich session metadata (who, when, what)
  - Could enable session-to-session messaging
  - Dashboard shows all active sessions
- ❌ **Cons**:
  - Requires Claude Code integration (non-trivial)
  - Heartbeat overhead on every deployment script
  - Stale session cleanup needed

**Friction Score**: 4/10 (requires session awareness in scripts)

#### Implementation Complexity
- ❌ **Very High** (2-3 days)
  - Implement session identification in all scripts
  - Add heartbeat mechanism to long-running scripts
  - Create cleanup job for stale sessions
  - Build dashboard for session visibility
  - Test across multiple concurrent sessions

**Code Locations**:
- `shared/utils/session_registry.py` - New session manager
- `bin/deploy-service.sh` - Register session, update deployments
- All other scripts - Add session awareness
- `cloud_functions/session_cleanup/main.py` - Clean stale sessions

#### Failure Modes
1. **Session not deregistered** (crash/Ctrl+C)
   - **Mitigation**: TTL on session docs (30 min inactivity)
   - **Recovery**: Automatic cleanup via scheduled function

2. **Heartbeat missed** (network issue)
   - **Mitigation**: Grace period (3 missed heartbeats = stale)
   - **Recovery**: Session reappears on next heartbeat

3. **Firestore unavailable**
   - **Mitigation**: Degrade to local-only mode (no coordination)
   - **Recovery**: Automatic when Firestore recovers

**Resilience Score**: 6/10 (complex, many failure modes)

#### Cost
- **Firestore**:
  - Session registration: 1 write per session
  - Heartbeats: 1 write per minute per active session
  - Deployment updates: 2 writes per deployment
  - Monthly: ~200 sessions × 60 min avg × 1 write = 12k writes
- **Cost**: 12k writes × $0.18/100k = **$0.022/month**

**Monthly Cost**: **$0.02**

---

## Comparison Matrix

| Approach | Prevents Conflicts | UX Friction | Implementation | Resilience | Cost/Month | Best For |
|----------|-------------------|-------------|----------------|------------|-----------|----------|
| **1. Firestore Lock** | ✅ Yes | 🟢 Low (2/10) | 🟡 Moderate (3-4h) | 🟢 High (8/10) | $0.001 | **Hard blocking** |
| **2. Slack Notifications** | ❌ No | 🟢 Zero (0/10) | 🟢 Very Low (30m) | 🟢 High (10/10) | $0 | **Awareness only** |
| **3. GitHub Deployments** | ⚠️ Partial | 🟡 Low (3/10) | 🔴 High (1d) | 🟡 Medium (6/10) | $0.06 | **Audit trail** |
| **4. Cloud Build Webhook** | ❌ No | 🟢 Zero (0/10) | 🟡 Moderate (4-6h) | 🟡 Medium (7/10) | $0.0003 | **Passive monitoring** |
| **5. Session Registry** | ⚠️ Partial | 🔴 Medium (4/10) | 🔴 Very High (2-3d) | 🔴 Low (6/10) | $0.02 | **Rich coordination** |

## Recommendations

### Primary Recommendation: **Approach #1 (Firestore Lock) + Approach #2 (Slack Notifications)**

**Rationale**:
- **Safety first**: Firestore lock prevents actual conflicts (hard requirement)
- **Awareness**: Slack notifications provide visibility with zero friction
- **Quick wins**: Both are low-complexity (1 day total implementation)
- **Cost-effective**: Combined cost of $0.001/month is negligible
- **Resilient**: TTL handles abandoned locks, Slack failures don't block deployments

**Implementation Plan**:

1. **Phase 1: Slack Notifications** (30 minutes)
   ```bash
   # In bin/deploy-service.sh, add after line 115:
   send_slack_alert \
     "🚀 Deploying $SERVICE ($BUILD_COMMIT) from $(hostname)" \
     "#daily-orchestration"

   # Add after line 426 (deployment complete):
   send_slack_alert \
     "✅ Deployed $SERVICE ($REVISION) in ${DURATION}s" \
     "#daily-orchestration"
   ```

2. **Phase 2: Firestore Deployment Lock** (3-4 hours)
   - Create `shared/utils/deployment_lock.py`
   - Add lock acquisition before Docker build (line 133)
   - Add lock release in cleanup (after line 878)
   - Add `--force` flag to override stuck locks
   - Test concurrent deployment scenarios

3. **Phase 3: Monitoring Dashboard** (optional, future)
   - Add deployment locks to unified dashboard
   - Show active deployments across sessions
   - Alert on stuck locks (>30 minutes)

### Secondary Recommendation: **Approach #4 (Cloud Build Webhook)** (Nice-to-have)

**Rationale**:
- **Passive monitoring**: Doesn't require script changes
- **Complements locks**: Provides audit trail of all builds
- **Existing check-active-deployments.sh**: Makes script faster (query Firestore vs gcloud)
- **Low cost**: $0.0003/month is negligible

**When to implement**: After primary recommendation is stable (1-2 weeks)

---

## Rejected Approaches

### Why NOT Approach #3 (GitHub Deployments)?
- **Over-engineered**: Adds auth complexity for minimal benefit
- **External dependency**: GitHub API rate limits and availability
- **Audit trail**: Git commit history already provides this
- **ROI**: 1 day implementation for limited value

### Why NOT Approach #5 (Session Registry)?
- **Over-engineered**: 2-3 days implementation for marginal benefit
- **Complexity**: Heartbeat mechanism across all scripts
- **Failure-prone**: Many moving parts, stale session cleanup
- **Better alternatives**: Locks + notifications solve 90% of problem with 10% of complexity

---

## Open Questions

1. **Session identification**: How to name sessions?
   - Proposed: `{user}@{hostname}_{YYYYMMDD_HHMMSS}`
   - Alternative: Let user set `SESSION_NAME` env var

2. **Lock override**: Should `--force` flag bypass locks?
   - Recommendation: Yes, for emergency deploys
   - Requires confirmation prompt to prevent accidents

3. **Notification channel**: Which Slack channel?
   - Proposed: `#daily-orchestration` (existing, low-traffic)
   - Alternative: Create `#deployments` channel

4. **Lock TTL duration**: 15 min or 20 min?
   - Data: 95th percentile deployment time is ~8 minutes
   - Recommendation: 20 minutes (2.5x median, handles slow builds)

---

## Success Metrics

After implementation, measure:
1. **Lock conflicts**: How many deployments blocked by locks? (expect <5% initially)
2. **Stale locks**: How often do locks expire without release? (target <1%)
3. **Deployment visibility**: Survey users - do they see deployment notifications? (target 100%)
4. **Time to deploy**: Does lock overhead add latency? (target <500ms)

---

## Next Steps

1. **Review this evaluation** with project stakeholders
2. **Implement Phase 1** (Slack notifications) - 30 minutes
3. **Test Phase 1** with concurrent deployments
4. **Implement Phase 2** (Firestore locks) - 3-4 hours
5. **Test Phase 2** with forced concurrent conflicts
6. **Document** new deployment flow in `CLAUDE.md`
7. **Consider Phase 3** (Cloud Build webhook) after 1-2 weeks

---

## Appendix: Example Lock Implementation

```python
# shared/utils/deployment_lock.py
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from google.cloud import firestore
from shared.clients import get_firestore_client

class DeploymentLockError(Exception):
    """Raised when deployment lock cannot be acquired."""
    pass

class DeploymentLock:
    """
    Distributed lock for coordinating deployments across Claude sessions.

    Usage:
        with DeploymentLock('prediction-worker', ttl_minutes=20):
            # Perform deployment
            deploy_service('prediction-worker')
    """

    def __init__(
        self,
        service_name: str,
        session_id: Optional[str] = None,
        ttl_minutes: int = 20,
        force: bool = False
    ):
        self.service_name = service_name
        self.session_id = session_id or self._get_session_id()
        self.ttl_minutes = ttl_minutes
        self.force = force
        self.firestore = get_firestore_client()
        self.lock_id = f"deploy_{service_name}"

    def _get_session_id(self) -> str:
        """Generate session ID from environment."""
        import socket
        from datetime import datetime
        import random

        user = os.environ.get('USER', 'unknown')
        hostname = socket.gethostname()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        rand = random.randint(1000, 9999)

        return f"{user}@{hostname}_{timestamp}_{rand}"

    def acquire(self):
        """Acquire deployment lock."""
        lock_ref = self.firestore.collection('deployment_locks').document(self.lock_id)

        # Try to create lock
        try:
            lock_ref.create({
                'service': self.service_name,
                'session_id': self.session_id,
                'claimed_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes)
            })
            return  # Success
        except Exception:
            # Lock already exists
            pass

        # Lock exists - check if stale or force override
        existing = lock_ref.get()
        if not existing.exists:
            # Race condition - retry
            time.sleep(0.1)
            return self.acquire()

        lock_data = existing.to_dict()

        # Check if stale (past TTL)
        if lock_data['expires_at'] < datetime.now(timezone.utc):
            # Stale lock - claim it
            lock_ref.set({
                'service': self.service_name,
                'session_id': self.session_id,
                'claimed_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes),
                'previous_session': lock_data['session_id'],
                'recovered_from_stale': True
            })
            print(f"⚠️  Recovered stale lock from session {lock_data['session_id']}")
            return

        # Force override
        if self.force:
            lock_ref.set({
                'service': self.service_name,
                'session_id': self.session_id,
                'claimed_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes),
                'previous_session': lock_data['session_id'],
                'forced_override': True
            })
            print(f"⚠️  FORCED override of lock held by {lock_data['session_id']}")
            return

        # Lock held by another session
        age_seconds = (datetime.now(timezone.utc) - lock_data['claimed_at']).total_seconds()
        raise DeploymentLockError(
            f"Service {self.service_name} is currently being deployed by another session.\n"
            f"  Locked by: {lock_data['session_id']}\n"
            f"  Lock age: {age_seconds:.0f}s (expires in {(lock_data['expires_at'] - datetime.now(timezone.utc)).total_seconds():.0f}s)\n"
            f"\n"
            f"Options:\n"
            f"  1. Wait for deployment to complete (~5-10 minutes)\n"
            f"  2. Use --force flag to override (CAUTION: may conflict with active deployment)"
        )

    def release(self):
        """Release deployment lock."""
        lock_ref = self.firestore.collection('deployment_locks').document(self.lock_id)
        lock_ref.delete()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False  # Don't suppress exceptions
```

### Usage in deploy-service.sh

```bash
# After line 115 (before Docker build)
echo ""
echo "[0.5/8] Acquiring deployment lock..."

# Try to acquire lock (with Python script)
python3 -c "
from shared.utils.deployment_lock import DeploymentLock
try:
    lock = DeploymentLock('$SERVICE', force=${FORCE:-False})
    lock.acquire()
    print('✅ Lock acquired')
except Exception as e:
    print(f'❌ {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo ""
    echo "Deployment blocked by lock."
    exit 1
fi

# Trap to ensure lock release on exit
trap 'python3 -c "from shared.utils.deployment_lock import DeploymentLock; DeploymentLock(\"$SERVICE\").release()"' EXIT
```

---

**End of Evaluation**
