# Team Boxscore Backfill - Handoff
**Date:** January 22, 2026
**Purpose:** Backfill 100 missing games of team boxscore data and reprocess cascade
**Priority:** P0 - CRITICAL (Blocking predictions)

---

## Your Mission

1. Run the team boxscore scraper backfill for 100 games (Dec 27, 2025 - Jan 21, 2026)
2. Process the raw data through Phase 2
3. Reprocess Phase 3-5 for the gap period AND the cascade period
4. Verify predictions are generated for Jan 21

---

## Context

### What's Missing

| Table | Gap Period | Records Missing |
|-------|------------|-----------------|
| `nbac_team_boxscore` | Dec 27 - Jan 21 | ~200 team records |
| `team_defense_game_summary` | Dec 27 - Jan 21 | 0 rows (depends on above) |
| `team_offense_game_summary` | Dec 27 - Jan 21 | Using fallback |
| `player_prop_predictions` | Jan 21 | **0 predictions** |

### Root Cause

Team boxscore scraper failed 148 times starting Dec 27. Errors: "Expected 2 teams for game X, got 0" (scraper tried to fetch data for games before they finished).

---

## Step 1: Run Team Boxscore Backfill

The game IDs CSV is already populated with 100 games.

```bash
cd /home/naji/code/nba-stats-scraper

# Verify CSV is ready
wc -l backfill_jobs/scrapers/nbac_team_boxscore/game_ids_to_scrape.csv
# Expected: 101 (100 games + header)

# Dry run first
PYTHONPATH=. python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --dry-run

# Run with 10 workers (~15-20 min)
PYTHONPATH=. python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
  --workers=10

# Monitor for failures
ls backfill_jobs/scrapers/nbac_team_boxscore/failed_games_*.json
```

**Expected:** All 100 games scraped successfully

---

## Step 2: Verify Raw Data in GCS

```bash
# Check GCS for scraped files
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/20260121/ | head -10
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/20260101/ | head -10
```

---

## Step 3: Process Raw Data (Phase 2)

The raw processor should pick up the new JSON files. You may need to trigger it:

```bash
# Check if raw processor is healthy
curl -s "https://nba-phase2-raw-processors-756957797294.us-west2.run.app/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Trigger processing for a specific date (repeat for all dates)
curl -X POST "https://nba-phase2-raw-processors-756957797294.us-west2.run.app/process" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-21", "processor": "nbac_team_boxscore"}'
```

**Verify in BigQuery:**
```sql
SELECT game_date, COUNT(*) as records
FROM nba_raw.nbac_team_boxscore
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;

-- Expected: ~200 records total (2 teams × ~100 games ÷ shared)
```

---

## Step 4: Reprocess Phase 3 (Analytics)

**Gap period reprocessing:**

```bash
# Option A: Use year phase3 script
./bin/backfill/run_year_phase3.sh --start-date=2025-12-27 --end-date=2026-01-21

# Option B: Trigger via API
for date in 2025-12-{27..31} 2026-01-{01..21}; do
  curl -X POST "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\", \"force_reprocess\": true}"
  sleep 5
done
```

**Verify:**
```sql
SELECT game_date, COUNT(*) as records
FROM nba_analytics.team_defense_game_summary
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;

-- Expected: Records for all dates with games
```

---

## Step 5: Reprocess Phase 4 (Precompute)

**Gap period + cascade period:**

The cascade extends ~21 days forward. So reprocess Dec 27 - Feb 11:

```bash
# Use year phase4 script
./bin/backfill/run_year_phase4.sh --start-date=2025-12-27 --end-date=2026-02-11
```

**Verify:**
```sql
SELECT game_date, COUNT(*) as records
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;
```

---

## Step 6: Regenerate Predictions for Jan 21

```bash
# Check prediction coordinator health
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Trigger prediction generation
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/trigger" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-21", "force_regenerate": true}'
```

**Verify:**
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-21'
  AND is_active = TRUE
GROUP BY game_date;

-- Expected: 850-900 predictions, 7 systems
```

---

## Step 7: Final Validation

```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 bin/validate_pipeline.py 2026-01-21 --legacy-view
```

**Expected output:**
- Total predictions: 850-900
- Games covered: 6-7
- Systems active: 7
- Phase 5: COMPLETE

---

## Troubleshooting

### If scraper backfill fails:
- Check scraper service health
- Check for rate limiting
- Review failed_games_*.json for specific errors

### If Phase 3 fails:
- Check for missing gamebook data (should exist)
- Verify Phase 2 raw data exists

### If predictions = 0:
- Check prediction-worker health (was returning 503)
- Check ml_feature_store has data for Jan 21
- Check composite_factors has data for Jan 21

---

## Reference Documents

- `/docs/08-projects/current/team-boxscore-data-gap-incident/INCIDENT-REPORT-JAN-22-2026.md`
  - Full backfill execution plan (Section 8)
  - Verification queries

---

## Cascade Scope Summary

| Backfilled | Affects Features Through | Reprocess Scope |
|------------|-------------------------|-----------------|
| Dec 27 - Jan 21 | Feb 11 (21 days forward) | Dec 28 - Feb 11 |

**Total reprocessing:** 46 days of Phase 4 + Phase 5

---

**Document Status:** Ready for Execution
**Estimated Time:** 2-3 hours (including verification)
