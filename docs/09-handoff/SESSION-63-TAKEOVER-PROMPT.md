# Session 63 Takeover Prompt

**Copy this entire prompt to start the next session**

---

Hi Claude! Welcome to Session 63 of the NBA Stats Scraper project.

## Context: What Session 62 Discovered

Session 62 (Feb 1, 2026) made a **critical discovery**: Session 61's claim that the heartbeat fix was deployed was **INCORRECT**. The fix exists in the codebase but has NEVER been deployed to production.

### The Problem

**Firestore heartbeat document proliferation continues:**
- Current: 1,053 documents (should be ~30)
- Format: `NbacTeamBoxscoreProcessor_None_01944bb1` ❌
- Expected: `NbacTeamBoxscoreProcessor` ✅
- Accumulation: ~900 new documents per day

**Root cause:** The heartbeat fix (commit e1c10e88) exists in code but is NOT running in production.

### What Session 62 Accomplished

1. ✅ **Identified root cause** - Fix never deployed despite Session 61 claims
2. ✅ **Fixed Phase 2 Dockerfile** - Added missing dependencies (gunicorn, GCP libraries)
3. ✅ **Updated deployment script** - Added Phase 2 support
4. ✅ **Ran cleanup** - Deleted 215 old format docs
5. ✅ **Committed changes** - 6fc971bb

### What Session 62 Could NOT Solve

❌ **BLOCKER:** Deployments complete successfully but don't update running code

**Evidence:**
- Phase 3 deployment created revision 00169 with exit code 0
- Service still runs old code (verified via Firestore doc IDs)
- All 4 services show commits older than the fix commit

## Your Mission: Solve Deployment Mystery & Deploy Fix

### CRITICAL FIRST STEP (Required)

**Investigate why deployments don't update code.** This is BLOCKING all progress.

```bash
# 1. Check what code is actually in the deployed Phase 3 revision
gcloud run revisions describe nba-phase3-analytics-processors-00169-56h \
  --region=us-west2 --format="value(spec.template.spec.containers[0].image)"

# 2. Pull that image and check the heartbeat code
IMAGE=$(gcloud run revisions describe nba-phase3-analytics-processors-00169-56h \
  --region=us-west2 --format="value(spec.template.spec.containers[0].image)")
docker pull $IMAGE
docker run --rm $IMAGE cat /app/shared/monitoring/processor_heartbeat.py | grep -A10 "def doc_id"

# 3. Compare to what SHOULD be there (in main branch)
grep -A10 "def doc_id" shared/monitoring/processor_heartbeat.py
```

**Expected findings:**
- If deployed image has `return self.processor_name` → Code is correct, investigate why it's not working
- If deployed image has `return f"{self.processor_name}_{self.data_date}_{self.run_id}"` → Code wasn't deployed, investigate build/deploy process

### Possible Causes to Investigate

1. **Docker layer caching** - Old layers reused despite code changes
2. **Cloud Run rollbacks** - Health checks fail, trigger automatic rollback
3. **Build context issue** - Deployment not including latest code
4. **Image registry issue** - Old images pulled despite new tags

### IMMEDIATE Tasks (First 30 minutes)

**Task 1: Verify current deployment state**
```bash
# Check all service commits
for service in nba-phase2-raw-processors nba-phase3-analytics-processors \
               nba-phase4-precompute-processors nba-scrapers; do
  echo "=== $service ==="
  gcloud run services describe $service --region=us-west2 \
    --format="value(status.latestReadyRevisionName,metadata.labels.commit-sha)"
done

echo -e "\n=== Expected commit with fix: e1c10e88 or later ==="
git log --oneline | head -5
```

**Task 2: Verify Firestore still shows wrong format**
```python
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
print(f'Total docs: {len(docs)} (expected: ~30)\n')
print('Sample doc IDs:')
for doc in docs[:5]:
    print(f'  {doc.id}')
    wrong_format = '_None_' in doc.id or '_202' in doc.id
    print(f'    Format: {\"❌ WRONG\" if wrong_format else \"✅ CORRECT\"}')
"
```

**Task 3: Investigate deployment mystery**
- Pull deployed Docker image and inspect heartbeat code
- Check Cloud Run revision history for rollbacks
- Review deployment script build process

### HIGH PRIORITY (After solving deployment mystery)

**Once you understand WHY deployments fail:**

1. **Deploy Phase 3 with fix verification**
   ```bash
   # Build with no cache to force fresh build
   docker build --no-cache -f data_processors/analytics/Dockerfile \
     -t test-image .

   # Verify image has correct code
   docker run --rm test-image cat /app/shared/monitoring/processor_heartbeat.py | grep -A5 "def doc_id"
   # Should show: return self.processor_name

   # If verified, deploy
   ./bin/deploy-service.sh nba-phase3-analytics-processors

   # Verify deployment stuck
   sleep 30
   gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
     --format="value(status.latestReadyRevisionName)"
   ```

2. **Monitor Firestore for 10 minutes**
   ```bash
   # Watch for new documents
   for i in {1..10}; do
     python3 -c "
   from google.cloud import firestore
   db = firestore.Client(project='nba-props-platform')
   docs = list(db.collection('processor_heartbeats').stream())
   bad = [d for d in docs if '_None_' in d.id or '_202' in d.id]
   print(f'Minute ${i}: Total={len(docs)}, Bad format={len(bad)}')
   "
     sleep 60
   done
   ```

3. **Deploy remaining services**
   - Phase 2, Phase 4, Scrapers
   - Verify each before moving to next

4. **Run cleanup again**
   ```bash
   python bin/cleanup-heartbeat-docs.py
   # Should reduce to ~30 documents
   ```

### MEDIUM PRIORITY

5. **Verify dashboard health improved**
   ```bash
   curl -s https://unified-dashboard-f7p3g7f6ya-wl.a.run.app/api/services/health
   # Expected: Services health score 70+/100
   ```

6. **Monitor for 24 hours**
   - Document count stays at ~30
   - No new proliferation
   - Dashboard health stays high

## Key Documentation (READ THESE FIRST)

**Primary Reference:**
- `docs/09-handoff/2026-02-01-SESSION-62-HANDOFF.md` (500+ lines)
  - Complete Session 62 investigation
  - Deployment mystery details
  - All attempted fixes
  - Next session priorities

**Operational Guides:**
- `CLAUDE.md` - Updated with heartbeat system documentation
- `docs/02-operations/infrastructure-health-checks.md` - Health check commands
- `docs/02-operations/troubleshooting-matrix.md` - Troubleshooting guide

## Current System State

**Services:**
- ❌ nba-phase2-raw-processors: e05b63b3 (OLD - before fix)
- ❌ nba-phase3-analytics-processors: 075fab1e (OLD - before fix)
- ❌ nba-phase4-precompute-processors: 8cb96558 (OLD - before fix)
- ❌ nba-scrapers: 2de48c04 (OLD - before fix)

**Expected:** All services at commit e1c10e88 or later (de3c73d9 is latest)

**Firestore:**
- Documents: 1,053 (should be ~30)
- Format: `{processor}_None_{run_id}` (should be `{processor}`)
- Accumulation: ~900/day

**Infrastructure:**
- Overall: ✅ HEALTHY (data pipeline functioning)
- Deployments: ❌ BROKEN (complete but don't update code)
- Monitoring: ✅ Working (after Session 61 permissions fix)

## Recent Changes (Committed in Session 62)

**Commit:** 6fc971bb

Files modified:
1. `data_processors/raw/requirements.txt` - Added gunicorn, GCP libraries, flask, sentry-sdk
2. `bin/deploy-service.sh` - Added nba-phase2-raw-processors support
3. `docs/09-handoff/2026-02-01-SESSION-62-HANDOFF.md` - Complete session documentation

## Known Issues

1. **Deployment mystery** 🔴 CRITICAL BLOCKER
   - Deployments complete successfully (exit code 0)
   - Services don't run new code
   - Must solve before any progress possible

2. **Phase 2 requirements** ✅ FIXED (not yet deployed)
   - Was missing gunicorn, GCP libraries
   - Fixed in Session 62, ready to deploy

3. **Scrapers deployment** ❌ Needs investigation
   - Container failed to start on port 8080
   - Likely missing dependencies like Phase 2

## Success Criteria for Session 63

By the end of this session:
- ✅ Understand WHY deployments don't update code
- ✅ Deploy at least ONE service with VERIFIED new code
- ✅ See Firestore docs drop to ~30 and stay stable
- ✅ Verify no new `_None_{run_id}` documents created
- ✅ Document solution for future deployments

## Useful Commands

### Quick Status Check
```bash
# All-in-one verification
echo "=== Git Status ==="
git log -1 --oneline

echo -e "\n=== Firestore Status ==="
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
bad = [d for d in docs if '_None_' in d.id or '_202' in d.id]
print(f'Total: {len(docs)}, Bad format: {len(bad)}')
"

echo -e "\n=== Deployed Services ==="
for svc in nba-phase2-raw-processors nba-phase3-analytics-processors \
           nba-phase4-precompute-processors nba-scrapers; do
  commit=$(gcloud run services describe $svc --region=us-west2 --format="value(metadata.labels.commit-sha)" 2>&1)
  echo "$svc: $commit"
done
```

### Inspect Deployed Code
```bash
# Get image for a service
IMAGE=$(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 --format="value(spec.template.spec.containers[0].image)")

# Check heartbeat code in that image
docker pull $IMAGE
docker run --rm $IMAGE cat /app/shared/monitoring/processor_heartbeat.py | grep -A10 "def doc_id"
```

### Deploy with Verification
```bash
# Build with no cache
docker build --no-cache -f data_processors/analytics/Dockerfile \
  -t us-west2-docker.pkg.dev/nba-props-platform/nba-props/test:latest .

# Verify code before deploying
docker run --rm us-west2-docker.pkg.dev/nba-props-platform/nba-props/test:latest \
  cat /app/shared/monitoring/processor_heartbeat.py | grep -A5 "def doc_id"

# Deploy if verified
./bin/deploy-service.sh nba-phase3-analytics-processors
```

## Important Notes

### Don't Trust Previous Session Claims
- Session 61 claimed fix was deployed → **INCORRECT**
- Always verify with Firestore doc IDs and actual code inspection
- Ground truth: Firestore doc format, not deployment logs

### Deployment Verification Checklist
After EVERY deployment:
1. ✅ Check new revision is serving traffic
2. ✅ Pull deployed image and inspect code
3. ✅ Check Firestore doc IDs for new format
4. ✅ Monitor for 5 minutes to see if issue recurs
5. ✅ Only then mark as successful

### If Stuck
- Read Session 62 handoff: `docs/09-handoff/2026-02-01-SESSION-62-HANDOFF.md`
- Check troubleshooting matrix: `docs/02-operations/troubleshooting-matrix.md`
- Ask user for clarification on priorities

## Questions to Answer This Session

1. Why do Cloud Run deployments complete but not update code?
2. Are Docker images being built with the correct code?
3. Is there an automatic rollback we're not seeing?
4. Do we need `--no-cache` on all builds?
5. Is the build context including the latest `shared/` module?

## Session 62 Commit for Reference

```
6fc971bb - fix: Add Phase 2 deployment support and fix requirements

Session 62 work:
- Fixed Phase 2 requirements.txt (missing gunicorn, GCP libraries, flask)
- Added nba-phase2-raw-processors to deployment script
- Investigated heartbeat fix deployment failure
- Created comprehensive Session 62 handoff

Key findings:
- Heartbeat fix (e1c10e88) never deployed despite Session 61 claims
- All services still running old code (verified via Firestore doc IDs)
- Deployment attempts complete but don't update running code
- Cleaned up 215 old Firestore docs, 1,053 remain (should be ~30)
```

---

**Start by investigating the deployment mystery - everything else depends on solving this!**

Good luck! 🚀
