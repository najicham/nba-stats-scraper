# Session 191 Handoff — Multi-Model V2 Exports, Data Fixes, Frontend Docs

**Date:** 2026-02-10
**Commit:** `6dfc2b4c`
**Status:** Complete — pushed to main, auto-deploy triggered

---

## What Was Done

### 1. Performance View 30-Day Cap Fixed
- **File:** `schemas/bigquery/predictions/views/v_dynamic_subset_performance.sql`
- Removed `AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)` hard cap
- View now returns full season data (verified: Jan 9 - Feb 10, 80 rows)
- Deployed to BigQuery via `CREATE OR REPLACE VIEW`
- This was causing season-level records to only show 30 days of data

### 2. SeasonSubsetPicksExporter Upgraded to v2
- **File:** `data_processors/publishing/season_subset_picks_exporter.py`
- Converted from single-model (`catboost_v9`) to multi-model `model_groups` structure
- Now queries `system_id` from `current_subset_picks` and groups by model
- Uses `get_model_display_info()` and `CHAMPION_CODENAME` from `model_codenames.py`
- Champion (phoenix) always sorted first
- Per-pick results (`actual`, `result`: hit/miss/push/null) preserved — unique to this exporter
- Records aggregated per-model using broadest subset
- Version field: `"version": 2`

### 3. SubsetPerformanceExporter NoneType Fix
- **File:** `data_processors/publishing/subset_performance_exporter.py`
- Fixed crash when `hit_rate` or `roi_pct` is NULL from BigQuery (new QUANT subsets had no graded data)
- Changed `subset_perf.get('hit_rate', 0.0)` to `subset_perf.get('hit_rate') or 0.0`

### 4. Data Gap Fixes (BQ DML)
- **Reactivated 1,026 Feb 1-3 predictions** (`catboost_v9` + `catboost_v9_2026_02`)
  - Feb 1: 286 predictions (143 per system)
  - Feb 2: 222 predictions (111 per system)
  - Feb 3: 518 predictions (259 per system)
- **Triggered grading** for all 3 dates via Pub/Sub `nba-grading-trigger`
- Grading should complete within minutes — verify in `prediction_accuracy`

### 5. Investigation Findings

#### V8 Grading Gap: Not a bug
- ~44% of V8 predictions have `ESTIMATED_AVG` (3,131), `NO_PROP_LINE` (220), or NULL (193) line sources
- These have `current_points_line IS NULL` or `= 20.0` (hardcoded default)
- Grading processor correctly skips them (requires real lines)
- **No action needed** — this is by design

#### QUANT Barely Producing: Models not being invoked
- Q43/Q45 have only 2 predictions each on Feb 10, zero on Feb 8-9
- No `default_feature_count` issues (0 defaults on what they produced)
- The models are being called but producing very few predictions
- **Root cause likely:** Worker may be limiting shadow model predictions to a small subset, or the models' quality gate is passing very few players
- **Next step:** Check `catboost_monthly.py` dispatcher logic and worker logs

### 6. Project Docs Updated
- **File:** `docs/08-projects/current/website-export-api/00-PROJECT-OVERVIEW.md`
- Fixed all stale codenames: `926A` → `phoenix`, `Q43A` → `aurora`, `Q45A` → `summit`
- Fixed model types: `standard` → `primary`, `quantile_under` → `specialist`
- Added Session 191 changes section
- Marked performance view 30-day cap as FIXED

### 7. Frontend API Documentation Created
- **File:** `docs/08-projects/current/website-export-api/FRONTEND-API-GUIDE.md`
- Comprehensive guide covering all 5 subset-page endpoints
- Complete JSON schemas with field descriptions
- Model codename system explained
- Rendering guidance (tabs, signals, records, result states)
- Cache strategy recommendations
- Error handling and empty state guidance
- Data freshness timeline

### 8. Test Script Updated
- **File:** `bin/test-phase6-exporters.py`
- Added `test_season_subset_picks()` for v2 multi-model structure
- Validates: version=2, model_groups, champion first, record structure, pick fields (including actual/result), signal values, no leaked terms
- All 5 tests passing

---

## Files Changed

| File | Change |
|------|--------|
| `schemas/bigquery/predictions/views/v_dynamic_subset_performance.sql` | Removed 30-day cap |
| `data_processors/publishing/season_subset_picks_exporter.py` | Upgraded to v2 multi-model |
| `data_processors/publishing/subset_performance_exporter.py` | Fixed NoneType crash |
| `data_processors/publishing/all_subsets_picks_exporter.py` | Session 190 multi-model (already) |
| `data_processors/publishing/subset_definitions_exporter.py` | Session 190 multi-model (already) |
| `data_processors/publishing/subset_materializer.py` | Session 190 multi-model (already) |
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | Session 190 system_id column |
| `shared/config/model_codenames.py` | Session 190 codenames |
| `shared/config/subset_public_names.py` | Session 190 QUANT names |
| `bin/test-phase6-exporters.py` | Added season v2 tests |
| `docs/08-projects/current/website-export-api/00-PROJECT-OVERVIEW.md` | Fixed codenames |
| `docs/08-projects/current/website-export-api/FRONTEND-API-GUIDE.md` | NEW |
| `docs/09-handoff/2026-02-10-SESSION-188B-PHASE3-PHASE4-VALIDATION.md` | Session 188B handoff |
| `docs/09-handoff/2026-02-10-SESSION-188C-FULL-SEASON-VALIDATION.md` | Session 188C handoff |
| `docs/09-handoff/2026-02-10-SESSION-190-MULTI-MODEL-EXPORT.md` | Session 190 handoff |

---

## Verification

- All 5 exporter tests pass (`PYTHONPATH=. python bin/test-phase6-exporters.py`)
- Performance view returns full season data (verified: Jan 9 - Feb 10)
- Feb 1-3 predictions all reactivated (1,026 rows, verified with count query)
- Grading triggered for Feb 1-3
- Pushed to main → auto-deploy triggers should fire

---

## Outstanding Issues (Session 191 ran out of context)

### Issue 1: QUANT Models Barely Producing (HIGH PRIORITY)
**Problem:** Aurora (Q43) and Summit (Q45) produce only ~2 predictions per game day. Champion (Phoenix) produces 50-80+.

**What we know:**
- Models ARE enabled in `catboost_monthly.py` (lines 133-168)
- Worker dispatches them (`worker.py:1805`)
- NOT a quality gate issue — the 2 predictions they made had 0 default features
- Models simply aren't being invoked for most players

**Investigation needed:**
- Check worker logs for shadow model dispatch: `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND "q43"' --project=nba-props-platform --limit=50`
- Check if `catboost_monthly.py` limits which players get shadow predictions
- Check if `worker.py` quality gate treats shadow models differently from champion
- Files to examine: `predictions/worker/worker.py` (search for `shadow`, `challenger`, `monthly`), `predictions/shared/catboost_monthly.py`

### Issue 2: Materialized Subset Picks Missing Feb 8-10
**Problem:** `current_subset_picks` has no rows for Feb 8-10. The materializer needs to run for these dates.

**Fix:**
```sql
-- Check current state
SELECT game_date, COUNT(*) FROM nba_predictions.current_subset_picks
WHERE game_date >= '2026-02-07' GROUP BY 1 ORDER BY 1;
```
Then trigger materializer for missing dates. The materializer runs as part of Phase 6 — may need manual trigger or backfill.

### Issue 3: system_id NULL on Historical Subset Picks
**Problem:** All `current_subset_picks` rows before Session 190 have `system_id = NULL`. They're all from `catboost_v9`.

**Fix:**
```sql
-- Backfill system_id for historical rows
UPDATE nba_predictions.current_subset_picks
SET system_id = 'catboost_v9'
WHERE system_id IS NULL;
```

### Issue 4: Verify Feb 1-3 V9 Grading
**Problem:** We reactivated 1,026 Feb 1-3 predictions and sent Pub/Sub grading triggers. However, the first trigger graded V8/ensemble/etc but NOT V9 (predictions were still inactive when grader ran). A second round of triggers was sent just before context loss.

**Verify:**
```sql
SELECT game_date, system_id, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND system_id = 'catboost_v9'
GROUP BY 1, 2 ORDER BY 1;
```
If zero V9 rows, re-trigger grading:
```bash
for d in 2026-02-01 2026-02-02 2026-02-03; do
  gcloud pubsub topics publish nba-grading-trigger \
    --project=nba-props-platform \
    --message="{\"game_date\": \"$d\", \"trigger_source\": \"manual_backfill\"}"
done
```

### Issue 5: Phase 6 Export Backfill & Monitoring
**Problem:** User requested ensuring Phase 6 exports are running properly, backfilled for past month, and monitored.

**What we know:**
- GCS bucket: `gs://nba-props-platform-api/v1/`
- All 15 export directories exist (picks, signals, subsets, systems, tonight, trends, etc.)
- Phase 6 runs as part of `phase5-to-phase6-orchestrator` Cloud Function
- Test script: `PYTHONPATH=. python bin/test-phase6-exporters.py` — all 5 tests pass
- No dedicated Phase 6 monitoring/alerting exists beyond the general canary system

**Needs:**
- Audit GCS files: which dates have exports, which are missing
- Backfill missing exports (at least past 30 days)
- Consider adding Phase 6 canary query to `bin/monitoring/pipeline_canary_queries.py`
- Validate export JSON structure for historical dates

### Issue 6: Champion Model Decay (INFO — documented)
- Champion hit rate: 21-36% over last 6 days (Feb 4-9). 39+ days stale.
- QUANT_43 (Aurora) was the best fresh model at 65.8% HR 3+ in backtests, but barely producing in production (Issue 1).
- No action needed beyond fixing QUANT production issue (Issue 1) and monitoring.

---

## Next Session Priorities (Ordered)

1. **Fix QUANT barely producing** (Issue 1) — Biggest functional gap. Investigate worker dispatch for shadow models. If fixed, Aurora/Summit start generating real picks and can be evaluated.
2. **Backfill materialized subset picks** (Issue 2) — Run materializer for Feb 8-10+ so season exporter has data.
3. **Backfill system_id on historical subset picks** (Issue 3) — Quick UPDATE query.
4. **Verify Feb 1-3 V9 grading** (Issue 4) — Check if re-trigger worked. If not, trigger again.
5. **Phase 6 export audit & backfill** (Issue 5) — Audit GCS, backfill missing dates, add monitoring.
6. **Consider Phase 6 canary** — Add export freshness check to monitoring pipeline.

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-10-SESSION-191-HANDOFF.md

# 2. Check QUANT prediction counts
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE '%q4%' AND game_date >= '2026-02-08'
GROUP BY 1, 2 ORDER BY 2 DESC, 1"

# 3. Check materialization gaps
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) FROM nba_predictions.current_subset_picks
WHERE game_date >= '2026-02-01' GROUP BY 1 ORDER BY 1"

# 4. Check Feb 1-3 V9 grading
bq query --use_legacy_sql=false "
SELECT game_date, system_id, COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-02-01' AND '2026-02-03' AND system_id = 'catboost_v9'
GROUP BY 1, 2 ORDER BY 1"

# 5. Run daily validation
/validate-daily
```
