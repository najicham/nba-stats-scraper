# Handoff: Daily Operations Check and Bug Fixes - January 9, 2026

## Session Summary

Comprehensive daily operations review of V8 deployment, discovered and fixed multiple issues across the prediction and scraper systems.

## Issues Fixed

### 1. Feature Version Mismatch (CRITICAL)

**Problem**: Prediction worker failing with "no_features" error for all players.

**Root Cause**: `predictions/worker/data_loaders.py` defaulted to `feature_version='v1_baseline_25'` but the V8 deployment upgraded the feature store to `v2_33features`. Query returned 0 rows due to version filter mismatch.

**Fix Applied**:
- Updated default feature_version from `v1_baseline_25` to `v2_33features` in:
  - `data_loaders.py` (3 functions)
  - `base_predictor.py`
  - `moving_average_baseline.py`
  - `zone_matchup_v1.py`
  - `ARCHITECTURE.md`
- Updated feature_count validation to accept both 25 and 33 features

**Commit**: `b63ca16 fix(predictions): Update feature_version default to v2_33features`

**Deployed**: `prediction-worker-00022-tct`

---

### 2. Cloud Scheduler Permission Failures

**Problem**: Three overnight Phase 4 jobs failing with PERMISSION_DENIED (error code 7).

**Root Cause**: Jobs were missing OIDC token authentication required for Cloud Run.

**Fix Applied**: Added OIDC service account configuration to:
- `ml-feature-store-daily`
- `player-composite-factors-daily`
- `player-daily-cache-daily`

**Command Used**:
```bash
gcloud scheduler jobs update http [JOB_NAME] --location=us-west2 \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  --oidc-token-audience="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date"
```

---

### 3. BettingPros Scraper Issues

**Problem A - Midnight API Failure**:
- BettingPros API returned corrupt/empty responses around midnight
- Error: `All encoding attempts failed for BettingProsEvents: Expecting value: line 1 column 1 (char 0)`
- This was a **transient BettingPros API issue**, not a code bug

**Problem B - Stats Field Mismatch**:
- `bp_events.get_scraper_stats()` returned `event_count` instead of `rowCount`
- Workflow executor looks for `rowCount` to determine success
- Result: Even successful runs showed "NO DATA" status

**Fixes Applied**:
1. Added `rowCount` field to `bp_events.py` data and stats
2. Added explicit `bp_events` and `bp_player_props` config to `scraper_parameters.yaml`
3. Manually triggered scrapers to recover today's data (2,497 props)

**Commit**: `8dc9153 fix(scrapers): Add rowCount to bp_events stats and explicit config`

---

### 4. Email Alerting Configuration

**Problem**: Scraper service (`nba-phase1-scrapers`) was missing email environment variables, so failure alerts weren't being sent.

**Fix Applied**: Added email configuration to Cloud Run service:
```bash
gcloud run services update nba-phase1-scrapers --region=us-west2 \
  --update-env-vars="EMAIL_ALERTS_TO=nchammas@gmail.com,EMAIL_CRITICAL_TO=nchammas@gmail.com,..."
```

**Deployed**: `nba-phase1-scrapers-00092-b7c`

---

## Current System Status

| Component | Status | Notes |
|-----------|--------|-------|
| V8 Predictions | ✅ Working | 108 predictions for today |
| Feature Store | ✅ Working | 33 features per player |
| Phase 6 Export | ✅ Working | Today's data exported |
| Cloud Scheduler | ✅ Fixed | OIDC tokens added |
| BettingPros Props | ✅ Recovered | 2,497 props for today |
| Email Alerts | ✅ Configured | Added to scraper service |

---

## Commits This Session

1. `b63ca16` - fix(predictions): Update feature_version default to v2_33features
2. `8dc9153` - fix(scrapers): Add rowCount to bp_events stats and explicit config

---

## Deployments This Session

| Service | Revision | Change |
|---------|----------|--------|
| `prediction-worker` | `00022-tct` | Feature version fix |
| `nba-phase1-scrapers` | `00092-b7c` | Email alerting config |

---

## Known Issues / Watch Items

### 1. BettingPros Workflow Reliability
- The betting_lines workflow failed at midnight due to BettingPros API returning corrupt data
- This was transient but may recur
- Consider adding specific retry logic for encoding errors

### 2. Other Failing Scheduler Jobs
- `bdl-injuries-hourly` - NOT_FOUND error (endpoint may have changed)
- `bigquery-daily-backup` - Internal error
- `self-heal-predictions` - Timeout issues

### 3. Scraper Service Needs Redeploy
The code fixes for `bp_events` are committed but NOT deployed to Cloud Run yet. The scraper service needs to be redeployed to pick up the `rowCount` fix.

**To deploy**:
```bash
# From project root
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

---

## Files Modified

```
predictions/worker/data_loaders.py          # Feature version default
predictions/worker/ARCHITECTURE.md          # Documentation update
predictions/worker/prediction_systems/base_predictor.py
predictions/worker/prediction_systems/moving_average_baseline.py
predictions/worker/prediction_systems/zone_matchup_v1.py
scrapers/bettingpros/bp_events.py           # rowCount field
config/scraper_parameters.yaml              # bp_events config
```

---

## Next Session Recommendations

1. **Deploy scraper service** to pick up bp_events rowCount fix
2. **Investigate bdl-injuries-hourly** - check if BDL API endpoint changed
3. **Monitor tonight's overnight jobs** - verify OIDC fix works for Phase 4 processors
4. **Consider adding retry logic** for BettingPros API encoding errors

---

## Reference: Key Investigation Findings

### BettingPros API Failure Pattern
```
Timestamp: 2026-01-09 00:05:34 - 00:06:37 UTC
Error: UTF-8 decode failed, then latin-1 failed
Root: API returned bytes starting with 0xc4 (invalid UTF-8 continuation byte)
Impact: bp_events returned HTTP 500, cascaded to bp_player_props failure
```

### Feature Version Query Issue
```sql
-- What data_loaders.py was querying (returned 0 rows):
SELECT * FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-09' AND feature_version = 'v1_baseline_25'

-- What actually exists (108 rows):
SELECT * FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-09' AND feature_version = 'v2_33features'
```

### Workflow Executor Stats Check
```python
# workflow_executor.py determines success by:
data_summary = result.get('data_summary', {})
record_count = data_summary.get('rowCount', 0)  # Must have 'rowCount' key
if record_count > 0:
    status = 'success'
else:
    status = 'no_data'  # This is what bp_events was hitting
```
