# Session 156 Handoff: Eliminate Non-Vegas Feature Defaults + Training Data Quality

**Date:** 2026-02-07
**Focus:** Feature store coverage, cache fallback completion, training data contamination fix

## What Was Done

### Problem Statement
The ML feature store had non-vegas defaults for ~57% of predicted players (only 43.3% fully complete). Zero-tolerance policy (Session 141) correctly blocks predictions for these players, but:
1. Coverage dropped from ~208 to ~76 predictions per game day
2. Incomplete feature store records were contaminating training data
3. Players returning from long injury got records with 7+ defaults — garbage data

### Root Causes Identified
1. `PlayerDailyCacheProcessor` only caches ~150-200 players with TODAY's games — players on rosters who are inactive/questionable were missed
2. Session 144 cache miss fallback (`_compute_cache_fields_from_games`) only filled 10 of 25+ fields
3. `_batch_extract_minutes_ppm()` had no fallback when its independent lookup missed a player
4. Feature store created records for players with zero recent game history (returning from 3+ month injury)
5. **Training data contamination**: Breakout classifier had ZERO quality filters on `ml_feature_store_v2` joins. CatBoost training lacked `required_default_count` filter.

### Changes Made (8 files, 194+ additions)

#### Layer 1: Better Data (prevent defaults from being created)

| File | Change |
|------|--------|
| `feature_extractor.py` | Expanded `_batch_extract_last_10_games` query to include `usage_rate`, `assisted_fg_makes`, `fg_makes`, `team_abbr` |
| `feature_extractor.py` | Completed `_compute_cache_fields_from_games` with ALL missing fields: `games_in_last_14_days`, `minutes_in_last_7/14_days`, `back_to_backs_last_14_days`, `assisted_rate_last_10`, `ppm_avg_last_10`, `player_usage_rate_season` |
| `ml_feature_store_processor.py` | Features 31-32 (minutes/PPM) now fall back to phase4_data cache values instead of hardcoded defaults |
| `ml_feature_store_processor.py` | Tightened player filter: requires `_last_10_games_lookup` (games in 60-day window). Players with no recent games get NO feature store record. |
| `player_daily_cache_processor.py` | Expanded player selection via UNION to include ALL rostered players on teams with games today |

#### Layer 2: Clean Training Data (prevent contaminated records from being used)

| File | Change |
|------|--------|
| `quick_retrain.py` | Added `required_default_count = 0` to training AND eval queries |
| `breakout_features.py` | Added `required_default_count = 0` AND `feature_quality_score >= 70` to LEFT JOIN |
| `backfill_breakout_shadow.py` | Added same quality gate to LEFT JOIN |
| `breakout_experiment_runner.py` | Added same quality gate to WHERE clause |
| `train_breakout_classifier.py` | Added same quality gate to WHERE clause |

#### Layer 3: Skill & Documentation

| File | Change |
|------|--------|
| `.claude/skills/model-experiment/SKILL.md` | Updated Data Quality Filtering section with zero-tolerance training requirements |

### How Returning-From-Injury Players Are Now Handled

This was a key design decision discussed during the session:

| Stage | What Happens | Why |
|-------|-------------|-----|
| Still injured (no games) | Not in `upcoming_player_game_context` | Normal — not expected to play |
| Return game (0 games in 60-day window) | **No feature store record created** | No meaningful recent features to compute. Would be 7+ defaults. |
| 1-2 games back | Feature store record created. Cache fallback computes features. Some may still default → blocked by quality gate. | Building up history |
| 3-5 games back | Enough history → `required_default_count = 0` → predictions start flowing | Full features available |

This is effectively a **per-player bootstrap period**. The daily cache expansion (Step 3) ensures the cache is ready immediately when they play, so the system ramps up quickly.

### Vegas Feature Exception (Preserved)

Features 25-27 (vegas_points_line, vegas_opening_line, vegas_line_move) remain in `OPTIONAL_FEATURES = {25, 26, 27}` per Session 145. Their absence:
- IS counted in `default_feature_count` (total, for visibility)
- Is NOT counted in `required_default_count` (gating)
- Does NOT block predictions
- Does NOT block training data inclusion

Feature 28 (`has_vegas_line`) is always `calculated` (0.0 or 1.0), never defaults.

## What Was NOT Done

### 1. Historical Backfill of Feature Store Records
The improved fallback will produce better features when re-run, but we did NOT backfill historical dates. This should be done for Jan-Feb 2026 (training data for future V10).

### 2. Historical Training Data Contamination Assessment
A diagnostic SQL script was written to `/tmp/.../scratchpad/check_training_contamination.sql` but NOT executed. The next session should run these queries to understand:
- How many records in Nov 2025 - Feb 2026 have `required_default_count > 0`?
- How many of those passed the old `feature_quality_score >= 70` filter (i.e., were in training)?
- Which features are most commonly defaulted?
- Whether the current V9 model was trained on contaminated data and needs retraining

### 3. Legacy Training Script Cleanup
There are 20+ training scripts in `ml/` and `ml/experiments/` that query `ml_feature_store_v2`. Only the 5 actively-used ones were updated. The legacy scripts (train_xgboost_v6.py, train_ensemble_v2_meta_learner.py, etc.) still lack quality filters. These should be:
- Archived or deleted if no longer used
- Updated with quality filters if still referenced
- Potentially consolidated into a shared base class for data loading

### 4. Model Retraining
If contamination assessment shows significant training data pollution, V9 should be retrained with the clean filters.

## Diagnostic Queries to Run

```sql
-- Quick check: contamination rate in training window
SELECT
  COUNT(*) as total,
  COUNTIF(COALESCE(required_default_count, default_feature_count, 0) = 0) as clean,
  COUNTIF(COALESCE(required_default_count, default_feature_count, 0) > 0) as contaminated,
  ROUND(100.0 * COUNTIF(COALESCE(required_default_count, default_feature_count, 0) > 0) / COUNT(*), 1) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2025-11-02' AND '2026-02-06'
  AND feature_count >= 33
  AND data_source NOT IN ('phase4_partial', 'early_season')
  AND feature_quality_score >= 70;

-- Records that WERE in training but SHOULDN'T have been
SELECT
  COUNTIF(
    feature_quality_score >= 70
    AND COALESCE(required_default_count, default_feature_count, 0) > 0
  ) as contaminated_in_training
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2025-11-02' AND '2026-02-06'
  AND feature_count >= 33
  AND data_source NOT IN ('phase4_partial', 'early_season');
```

## Next Session Priorities

1. **Run contamination queries** — Understand the scope of the problem
2. **Decide on V9 retrain** — If >5% contamination in training data, retrain with clean filters
3. **Backfill feature store** — Re-run ML feature store processor for Jan-Feb 2026 dates
4. **Legacy script cleanup** — Archive unused training scripts, consider shared data loading base class
5. **Deploy changes** — Push to main (auto-deploy triggers). Monitor cache miss rates and default counts in Slack.

## Files Modified

```
data_processors/precompute/ml_feature_store/feature_extractor.py
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
ml/experiments/quick_retrain.py
ml/experiments/backfill_breakout_shadow.py
ml/experiments/breakout_experiment_runner.py
ml/experiments/train_breakout_classifier.py
ml/features/breakout_features.py
.claude/skills/model-experiment/SKILL.md
```

## Key Design Decisions

1. **Require `_last_10_games_lookup` not just `_season_stats_lookup`** — Season-only stats from 3 games in October are meaningless when making February predictions. The 60-day lookback window is the correct signal for "this player has recent game data."

2. **LEFT JOIN quality filters on breakout training** — Added conditions directly to the LEFT JOIN's ON clause (`AND COALESCE(mf.required_default_count, ...) = 0`). This means records without a clean feature store match get NULL features (which the breakout code already handles with defaults). This is safer than an INNER JOIN which would drop valid games that just lack feature store data.

3. **COALESCE for backwards compatibility** — `COALESCE(mf.required_default_count, mf.default_feature_count, 0)` handles records from before Session 141 when `required_default_count` didn't exist, and records from before Session 145 when it was added.

4. **No feature store records > No bad feature store records** — It's better to have no record for a returning-from-injury player than to have a record full of defaults that could contaminate training data or inflate metrics.
