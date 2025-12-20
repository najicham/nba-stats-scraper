# Session 153: Pipeline Fixes - Scraper and Phase 2 Routing

**Date:** 2025-12-20
**Duration:** ~2 hours
**Status:** Major fixes deployed, pipeline flowing again

## Summary

Fixed multiple issues preventing the prediction pipeline from flowing. The root causes were:
1. Scheduler jobs pointing to outdated scraper service
2. Multiple GCS exporters overwriting gcs_path
3. Odds scraper status detection using wrong field name
4. Phase 2 processor registry missing route for current game lines

## Issues Fixed

### 1. Scheduler Jobs Pointing to Wrong Service
**Problem:** The 4 orchestration scheduler jobs were calling `nba-scrapers` (deployed Nov 17) instead of `nba-phase1-scrapers` (deployed Dec 17 with gcs_path fix).

**Fix:** Updated all scheduler jobs:
```bash
gcloud scheduler jobs update http cleanup-processor --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/cleanup"
gcloud scheduler jobs update http daily-schedule-locker --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/generate-daily-schedule"
gcloud scheduler jobs update http execute-workflows --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows"
gcloud scheduler jobs update http master-controller-hourly --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/evaluate"
```

### 2. Multiple GCS Exporters Overwriting gcs_path
**Problem:** Scrapers with multiple exporters (e.g., schedule + metadata) had the last exporter overwrite `gcs_output_path`, causing Phase 2 to process the wrong file.

**Fix:** Modified `scrapers/scraper_base.py` to only capture the FIRST gcs_path:
```python
if 'gcs_output_path' not in self.opts:
    self.opts['gcs_output_path'] = exporter_result['gcs_path']
```

**Commit:** `3245512`

### 3. Schedule Processor HASH_FIELDS Mismatch
**Problem:** `HASH_FIELDS` referenced `game_time_utc` which doesn't exist in transformed data.

**Fix:** Changed to `game_date_est` in `data_processors/raw/nbacom/nbac_schedule_processor.py`

**Commit:** `a480f96`

### 4. Odds Scraper Status Detection Bug
**Problem:** Odds scrapers use `rowCount` (camelCase) but `_determine_execution_status()` only checked `record_count` (snake_case). Result: scrapers reported `no_data` even when 8 rows were scraped.

**Fix:** Added `rowCount` to pattern list in `scrapers/scraper_base.py`:
```python
elif 'rowCount' in self.data:
    # Odds scrapers use rowCount (camelCase)
    record_count = self.data.get('rowCount', 0)
```

**Commit:** `dc07130`

### 5. Phase 2 Processor Routing Gap
**Problem:** `PROCESSOR_REGISTRY` only had `odds-api/game-lines-history` but NOT `odds-api/game-lines`. Current/live game lines were silently ignored!

**Fix:** Added missing route in `data_processors/raw/main_processor_service.py`:
```python
'odds-api/game-lines': OddsGameLinesProcessor,  # Current/live game lines
```

**Commit:** `dc07130`

## Deployments

| Service | Revision | Status |
|---------|----------|--------|
| nba-phase1-scrapers | 00023-ml9 | Deployed with all fixes |
| nba-phase2-raw-processors | 00020-vsn | Deployed with routing fix |

## Verified Working

### Schedule Pipeline
```
Scraper → GCS → Pub/Sub (success, gcs_path) → Phase 2 → BigQuery
         ✅      ✅                            ✅         ✅ 1,231 games
```

### Odds Game Lines Pipeline
```
Scraper → GCS → Pub/Sub (success, 8 records) → Phase 2 → BigQuery
         ✅      ✅                              ✅         ✅ 8 rows
```

## Current Pipeline State

```sql
-- As of 2025-12-20 22:30 UTC
| Table                        | Latest Data | Status |
|------------------------------|-------------|--------|
| nbac_schedule                | 2026-04-12  | ✅ Fresh (future games) |
| player_game_summary          | 2025-12-19  | ✅ Fresh |
| player_composite_factors     | 2025-12-19  | ✅ Fresh |
| ml_feature_store_v2          | 2025-12-19  | ✅ Fresh |
| odds_api_game_lines          | 2025-12-20  | ✅ FIXED (was 0 rows) |
| upcoming_player_game_context | 2025-12-19  | ⚠️ Missing Dec 20 |
| player_prop_predictions      | 2025-12-13  | ❌ Still stuck |
```

## Remaining Work (Priority Order)

### 1. Backfill Odds Data Dec 10-20
GCS files exist but weren't processed due to the routing bug. Need to reprocess:
```bash
gsutil ls "gs://nba-scraped-data/odds-api/game-lines/" | tail -15
# Shows: 2025-12-06 through 2025-12-20
```

Options:
- Manual republish via Pub/Sub
- Direct processor invocation for each file
- Write a backfill script

### 2. Trigger Phase 3 Re-run
Phase 3 was failing due to stale schedule data. Now that schedule is fresh, it should work:
```bash
# Test manually
curl -X POST "https://nba-phase3-analytics-processors.../process-analytics" \
  -H "Content-Type: application/json" \
  -d '{"processor": "upcoming_player_game_context", "game_date": "2025-12-20"}'
```

### 3. End-to-End Pipeline Verification
Once Phase 3 is running:
- Verify Phase 4 precompute updates
- Verify Phase 5 predictions generate
- Verify Phase 6 grading works

### 4. Grading Backfill (from Session 151)
Still pending - wait until pipeline is fully flowing.

## Files Changed

```
scrapers/scraper_base.py                           # gcs_path capture + rowCount detection
data_processors/raw/main_processor_service.py      # Added odds-api/game-lines route
data_processors/raw/nbacom/nbac_schedule_processor.py  # Fixed HASH_FIELDS
```

## Git Log

```
dc07130 fix: Odds scraper status detection and Phase 2 routing
3245512 fix: Only capture first gcs_path for Pub/Sub (primary data exporter)
a480f96 fix: Update schedule processor HASH_FIELDS to use existing field
```

## Quick Verification Commands

```bash
# Check scheduler jobs point to correct service
gcloud scheduler jobs list --location us-west2 --format="table(name,httpTarget.uri)" | grep phase1-scrapers

# Test odds scraper
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "oddsa_game_lines", "event_id": "EVENT_ID", "game_date": "2025-12-20"}'

# Check odds data in BigQuery
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_raw.odds_api_game_lines WHERE game_date >= "2025-12-20" GROUP BY 1'

# Check Phase 2 logs for game lines processing
gcloud run services logs read nba-phase2-raw-processors --region us-west2 --limit 50 | grep -E "game-lines|OddsGame"
```

## Notes

- The old `nba-scrapers` service (Nov 17) still exists but is no longer used
- Consider cleaning it up to avoid confusion
- Phase 3 processors may still fail if odds data isn't backfilled (they're optional deps but some are critical)
