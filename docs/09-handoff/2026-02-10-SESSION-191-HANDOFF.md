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

## Next Session Priorities

1. **Verify grading completed** for Feb 1-3 (check `prediction_accuracy` table)
2. **Investigate QUANT barely producing** — check worker dispatch logic, logs, and whether shadow models get same player list as champion
3. **Monitor Cloud Build** — verify auto-deploy completed for phase6 service
4. **Run full export cycle** — trigger Phase 6 to regenerate all JSON files with updated exporters
5. **Consider V8 grading**: The ~44% ungraded V8 predictions are by design (no real lines), but Feb 1 has 199/336 (59%) ungraded — some of those may have real lines that failed to grade for another reason
