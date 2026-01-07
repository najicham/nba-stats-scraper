# Next Chat Session Prompt

Copy everything below this line into a new chat:

---

## Context: Pipeline Reliability & Test Environment

I've been working on pipeline reliability improvements for my NBA stats scraper. The previous session deployed all 25 reliability improvements and built a test environment.

## What Was Done (Previous Session)

**Deployments completed:**
- Prediction Coordinator (with COORDINATOR_API_KEY auth)
- Prediction Worker (batch loading, 500 on empty predictions)
- Admin Dashboard (rate limiting, audit trail)
- 4 Cloud Functions: phase4-to-phase5, phase5-to-phase6, dlq-monitor, backfill-trigger

**Test environment built:**
- `bin/testing/setup_test_datasets.sh` - Creates test BigQuery datasets
- `bin/testing/replay_pipeline.py` - Full pipeline replay orchestrator
- `bin/testing/validate_replay.py` - Validation framework
- `bin/testing/run_tonight_tests.sh` - Automated test runner
- 4 test datasets created: `test_nba_source`, `test_nba_analytics`, `test_nba_predictions`, `test_nba_precompute`

**Bugs fixed during deployment:**
- Added `pandas` and `google-cloud-storage` to coordinator requirements
- Added `google-cloud-bigquery` to phase5-to-phase6 requirements
- Created missing `boxscore-gaps-detected` Pub/Sub topic

## What Needs To Be Done Now

### Priority 1: Run and verify tonight's tests

Run the test commands to verify all deployments work:

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Health checks
curl -s https://prediction-coordinator-756957797294.us-west2.run.app/health
curl -s https://prediction-worker-756957797294.us-west2.run.app/health
curl -s https://nba-admin-dashboard-756957797294.us-west2.run.app/health

# Cloud function status
gcloud functions describe phase4-to-phase5 --region=us-west2 --format="value(state)"
gcloud functions describe dlq-monitor --region=us-west2 --format="value(state)"

# Test DLQ monitor
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/dlq-monitor" | python -m json.tool | head -20

# Dry run replay
PYTHONPATH=. python bin/testing/replay_pipeline.py 2024-12-15 --dry-run

# Validate production data
PYTHONPATH=. python bin/testing/validate_replay.py $(date -d yesterday +%Y-%m-%d) --prefix=""
```

### Priority 2: Complete test environment for full replay

The replay pipeline is built but processors don't read `dataset_prefix` parameter yet.

To enable full test isolation, add `DATASET_PREFIX` env var support to:
- `data_processors/analytics/analytics_base.py`
- `data_processors/precompute/precompute_base.py`
- `predictions/coordinator/coordinator.py`

### Priority 3: Secrets migration (P0-SEC-2)

Move 7 secrets from .env to Google Secret Manager (still pending from reliability improvements).

---

## Key Files to Read

### Session Handoff (Start Here)
```
/home/naji/code/nba-stats-scraper/docs/09-handoff/2025-12-31-SESSION-DEPLOYMENT-AND-TEST-ENV.md
```

### Test Environment Documentation
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/test-environment/README.md
/home/naji/code/nba-stats-scraper/docs/08-projects/current/test-environment/IMPLEMENTATION-PLAN.md
```

### New Test Scripts
```
/home/naji/code/nba-stats-scraper/bin/testing/replay_pipeline.py
/home/naji/code/nba-stats-scraper/bin/testing/validate_replay.py
/home/naji/code/nba-stats-scraper/bin/testing/run_tonight_tests.sh
```

### Reliability TODO (Reference)
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/pipeline-reliability-improvements/COMPREHENSIVE-TODO-DEC30.md
```

---

## What I'd Like You To Do

1. Read the session handoff first to understand current state
2. Run the test commands to verify deployments
3. Document test results
4. If tests pass, start on dataset_prefix support for full replay capability
5. Use parallel agents where possible to speed things up

Please start by reading the handoff document and running the health checks.
