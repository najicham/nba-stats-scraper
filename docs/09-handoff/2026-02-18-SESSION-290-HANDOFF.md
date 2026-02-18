# Session 290 Handoff — Feature Extraction Fix, Skills Cleanup, Feature Store Audit

**Date:** 2026-02-18
**Focus:** Fix feature extraction bugs, consolidate Claude skills, comprehensive feature audit

## What Was Done

### 1. Feature Extractor Fix (DEPLOYED)

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Removed all-or-nothing fallback from 3 batch extraction methods. Previously, if even ONE player/team had exact-date data, the fallback window (14/7 days) never triggered, leaving all other players with NULL features. But the fix was NOT to use a ranked window — that would mask stale data as `source='phase4'`, bypassing zero-tolerance quality scoring.

**Correct fix:** Exact-date-only queries. Missing data stays NULL, flows through proper quality chain.

| Method | Old Behavior | New Behavior |
|--------|-------------|--------------|
| `_batch_extract_daily_cache` | Exact date, 14-day fallback if empty | Exact date only |
| `_batch_extract_shot_zone` | Exact date, 14-day fallback if empty | Exact date only |
| `_batch_extract_team_defense` | Exact date, 7-day fallback if empty | Exact date only |

**NOT fixed:** `_batch_extract_composite_factors` has the same all-or-nothing pattern but is a different case (matchup-specific factors like pace_score must NOT use wrong-opponent data). Validation shows 261 bugs — needs fixing next session.

### 2. Validation Tool Updated (DEPLOYED)

**File:** `bin/validate_feature_sources.py`

Updated SQL for daily_cache, shot_zone, and team_defense groups to use exact-date matching (was using 14/7-day windows that would report false bugs now that extraction is exact-date-only).

### 3. Feature Store Backfill (COMPLETE)

Ran ML feature store backfill for retrain window:
- **Date range:** 2026-01-06 to 2026-02-17 (42-day rolling window)
- **Result:** 38/38 game dates, 10,359 players, 0 failures
- **Duration:** ~40 minutes

### 4. Skills Cleanup (DEPLOYED)

| Action | Skills | Reason |
|--------|--------|--------|
| Removed | `bdl-quality-check` | BDL disabled since Session 205 |
| Merged | `experiment-tracker` → `model-experiment` | Duplicate experiment tracking queries |
| Merged | `compare-models` → `model-health` | Landscape view + comparison SQL |
| Deleted | `validate-historical.md` (duplicate) | Kept `validate-historical/SKILL.md` |
| Regularized | 9 orphaned `.md` files | Moved to proper `*/SKILL.md` directories |

**Net result:** 28 properly registered skills (was 22 active + 10 orphaned + 1 obsolete)

### 5. Comprehensive Feature Store Audit

**Current state:** 54 features (f0-f53). V9 uses 33 (production), V12 uses 50 (shadow).

**Key findings:**
- f47 (teammate_usage_available) and f50 (multi_book_line_std) — code exists but backfill never run. All NULL.
- No feature importance analysis ever done — don't know which features drive predictions
- Top feature gaps identified: pace-adjusted metrics, player-matchup variance, line movement

## Post-Backfill Validation Results

Validation for retrain window (Jan 6 - Feb 17) shows remaining bugs:

| Feature Group | Bug Count | Root Cause |
|---------------|-----------|------------|
| f5-8 (composite_factors) | 261 | All-or-nothing fallback NOT FIXED (separate from the 3 we fixed) |
| f9-12, f15-17, f21, f24, f28, f30 (calculated) | 342 each | Backfill-mode limitation — some players lack UPCG context data |
| f13-14 (team_defense) | 268 | Source exists for exact date but per-player extraction didn't use it |
| f18-20 (shot_zone) | 544 | Source exists for exact date but per-player extraction didn't use it |
| f29 (avg_points_vs_opponent) | 3,174 | Calculated feature bug — needs investigation |
| f25-27 (vegas) | 0 | CLEAN — all NULLs are legitimate (bench players) |

**Bottom line:** The extraction fix cleaned up the batch-level all-or-nothing bug, but per-player extraction still has issues. Needs deeper investigation next session.

## What's Next (Priority Order)

### Priority 1: Fix Remaining Extraction Bugs
- Fix `_batch_extract_composite_factors` all-or-nothing fallback (261 bugs)
- Investigate why f13-14, f18-20 have bugs when source exists for exact date (per-player extraction issue)
- Fix f29 (avg_points_vs_opponent) — 3,174 bugs, calculated feature should never be NULL
- Fix f9-12 calculated feature NULLs in backfill mode

### Priority 2: Retrain Models
- Games resume Feb 19 (tomorrow)
- V9 champion was retrained Feb 16 (training through Feb 5) — still relatively fresh
- After fixing extraction bugs + re-backfilling, retrain with `./bin/retrain.sh --promote --eval-days 14`
- No separate experiment needed — retrain includes 6 governance gates

### Priority 3: Feature Improvements
- Run `bin/backfill_f47_f50.py` to populate f47 and f50 with real data
- Run `CatBoost.get_feature_importance()` after retrain to understand which features matter
- Add pace-adjusted metrics (3-4 new features, low effort, high value):
  - `possessions_per_game` = minutes * team_pace / 48
  - `points_per_possession` = points / possessions
  - `pace_adjusted_season_avg` = season_avg / (team_pace / 100)
- Add player-matchup variance features (2-3 new features, low effort):
  - `points_vs_opponent_std` (variance vs specific opponent)
  - `recent_3g_vs_opponent` (last 3 games, not seasonal average)

### Priority 4: Deferred Items
- Split `validate-daily` skill (6,167 lines — largest skill, 40% of all skill code)
- Full-season backfill blocked by missing `team_defense_zone_analysis` for early dates
- Features array column removal (Phase 8) — deferred 2+ weeks for stability

## Commits

1. `81dd960c` — fix: remove all-or-nothing fallback from batch extraction methods
2. `b6aaa038` — chore: consolidate Claude skills — remove 4, regularize 9 orphaned
3. `e7825c24` — fix: align validation tool with exact-date extraction logic

## Key Files Modified

| File | Changes |
|------|---------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Exact-date-only queries for 3 batch methods |
| `bin/validate_feature_sources.py` | Exact-date matching in validation SQL |
| `.claude/skills/model-experiment/SKILL.md` | Merged experiment-tracker queries |
| `.claude/skills/model-health/SKILL.md` | Merged compare-models landscape view |
| 9 orphaned skill `.md` files | Migrated to proper `*/SKILL.md` directories |
