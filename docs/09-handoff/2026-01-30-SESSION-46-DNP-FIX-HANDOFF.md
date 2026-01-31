# Session 46 Handoff - DNP Data Corruption Fix

**Date:** 2026-01-30
**Duration:** ~1.5 hours
**Focus:** Fix DNP data corruption causing model performance collapse
**Status:** 88% complete (22/25 January dates fixed)

---

## Executive Summary

Session 46 fixed the critical DNP data corruption issue identified in Session 45. DNP (Did Not Play) players were being recorded with `points = 0` instead of `NULL`, corrupting ~32% of January 2026 data and causing star player features to be artificially lowered.

### Key Accomplishments

1. **Reprocessed 22 of 25 January dates** through analytics backfill
2. **Fixed NULL team_abbr bug** by adding `_derive_team_abbr()` helper method
3. **Committed fix** in `3509c81b`

### Before vs After

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Zero-point games | 32-50% | 6-12% |
| DNP marked | 0 | 70-150 per day |
| Star player features | Corrupted (0s) | Clean |

---

## What Was Fixed

### 1. Analytics Layer Reprocessing

Ran `player_game_summary_analytics_backfill.py` for all January dates with raw gamebook data:

```bash
source .venv/bin/activate && PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py --dates <dates>
```

### 2. NULL team_abbr Fix (Commit 3509c81b)

Added `_derive_team_abbr()` helper method to `player_game_summary_processor.py` that derives team_abbr from game_id context when it's NULL in raw gamebook data.

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Logic:**
1. Use existing team_abbr if available
2. Parse from game_id (format: `YYYYMMDD_AWAY_HOME`) using is_home flag
3. Fallback to source_home_team/source_away_team

---

## Current Status

### Fixed Dates (22/25)

| Date Range | Status | Notes |
|------------|--------|-------|
| Jan 1-7 | ✅ FIXED | 6-10% zero points |
| Jan 9-21 | ✅ FIXED | 6-10% zero points |
| Jan 24-29 | ✅ FIXED | 6-12% zero points |

### Remaining Issues (3/25)

| Date | Issue | Resolution Needed |
|------|-------|-------------------|
| **Jan 8** | Only 3 games, incomplete team stats | Low priority - data completeness issue |
| **Jan 22** | No raw gamebook PDFs in GCS | Scrape from NBA.com |
| **Jan 23** | No raw gamebook PDFs in GCS | Scrape from NBA.com |

---

## Next Session Tasks

### Priority 1: Scrape Missing Gamebook PDFs (Jan 22-23)

**16 games need scraping:**

```
# Jan 22 (8 games)
20260122/CHAORL, 20260122/HOUPHI, 20260122/DENWAS, 20260122/GSWDAL
20260122/CHIMIN, 20260122/SASUTA, 20260122/LALLAC, 20260122/MIAPOR

# Jan 23 (8 games)
20260123/HOUDET, 20260123/PHXATL, 20260123/BOSBKN, 20260123/SACCLE
20260123/NOPMEM, 20260123/DENMIL, 20260123/INDOKC, 20260123/TORPOR
```

**Option A: Use Cloud Run Job**
```bash
gcloud run jobs execute nbac-gamebook-backfill \
  --args="^|^--start-date=2026-01-22|--end-date=2026-01-23" \
  --region=us-west2
```

**Option B: Direct scraper call**
```bash
# Get scraper service URL
SCRAPER_URL=$(gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="value(status.url)")

# Scrape each game (4 second delay required)
for game_code in 20260122/CHAORL 20260122/HOUPHI ...; do
  curl -X GET "$SCRAPER_URL/nbac_gamebook_pdf?game_code=$game_code" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)"
  sleep 4
done
```

After scraping, run raw processor then analytics backfill:
```bash
source .venv/bin/activate && PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py --dates 2026-01-22,2026-01-23
```

### Priority 2: Verify Nov-Dec 2025 DNP Handling

Check if historical data also needs reprocessing:

```sql
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as total,
  COUNTIF(is_dnp = TRUE) as dnp_marked,
  COUNTIF(points IS NULL) as null_pts,
  ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2025-11-01' AND game_date < '2026-01-01'
GROUP BY 1
ORDER BY 1;
```

If `dnp_marked = 0` and `pct_zero > 30%`, those months need reprocessing.

### Priority 3: Re-evaluate Model Performance

With clean data, re-run predictions and check if performance improves:

```sql
-- Check prediction accuracy for fixed dates vs broken dates
SELECT
  CASE WHEN game_date IN ('2026-01-08', '2026-01-22', '2026-01-23')
       THEN 'BROKEN' ELSE 'FIXED' END as data_status,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as model_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as line_mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-01' AND game_date < '2026-01-30'
  AND line_value IS NOT NULL
GROUP BY 1;
```

---

## Key Files

| File | Purpose |
|------|---------|
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Main processor with DNP fix and team_abbr derivation |
| `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` | Backfill script for reprocessing |
| `backfill_jobs/scrapers/nbac_gamebook/nbac_gamebook_scraper_backfill.py` | Gamebook scraping job |

---

## Verification Query

Run this to verify DNP handling is correct:

```sql
SELECT
  game_date,
  COUNTIF(is_dnp = TRUE) as dnp_marked,
  ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero,
  CASE WHEN COUNTIF(is_dnp = TRUE) > 0 THEN 'FIXED' ELSE 'ISSUE' END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2026-01-01' AND game_date < '2026-01-30'
GROUP BY game_date
ORDER BY game_date;
```

**Expected:** All dates should show `FIXED` except Jan 8, 22, 23.

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `3509c81b` | fix: Derive team_abbr from game context for DNP players |

---

## Uncommitted Changes

```
M .pre-commit-hooks/check_import_paths.py
M CLAUDE.md
M backfill_jobs/scrapers/bp_props/deploy.sh
M data_processors/analytics/upcoming_player_game_context/calculators/__init__.py
M data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py
M data_processors/analytics/upcoming_player_game_context/team_context.py
M docs/08-projects/current/nba-backfill-2021-2026/CURRENT-STATUS.md
M docs/09-handoff/2026-01-30-SESSION-34-CATBOOST-V9-EXPERIMENTS-HANDOFF.md
?? data_processors/analytics/upcoming_player_game_context/calculators/schedule_context_calculator.py
?? docs/09-handoff/2026-01-30-SESSION-44-DEEP-INVESTIGATION-HANDOFF.md
```

---

## Key Learnings

1. **DNP handling was broken in analytics layer** - Raw data was correct, but analytics didn't mark DNP properly
2. **NULL team_abbr in raw data** - Some DNP players don't have team_abbr extracted from gamebook PDF
3. **game_id format is reliable** - Can derive team info from `YYYYMMDD_AWAY_HOME` format
4. **Jan 22-23 gamebooks never scraped** - Root cause unknown, need manual scrape

---

## Session 46 Complete

The critical DNP data corruption issue is 88% fixed. Star player features should now be calculated correctly for 22 of 25 January dates. Remaining work is to scrape missing gamebook PDFs and verify historical data.

*Next session should focus on scraping Jan 22-23 gamebooks, then re-evaluating model performance with clean data.*
