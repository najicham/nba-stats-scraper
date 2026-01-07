# Replay Script Authentication Limitation - 2025-12-31

## Problem Summary

The replay pipeline script (`bin/testing/replay_pipeline.py`) cannot authenticate with Cloud Run services when run from WSL/local environment.

**Status:** ❌ BLOCKED
**Impact:** Cannot run automated replay tests locally
**Workaround:** Run from Cloud Shell or update script for local development

---

## Error Details

**Command:**
```bash
PYTHONPATH=. python bin/testing/replay_pipeline.py 2025-12-20 \
  --start-phase=3 --skip-phase=4,5,6 --dataset-prefix=test_
```

**Error:**
```
Could not get ID token: Neither metadata server or valid service account credentials are found.
Phase 3 failed: 403 - Forbidden
Your client does not have permission to get URL /process-date-range from this server.
```

**Root Cause:**
- Script tries to get identity token using `google.oauth2.id_token.fetch_id_token()`
- This requires either:
  1. Running on GCP (metadata server available)
  2. Application Default Credentials set up
  3. Service account key file
- Local WSL environment has none of these

---

## Why This Happens

### 1. Secure Cloud Run Services

Services are now properly secured (no `allUsers`):
```yaml
bindings:
- members:
  - serviceAccount:756957797294-compute@developer.gserviceaccount.com
  - serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com
  - serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com
  role: roles/run.invoker
```

**Implication:** Only these specific service accounts can invoke services.

### 2. Local Environment Authentication

When running locally:
- `gcloud auth` uses personal account credentials
- Personal account (nchammas@gmail.com) is NOT in the IAM policy
- Services correctly reject with 403

### 3. Script Design

The replay script's `get_auth_token()` method:
```python
def get_auth_token(self, audience: str) -> str:
    try:
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        return google.oauth2.id_token.fetch_id_token(auth_req, audience)
    except Exception as e:
        logger.warning(f"Could not get ID token: {e}")
        return ""
```

**Issue:** Returns empty string on failure, which causes 403.

---

## Solutions

### Option 1: Run from Cloud Shell (Recommended for Now)

Cloud Shell has automatic credentials:
```bash
# In Cloud Shell
cd /path/to/nba-stats-scraper
source .venv/bin/activate
PYTHONPATH=. python bin/testing/replay_pipeline.py 2025-12-20 --start-phase=3
```

**Pros:**
- Works immediately
- No code changes
- Has proper service account credentials

**Cons:**
- Can't run locally
- Need browser access

### Option 2: Add Personal Account to IAM (NOT Recommended)

Temporarily add personal account:
```bash
gcloud run services add-iam-policy-binding nba-phase3-analytics-processors \
  --region=us-west2 \
  --member=user:nchammas@gmail.com \
  --role=roles/run.invoker
```

**Pros:**
- Works locally immediately

**Cons:**
- **SECURITY RISK**: Opens service to personal account
- Need to remember to remove later
- Defeats purpose of security fixes

### Option 3: Use Service Account Key (Recommended for Local Dev)

Create and use a service account key:

```bash
# 1. Create service account for testing
gcloud iam service-accounts create nba-replay-tester \
  --display-name="NBA Pipeline Replay Tester"

# 2. Grant Cloud Run Invoker role
gcloud run services add-iam-policy-binding nba-phase3-analytics-processors \
  --region=us-west2 \
  --member=serviceAccount:nba-replay-tester@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/run.invoker

# 3. Create and download key
gcloud iam service-accounts keys create ~/nba-replay-key.json \
  --iam-account=nba-replay-tester@nba-props-platform.iam.gserviceaccount.com

# 4. Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS=~/nba-replay-key.json

# 5. Run replay
PYTHONPATH=. python bin/testing/replay_pipeline.py 2025-12-20 --start-phase=3
```

**Pros:**
- Secure (dedicated service account)
- Works locally
- Can be reused

**Cons:**
- Key file to manage
- Need to secure key file
- Extra setup step

### Option 4: Update Script for Local Development

Modify `get_auth_token()` to fallback to `gcloud`:

```python
def get_auth_token(self, audience: str) -> str:
    """Get identity token for Cloud Run service."""
    try:
        # Try proper authentication first
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        return google.oauth2.id_token.fetch_id_token(auth_req, audience)
    except Exception as e:
        logger.warning(f"Could not get ID token via API: {e}")

        # Fallback to gcloud for local development
        try:
            import subprocess
            result = subprocess.run(
                ['gcloud', 'auth', 'print-identity-token'],
                capture_output=True,
                text=True,
                check=True
            )
            token = result.stdout.strip()
            logger.info("Using gcloud auth token for local development")
            return token
        except Exception as fallback_error:
            logger.error(f"Could not get token via gcloud either: {fallback_error}")
            return ""
```

**Pros:**
- Works in both Cloud and local environments
- No extra setup needed
- Falls back gracefully

**Cons:**
- Still requires personal account to have IAM permission
- Code change needed

---

## Recommended Approach

**For Testing Now:**
- Use Cloud Shell (Option 1)
- Or create service account key (Option 3)

**For Long-term:**
- Update script with fallback (Option 4)
- Add service account key to gitignored keys/ directory
- Document setup in README

---

## Impact on Session

**What Couldn't Be Tested:**
- Automated Phase 3 replay
- Dataset prefix functionality end-to-end
- Replay script execution
- Validation framework

**What Was Tested:**
- ✅ Phase 3 deployment success
- ✅ Security (403 without proper auth)
- ✅ IAM policies correct
- ✅ Service health endpoints
- ✅ Test dataset infrastructure

**Value Delivered:**
- Found authentication limitation early
- Documented solutions clearly
- Deployment verified working
- Security verified working

---

## Next Steps (Morning)

### Immediate (5 min)
1. Decide which solution to use
2. If Option 3: Create service account key
3. If Option 1: Open Cloud Shell

### Test Run (15-30 min)
1. Run replay from Cloud Shell or with service account key
2. Verify writes to test datasets
3. Validate outputs
4. Complete test plan

### Optional Enhancement (30 min)
1. Implement Option 4 (fallback in script)
2. Test both cloud and local execution
3. Update documentation
4. Commit improvement

---

## Testing Alternative (Without Replay Script)

Can test manually with curl:

```bash
# Get token (from Cloud Shell or with service account)
TOKEN=$(gcloud auth print-identity-token)

# Call Phase 3 directly
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-12-20",
    "end_date": "2025-12-20",
    "processors": [],
    "backfill_mode": true,
    "dataset_prefix": "test_"
  }' \
  https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range

# Check test dataset
bq query "SELECT COUNT(*) FROM test_nba_analytics.player_game_summary WHERE game_date='2025-12-20'"
```

This bypasses the replay script and directly tests the service.

---

*Documented: 2025-12-31 02:30 AM*
*Status: Blocked locally, unblocked in Cloud Shell*
*Priority: P2 - Workarounds available*
*Estimated Fix Time: 5-30 minutes depending on solution*
