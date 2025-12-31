# Session 173: Morning Pipeline Fixes

**Date:** December 27, 2025 (Saturday)
**Time:** 10:53 AM - 12:45 PM ET

---

## Summary

Morning session fixing several pipeline issues discovered overnight:

1. **Dec 26 boxscores not in BigQuery** - Fixed by clearing stale run history
2. **Live grading showing 0 predictions** - Fixed by granting BigQuery Data Viewer permission
3. **Dec 26 gamebooks** - Only 1/9 processed, needs backfill
4. **BDL player box scores scraper** - Broken due to missing GCS path (code fix exists, needs deploy)

---

## Completed Fixes

### 1. Dec 26 Boxscores in BigQuery

**Issue:** Phase 2 processed the BDL boxscores file but wrote 0 rows. Run history showed `status: success` with `records_processed: 0`.

**Root Cause:** SmartIdempotencyMixin was skipping processing because run_history already had a "success" entry, even though no data was written.

**Fix:**
```sql
DELETE FROM nba_reference.processor_run_history
WHERE processor_name = 'BdlBoxscoresProcessor'
  AND data_date = '2025-12-26'
  AND status = 'success'
  AND records_processed = 0
```

Then re-triggered processing via Pub/Sub message.

**Result:** 282 player records for 8 games now in BigQuery.

### 2. Live Grading Export

**Issue:** Live grading export was returning 0 predictions even though predictions existed.

**Root Cause:** `processor-sa` service account had `bigquery.jobUser` but not `bigquery.dataViewer` permission.

**Fix:**
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:processor-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"
```

**Result:** Live grading now shows 54 predictions for Dec 26.

---

## Remaining Issues

### Dec 26 Gamebooks (1/9 processed)

Only the MIA@ATL gamebook was scraped/processed. The other 8 games don't have gamebook PDFs in GCS.

**To Fix:**
1. Run gamebook backfill script
2. Or investigate why the scraper only processed 1 game

### BDL Player Box Scores Scraper

The `bdl_player_box_scores.py` scraper was failing with:
```
ValueError: Unknown path template key: bdl_player_box_scores
```

**Status:** Code fix exists in commit `7e1e222`. Need to redeploy scrapers service.

### "Broken pipe" Email Alerts

Received 5 emails about GetNbaComGamebookPdf with "Broken pipe" errors. This was triggered by the gamebook backfill attempt. These are intermittent networking errors.

---

## Data Status

| Table | Dec 25 | Dec 26 | Status |
|-------|--------|--------|--------|
| bdl_player_boxscores | 174 | 282 | ✅ |
| player_prop_predictions | 850 | 440 (active) | ✅ |
| Live Grading | N/A | 54 predictions | ✅ |
| Gamebook Data | 5/5 | 1/9 | ⚠️ |

---

## Scheduler Status

Morning schedulers (same-day-phase3/4/predictions) ran successfully today:
- `same-day-phase3`: 10:30 AM ✅
- `same-day-phase4`: 11:00 AM (pending - no games today)
- `same-day-predictions`: 11:30 AM (pending - no games today)

No NBA games today (Saturday), so morning schedulers have nothing to process.

---

## Commands for Reference

### Check Boxscores
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= '2025-12-25'
GROUP BY 1 ORDER BY 1"
```

### Clear Stale Run History
```bash
bq query --use_legacy_sql=false "
DELETE FROM nba_reference.processor_run_history
WHERE processor_name = 'PROCESSOR_NAME'
  AND data_date = 'YYYY-MM-DD'
  AND status = 'success'
  AND records_processed = 0"
```

### Trigger Live Export
```bash
curl -X POST 'https://us-west2-nba-props-platform.cloudfunctions.net/live-export' \
  -H 'Content-Type: application/json' \
  -d '{"target_date": "2025-12-26"}'
```

---

*Session 173 - December 27, 2025*
