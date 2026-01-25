# Services Inventory

Complete list of all services in the NBA pipeline.

## Cloud Run Services

| Service | Phase | Purpose | Deploy Script |
|---------|-------|---------|---------------|
| `nba-phase1-scrapers` | 1 | Runs scrapers, workflow evaluation | `bin/scrapers/deploy/deploy_scrapers_simple.sh` |
| `nba-phase2-raw-processors` | 2 | Processes raw data to BigQuery | `bin/raw/deploy/deploy_processors_simple.sh` |
| `nba-phase3-analytics-processors` | 3 | Generates analytics tables | `bin/analytics/deploy/deploy_analytics_processors.sh` |
| `nba-phase4-precompute-processors` | 4 | Precomputes features | `bin/precompute/deploy/deploy_precompute_processors.sh` |
| `nba-phase5-prediction-coordinator` | 5 | Coordinates predictions | `bin/predictions/deploy/deploy_prediction_coordinator.sh` |
| `nba-phase5-prediction-worker` | 5 | Runs ML predictions | `bin/predictions/deploy/deploy_prediction_worker.sh` |

## Cloud Functions

| Function | Trigger | Memory | Purpose |
|----------|---------|--------|---------|
| `phase2-to-phase3-orchestrator` | Pub/Sub: nba-phase2-raw-complete | 512MB | Triggers Phase 3 after Phase 2 |
| `phase3-to-phase4-orchestrator` | Pub/Sub: nba-phase3-analytics-complete | 512MB | Triggers Phase 4 after Phase 3 |
| `phase4-to-phase5-orchestrator` | Pub/Sub: nba-phase4-precompute-complete | 512MB | Triggers Phase 5 after Phase 4 |
| `phase5-to-phase6-orchestrator` | Pub/Sub: nba-phase5-predictions-complete | 512MB | Triggers Phase 6 after Phase 5 |
| `phase5b-grading` | Pub/Sub: nba-grading-trigger | 1GB | Grades predictions |
| `phase6-export` | Pub/Sub: nba-phase6-export-trigger | 2GB | Exports to API |

### Memory Guidelines

**Orchestrators:** Minimum 512MB. BigQuery and Firestore clients consume ~250MB at startup.

**Warning Signs:**
- Log message: `Memory limit of X MiB exceeded with Y MiB used`
- Container exits with code 137 (OOM killed)
- Startup probe failures

**Monitoring:**
```bash
# Check all service memory allocations
./bin/monitoring/check_cloud_resources.sh

# Include OOM warning check from logs
./bin/monitoring/check_cloud_resources.sh --check-logs
```

## Cloud Scheduler Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| `master-controller-hourly` | `0 * * * *` | Hourly workflow evaluation |
| `execute-workflows` | `5 0-23 * * *` | Execute pending workflows |
| `daily-schedule-locker` | `0 10 * * *` | Lock schedule for the day |
| `cleanup-processor` | `*/15 * * * *` | Clean up stale runs |
| `grading-daily` | `0 11 * * *` | Daily grading run |

## Pub/Sub Topics

| Topic | Publisher | Subscriber |
|-------|-----------|------------|
| `nba-phase1-scraper-complete` | Scrapers | Phase 2 |
| `nba-phase2-raw-complete` | Phase 2 Processors | phase2-to-phase3 |
| `nba-phase3-analytics-complete` | Phase 3 Processors | phase3-to-phase4 |
| `nba-phase4-precompute-complete` | Phase 4 Processors | phase4-to-phase5 |
| `nba-phase5-predictions-complete` | Phase 5 Processors | phase5-to-phase6 |

## Checking Service Health

```bash
# List all Cloud Run services with deploy times
gcloud run services list --format="table(SERVICE,REGION,LAST_DEPLOYED)"

# Check specific service logs
gcloud run services logs read nba-phase1-scrapers --region=us-west2 --limit=50

# List Cloud Scheduler jobs
gcloud scheduler jobs list --location=us-west2

# Check Cloud Function status
gcloud functions list --format="table(NAME,STATUS)"
```

## Version Tracking

**Problem:** Services can become stale (e.g., scrapers was 5 months old).

**Solution:** Check deployment dates:
```bash
gcloud run revisions list --service=SERVICE_NAME --region=us-west2 --format="table(REVISION,DEPLOYED)" | head -3
```

**TODO:** Add commit SHA to Cloud Run labels for better tracking.
