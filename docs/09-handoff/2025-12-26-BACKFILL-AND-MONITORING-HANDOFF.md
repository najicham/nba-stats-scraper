# Handoff: Backfill and Daily Monitoring

**Date:** December 26, 2025
**From:** Session 171 (Same-Day Predictions Fix)
**To:** Backfill/Monitoring Chat

---

## Context

Session 171 fixed the root cause of missing predictions:
- **Problem:** Overnight schedulers process YESTERDAY, not TODAY
- **Solution:** Added morning schedulers for same-day predictions

**Current State:**
- Predictions ARE generating (1950 for Dec 26)
- Exports ARE working (GCS files present)
- Morning schedulers created and will run tomorrow at 10:30 AM ET

---

## Remaining Work for This Chat

### 1. Backfill Dec 21-25 Predictions (HIGH)

5 days of predictions are missing. Games were played but predictions weren't generated.

**For each date (Dec 21, 22, 23, 25 - skip Dec 24 no games):**

```bash
DATE="2025-12-25"  # Change for each date
TOKEN=$(gcloud auth print-identity-token)

# Step 1: Phase 3 - PlayerGameSummary (historical mode)
curl -s -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"start_date\": \"$DATE\",
    \"end_date\": \"$DATE\",
    \"processors\": [\"PlayerGameSummaryProcessor\"],
    \"backfill_mode\": true
  }"

# Wait 30-60 seconds

# Step 2: Phase 4 - MLFeatureStore (backfill mode)
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"analysis_date\": \"$DATE\",
    \"processors\": [\"MLFeatureStoreProcessor\"],
    \"backfill_mode\": true
  }"

# Wait 60 seconds

# Step 3: Phase 5 - Generate predictions
curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"game_date\": \"$DATE\", \"force\": true}"
```

**Verification:**
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2025-12-21' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date"
```

### 2. Verify Tomorrow's Schedulers (MEDIUM)

Tomorrow (Dec 27), the new morning schedulers should run automatically:
- 10:30 AM ET: `same-day-phase3`
- 11:00 AM ET: `same-day-phase4`
- 11:30 AM ET: `same-day-predictions`

**To verify after 11:30 AM:**
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions, MAX(created_at) as last_created
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-27' AND is_active = TRUE
GROUP BY game_date"
```

**If predictions don't exist, manually trigger:**
```bash
gcloud scheduler jobs run same-day-phase3 --location=us-west2
# Wait 30 seconds
gcloud scheduler jobs run same-day-phase4 --location=us-west2
# Wait 60 seconds
gcloud scheduler jobs run same-day-predictions --location=us-west2
```

### 3. AWS SES for Phase 4 (LOW)

Email alerting on Phase 4 may fail. Phase 2 uses secrets:
- `aws-ses-access-key-id`
- `aws-ses-secret-access-key`

**To add to Phase 4:**
```bash
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --update-secrets="AWS_SES_ACCESS_KEY_ID=aws-ses-access-key-id:latest,AWS_SES_SECRET_ACCESS_KEY=aws-ses-secret-access-key:latest" \
  --set-env-vars="AWS_SES_REGION=us-west-2"
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `docs/08-projects/current/SYSTEM-STATUS.md` | Current system status |
| `docs/02-operations/runbooks/prediction-pipeline.md` | Prediction pipeline runbook |
| `bin/orchestrators/setup_same_day_schedulers.sh` | Morning scheduler setup |

---

## What's Working Now

| Component | Status |
|-----------|--------|
| Phase 1 Scrapers | ✅ |
| Phase 2 Raw Processors | ✅ |
| Phase 3 Analytics | ✅ (just redeployed with correct image) |
| Phase 4 Precompute | ✅ (has TODAY support) |
| Phase 5 Predictions | ✅ (1950 predictions for Dec 26) |
| Phase 6 Export | ✅ (GCS exports present) |
| Morning Schedulers | ✅ Created (first run Dec 27) |

---

## Quick Health Check

```bash
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  echo -n "$svc: "
  curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq -r '.status' 2>/dev/null || echo "failed"
done
```

---

## Commits from Session 171

```
ee75baf - feat: Add same-day prediction schedulers and TODAY date support
```

---

*Questions? Check `docs/02-operations/runbooks/prediction-pipeline.md` for detailed commands.*
