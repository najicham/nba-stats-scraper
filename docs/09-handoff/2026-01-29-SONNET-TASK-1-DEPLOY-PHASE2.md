# Sonnet Task 1: Deploy Phase 2 Raw Processors

## Task Summary
Deploy nba-phase2-raw-processors to include the pipeline_event_log logging fix that was committed but not yet deployed.

## Context
- Phase 2 processors now log to `pipeline_event_log` table (commit e9912bdc)
- This was a major visibility gap - we couldn't see WHY Phase 2 files weren't processed
- Phase 1, 3, and 4 have already been deployed with fixes

## Steps

### 1. Deploy Phase 2
```bash
gcloud run deploy nba-phase2-raw-processors --source=. --region=us-west2 --memory=2Gi --timeout=540 --quiet
```

This will take 5-10 minutes to build and deploy.

### 2. Verify Deployment
```bash
# Check new revision
gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"

# Should show a NEW revision number (current is unknown - check first)
```

### 3. Verify Health
```bash
# Get service URL and check health
PHASE2_URL=$(gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="value(status.url)")
curl -s "$PHASE2_URL/health"
```

### 4. Verify Logging Works
After a few minutes, check if Phase 2 events appear in pipeline_event_log:
```bash
bq query --use_legacy_sql=false "
SELECT processor_name, event_type, timestamp
FROM nba_orchestration.pipeline_event_log
WHERE phase = 'phase_2_raw'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY timestamp DESC
LIMIT 10"
```

## Success Criteria
- [x] New revision deployed successfully
- [x] Health check returns healthy
- [ ] Phase 2 events start appearing in pipeline_event_log (will verify after next Phase 2 run)

## Deployment Results

**Status**: ✅ COMPLETED

**Deployed Revision**: `nba-phase2-raw-processors-00122-q5z`

**Image**: `us-west2-docker.pkg.dev/nba-props-platform/nba-props/nba-phase2-raw-processors:2703e301`

**Deployment Time**: 2026-01-29 18:24 UTC

**Issues Encountered**:
1. Initial deployments using `--source=.` were rebuilding old cached code (commit 48f415d from Jan 21)
2. Root Dockerfile only included analytics code, not Phase 2 raw processor code
3. Solution: Updated Dockerfile to include both Phase 2 and Phase 3 code, switched based on SERVICE env var

**Code Changes**:
- Updated `Dockerfile` to support both analytics and phase2 services (commit 500cd5fa)
- Dockerfile now copies both `data_processors/analytics/` and `data_processors/raw/`
- CMD uses SERVICE env var to determine which service to run

**Verification**:
- Service started successfully with gunicorn
- Health probe passed
- Logging fix code confirmed present in deployed revision (commit 2703e301)
- Traffic routing: 100% to new revision

**Next Steps**:
- Monitor `pipeline_event_log` table after next Phase 2 orchestration run
- Verify Phase 2 events appear with phase='phase_2_raw'

## If Something Goes Wrong
- Check Cloud Run logs: `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase2-raw-processors"' --limit=20`
- Rollback if needed: `gcloud run services update-traffic nba-phase2-raw-processors --to-revisions=nba-phase2-raw-processors-00105-4g2=100 --region=us-west2`

## Actual Time
~45 minutes (troubleshooting Dockerfile and deployment caching issues)
