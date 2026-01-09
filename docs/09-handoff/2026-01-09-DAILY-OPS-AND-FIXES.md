# Handoff: Daily Operations Check and Bug Fixes - January 9, 2026

## Session Summary

Comprehensive daily operations review of V8 ML deployment. Discovered and fixed multiple critical issues across prediction worker, Cloud Scheduler, and BettingPros scraper systems.

---

## Issues Fixed This Session

### 1. Feature Version Mismatch (CRITICAL - Prediction Worker)

**Problem**: Prediction worker failing with "no_features" error for all players in Pub/Sub retry loop.

**Root Cause**: V8 deployment upgraded feature store to `v2_33features` (33 features), but `predictions/worker/data_loaders.py` still defaulted to `feature_version='v1_baseline_25'`. The BigQuery query filtered by version and returned 0 rows.

**Evidence**:
```sql
-- Query was filtering for non-existent version:
WHERE feature_version = 'v1_baseline_25'  -- Returns 0 rows

-- Actual data has:
WHERE feature_version = 'v2_33features'   -- Returns 108 rows
```

**Fix Applied**:
- Updated default `feature_version` from `v1_baseline_25` to `v2_33features` in 5 files
- Updated feature_count validation to accept both 25 and 33 features for backward compatibility

**Files Changed**:
- `predictions/worker/data_loaders.py` (lines 80, 591, 713)
- `predictions/worker/prediction_systems/base_predictor.py`
- `predictions/worker/prediction_systems/moving_average_baseline.py`
- `predictions/worker/prediction_systems/zone_matchup_v1.py`
- `predictions/worker/ARCHITECTURE.md`

**Commit**: `b63ca16 fix(predictions): Update feature_version default to v2_33features`

**Deployed**: `prediction-worker-00022-tct` ✅

---

### 2. Cloud Scheduler Permission Failures (Phase 4 Overnight Jobs)

**Problem**: Three overnight Phase 4 CASCADE jobs failing with PERMISSION_DENIED (error code 7).

**Root Cause**: Jobs were missing OIDC token authentication required for authenticated Cloud Run services.

**Affected Jobs**:
- `ml-feature-store-daily` (11:30 PM PT)
- `player-composite-factors-daily` (11:00 PM PT)
- `player-daily-cache-daily` (11:15 PM PT)

**Fix Applied**:
```bash
gcloud scheduler jobs update http [JOB_NAME] --location=us-west2 \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  --oidc-token-audience="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date"
```

**Verified**: Manually triggered `player-composite-factors-daily` - succeeded with empty status (no error code).

---

### 3. BettingPros Scraper Issues (Two Separate Problems)

#### Problem A: Midnight API Failure (Transient)

**Symptom**: `bp_events` returning HTTP 500 at midnight (00:05 UTC).

**Root Cause**: BettingPros API returned corrupt/empty response that couldn't be parsed.

**Error Chain**:
```
1. Proxy succeeded (0.9s connection)
2. UTF-8 decode failed: 'utf-8' codec can't decode byte 0xc4 in position 4
3. Latin-1 fallback failed
4. JSON parse failed: Expecting value: line 1 column 1 (char 0)
```

**Resolution**: Transient BettingPros API issue. Manually triggered scrapers to recover data:
```bash
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "bp_events", "date": "2026-01-09"}'
```

**Result**: 2,497 props recovered for Jan 9.

#### Problem B: Stats Field Mismatch (Code Bug)

**Symptom**: Even successful `bp_events` runs showed "NO DATA" in workflow logs.

**Root Cause**: Workflow executor checks `data_summary.get('rowCount', 0)` but `bp_events` only returned `event_count`.

**Fix Applied**:
- Added `rowCount` field to `bp_events.py` data dict and `get_scraper_stats()`
- Added explicit `bp_events` and `bp_player_props` config to `scraper_parameters.yaml`

**Commit**: `8dc9153 fix(scrapers): Add rowCount to bp_events stats and explicit config`

**Deployed**: `nba-phase1-scrapers-00093-ldd` ✅

---

### 4. Email Alerting Not Configured (Scraper Service)

**Problem**: Scraper failures weren't sending email alerts. Logs showed "No recipients for CRITICAL alert".

**Root Cause**: `nba-phase1-scrapers` Cloud Run service was missing email environment variables.

**Fix Applied**:
```bash
gcloud run services update nba-phase1-scrapers --region=us-west2 \
  --update-env-vars="EMAIL_ALERTS_TO=nchammas@gmail.com,EMAIL_CRITICAL_TO=nchammas@gmail.com,BREVO_SMTP_HOST=smtp-relay.brevo.com,BREVO_SMTP_PORT=587,BREVO_SMTP_USERNAME=YOUR_EMAIL@smtp-brevo.com,BREVO_FROM_EMAIL=alert@989.ninja,BREVO_FROM_NAME=PK,BREVO_SMTP_PASSWORD=..."
```

**Verified**: Email alerting status shows ENABLED in deployment output.

---

## Final System Status

| Component | Revision | Status | Notes |
|-----------|----------|--------|-------|
| `prediction-worker` | `00022-tct` | ✅ Healthy | Feature version fix deployed |
| `nba-phase1-scrapers` | `00093-ldd` | ✅ Healthy | rowCount fix + email alerts |
| Cloud Scheduler (Phase 4) | N/A | ✅ Fixed | OIDC tokens added |
| V8 Predictions | N/A | ✅ Working | 108 predictions for today |
| BettingPros Props | N/A | ✅ Recovered | 2,497 props for Jan 9 |

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `b63ca16` | fix(predictions): Update feature_version default to v2_33features |
| `8dc9153` | fix(scrapers): Add rowCount to bp_events stats and explicit config |
| `2d5726a` | docs: Add daily ops and fixes handoff for 2026-01-09 |

---

## Deployments This Session

| Service | Old Revision | New Revision | Changes |
|---------|--------------|--------------|---------|
| `prediction-worker` | `00021-xxq` | `00022-tct` | Feature version fix |
| `nba-phase1-scrapers` | `00091-7nt` | `00093-ldd` | rowCount fix + email config |

---

## Known Issues / Watch Items

### Still Failing Scheduler Jobs (Lower Priority)

| Job | Error | Notes |
|-----|-------|-------|
| `bdl-injuries-hourly` | NOT_FOUND (5) | BDL API endpoint may have changed |
| `bigquery-daily-backup` | INTERNAL (13) | Cloud Function issue |
| `self-heal-predictions` | DEADLINE_EXCEEDED (4) | Timeout - may need optimization |

### BettingPros API Reliability

The midnight failure was transient (corrupt API response). May recur. Consider:
- Adding specific retry logic for encoding errors
- Adding circuit breaker for repeated API failures
- Monitoring for similar failures

---

## Key Technical Details for Future Reference

### Feature Store Version Query

```sql
-- V8 uses v2_33features (33 features including minutes/PPM)
SELECT player_lookup, feature_count, feature_version
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
-- Expected: feature_version = 'v2_33features', feature_count = 33
```

### Workflow Executor Stats Check

```python
# workflow_executor.py line 600-605
data_summary = result.get('data_summary', {})
record_count = data_summary.get('rowCount', 0)  # MUST have 'rowCount' key
if record_count > 0:
    status = 'success'
else:
    status = 'no_data'
```

### Cloud Scheduler OIDC Pattern

```bash
# All Cloud Run authenticated endpoints need OIDC token
gcloud scheduler jobs update http [JOB] --location=us-west2 \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  --oidc-token-audience="[CLOUD_RUN_URL]/[ENDPOINT]"
```

---

## Verification Commands

```bash
# Check prediction worker health
curl -s https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health | jq .status

# Check scraper service health
curl -s https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health | jq '.status, .components.scrapers.available'

# Check today's V8 predictions
bq query --use_legacy_sql=false "SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE() GROUP BY system_id"

# Check feature store
bq query --use_legacy_sql=false "SELECT COUNT(*), AVG(feature_count) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = CURRENT_DATE()"

# Check BettingPros props freshness
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) FROM nba_raw.bettingpros_player_points_props WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY) GROUP BY game_date ORDER BY game_date DESC"

# Check scheduler job status
gcloud scheduler jobs list --location=us-west2 --format="table(name,state,status.code,lastAttemptTime)" | head -20
```

---

## Next Session Recommendations

1. **Monitor tonight's overnight jobs** - Verify OIDC fix works for Phase 4 processors (11 PM - 11:30 PM PT)
2. **Investigate bdl-injuries-hourly** - Check if Ball Don't Lie API endpoint changed
3. **Consider BettingPros resilience** - Add retry logic for encoding errors
4. **Review bigquery-daily-backup** - Check Cloud Function logs for internal error cause

---

## Project Context

- **V8 ML Model**: CatBoost with 33 features (including minutes_avg_last_10, ppm_avg_last_10)
- **Feature Store**: `nba_predictions.ml_feature_store_v2` with `v2_33features` version
- **Prediction System**: Ensemble of CatBoost V8 + Zone Matchup + Moving Average + Similarity
- **Daily Pipeline**: Phase 3 (10:30 AM ET) → Phase 4 (11:00 AM ET) → Phase 5 (11:30 AM ET) → Phase 6 (1:00 PM ET)
- **Overnight Pipeline**: Phase 4 CASCADE processors (11:00 PM - 11:30 PM PT)
