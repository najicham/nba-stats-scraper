# Feature Store Upcoming Games - Verification Checklist

**Date:** 2026-02-03
**Purpose:** Ensure all pieces are in place for tomorrow's automated run

---

## Pre-Flight Checklist

### 1. Scheduler Jobs Configured

```bash
# Verify player-composite-factors-upcoming
gcloud scheduler jobs describe player-composite-factors-upcoming --location=us-west2 \
  --format='value(httpTarget.body)' | base64 -d
```
**Expected:** `{"processors":["PlayerCompositeFactorsProcessor"],"analysis_date":"TODAY","strict_mode":false,"skip_dependency_check":true}`

```bash
# Verify ml-feature-store-7am-et
gcloud scheduler jobs describe ml-feature-store-7am-et --location=us-west2 \
  --format='value(httpTarget.body)' | base64 -d
```
**Expected:** `{"processors":["MLFeatureStoreProcessor"],"analysis_date":"TODAY","strict_mode":false,"skip_dependency_check":true}`

```bash
# Verify ml-feature-store-1pm-et
gcloud scheduler jobs describe ml-feature-store-1pm-et --location=us-west2 \
  --format='value(httpTarget.body)' | base64 -d
```
**Expected:** `{"processors":["MLFeatureStoreProcessor"],"analysis_date":"TODAY","strict_mode":false,"skip_dependency_check":true}`

---

### 2. Code Deployed

```bash
# Check deployment status
./bin/check-deployment-drift.sh --verbose
```
**Expected:** All services show "Up to date"

```bash
# Verify deployed commit includes the fix
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format='value(metadata.labels.commit-sha)'
```
**Expected:** Commit that includes the fallback query changes (7161d974 or later)

---

### 3. Current Data Status

```bash
# Check today's feature quality
bq query --use_legacy_sql=false "
SELECT
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()"
```
**Expected:** avg_quality >= 85, high_quality > 250

```bash
# Check today's composite factors
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as players,
  COUNT(DISTINCT game_id) as games
FROM nba_precompute.player_composite_factors
WHERE game_date = CURRENT_DATE()
GROUP BY game_date"
```
**Expected:** 300+ players, matches today's scheduled games

---

## Tomorrow Morning Validation

Run these at 8 AM ET to verify the automated schedule worked:

### 1. Check Composite Factors Created (5 AM job)

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  MIN(created_at) as earliest_created,
  COUNT(*) as players
FROM nba_precompute.player_composite_factors
WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_date"
```
**Expected:** created_at around 10:00 UTC (5 AM ET)

### 2. Check Feature Store Updated (7 AM job)

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  MIN(created_at) as earliest_created,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_date"
```
**Expected:** created_at around 12:00 UTC (7 AM ET), avg_quality >= 85

### 3. Check Logs for Errors

```bash
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors" AND severity>=ERROR' \
  --limit=10 --freshness=12h --format='table(timestamp,textPayload)'
```
**Expected:** No errors related to composite factors or feature store

---

## Troubleshooting

### If feature quality is still low

1. **Check if composite factors exist for today:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT COUNT(*) FROM nba_precompute.player_composite_factors
   WHERE game_date = CURRENT_DATE()"
   ```

2. **If 0 records, manually trigger composite factors:**
   ```bash
   curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"processors": ["PlayerCompositeFactorsProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'
   ```

3. **Then refresh feature store:**
   ```bash
   curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'
   ```

### If scheduler jobs didn't run

1. **Check job state:**
   ```bash
   gcloud scheduler jobs list --location=us-west2 --format='table(name,state,scheduleTime)'
   ```

2. **Manually run the jobs:**
   ```bash
   gcloud scheduler jobs run player-composite-factors-upcoming --location=us-west2
   gcloud scheduler jobs run ml-feature-store-7am-et --location=us-west2
   ```

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Feature Quality (avg) | >= 85% | 85.1% |
| High Quality Players | >= 250 | 263 |
| Low Quality Players | 0 | 0 |
| Composite Factors Coverage | >= 90% | 100% |
