# Good Morning - Placeholder Line Remediation Session 79

**Copy/paste this to continue:**

---

Good morning! I'm continuing the placeholder line remediation project from Session 78.

## Current Status

**Progress**: 70% complete (Phases 1-3 done, Phase 4a blocked)

**What's Working**:
- ✅ Phase 1 code fixed (Tuple import added, validation gate logic ready)
- ✅ Coordinator timeout fixed (batch loading bypassed)
- ✅ Phase 2-3 complete (18,990 deleted, 12,579 backfilled)

**What's Blocking**: Worker deployment doesn't include the `shared/` module, causing:
```
ModuleNotFoundError: No module named 'shared'
```

## Root Cause (Discovered in Session 78)

When we deploy with `gcloud run deploy --source .`, the buildpack doesn't include our copied `shared/` directory. Even revision `prediction-worker-00044-g7f` (which has Phase 1 code fixes) fails to boot because it's missing `shared/`.

## Your Task - Fix Worker Deployment

**Read the comprehensive handoff first**:
- `docs/09-handoff/2026-01-17-SESSION-78-FINAL-SUMMARY.md` (Session 78 findings)
- `docs/09-handoff/2026-01-17-SESSION-78-PHASE1-DEPLOYMENT-HANDOFF.md` (Technical details)

**Then choose one deployment fix**:

### Option A: Create Dockerfile (RECOMMENDED)

```dockerfile
# predictions/worker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy shared module from repository root
COPY ../../shared ./shared

# Copy worker code
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run worker
CMD exec gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 300 worker:app
```

Deploy:
```bash
cd /home/naji/code/nba-stats-scraper
gcloud run deploy prediction-worker \
  --source predictions/worker \
  --region us-west2 \
  --project nba-props-platform \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform"
```

### Option B: Cloud Build Config

Create `predictions/worker/cloudbuild.yaml`:
```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - 'gcr.io/nba-props-platform/prediction-worker:$SHORT_SHA'
      - '-f'
      - 'predictions/worker/Dockerfile'
      - '.'

  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'prediction-worker'
      - '--image=gcr.io/nba-props-platform/prediction-worker:$SHORT_SHA'
      - '--region=us-west2'
      - '--platform=managed'
```

### Option C: Restructure Code

Move `shared/` into `predictions/worker/shared/` permanently and update imports.

## After Worker Deploys Successfully

**Test Phase 4a - THE CRITICAL VALIDATION**:

```bash
# 1. Verify worker is healthy
curl -s https://prediction-worker-756957797294.us-west2.run.app/health

# 2. Trigger Jan 9 predictions
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "X-API-Key: 0B5gc7vv9oNZYjST9lhe4rY2jEG2kYdz" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-09", "min_minutes": 15, "force": true}'

# 3. Wait 5 minutes for batch to complete

# 4. THE CRITICAL VALIDATION (must have 0 placeholders!)
bq query --nouse_legacy_sql "
SELECT
  game_date, system_id, COUNT(*) as count,
  COUNTIF(current_points_line = 20.0) as placeholders
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-09'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
GROUP BY game_date, system_id
ORDER BY system_id"

# SUCCESS CRITERIA: placeholders = 0 for ALL systems
# This proves Phase 1 validation gate works!
```

## If Phase 4a Succeeds (0 Placeholders)

Continue with:
- **Phase 4b**: Regenerate XGBoost V1 for 53 dates (~4 hours)
  - Script: `scripts/nba/phase4_regenerate_predictions.sh`

- **Phase 5**: Setup monitoring views (~10 minutes)
  - Script: `scripts/nba/phase5_setup_monitoring.sql`

- **Final Validation**: Verify 0 placeholders across all dates since Nov 19

## Quick Context

**Working Directory**: `/home/naji/code/nba-stats-scraper`
**GCP Project**: `nba-props-platform`
**Git Status**: All Session 78 fixes committed
**Latest Commits**:
- `0f2cc43` - Session 78 final summary and coordinator bypass fix
- `028e58d` - Add missing Tuple import for validation gate

**Current Worker Issue**: Missing `shared/` module in Cloud Run container
**Current Coordinator**: `prediction-coordinator-00044-tz9` (batch loading bypassed, working)

## Expected Timeline

- **Worker Deployment Fix**: 30 minutes
- **Phase 4a Validation**: 30 minutes
- **Phase 4b Execution**: 4 hours
- **Phase 5 + Final Validation**: 30 minutes
- **Total**: ~5.5 hours to completion

---

Let's fix the deployment and complete this project!
