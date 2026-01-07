# Session 173 Handoff: Pipeline Fixes and Remaining Work

**Date:** December 27, 2025 (Saturday)
**Time:** 10:53 AM - 12:50 PM ET
**Status:** Partial fixes complete, some items remain

---

## Executive Summary

Session 173 fixed critical pipeline issues:
1. ✅ Dec 26 boxscores now in BigQuery (282 records)
2. ✅ Live grading export now working (54 predictions visible)
3. ⚠️ Dec 26 gamebooks still incomplete (1/9 games)
4. ⚠️ BDL player box scores scraper needs deploy

**No NBA games today (Saturday Dec 27)**, so no urgent action needed.

---

## Completed Fixes

### 1. Dec 26 Boxscores in BigQuery ✅

**Problem:** BDL boxscores file existed in GCS but BigQuery had 0 records.

**Root Cause Discovery:**
- Phase 2 processor ran and returned `rows_processed: 0, total_runtime: 0`
- `RunHistoryMixin.check_already_processed()` found entries with `status: success`
- Idempotency blocked reprocessing even though data wasn't written

**Key Insight:** The processor marked runs as "success" with 0 rows. This is a bug pattern to watch for.

**Fix Applied:**
```sql
DELETE FROM nba_reference.processor_run_history
WHERE processor_name = 'BdlBoxscoresProcessor'
  AND data_date = '2025-12-26'
  AND status = 'success'
  AND records_processed = 0
```

Then re-triggered via Pub/Sub:
```bash
TOKEN=$(gcloud auth print-identity-token)
MESSAGE_DATA=$(echo -n '{
  "scraper_name": "bdl_box_scores_scraper",
  "gcs_path": "gs://nba-scraped-data/ball-dont-lie/boxscores/2025-12-26/20251227_030513.json",
  "status": "success"
}' | base64 -w0)

curl -X POST "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"message\": {\"data\": \"$MESSAGE_DATA\"}}"
```

**Result:** 282 player records for 8 games now in `nba_raw.bdl_player_boxscores`

### 2. Live Grading Export ✅

**Problem:** Live grading export showed 0 predictions even though we have 440+ predictions for Dec 26.

**Root Cause:** `processor-sa` service account (used by live-export Cloud Function) had `bigquery.jobUser` but NOT `bigquery.dataViewer`. It could create query jobs but couldn't read the predictions table.

**Fix Applied:**
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:processor-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"
```

**Result:** Live grading now shows 54 predictions for Dec 26:
```json
{
  "total_predictions": 54,
  "graded": 0,
  "pending": 54,
  "games_in_progress": 0,
  "games_final": 0
}
```

Note: `games_final: 0` because the BDL live API only returns today's games.

---

## Remaining Issues

### 1. Dec 26 Gamebooks (1/9 processed) ⚠️

**Status:** Only MIA@ATL gamebook exists in GCS. The other 8 games have no gamebook PDFs.

**Files present:**
- `gs://nba-scraped-data/nba-com/gamebooks-pdf/2025-12-26/20251226-MIAATL/` - ONLY THIS

**Backfill attempt failed** with "Broken pipe" errors (5 email alerts received).

**To Fix:**
```bash
# Option 1: Run backfill script
PYTHONPATH=. .venv/bin/python scripts/backfill_gamebooks.py --date 2025-12-26

# Option 2: Manually trigger scraper for each game
# (Requires investigating why scraper only processed 1 game)
```

### 2. BDL Player Box Scores Scraper ⚠️

**Problem:** Scraper fails with:
```
ValueError: Unknown path template key: bdl_player_box_scores
```

**Status:** Code fix exists in commit `7e1e222` - the path template was added to `gcs_path_builder.py`

**To Fix:** Deploy scrapers service:
```bash
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

### 3. Run History Bug (Investigation Needed)

**Pattern Identified:** Processors are marking runs as `status: success` even when `records_processed: 0`. This blocks future reprocessing.

**Affected:** At minimum `BdlBoxscoresProcessor` on Dec 26. May affect others.

**Recommendation:**
1. Audit run history for other 0-row "success" entries
2. Consider code fix to only mark "success" if records_processed > 0

---

## Current Data Status

### Predictions by Date
```
| game_date  | predictions |
|------------|-------------|
| 2025-12-20 |         800 |
| 2025-12-21 |         600 |
| 2025-12-22 |         700 |
| 2025-12-23 |         975 |
| 2025-12-25 |         850 |
| 2025-12-26 |        1950 |
```

### Dec 26 Boxscores
- **BDL Player Boxscores:** 282 records, 8 games ✅
- **Gamebook Data:** 1/9 games ⚠️

### Scheduler Status (Dec 27)
- `same-day-phase3`: Ran at 10:30 AM ET ✅
- `same-day-phase4`: Ran at 11:00 AM ET (no games to process)
- `same-day-predictions`: Ran at 11:30 AM ET (no games to process)

---

## Key Commands Reference

### Check Run History for Processor
```bash
bq query --use_legacy_sql=false "
SELECT processor_name, data_date, status, records_processed, started_at
FROM nba_reference.processor_run_history
WHERE processor_name = 'PROCESSOR_NAME'
ORDER BY started_at DESC
LIMIT 10"
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

### Re-trigger Phase 2 Processing
```bash
TOKEN=$(gcloud auth print-identity-token)
MESSAGE_DATA=$(echo -n '{
  "scraper_name": "SCRAPER_NAME",
  "gcs_path": "gs://nba-scraped-data/PATH/TO/FILE.json",
  "status": "success"
}' | base64 -w0)

curl -X POST "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"message\": {\"data\": \"$MESSAGE_DATA\"}}"
```

### Trigger Live Export
```bash
curl -X POST 'https://us-west2-nba-props-platform.cloudfunctions.net/live-export' \
  -H 'Content-Type: application/json' \
  -d '{"target_date": "YYYY-MM-DD"}'
```

### Check Prediction Counts
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2025-12-20' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date"
```

### Check BDL Boxscores
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(*) as records
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= '2025-12-25'
GROUP BY game_date ORDER BY game_date"
```

---

## Service Account Permissions

`processor-sa@nba-props-platform.iam.gserviceaccount.com` now has:
- `roles/bigquery.jobUser` (added Session 172)
- `roles/bigquery.dataViewer` (added Session 173)
- `roles/secretmanager.secretAccessor`

---

## Architecture Notes

### Run History Idempotency Flow
1. `RunHistoryMixin.check_already_processed()` queries `nba_reference.processor_run_history`
2. If `status IN ('running', 'success', 'partial')` exists, processing is skipped
3. Bug: Processors can mark "success" with 0 rows, permanently blocking reprocessing

### Live Grading Flow
1. Cloud Function `live-export` runs every 3 min during games (7 PM - 2 AM ET)
2. Queries `nba_predictions.player_prop_predictions` for target date
3. Fetches live scores from BDL API
4. Exports to `gs://nba-props-platform-api/v1/live-grading/{date}.json`

### BDL Boxscores Flow
1. Scraper writes to `gs://nba-scraped-data/ball-dont-lie/boxscores/{date}/`
2. Pub/Sub triggers Phase 2 `BdlBoxscoresProcessor`
3. Processor extracts player stats from nested `home_team.players` and `visitor_team.players`
4. Writes to `nba_raw.bdl_player_boxscores`

---

## Todo List for Next Session

### High Priority
1. [ ] **Deploy scrapers service** - Enables BDL player box scores scraper
   ```bash
   ./bin/scrapers/deploy/deploy_scrapers_simple.sh
   ```

2. [ ] **Backfill Dec 26 gamebooks** - 8/9 games missing
   ```bash
   PYTHONPATH=. .venv/bin/python scripts/backfill_gamebooks.py --date 2025-12-26
   ```

### Medium Priority
3. [ ] **Audit run history for other 0-row "success" entries**
   ```sql
   SELECT processor_name, data_date, COUNT(*)
   FROM nba_reference.processor_run_history
   WHERE status = 'success' AND records_processed = 0
   GROUP BY 1, 2
   ORDER BY data_date DESC
   ```

4. [ ] **Monitor Dec 28 pipeline** - Next game day
   - Check morning schedulers ran (10:30, 11:00, 11:30 AM ET)
   - Verify predictions generated
   - Verify live export working during games

### Low Priority
5. [ ] **Investigate gamebook scraper** - Why did it only process 1/9 games?

6. [ ] **Consider code fix** - Processors should not mark "success" with 0 records

---

## Related Documents

- `docs/08-projects/current/SESSION-172-STATUS.md` - Previous session (backfill)
- `docs/08-projects/current/SESSION-173-MORNING-STATUS.md` - This session details
- `docs/09-handoff/2025-12-26-SESSION170-PIPELINE-FIX-AND-LIVE-EXPORT.md` - Pipeline architecture context
- `docs/02-operations/runbooks/prediction-pipeline.md` - Prediction pipeline runbook

---

## Quick Health Check Commands

```bash
# Check all services healthy
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  echo -n "$svc: "
  curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq -r '.status' 2>/dev/null || echo "failed"
done

# Check today's games
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | jq '.scoreboard.games | length'

# Check live export
gsutil cat "gs://nba-props-platform-api/v1/live/today.json" | jq '{updated_at, total_games, games_in_progress, games_final}'
```

---

*Handoff created: December 27, 2025 12:50 PM ET*
*Session 173 by Claude Opus 4.5*
