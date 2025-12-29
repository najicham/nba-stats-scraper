# Session 184 Handoff - Pipeline Robustness Improvements

**Date:** 2025-12-29
**Session:** 184
**Previous Session:** 183 (see 2025-12-29-SESSION183-COMPLETE-HANDOFF.md)
**Status:** 3 of 4 deployments complete, Phase 5 blocked on permissions

---

## Summary

This session addressed all P1 tasks from Session 183 handoff:

1. **Circuit Breaker Hardcodes** - All 5 processors updated to use 24h config
2. **Prediction Worker Duplicates** - MERGE logic implemented (code ready, deploy pending)
3. **Circuit Breaker Auto-Reset** - Added to completeness check

---

## Changes Made

### 1. Circuit Breaker Lockout (7 days → 24 hours) ✅ DEPLOYED

Updated 6 occurrences in 5 processors to use `shared.config.orchestration_config`:

| File | Line | Status |
|------|------|--------|
| `player_composite_factors_processor.py` | 1066 | ✅ Deployed (Phase 4) |
| `player_shot_zone_analysis_processor.py` | 810 | ✅ Deployed (Phase 4) |
| `player_daily_cache_processor.py` | 1172, 1245 | ✅ Deployed (Phase 4) |
| `team_defense_zone_analysis_processor.py` | 607 | ✅ Deployed (Phase 4) |
| `upcoming_team_game_context_processor.py` | 1036 | ✅ Deployed (Phase 3) |

**Pattern applied:**
```python
from shared.config.orchestration_config import get_orchestration_config
config = get_orchestration_config()
circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=config.circuit_breaker.entity_lockout_hours)
```

### 2. Prediction Worker MERGE ✅ CODE COMPLETE, ⚠️ DEPLOY PENDING

**File:** `predictions/worker/worker.py`

Changed from `WRITE_APPEND` (causes duplicates on Pub/Sub retry) to staging table + MERGE:

1. Load predictions to temp staging table
2. MERGE from staging to main table on `(player_lookup, game_date)`
3. On match: UPDATE with new values
4. On no match: INSERT
5. Cleanup staging table

**Why it matters:** Pub/Sub retries were causing 5x duplicate predictions.

### 3. Circuit Breaker Auto-Reset ✅ DEPLOYED

**File:** `data_processors/raw/main_processor_service.py`

Added `_auto_reset_circuit_breakers()` function that:
- Runs during daily 6 AM ET boxscore completeness check
- Clears circuit breakers for players/teams that now have boxscore data
- Prevents cascading lockouts after data is backfilled

**Endpoint:** `POST /monitoring/boxscore-completeness`
- New response field: `circuit_breakers_reset: <count>`
- Optional param: `auto_reset_circuit_breakers: false` to disable

---

## Deployment Status

| Phase | Service | Revision | Status |
|-------|---------|----------|--------|
| Phase 2 | nba-phase2-raw-processors | 00048-8gh | ✅ Deployed |
| Phase 3 | nba-phase3-analytics-processors | 00030-zzv | ✅ Deployed |
| Phase 4 | nba-phase4-precompute-processors | 00027-zsv | ✅ Deployed |
| Phase 5 | prediction-worker | 00006-x52 | ❌ BLOCKED |

---

## Phase 5 Deployment Issue

### Error
```
denied: Permission "artifactregistry.repositories.uploadArtifacts" denied on resource
"projects/nba-props-platform-dev/locations/us-west2/repositories/nba-props"
```

### Root Cause
The deploy script pushes Docker images to `nba-props-platform-dev` project's Artifact Registry, but current gcloud credentials lack the `Artifact Registry Writer` role.

### Fix Options

**Option 1: Grant permissions (recommended)**
```bash
# Grant Artifact Registry Writer to your user account
gcloud artifacts repositories add-iam-policy-binding nba-props \
  --location=us-west2 \
  --project=nba-props-platform-dev \
  --member="user:YOUR_EMAIL" \
  --role="roles/artifactregistry.writer"
```

**Option 2: Use Cloud Build directly**
```bash
cd predictions/worker
gcloud builds submit --tag us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest .
gcloud run deploy prediction-worker --image us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest --region us-west2
```

**Option 3: Deploy from different machine with permissions**
The code is committed and pushed to main. Anyone with deploy permissions can run:
```bash
./bin/predictions/deploy/deploy_prediction_worker.sh
```

---

## Git Commits

```
e9ae09e feat: Pipeline robustness improvements (Session 184)
```

---

## Verification Commands

### Check circuit breaker config:
```bash
PYTHONPATH=. python3 -c "
from shared.config.orchestration_config import get_orchestration_config
config = get_orchestration_config()
print(f'Entity lockout: {config.circuit_breaker.entity_lockout_hours} hours')
"
```

### Check active circuit breakers:
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT processor_name, entity_id, analysis_date, circuit_breaker_until
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY circuit_breaker_until DESC
LIMIT 10
"
```

### Test boxscore completeness with auto-reset:
```bash
gcloud scheduler jobs run boxscore-completeness-check --location=us-west2
# Check logs for "Auto-reset X circuit breakers"
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors" AND textPayload=~"Auto-reset"' --limit=5 --freshness=10m
```

### Check prediction duplicates (should be fixed after Phase 5 deploy):
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT player_lookup, game_date, COUNT(*) as copies
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY player_lookup, game_date
HAVING COUNT(*) > 1
LIMIT 5
"
```

---

## Remaining Work

### Immediate (needs Phase 5 deploy)
- Deploy Phase 5 prediction-worker with MERGE fix

### Future (documented in PIPELINE-ROBUSTNESS-PLAN.md)
- P2: Automatic backfill trigger when gaps detected
- P2: Extend self-heal to Phase 2 data checks
- P3: Morning data completeness email report

---

## Files Modified

```
data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py
data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py
data_processors/raw/main_processor_service.py
predictions/worker/worker.py
```
