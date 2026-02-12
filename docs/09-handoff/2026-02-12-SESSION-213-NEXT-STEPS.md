# Session 213 - Next Steps: Phase 6 Deployment & Cloud Build Standardization

**Date:** 2026-02-12 (for next session)
**Previous Session:** 212 (Grading Coverage Investigation + DNP Voiding)
**Priority:** Medium (Phase 6 deployment needed, Cloud Build standardization recommended)

## TL;DR

Session 212 completed grading investigation and DNP voiding fix (100% coverage achieved). Two items remain:
1. **Deploy phase6-export** with Session 211 quality filtering (currently outdated)
2. **Standardize Cloud Function deployments** via Cloud Build triggers (prevent future drift)

## What Session 212 Accomplished

### ✅ Completed
1. **Grading Coverage Investigation**
   - Root cause: NO_PROP_LINE predictions intentionally excluded
   - Fixed grading_gap_detector to calculate graded/gradable correctly
   - Result: No real grading gaps exist

2. **DNP Voiding Implementation**
   - DNP predictions now graded as `is_voided=True` instead of skipped
   - 100% grading coverage (289 active + 36 voided = 325 total)
   - Deployed to phase5b-grading Cloud Function ✅

3. **Grading Gap Detector Automation**
   - Deployed as Cloud Function
   - Runs daily at 9 AM ET via Cloud Scheduler
   - Auto-detects gaps and triggers backfills ✅

### 📊 Results
- **Grading coverage:** 100% (every prediction gets a record)
- **Audit trail:** Complete with `is_voided`, `void_reason`, `graded_at`
- **Automation:** Daily gap detection active

## Outstanding Work

### 1. Deploy phase6-export (HIGH PRIORITY)

**Problem:** Phase 6 quality filtering from Session 211 NOT deployed yet.

**Current State:**
- `phase6-export` Cloud Function on commit `b5e5c5c` (Session 209)
- Session 211 quality filtering in commits `2111d8c0` and later
- Best bets exports missing quality fields

**Impact:**
- User-facing exports may include low-quality predictions
- Quality filtering not active in production

**Action Required:**
```bash
# Option A: Quick manual deploy (5 min)
cd /home/naji/code/nba-stats-scraper
gcloud functions deploy phase6-export \
  --gen2 \
  --region=us-west2 \
  --runtime=python311 \
  --entry-point=main \
  --trigger-topic=nba-phase6-trigger \
  --service-account=756957797294-compute@developer.gserviceaccount.com \
  --memory=1GiB \
  --timeout=300s \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform" \
  --source=./orchestration/cloud_functions/phase6_export \
  --quiet
```

**Verification:**
```bash
# After deployment, check best_bets export has quality filtering
gsutil cat gs://nba-props-platform-api/v1/best-bets/latest.json | \
  python3 -c "import json, sys; data = json.load(sys.stdin); \
  print('Quality filtering:', 'quality_alert_level' in data['picks'][0] if data['picks'] else 'No picks')"
```

### 2. Standardize Cloud Build Deployment (RECOMMENDED)

**Problem:** Mixed deployment approach causes drift.

**Current State:**
- ✅ Cloud Run services: Auto-deploy via Cloud Build triggers
- ⚠️ Cloud Functions: Manual `gcloud functions deploy`
- Result: Easy to miss deployments, drift risk

**Two Approaches:**

#### Approach A: Convert Functions → Cloud Run (PREFERRED)

**Benefits:**
- All services use same deployment pattern
- Better scaling/performance
- Easier debugging (Cloud Run has better logging)
- Auto-deploy on push to main

**Functions to Convert:**
1. `phase5b-grading` - Grading service
2. `phase6-export` - Publishing/export service
3. `grading-gap-detector` - Daily gap detection (just deployed!)

**Effort:** ~2 hours for all three
- Create Dockerfile for each
- Set up Cloud Build triggers
- Test deployments
- Update documentation

#### Approach B: Add Cloud Build Triggers for Functions

**Benefits:**
- Keep functions as-is
- Add automation layer

**Process:**
1. Create `cloudbuild.yaml` for each function
2. Set up triggers watching relevant directories
3. Auto-deploy on push to main

**Effort:** ~1 hour

### 3. Related: 30 Failing Cloud Scheduler Jobs

Session 212 (Part 2) discovered **30 of 129 scheduler jobs failing**:
- 3 PERMISSION_DENIED (IAM issues)
- 14 INTERNAL (500 errors from targets)
- 1 UNAUTHENTICATED (auth config broken)
- 5 DEADLINE_EXCEEDED (timeouts)

**Note:** Not urgent, but should be triaged in future session.

## Recommended Session 213 Plan

### Quick Win (30 min)
1. ✅ Deploy phase6-export manually
2. ✅ Verify quality filtering in exports
3. ✅ Update handoff docs

### Full Solution (2-3 hours)
1. ✅ Deploy phase6-export manually (first)
2. ✅ Convert phase5b-grading → Cloud Run
3. ✅ Convert phase6-export → Cloud Run
4. ✅ Convert grading-gap-detector → Cloud Run
5. ✅ Set up Cloud Build triggers for all three
6. ✅ Test auto-deploy workflow
7. ✅ Update documentation

### Minimal Approach (if time-limited)
1. ✅ Deploy phase6-export manually
2. 📋 Document Cloud Build conversion as future work

## Files to Review

**Session 212 Commits:**
```bash
git log --oneline d00fcd97..13742c00
# Shows: DNP voiding, grading-gap-detector deployment, symlinks
```

**Key Files:**
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - DNP voiding logic
- `bin/monitoring/grading_gap_detector.py` - Fixed gap detector
- `orchestration/cloud_functions/grading-gap-detector/` - New Cloud Function
- `orchestration/cloud_functions/grading/` - Symlinks added for deployment

**Documentation:**
- `docs/08-projects/current/session-212-grading-coverage/ROOT-CAUSE-ANALYSIS.md`
- `docs/09-handoff/2026-02-11-SESSION-212-HANDOFF.md` (Part 1 & 2)

## Quick Start Commands

```bash
# 1. Read latest handoff
cat docs/09-handoff/2026-02-12-SESSION-213-NEXT-STEPS.md

# 2. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 3. Verify grading gap detector
gcloud functions describe grading-gap-detector --gen2 --region=us-west2 --format="value(state,updateTime)"

# 4. Check phase6-export status
gcloud functions describe phase6-export --gen2 --region=us-west2 --format="value(labels.commit-sha,updateTime)"

# 5. Deploy phase6-export (if needed)
# See Action Required section above
```

## Success Criteria

### Phase 6 Deployment
- ✅ phase6-export deployed with latest code
- ✅ Commit SHA matches current main branch
- ✅ Best bets export includes quality fields
- ✅ Quality filtering active in production

### Cloud Build Standardization (if done)
- ✅ All critical services on Cloud Run
- ✅ Cloud Build triggers configured
- ✅ Test deployment succeeds
- ✅ No manual deployment needed

## Questions for Next Session

1. **Approach decision:** Convert to Cloud Run (2-3h) or manual deploy + plan conversion (30min)?
2. **Priority:** Should we tackle the 30 failing scheduler jobs too?
3. **Scope:** Just phase6-export, or full Cloud Build standardization?

## Session 212 Final Stats

**Time:** ~4 hours
**Commits:** 8 commits (grading fix, gap detector, symlinks, docs)
**Deployments:** 2 Cloud Functions (phase5b-grading, grading-gap-detector)
**Impact:** 100% grading coverage, daily automated monitoring
**Outstanding:** Phase 6 deployment, Cloud Build standardization

---

**Ready to start Session 213!** 🚀

Recommended: Start with phase6-export deployment (30 min quick win), then decide on Cloud Run conversion.
