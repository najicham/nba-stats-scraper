# Session 152: Pipeline Diagnosis - Deep Root Cause Analysis

**Date:** 2025-12-20
**Status:** Diagnosis complete, fixes partially applied, needs continuation
**Previous Session:** Session 150/151

---

## Executive Summary

This session committed pending changes from Sessions 143-151 and diagnosed why predictions are still stuck at Dec 13 despite the Phase 2-5 code fixes from Session 150. We found **multiple systemic issues** in the scraper-to-processor pipeline.

### What Was Fixed This Session

| Fix | Status | Files Changed |
|-----|--------|---------------|
| Phase 3 yaml dependency | ✅ Deployed | `data_processors/analytics/requirements.txt` |
| Phase 3 odds optional | ✅ Deployed | `upcoming_player_game_context_processor.py` |
| Session 143-151 commits | ✅ Pushed | 4 commits to main |

### What Still Needs Fixing

| Issue | Priority | Impact |
|-------|----------|--------|
| Scraper completion events missing `gcs_path` | HIGH | Phase 2 never processes files |
| Schedule processor hash field mismatch | HIGH | Can't update schedule data |
| Scraper status reporting (no_data when files exist) | MEDIUM | Game lines not processed |

---

## Root Cause Chain (Complete Picture)

```
                    SCRAPER LAYER (Phase 1)
                    ========================
Issue 1: Schedule scraper publishes completion with status=success but NO gcs_path
Issue 2: Game lines scraper publishes status=no_data when files EXIST in GCS
                              ↓
                    PROCESSOR LAYER (Phase 2)
                    ==========================
Phase 2 sees no gcs_path → Skips processing → BigQuery not updated
                              ↓
                    STALENESS (Phase 2 → 3)
                    ========================
Issue 3: Schedule table processed_at = 2025-09-18 (94 days old!)
Phase 3 dependency check: "Stale dependencies (FAIL threshold): 2249.2h old"
                              ↓
                    BLOCKED PHASES (3-5)
                    =====================
Phase 3 fails → Phase 4 can't run → Phase 5 predictions stuck at Dec 13
```

---

## Detailed Issue Analysis

### Issue 1: Scraper Completion Events Missing gcs_path

**Evidence:**
```
INFO:data_processors.raw.main_processor_service:Processing Scraper Completion message from: nbac_schedule_api
WARNING:data_processors.raw.main_processor_service:Scraper nbac_schedule_api published event with status=success but no gcs_path.
INFO:data_processors.raw.main_processor_service:Skipping processing for nbac_schedule_api (status=success): No file to process
```

**GCS shows files exist:**
```bash
gsutil ls -l "gs://nba-scraped-data/nba-com/schedule/2025-26/" | tail -3
# 1997958  2025-12-20T18:06:00Z  gs://nba-scraped-data/nba-com/schedule/2025-26/2025-12-20T18:05:03.690956+00:00.json
```

**Root Cause Location:**
- `scrapers/scraper_base.py` lines 1611-1612 - exporter must return `{'gcs_path': path}`
- `scrapers/nbacom/nbac_schedule_api.py` - check if exporter returns gcs_path

**Files to Read:**
- `scrapers/scraper_base.py:1611-1612` - where gcs_path is set
- `scrapers/scraper_base.py:697-701` - where completion event is published
- `scrapers/nbacom/nbac_schedule_api.py` - schedule scraper implementation

---

### Issue 2: Schedule Processor Hash Field Mismatch

**Evidence:**
```
ERROR:data_processors.raw.smart_idempotency_mixin:Failed to compute hash for record:
Hash field 'game_time_utc' not found in record.
Available fields: ['game_id', 'game_code', 'season', 'game_date', ...]
```

**Root Cause:** The processor's smart idempotency config specifies `game_time_utc` as a hash field, but the actual data schema doesn't include this field.

**Files to Read:**
- `data_processors/raw/nbacom/nbac_schedule_processor.py` - find `HASH_FIELDS` or `get_hash_fields`
- `data_processors/raw/smart_idempotency_mixin.py` - understand hash field logic

---

### Issue 3: Game Lines Scraper Reports no_data

**Evidence:**
```
INFO:data_processors.raw.main_processor_service:Processing Scraper Completion message from: oddsa_current_game_lines
WARNING:...Scraper oddsa_current_game_lines published event with status=no_data but no gcs_path.
INFO:...Skipping processing for oddsa_current_game_lines (status=no_data)
```

**But GCS has data:**
```bash
gsutil ls "gs://nba-scraped-data/odds-api/game-lines/2025-12-20/"
# Shows 10 game folders with valid JSON files
```

**Files to Read:**
- `scrapers/oddsapi/odds_game_lines.py` - game lines scraper
- Check how it determines status and gcs_path

---

## Current Pipeline Data State

```sql
-- Run this to check current state
SELECT
  "player_composite_factors" as tbl, MAX(game_date) as latest FROM nba_precompute.player_composite_factors
UNION ALL SELECT "player_daily_cache", MAX(cache_date) FROM nba_precompute.player_daily_cache
UNION ALL SELECT "ml_feature_store_v2", MAX(game_date) FROM nba_predictions.ml_feature_store_v2
UNION ALL SELECT "player_prop_predictions", MAX(game_date) FROM nba_predictions.player_prop_predictions
UNION ALL SELECT "player_game_summary", MAX(game_date) FROM nba_analytics.player_game_summary
UNION ALL SELECT "upcoming_player_game_context", MAX(game_date) FROM nba_analytics.upcoming_player_game_context
ORDER BY tbl
```

**As of end of this session:**
| Table | Latest Date | Status |
|-------|-------------|--------|
| player_game_summary | 2025-12-19 | ✅ OK |
| player_composite_factors | 2025-12-19 | ✅ OK |
| ml_feature_store_v2 | 2025-12-19 | ✅ OK |
| player_prop_predictions | **2025-12-13** | ⚠️ Stuck |
| upcoming_player_game_context | 2025-12-19 | ⚠️ Missing Dec 20 |
| nbac_schedule (processed_at) | **2025-09-18** | ❌ Stale |

---

## Commits Made This Session

```bash
git log --oneline -4
# 467d1c8 docs: Add handoff documentation for Sessions 143-150
# a648f6d feat: Add deployment scripts for Phase 5B and Phase 6
# b4be985 feat: Add Phase 6 exporters and prediction worker improvements
# 59fcfa4 fix: Restore pipeline after 6-day outage (Dec 13-19)
```

**Uncommitted changes:**
```bash
git status
# modified: data_processors/analytics/requirements.txt (pyyaml added)
# modified: data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py (odds optional)
```

---

## Deployments Made

| Service | Status | Notes |
|---------|--------|-------|
| nba-phase3-analytics-processors | ✅ Deployed | Revision 00015-nn7, includes yaml + optional odds fixes |
| Other services | No changes | |

---

## Action Plan for Next Session

### Priority 1: Fix Scraper Completion Events (unblocks everything)

1. **Read and understand the scraper base:**
   ```bash
   # Key file
   cat scrapers/scraper_base.py | grep -A 20 "def _publish_completion_event"
   ```

2. **Check schedule scraper exporter:**
   ```bash
   # Find where gcs_path should be returned
   grep -n "gcs_path\|export" scrapers/nbacom/nbac_schedule_api.py
   ```

3. **Fix pattern:** Ensure exporter returns `{'gcs_path': <path>}` so completion event includes it

4. **Redeploy scrapers**

### Priority 2: Fix Schedule Processor Hash Field

1. **Find the hash field config:**
   ```bash
   grep -n "HASH_FIELDS\|hash_fields\|game_time_utc" data_processors/raw/nbacom/nbac_schedule_processor.py
   ```

2. **Change to use available field** (e.g., `game_date_est` instead of `game_time_utc`)

3. **Redeploy Phase 2 OR run locally to update schedule data**

### Priority 3: Commit Pending Changes

```bash
git add data_processors/analytics/requirements.txt
git add data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
git commit -m "fix: Make odds data optional in Phase 3, add pyyaml dependency"
git push
```

### Priority 4: Run Grading Backfill (from Session 151)

```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-06 \
  --end-date 2025-12-19
```

---

## Quick Reference: Key Files

| Purpose | File Path |
|---------|-----------|
| Scraper base (completion events) | `scrapers/scraper_base.py` |
| Schedule scraper | `scrapers/nbacom/nbac_schedule_api.py` |
| Game lines scraper | `scrapers/oddsapi/odds_game_lines.py` |
| Schedule processor | `data_processors/raw/nbacom/nbac_schedule_processor.py` |
| Smart idempotency (hash fields) | `data_processors/raw/smart_idempotency_mixin.py` |
| Phase 3 upcoming player context | `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` |
| Phase 3 analytics base | `data_processors/analytics/analytics_base.py` |
| Session 150 handoff | `docs/09-handoff/2025-12-20-SESSION150-PIPELINE-STATUS-AND-ISSUES.md` |
| Session 151 handoff | `docs/09-handoff/2025-12-20-SESSION151-NO-LINE-PLAYERS-GRADING-UPDATE.md` |

---

## Verification Commands

### Check if scrapers are publishing correctly:
```bash
gcloud run services logs read nba-scrapers --region us-west2 --limit 50 2>&1 | grep -E "publish|completion|gcs_path"
```

### Check Phase 2 processing:
```bash
gcloud run services logs read nba-phase2-raw-processors --region us-west2 --limit 50 2>&1 | grep -E "schedule|Processing"
```

### Check Phase 3 status:
```bash
gcloud run services logs read nba-phase3-analytics-processors --region us-west2 --limit 30
```

### Check schedule freshness:
```bash
bq query --use_legacy_sql=false '
SELECT game_date, MAX(processed_at) as last_processed, COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date >= "2025-12-18"
GROUP BY game_date
ORDER BY game_date DESC'
```

---

## Session Statistics

- **Issues discovered:** 3 new systemic issues
- **Fixes applied:** 2 (yaml dependency, optional odds)
- **Fixes deployed:** 1 (Phase 3)
- **Commits:** 4 pushed to main
- **Uncommitted changes:** 2 files
- **Pipeline status:** Still blocked by scraper issues

---

## Context for Next Session

The prediction pipeline has been broken since Dec 13. Session 150 fixed the Phase 2-5 code bugs, but this session discovered that the **scrapers aren't publishing correct completion events** - they save files to GCS but don't tell Phase 2 where the files are.

The fastest path to working predictions:
1. Fix the scraper completion event publishing
2. OR: Manually run Phase 2 processors with explicit GCS paths
3. Then Phase 3→4→5 should flow

The grading backfill from Session 151 is ready to run but should wait until the pipeline is flowing again.

---

*End of handoff*
