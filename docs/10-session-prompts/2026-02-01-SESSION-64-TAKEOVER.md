# Session 64 Takeover Prompt

**Date:** 2026-02-01
**Previous Session:** Session 63 Part 2 (Heartbeat Fix Deployment)
**System Status:** ✅ Healthy - All critical issues resolved

---

## TL;DR - What You Need to Know

Session 63 Part 2 **successfully deployed the heartbeat fix** and resolved the Firestore document proliferation issue. The system is now stable with 18 Firestore heartbeat documents (down from 1,053). All Phase 2+ services are running correct code. **No urgent work required.**

**Current State:**
- ✅ Firestore heartbeat documents: 18 (expected ~30)
- ✅ Bad format documents: 0
- ✅ All services running with correct heartbeat code
- ⚠️ 20+ backfill jobs still use old code (but not actively running)

---

## What Session 63 Part 2 Accomplished

### The Problem We Solved

**Issue:** Firestore `processor_heartbeats` collection had 1,053 documents (should be ~30)
- Documents had bad format: `NbacTeamBoxscoreProcessor_None_097ffc9c`
- Should be: `NbacTeamBoxscoreProcessor` or `p2_nba_raw.nbac_team_boxscore`
- Accumulating ~900 new documents per day
- Heartbeat fix (commit `e1c10e88`) existed but wasn't deployed

### Root Causes Discovered

**Root Cause #1: Cloud Run Revision Snapshots**

Cloud Run services use **revision snapshots**, not live `:latest` image tags.

When you deploy:
1. Docker image built and tagged as `:latest`
2. Cloud Run creates a revision referencing that specific image digest
3. Service continues using that revision even if `:latest` is updated

**Implication:** Session 62 may have updated `:latest` tags but didn't deploy new revisions.

**Root Cause #2: Separate Backfill Job Images**

20+ Cloud Run **JOBS** (not services) use separate Docker images in `gcr.io`:
- `nbac-team-boxscore-processor-backfill`
- `nbac-schedule-processor-backfill`
- `bettingpros-player-props-processor-backfill`
- ... (17 more)

These jobs weren't updated when service images were updated. Jobs last ran in September 2025, so not actively creating bad documents.

### What We Fixed

1. **Deployed Phase 2 with heartbeat fix**
   - Service: `nba-phase2-raw-processors`
   - Revision: `nba-phase2-raw-processors-00129-lf2`
   - Commit: `ce269d67` (includes fix from `e1c10e88`)
   - Verified logs show correct format

2. **Cleaned up Firestore**
   - Deleted 1,035 bad-format documents
   - Remaining: 18 good-format documents
   - Verified no new bad documents for 2 minutes

3. **Documented the investigation**
   - Comprehensive handoff: `docs/09-handoff/2026-02-01-SESSION-63-PART-2-HEARTBEAT-FIX.md`
   - Root cause analysis
   - Commands reference
   - Key learnings

---

## Current System State

### Firestore Heartbeat Documents

**Total:** 18 documents ✅

**Expected:** ~30 (one per active processor)

**Sample document IDs:**
```
AsyncUpcomingPlayerGameContextProcessor
PlayerCompositeFactorsProcessor
PlayerGameSummaryProcessor
TeamDefenseGameSummaryProcessor
TeamOffenseGameSummaryProcessor
p2_nba_raw.bdl_live_boxscores
p2_nba_raw.nbl_player_boxscores
p2_nba_raw.bettingpros_player_points_props
p2_nba_raw.nbac_gamebook_player_stats
p2_nba_raw.nbac_injury_report
p2_nba_raw.nbac_schedule
p2_nba_raw.nbac_team_boxscore
p2_nba_raw.odds_api_game_lines
p2_nbac_player_boxscores
```

**Document format:**
- Phase 2 processors: `p2_{table_name}` (e.g., `p2_nba_raw.nbac_team_boxscore`)
- Phase 3+ processors: `{ProcessorName}` (e.g., `PlayerGameSummaryProcessor`)

### Service Deployment Status

| Service | Revision | Commit | Heartbeat Status |
|---------|----------|--------|------------------|
| nba-phase2-raw-processors | 00129-lf2 | ce269d67 | ✅ Fixed |
| nba-phase3-analytics-processors | 00169-56h | 075fab1e* | ✅ Working |
| nba-phase4-precompute-processors | Unknown | 8cb96558* | ✅ Working |
| nba-scrapers | Unknown | 2de48c04 | ⚠️ Not checked |

*Note: Commit labels may be stale, but Docker images have correct code

### Cloud Run Jobs Status

**Total:** 20+ backfill jobs

**Image registry:** `gcr.io/nba-props-platform/` (separate from services)

**Heartbeat code:** Old format (would create `ProcessorName_None_RunId` if run)

**Last execution:** September 2025 (5 months ago)

**Impact:** Not actively creating bad documents

**Action needed:** Update job images before next backfill run (not urgent)

### Known Issues

**None blocking.** Optional improvements:

1. **Backfill jobs have old code** (Low priority - not actively running)
   - 20+ jobs in `gcr.io` registry with old heartbeat code
   - Could update to use same images as services
   - Or rebuild with latest code

2. **No monitoring for heartbeat doc count** (Medium priority)
   - Could add alert if collection exceeds 50 documents
   - Would catch future proliferation issues early

3. **Cleanup script incomplete** (Low priority)
   - `bin/cleanup-heartbeat-docs.py` only detects date-based old format
   - Doesn't detect `_None_` format
   - Could update to handle all old formats

---

## Quick Status Check Commands

### Check Firestore Heartbeat Status

```bash
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
bad = [d for d in docs if '_None_' in d.id or '_202' in d.id]
print(f'Total documents: {len(docs)} (expected: ~30)')
print(f'Bad format: {len(bad)} (expected: 0)')
print(f'\nStatus: {\"✅ Healthy\" if len(bad) == 0 and len(docs) < 50 else \"⚠️ Issue detected\"}')"
```

**Expected output:**
```
Total documents: 18 (expected: ~30)
Bad format: 0 (expected: 0)

Status: ✅ Healthy
```

### Check Service Deployments

```bash
for service in nba-phase2-raw-processors nba-phase3-analytics-processors \
               nba-phase4-precompute-processors nba-scrapers; do
  echo "=== $service ==="
  gcloud run services describe $service --region=us-west2 \
    --format="value(status.latestReadyRevisionName,metadata.labels.commit-sha)" 2>/dev/null \
    || echo "Not found"
done
```

### Check Recent Heartbeat Activity

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND (textPayload=~"Heartbeat" OR jsonPayload.message=~"Heartbeat")' \
  --limit=10 --freshness=30m --format=json \
  | jq -r '.[] | {service: .resource.labels.service_name, msg: (.jsonPayload.message // .textPayload)} | "\(.service): \(.msg)"'
```

---

## If You Need to Deploy Services

### Standard Deployment

```bash
# Always use the deployment script (builds from repo root)
./bin/deploy-service.sh <service-name>

# Available services:
#   - nba-phase2-raw-processors
#   - nba-phase3-analytics-processors
#   - nba-phase4-precompute-processors
#   - nba-scrapers
#   - prediction-coordinator
#   - prediction-worker
```

### Verify Deployment Actually Worked

**IMPORTANT:** Don't trust deployment exit codes. Always verify:

```bash
SERVICE=nba-phase2-raw-processors

# 1. Check active revision
gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# 2. Check image being used
IMAGE=$(gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(spec.template.spec.containers[0].image)")
echo "Image: $IMAGE"

# 3. Verify code in deployed image
docker pull $IMAGE
docker run --rm $IMAGE cat /app/shared/monitoring/processor_heartbeat.py \
  | grep -A5 "def doc_id"

# Expected output: "return self.processor_name" ✅

# 4. Check runtime behavior
gcloud logging read "resource.labels.service_name=\"$SERVICE\"" \
  --limit=10 --freshness=10m | grep -i heartbeat
```

---

## If Heartbeat Documents Start Proliferating Again

### Diagnose the Issue

```bash
# Check current state
python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())

cutoff = datetime.now() - timedelta(hours=1)

# Find recent bad documents
recent_bad = []
for doc in docs:
    data = doc.to_dict()
    last_hb = data.get('last_heartbeat')
    if '_None_' in doc.id or '_202' in doc.id:
        if last_hb and hasattr(last_hb, 'replace') and last_hb.replace(tzinfo=None) > cutoff:
            recent_bad.append(doc.id)

if recent_bad:
    print(f'⚠️  {len(recent_bad)} bad documents created in last hour!')
    print('Recent bad documents:')
    for doc_id in recent_bad[:10]:
        print(f'  {doc_id}')
else:
    print('✅ No new bad documents in last hour')
"
```

### Find Which Service is Creating Bad Documents

```bash
# Search logs for the bad processor name
PROCESSOR_NAME="NbacTeamBoxscoreProcessor"  # Replace with actual bad processor

gcloud logging read "resource.type=\"cloud_run_revision\"
  AND textPayload=~\"$PROCESSOR_NAME\"" \
  --limit=20 --freshness=1h --format=json \
  | jq -r '.[] | {service: .resource.labels.service_name, revision: .resource.labels.revision_name, msg: (.textPayload // .jsonPayload.message)} | "\(.service) (\(.revision)): \(.msg)"' \
  | head -20
```

### Clean Up Bad Documents

```bash
python3 << 'EOF'
from google.cloud import firestore

db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
bad_docs = [d for d in docs if '_None_' in d.id or '_202' in d.id]

print(f"Found {len(bad_docs)} bad-format documents")

if len(bad_docs) > 0:
    print("Deleting...")
    batch_size = 500
    for i in range(0, len(bad_docs), batch_size):
        batch = db.batch()
        for doc in bad_docs[i:i+batch_size]:
            batch.delete(doc.reference)
        batch.commit()
        print(f"Deleted {min(i+batch_size, len(bad_docs))}/{len(bad_docs)}")

    remaining = len(list(db.collection('processor_heartbeats').stream()))
    print(f"\n✅ Cleanup complete. Remaining documents: {remaining}")
else:
    print("✅ No bad documents to clean up")
EOF
```

---

## If You Need to Update Backfill Jobs

**When:** Before running backfill jobs (they currently have old heartbeat code)

**Option 1: Use same image as Phase 2 service (Recommended)**

```bash
# Update job to use Phase 2 service image
gcloud run jobs update nbac-team-boxscore-processor-backfill \
  --region=us-west2 \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/nba-phase2-raw-processors:latest

# Repeat for other jobs
```

**List of backfill jobs:**
```
nbac-team-boxscore-processor-backfill
nbac-schedule-processor-backfill
bettingpros-player-props-processor-backfill
nbac-injury-report-processor-backfill
nbac-player-boxscore-processor-backfill
bdl-active-players-processor-backfill
bdl-standings-processor-backfill
bdl-boxscores-processor-backfill
bdl-injuries-processor-backfill
bigdataball-pbp-processor-backfill
br-roster-processor-backfill
espn-boxscore-processor-backfill
espn-scoreboard-processor-backfill
espn-team-roster-processor-backfill
gamebook-registry-processor-backfill
nba-players-registry-processor-backfill
nbac-gamebook-processor-backfill
nbac-play-by-play-processor-backfill
nbac-player-movement-processor-backfill
nbac-referee-processor-backfill
odds-game-lines-processor-backfill
```

**Option 2: Rebuild job images**

Find and rebuild job Dockerfiles (more work, use Option 1 instead)

---

## Key Learnings from Session 63 Part 2

### 1. Cloud Run Deployment Mechanics

**Cloud Run uses revision snapshots, not live image tags.**

When you run `gcloud run deploy`:
1. Builds/pulls the Docker image
2. Creates a **revision** pointing to the specific image digest
3. Routes traffic to that revision

**Key insight:** Updating the `:latest` tag doesn't automatically update the service. You must deploy a new revision.

**Verification is critical:**
- ❌ Don't trust: Deployment exit code (0 ≠ correct code deployed)
- ❌ Don't trust: Service commit labels (can be stale)
- ✅ Do verify: Actual code in running container
- ✅ Do verify: Runtime behavior (logs, Firestore, BigQuery)

### 2. Cloud Run Services vs Jobs

**Services:**
- Long-running HTTP servers
- Auto-scale based on traffic
- Example: `nba-phase2-raw-processors`

**Jobs:**
- Execute once and exit
- Triggered manually or scheduled
- **Use separate Docker images**
- Example: `nbac-team-boxscore-processor-backfill`

**Critical:** Deploying a service does NOT update related jobs!

### 3. Firestore Document Proliferation Pattern

**Symptom:** Collection grows unbounded

**Bad pattern:**
```python
doc_id = f"{processor_name}_{date}_{run_id}"  # New doc every run
```

**Good pattern:**
```python
doc_id = processor_name  # Update same doc every run
```

**Detection:** Collection has >2x expected documents

**Fix:** Delete old format documents, deploy correct code

---

## Other Context You Should Know

### Session 63 Also Did V8 Hit Rate Investigation

There's a **separate** Session 63 handoff for V8 hit rate work:
- File: `docs/09-handoff/2026-02-01-SESSION-63-HANDOFF.md`
- Focus: Daily vs backfill code path differences
- Status: Investigation complete, fix plan created
- Action: Waiting for Phase 1 verification

**Don't confuse the two Session 63 parts:**
- Session 63 Part 1: V8 hit rate investigation (separate chat)
- Session 63 Part 2: Heartbeat fix deployment (this context)

### Recent Sessions Overview

| Session | Date | Focus | Status |
|---------|------|-------|--------|
| 60 | 2026-01-31 | Orchestrator deployment fix | ✅ Complete |
| 61 | 2026-02-01 | Infrastructure health audit | ✅ Complete |
| 62 | 2026-02-01 | Vegas line backfill fix | ✅ Complete |
| 63 Part 1 | 2026-02-01 | V8 hit rate investigation | ⏳ Awaiting Phase 1 |
| 63 Part 2 | 2026-02-01 | Heartbeat fix deployment | ✅ Complete |

### Documentation Locations

| Document | Purpose |
|----------|---------|
| `CLAUDE.md` | Session instructions, conventions, commands |
| `docs/09-handoff/` | Session handoff documents |
| `docs/02-operations/troubleshooting-matrix.md` | Common issues and fixes |
| `docs/01-architecture/` | System architecture |
| `docs/03-phases/` | Phase-specific documentation |

### Important Git Commits

| Commit | Date | Description |
|--------|------|-------------|
| e1c10e88 | ~Jan 2026 | Heartbeat fix (use processor_name as doc_id) |
| ce269d67 | 2026-02-01 | Latest commit (includes heartbeat fix) |
| b8c392ca | 2026-02-01 | Session 63 Part 2 handoff |

---

## What You Could Work On (All Optional)

### High Priority (If Needed)

1. **Continue V8 hit rate investigation**
   - See: `docs/09-handoff/2026-02-01-SESSION-63-HANDOFF.md`
   - Next: Phase 1.1 - Save current state for Jan 12
   - Then: Test backfill mode hypothesis

2. **Update backfill jobs** (before next backfill run)
   - 20+ jobs still have old heartbeat code
   - Simple fix: Update to use Phase 2 service image
   - Not urgent (jobs haven't run since Sept 2025)

### Medium Priority

3. **Add heartbeat document count monitoring**
   - Alert if collection exceeds 50 documents
   - Prevents future proliferation issues

4. **Update cleanup script**
   - Add `_None_` format detection
   - File: `bin/cleanup-heartbeat-docs.py`

5. **Add deployment verification to deploy script**
   - Auto-check that correct code actually deployed
   - File: `bin/deploy-service.sh`

### Low Priority

6. **Consolidate backfill job Dockerfiles**
   - Use shared base image
   - Ensures consistency across jobs

---

## How to Start Your Session

### 1. Check System Health

```bash
# Quick health check
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
bad = [d for d in docs if '_None_' in d.id or '_202' in d.id]
total = len(docs)
bad_count = len(bad)
status = '✅ Healthy' if bad_count == 0 and total < 50 else '⚠️ Needs attention'
print(f'Firestore heartbeats: {total} documents, {bad_count} bad format')
print(f'Status: {status}')
"
```

**Expected:** `Firestore heartbeats: 18 documents, 0 bad format` / `Status: ✅ Healthy`

### 2. Read Recent Context

```bash
# Read latest handoff
cat docs/09-handoff/2026-02-01-SESSION-63-PART-2-HEARTBEAT-FIX.md | less

# Check git log
git log --oneline -10

# Check for uncommitted changes
git status
```

### 3. Decide What to Work On

Options:
- Continue V8 hit rate investigation (see other Session 63 handoff)
- Regular feature work or bug fixes
- Optional improvements listed above
- User requests

---

## Emergency Procedures

### If Heartbeat Documents Proliferating Again

1. Run quick status check (see above)
2. Identify which service creating bad documents (search logs)
3. Check if backfill jobs are running: `gcloud run jobs executions list --job=<job-name> --limit=1`
4. If service issue: Redeploy with `./bin/deploy-service.sh`
5. If job issue: Update job image or pause job
6. Clean up bad documents (see cleanup script above)

### If Service Deployment Needed Urgently

```bash
# Deploy with verification
./bin/deploy-service.sh <service-name>

# Immediately verify
gcloud logging read "resource.labels.service_name=\"<service-name>\"" \
  --limit=10 --freshness=5m
```

### If Firestore Collection Growing

```bash
# Check growth rate
python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())

cutoff = datetime.now() - timedelta(hours=1)
recent = [d for d in docs if d.to_dict().get('last_heartbeat') and
          d.to_dict()['last_heartbeat'].replace(tzinfo=None) > cutoff]

print(f'Total: {len(docs)}')
print(f'Updated in last hour: {len(recent)}')
print(f'Growth rate: ~{len(recent) * 24} docs/day')
"
```

---

## Final Notes

**System Status:** ✅ Healthy - No urgent issues

**Last Verified:** 2026-02-01 ~22:00 UTC (end of Session 63 Part 2)

**Next Verification Recommended:** Anytime before major work

**Key Files to Know:**
- Handoff: `docs/09-handoff/2026-02-01-SESSION-63-PART-2-HEARTBEAT-FIX.md`
- Heartbeat code: `shared/monitoring/processor_heartbeat.py`
- Deployment script: `bin/deploy-service.sh`
- Cleanup script: `bin/cleanup-heartbeat-docs.py`

**If You Have Questions:**
- Check `CLAUDE.md` for project conventions
- Read recent handoffs in `docs/09-handoff/`
- Check troubleshooting guide: `docs/02-operations/troubleshooting-matrix.md`

**Good luck with Session 64!** 🚀

---

*Created: 2026-02-01 Session 63 Part 2*
*For: Session 64 and beyond*
