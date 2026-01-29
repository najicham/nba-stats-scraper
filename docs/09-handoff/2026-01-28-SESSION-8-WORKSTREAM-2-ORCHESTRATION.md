# Workstream 2: Orchestration Resilience

## Mission
Ensure the phase transition orchestrators NEVER fail silently. Every phase transition should be logged, and failures should trigger immediate alerts.

## Current State

### Architecture
```
Phase 2 Complete → Pub/Sub → phase2_to_phase3 Cloud Function → Triggers Phase 3
Phase 3 Complete → Pub/Sub → phase3_to_phase4 Cloud Function → Triggers Phase 4
Phase 4 Complete → Pub/Sub → phase4_to_phase5 Cloud Function → Triggers Phase 5
```

### Cloud Functions
| Function | Trigger Topic | Output Topic | Status |
|----------|---------------|--------------|--------|
| phase2-to-phase3-orchestrator | nba-phase2-raw-complete | nba-phase3-trigger | Deployed |
| phase3-to-phase4-orchestrator | nba-phase3-analytics-complete | nba-phase4-trigger | Deployed |
| phase4-to-phase5-orchestrator | nba-phase4-precompute-complete | nba-phase5-trigger | Deployed |

### Known Issues Found Today

1. **Import errors in Cloud Functions** - `shared.utils` imports failed because deploy scripts didn't include the full shared/ directory
   - **Fix applied**: Updated deploy scripts to include `shared/utils/` in deployment package
   - **Deployed**: All 3 phase orchestrators redeployed

2. **Firestore import missing** - `completion_tracker.py` used `firestore.SERVER_TIMESTAMP` without importing `firestore`
   - **Fix applied**: Added `from google.cloud import firestore` import
   - **Committed**: `dd42a0d3`

3. **Phase execution log gaps** - No entries for Jan 26-28 because Cloud Functions had import errors
   - **Root cause**: Symlink deployment issue
   - **Fix**: Deploy scripts now use `rsync -aL` to dereference symlinks

4. **Phase 3 completion tracking** - Only 2/5 processors logged completion to Firestore
   - **Root cause**: `TeamDefenseGameSummaryProcessor` had no trigger path in `ANALYTICS_TRIGGERS`
   - **Fix applied**: Added to `bdl_player_boxscores` triggers
   - **Committed**: `9acca7d7`

5. **Inconsistent table_name format** - Some processors had dataset prefix, others didn't
   - **Fix applied**: Normalized all to just table name without prefix

## Goals

### 1. Audit ALL Cloud Functions for Import Issues
Check every Cloud Function in `orchestration/cloud_functions/` for:
- Missing imports
- Symlink issues that won't deploy correctly
- Hardcoded paths that break in Cloud environment

### 2. Create Deployment Drift Detection
- Daily GitHub Action that checks deployed revision vs latest commit
- Alert if any Cloud Function is more than 24 hours behind
- Auto-create issue for stale deployments

### 3. Add Retry Logic for Firestore Failures
The completion_tracker already has BigQuery backup, but needs:
- Proper retry with exponential backoff
- Alert when falling back to BigQuery
- Periodic reconciliation between Firestore and BigQuery

### 4. Ensure phase_execution_log is ALWAYS Written
- Add try/catch around all logging calls
- Fall back to BigQuery if Firestore fails
- Add monitoring for missing log entries

### 5. Add Health Endpoints to All Orchestrators
Session 7 added `CachedHealthChecker` to phase orchestrators, but need to verify:
- All orchestrators have `/health` endpoint
- Health checks verify BigQuery, Firestore, Pub/Sub connectivity
- Cloud Scheduler pings health endpoints regularly

## Key Files

### Cloud Functions to Audit
```
orchestration/cloud_functions/
├── phase2_to_phase3/main.py
├── phase3_to_phase4/main.py
├── phase4_to_phase5/main.py
├── phase5_to_phase6/main.py
├── auto_backfill_orchestrator/main.py
├── daily_health_check/main.py
├── daily_health_summary/main.py
├── self_heal/main.py
└── ... (40+ more)
```

### Deploy Scripts
```
bin/orchestrators/
├── deploy_phase2_to_phase3.sh
├── deploy_phase3_to_phase4.sh
├── deploy_phase4_to_phase5.sh
├── deploy_phase5_to_phase6.sh
└── sync_shared_utils.sh
```

### Shared Utilities
```
shared/utils/
├── completion_tracker.py      # Dual-write to Firestore/BigQuery
├── phase_execution_logger.py  # Logs to phase_execution_log
├── bigquery_utils.py
└── bigquery_utils_v2.py
```

## Audit Checklist

For each Cloud Function, verify:

- [ ] All imports resolve correctly
- [ ] No symlinks in deployment package (rsync -aL used)
- [ ] Health endpoint exists and works
- [ ] Error handling doesn't swallow exceptions
- [ ] Completion messages are published
- [ ] phase_execution_log is written
- [ ] Firestore completion is recorded

## Deployment Drift Detection

Create `.github/workflows/check-cloud-function-drift.yml`:
```yaml
name: Check Cloud Function Deployment Drift

on:
  schedule:
    - cron: '0 12 * * *'  # Daily at noon UTC

jobs:
  check-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check deployed versions
        run: |
          # For each Cloud Function, compare deployed revision to latest commit
          # Alert if drift detected
```

## Testing Plan

1. **Simulate Firestore failure** - Verify BigQuery fallback works
2. **Deploy with intentional import error** - Verify health check catches it
3. **Check all Cloud Functions have health endpoints**
4. **Verify phase_execution_log has entries for today**

## Success Criteria

1. **Zero silent failures** - All errors logged and alerted
2. **100% phase_execution_log coverage** - Every phase transition logged
3. **Deployment drift < 24 hours** - Automated detection
4. **Health endpoints on all orchestrators** - Verifiable connectivity
5. **Firestore/BigQuery consistency** - Dual-write always works

## Related Documentation
- `docs/01-architecture/phase-transitions.md`
- `docs/02-operations/cloud-function-deployment.md`
- Session 7 handoff: `docs/09-handoff/2026-01-28-SESSION-7-HANDOFF.md`
