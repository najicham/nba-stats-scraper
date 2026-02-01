# Session 62 Takeover Prompt

**Copy this entire prompt to start the next session**

---

Hi Claude! Welcome to Session 62 of the NBA Stats Scraper project.

## Context: What Session 61 Accomplished

Session 61 (Feb 1, 2026) completed THREE major infrastructure fixes:

1. **Firestore Heartbeat Document Proliferation Fix** ✅
   - Fixed design flaw: heartbeat doc_id included run_id → created new doc every run
   - Reduced from 106,349 documents to ~30 (99.97% reduction)
   - Deployed fix to Phase 3 & Phase 4
   - Deleted 105,623 old documents
   - **Expected impact:** Dashboard services health score 39 → 70+/100

2. **Dockerfile Organization Cleanup** ✅
   - Organized 21 scattered Dockerfiles into 2 clear patterns
   - Removed confusing root Dockerfiles
   - Created Phase 2 Dockerfile (now deployable!)
   - Created 400+ line organization guide
   - Repository root is now clean

3. **Infrastructure Health Audit + Monitoring Fix** ✅
   - Ran systematic 20-minute audit of BigQuery, Cloud Run, GCS, Logs, Costs
   - Found 6 issues (0 CRITICAL, 1 HIGH, 1 MEDIUM, 4 LOW)
   - Fixed monitoring permissions error (prediction-worker)
   - Created 557-line infrastructure health check guide

## Your First Tasks

### IMMEDIATE (First 10 minutes)

1. **Verify Dashboard Health Improvement**
   ```bash
   # Check dashboard or run verification from Session 61 handoff
   # Expected: Services health score should be 70+/100 (was 39/100)
   ```

2. **Verify Monitoring Errors Stopped**
   ```bash
   gcloud logging read 'resource.labels.service_name="prediction-worker"
     AND textPayload=~"monitoring.timeSeries.create"
     AND timestamp>="'$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')'"' --limit=5
   # Expected: Should see 0 errors (was 57 errors/day)
   ```

3. **Check Firestore Document Count**
   ```python
   from google.cloud import firestore
   db = firestore.Client(project='nba-props-platform')
   count = len(list(db.collection('processor_heartbeats').stream()))
   print(f"Heartbeat docs: {count}")
   # Expected: ~30-50 docs (was 106,349)
   ```

### HIGH PRIORITY (Next Session Focus)

Choose ONE of these based on what you find:

**Option 1: If Dashboard Health Still Low**
- Investigate why dashboard didn't improve
- Check if Phase 2 is creating too many old-format heartbeat docs
- Run cleanup script: `python bin/cleanup-heartbeat-docs.py`
- Consider deploying Phase 2 with new Dockerfile

**Option 2: If Everything Verified Successfully**
- Investigate 143 unidentified errors found in audit
  - See `docs/02-operations/infrastructure-health-checks.md` for commands
  - Sample logs to identify error sources
  - Create fixes as needed

**Option 3: Deploy Phase 2 (Recommended if time permits)**
- Phase 2 now has proper Dockerfile: `data_processors/raw/Dockerfile`
- This will stop it from creating old-format heartbeat docs
- Use deployment guide in CLAUDE.md

## Key Documentation (READ THESE FIRST)

**Primary Reference:**
- `docs/09-handoff/2026-02-01-SESSION-61-HANDOFF.md` (858 lines)
  - Complete Session 61 summary
  - All three fixes explained in detail
  - Verification commands
  - Known issues and next priorities

**Operational Guides:**
- `docs/02-operations/infrastructure-health-checks.md` (NEW - 557 lines)
  - Complete infrastructure audit guide
  - Commands for all components
  - Issue triage by severity
- `docs/02-operations/troubleshooting-matrix.md` (Section 7 updated)
  - Observability troubleshooting
  - Monitoring permissions fix

**Quick Reference:**
- `CLAUDE.md` (updated with Heartbeat System section)
  - Project conventions
  - Dockerfile organization
  - Heartbeat system design
  - Common fixes

## Current System State

**Deployments:**
- ✅ nba-phase3-analytics-processors: Revision 00165 (with heartbeat fix)
- ✅ nba-phase4-precompute-processors: Revision 00091 (with heartbeat fix)
- ⏳ nba-phase2-raw-processors: Revision 00126 (OLD - no heartbeat fix yet)
- ✅ prediction-worker: Has monitoring.metricWriter permissions now

**Known Issues:**
- Phase 2 still creating old-format heartbeat docs (~22/hour)
- 143 unidentified errors in logs (needs investigation)
- 50 staging tables cluttering nba_predictions dataset (low priority cleanup)
- 5 empty GCS buckets (cosmetic issue)

**Infrastructure Health:**
- Overall: ✅ HEALTHY
- No critical failures
- Data pipeline functioning (800+ predictions/day)
- BigQuery very efficient (1.98 GB processed/week)
- Storage costs minimal ($0.08/month GCS)

## Prioritized Work Queue

**IMMEDIATE (Required):**
1. Run verification checks above
2. Report findings (dashboard health, monitoring errors, doc count)

**HIGH PRIORITY:**
1. Investigate 143 unidentified errors (if verifications pass)
2. Deploy Phase 2 with new Dockerfile (stops old-format heartbeat docs)
3. Monitor dashboard health for 24 hours

**MEDIUM PRIORITY:**
1. Clean up 50 staging tables in nba_predictions
2. Update old deployment scripts to use new Dockerfile paths
3. Add monitoring alert if heartbeat docs > 100

**LOW PRIORITY:**
1. Clean up empty GCS buckets
2. Investigate 3 temp tables in nba_raw
3. Set up billing export analysis

## Useful Commands

**Check Heartbeat Document Count:**
```python
from google.cloud import firestore
from datetime import datetime, timezone, timedelta

db = firestore.Client(project='nba-props-platform')
all_docs = list(db.collection('processor_heartbeats').stream())
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
recent = [d for d in all_docs if d.to_dict().get('last_heartbeat') >= cutoff]

print(f"Total docs: {len(all_docs)}")
print(f"Recent (last hour): {len(recent)}")
print(f"Status: {'✅ Good' if len(all_docs) < 100 else '⚠️ Too many'}")
```

**Check for Old-Format Heartbeat Docs:**
```python
old_format = [d for d in all_docs if '_202' in d.id]
print(f"Old format docs: {len(old_format)}")
```

**Run Cleanup Script:**
```bash
# Preview what will be deleted
python bin/cleanup-heartbeat-docs.py --dry-run

# Actually delete (requires typing "DELETE" to confirm)
python bin/cleanup-heartbeat-docs.py
```

**Deploy Phase 2:**
```bash
# Phase 2 now has a Dockerfile - can deploy like other services
./bin/deploy-service.sh nba-phase2-raw-processors \
  -f data_processors/raw/Dockerfile
```

## Session 61 Commits (for reference)

- `e1c10e88` - Fix heartbeat document ID (processor_name only)
- `68d1e707` - Add cleanup script
- `ea6d684c` - Dockerfile organization cleanup
- `a24f5ba8` - Session 61 handoff documentation
- `0cfbbe94` - Infrastructure audit + monitoring fix

## Success Metrics for This Session

At the end of Session 62, we should have:
- ✅ Verified all Session 61 fixes are working
- ✅ Dashboard services health score ≥ 70/100
- ✅ No monitoring permission errors
- ✅ Firestore docs stable at ~30-50
- ✅ Investigated OR deployed Phase 2 OR cleaned up errors
- ✅ Created Session 62 handoff document

## Questions?

If anything is unclear:
1. Read the Session 61 handoff first: `docs/09-handoff/2026-02-01-SESSION-61-HANDOFF.md`
2. Check troubleshooting guide: `docs/02-operations/troubleshooting-matrix.md`
3. Run `/validate-daily` to check system health
4. Ask user for clarification on priorities

---

**Start by running the verification checks above, then report what you find!**

Good luck! 🚀
