# NBA Props Platform - System Status

**Last Updated:** December 26, 2025 (Session 171)

---

## Quick Status Overview

| Pipeline Phase | Status | Last Run | Notes |
|----------------|--------|----------|-------|
| Phase 1 (Scrapers) | :white_check_mark: Working | Hourly | Running on schedule |
| Phase 2 (Raw Processors) | :white_check_mark: Working | On data arrival | Triggered by Pub/Sub |
| Phase 3 (Analytics) | :white_check_mark: Working | Multiple triggers | Fixed Dec 26 (wrong Docker image) |
| Phase 4 (Precompute) | :white_check_mark: Working | Overnight + Morning | NEW: same-day scheduler added |
| Phase 5 (Predictions) | :white_check_mark: Working | Morning | NEW: same-day scheduler added |
| Phase 6 (Export) | :white_check_mark: Working | Multiple times daily | Exports to GCS |

---

## Active Schedulers

### Same-Day Predictions (NEW - Added Dec 26)

| Scheduler | Time (ET) | What It Does |
|-----------|-----------|--------------|
| `same-day-phase3` | 10:30 AM | UpcomingPlayerGameContextProcessor for TODAY |
| `same-day-phase4` | 11:00 AM | MLFeatureStoreProcessor for TODAY (same-day mode) |
| `same-day-predictions` | 11:30 AM | Prediction coordinator for TODAY |

### Overnight Processing (Post-Game)

| Scheduler | Time (PT) | What It Does |
|-----------|-----------|--------------|
| `player-composite-factors-daily` | 11:00 PM | Composite factors for YESTERDAY |
| `player-daily-cache-daily` | 11:15 PM | Daily cache for YESTERDAY |
| `ml-feature-store-daily` | 11:30 PM | ML features for YESTERDAY |

### Exports (Phase 6)

| Scheduler | Time (ET) | What It Does |
|-----------|-----------|--------------|
| `phase6-daily-results` | 5:00 AM | Export yesterday's results |
| `phase6-tonight-picks` | 1:00 PM | Export tonight's predictions |
| `phase6-hourly-trends` | Hourly 6AM-11PM | Export trend data |
| `live-export-evening` | Every 3 min 7-11 PM | Live scores during games |
| `live-export-late-night` | Every 3 min 12-1 AM | Late night games |

### Other

| Scheduler | Time (ET) | What It Does |
|-----------|-----------|--------------|
| `execute-workflows` | :05 every hour | Master workflow executor |
| `master-controller-hourly` | :00 every hour | Pipeline orchestration |
| `grading-daily` | 11:00 AM | Grade yesterday's predictions |

---

## Known Issues (Active)

### 1. AWS SES Missing on Phase 4
**Priority:** LOW
**Impact:** Email alerts from Phase 4 fail silently

Phase 4 service doesn't have AWS SES credentials configured. Email alerting will fail.

**Fix:** Add AWS credentials to Phase 4 deploy script or run:
```bash
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --set-env-vars="AWS_ACCESS_KEY_ID=<KEY>,AWS_SECRET_ACCESS_KEY=<SECRET>"
```

### 2. Prediction Gap Dec 21-25
**Priority:** MEDIUM
**Impact:** Historical predictions missing

Predictions from Dec 21-25 don't exist. The pipeline was broken during this period.

**Fix:** Backfill using manual commands (see runbook)

### 3. player_daily_cache Low Coverage
**Priority:** LOW
**Impact:** Only 44/172 players in cache for some dates

Investigation needed to understand why cache coverage is low.

---

## Recently Resolved Issues

### Phase 5 Predictions Not Running (Resolved Dec 26)
**Root Cause:** No same-day prediction scheduler existed. Overnight schedulers process YESTERDAY's games.

**Resolution:**
- Added `TODAY` date support to Phase 3/4 services
- Created morning schedulers for same-day predictions
- See: `docs/08-projects/current/PHASE5-PREDICTIONS-NOT-RUNNING.md`

### Phase 3 Wrong Docker Image (Resolved Dec 26)
**Root Cause:** Phase 3 service was running Phase 4 code.

**Resolution:** Redeployed with correct `analytics-processor.Dockerfile`.

---

## Service URLs

| Service | URL | Health Check |
|---------|-----|--------------|
| Phase 1 Scrapers | https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app | /health |
| Phase 2 Raw | https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app | /health |
| Phase 3 Analytics | https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app | /health |
| Phase 4 Precompute | https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app | /health |
| Prediction Coordinator | https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app | /health |
| Prediction Worker | https://prediction-worker-f7p3g7f6ya-wl.a.run.app | /health |

---

## Quick Health Check

```bash
# Check all services
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  echo -n "$svc: "
  curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq -r '.status // .error // "failed"' 2>/dev/null || echo "failed"
done
```

---

## Key BigQuery Tables

| Table | Purpose | Expected Freshness |
|-------|---------|-------------------|
| `nba_raw.*` | Raw scraped data | Updated hourly |
| `nba_analytics.player_game_summary` | Per-game player stats | After games complete |
| `nba_analytics.upcoming_player_game_context` | Today's expected players | By 11 AM ET |
| `nba_precompute.ml_feature_store_v2` | ML features | By 11:30 AM ET |
| `nba_predictions.player_prop_predictions` | Generated predictions | By noon ET |

---

## Emergency Procedures

### Pipeline Completely Down
1. Check GCP status: https://status.cloud.google.com/
2. Check Cloud Run services are deployed
3. Check Pub/Sub topics exist
4. Manually trigger schedulers

### Predictions Not Generating
1. Check Phase 4 completion in Firestore
2. Run Phase 4→5 orchestrator manually
3. Trigger prediction coordinator directly:
```bash
curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"force": true}'
```

### Exports Missing
1. Check Phase 6 Cloud Function logs
2. Manually trigger export:
```bash
gcloud scheduler jobs run phase6-tonight-picks --location=us-west2
```

---

## Related Documentation

- [Prediction Pipeline Runbook](../../02-operations/runbooks/prediction-pipeline.md)
- [Troubleshooting Guide](../../02-operations/troubleshooting.md)
- [Daily Monitoring](../../02-operations/daily-monitoring.md)
