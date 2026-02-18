# Session 291+292 Handoff — NaN Bug Fix, Extraction Cleanup, Backfill, Publishing

**Date:** 2026-02-18
**Focus:** Root cause investigation of feature extraction bugs, NaN fix, data cleanup, backfill, publishing enhancements

## What Was Done

### 1. Deep Root Cause Investigation (Session 291)

Investigated all bug categories from Session 290 handoff. Found most reported bugs had fewer root causes than expected:

| Reported Bug | Count | Actual Root Cause | Resolution |
|---|---|---|---|
| f5-8 composite_factors | 261 | 342 ALL_NULL stale rows from prior backfills | Deleted stale data |
| f9-12, f15-17, f21, f24, f28, f30 calculated | 342 each | Same 342 ALL_NULL stale rows | Deleted stale data |
| f13-14 team_defense | 268 | Same ALL_NULL stale rows | Deleted stale data |
| **f29 avg_points_vs_opponent** | **3,174** | **Pandas NaN bypasses `is not None` check; NaN is truthy in Python `or` chain** | **Code fix: `_safe_float` + `_is_valid_value` helpers** |
| f18-20 shot_zone | 544 | 232 ALL_NULL + 312 false positives (source row exists but values NULL) | Deleted stale data + fixed validation SQL |
| 79 duplicate rows on Jan 10 | 79 | Overlapping backfill runs | Deleted duplicates |

### 2. Code Fixes

**Commit `1ff893f9` (Session 291):**
- `feature_extractor.py`: Removed all-or-nothing fallback from `_batch_extract_composite_factors` → exact-date-only
- `ml_feature_store_processor.py`: Added `_safe_float(val, default)` helper for f29/f30 NaN safety
- `validate_feature_sources.py`: Shot zone validation requires non-NULL values

**Commit `f96eb275` (Session 292):**
- `ml_feature_store_processor.py`: Added `_is_valid_value()` static method — universal NaN-safe check
- Applied to ALL three feature helpers: `_get_feature_with_fallback`, `_get_feature_nullable`, `_get_feature_phase4_only`
- Also fixed f31/f32 minutes_ppm extraction to use `_is_valid_value()`

**Commit `720520fc` (Session 292):**
- `tonight_all_players_exporter.py`: Added minutes, FG%, 3PT%, +/- to last 10 games
- `tonight_player_exporter.py`: Date-keyed paths (`tonight/player/{date}/{lookup}.json`) for historical browsing
- `player_game_summary_processor.py`: Fixed `_parse_plus_minus()` to handle numeric values (was silently dropping ALL plus_minus data)
- `validate-daily SKILL.md`: Box score column completeness check
- `backfill_tonight_player_exports.py`: New resumable backfill script for date-keyed exports

### 3. Data Cleanup (Session 291, DONE)

```sql
-- Deleted 342 ALL_NULL stale rows
DELETE FROM ml_feature_store_v2 WHERE game_date BETWEEN '2026-01-06' AND '2026-02-17'
  AND feature_0_value IS NULL AND feature_5_value IS NULL AND feature_9_value IS NULL;
-- Deduplicated 79 rows on Jan 10
```

### 4. Backfill Results

Two full passes completed (38 dates each, 0 failures):
- **Pass 1 (Session 291):** Fixed ALL_NULL, composite_factors, partial f29
- **Pass 2 (Session 292):** Applied `_is_valid_value()` NaN-safe helpers to all features

### 5. Validation Results (Final — After Session 292)

| Metric | Session 290 | Session 291 | Session 292 |
|---|---|---|---|
| Features with bugs | 30 | 3 | **2** |
| Total bugs | ~8,000+ | 659 | **519** |
| f29 bugs | 3,174 | 140 | **0** |
| f5-8 bugs | 261 | 0 | 0 |
| f13-14 bugs | 268 | 0 | 0 |
| f18-20 bugs | 544 | 0 | 0 |

**Remaining 2 features with bugs (both upstream data gaps, not code bugs):**
- **f4 `games_in_last_7_days` (188 bugs):** `player_daily_cache` has the row but this field is NULL for ~3% of players. Upstream cache processor doesn't always compute it.
- **f32 `ppm_avg_last_10` (331 bugs):** `player_game_summary` doesn't have enough recent games for ~14% of players (bench players). This is expected behavior.

Both are blocked by zero tolerance quality gates — no impact on predictions.

### 6. f4/f32 Root Cause (Session 292 Investigation)

These are NOT NaN bugs. The upstream source tables have the rows but the specific fields are NULL:
- `player_daily_cache.games_in_last_7_days` = NULL for 290/8634 rows (3.4%)
- `player_game_summary` has no games in last 30 days for many bench players → no PPM data

The `_get_feature_with_fallback` code correctly falls through to default. The `_is_valid_value()` fix ensures NaN never leaks through, but these cases are genuine None values.

**Potential fix:** In `feature_extractor.py:extract_phase4_data()`, when daily_cache has the player but specific fields are NULL, fill from `_compute_cache_fields_from_games` (currently only runs on complete cache misses). Low priority since affected players are blocked.

### 7. NaN Bug Root Cause (Technical Detail)

The f29 bug chain:
1. BQ `LEFT JOIN` with no matching games → `AVG(g.points) = NULL`
2. Pandas converts BQ NULL → `float('nan')` in `.to_dict('records')`
3. Code checks `val is not None` → NaN passes (NaN is not None)
4. `features[29] = NaN`
5. **Dual-write divergence:**
   - `features` array: sanitizer converts NaN→None→0.0
   - `feature_29_value`: sanitizer converts NaN→None (stays NULL)

**Fix:** `_is_valid_value()` checks both `is None` AND `math.isnan()`. Applied to all feature helpers.

## What's Next (Priority Order)

### Priority 1: Retrain After Games Resume (Feb 19-20)
- Games resume Feb 19
- Wait 1-2 days for eval data, then:
```bash
./bin/retrain.sh --promote --eval-days 3   # Shorter eval window initially
```

### Priority 2: Backfill plus_minus in player_game_summary
- `_parse_plus_minus()` was fixed to handle numeric values (was silently dropping ALL values)
- Need to re-process historical games to populate plus_minus:
```bash
# Backfill Phase 3 player_game_summary to pick up plus_minus fix
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary_backfill.py --start-date 2025-10-22 --end-date 2026-02-17
```

### Priority 3: Backfill date-keyed tonight player exports
```bash
PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --skip-existing
```

### Priority 4: Deferred Items (from Session 290)
- Split `validate-daily` skill (6,167 lines, 40% of all skill code)
- Full-season feature store backfill (blocked by missing `team_defense_zone_analysis` for early dates)
- Features array column removal (Phase 8) — deferred 2+ weeks
- Feature importance analysis (`CatBoost.get_feature_importance()`)
- Pace-adjusted metrics (new features)
- f4/f32 upstream fix (partial cache miss handling in `extract_phase4_data`)

## Commits

1. `1ff893f9` — fix: exact-date composite_factors extraction, NaN-safe f29 opponent history
2. `f96eb275` — fix: NaN-safe feature helpers prevent BQ NULL → pandas NaN inconsistencies
3. `720520fc` — feat: add box score detail to player exports, date-keyed player pages

## Key Files Modified

| File | Changes |
|------|---------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Exact-date-only composite_factors |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | `_is_valid_value()` NaN-safe helper, all feature methods |
| `bin/validate_feature_sources.py` | Shot zone validation requires non-NULL values |
| `data_processors/publishing/tonight_all_players_exporter.py` | Box score detail in last 10 games |
| `data_processors/publishing/tonight_player_exporter.py` | Date-keyed export paths |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Fixed `_parse_plus_minus()` |
| `bin/backfill/backfill_tonight_player_exports.py` | New backfill script |
| `.claude/skills/validate-daily/SKILL.md` | Box score completeness check |

## Production State

| Component | Status |
|-----------|--------|
| Production model | `catboost_v9_33f_train20251102-20260205_20260216_191144` (fresh, 12 days) |
| Feature store | Backfilled Jan 6 - Feb 17, 31/33 features CLEAN |
| Code deploy | Auto-deployed via push to main |
| Games | Resume Feb 19 |
| Feature bugs | 2 remaining (f4: 188, f32: 331) — all upstream data gaps, blocked by quality gates |
