# Session 157 Prompt

Copy everything below this line into a new chat:

---

START, then read `docs/09-handoff/2026-02-07-SESSION-156-HANDOFF.md` for full context.

## Session 156 Summary

We made changes across 9 files (not yet committed/pushed) to eliminate non-vegas feature defaults and fix training data contamination. The changes fall into three layers:

**Layer 1 — Better data (prevent defaults):**
- Completed the cache miss fallback in `feature_extractor.py` — now computes ALL 25+ fields from `last_10_games` data when daily cache misses a player
- Features 31-32 (minutes/PPM, 25% combined model importance) now fall back to cache-computed values instead of hardcoded defaults
- Expanded daily cache player selection to include all rostered players on game-day teams
- Tightened feature store filter: players must have games in the 60-day lookback window (not just season stats). Returning-from-injury players with zero recent games get NO feature store record — they naturally re-enter after 3-5 games back (per-player bootstrap period).

**Layer 2 — Clean training data (prevent contamination):**
- Added `COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0` to ALL 5 active training scripts (quick_retrain.py, breakout_features.py, backfill_breakout_shadow.py, breakout_experiment_runner.py, train_breakout_classifier.py)
- Previously: CatBoost had `feature_quality_score >= 70` but no default filter. Breakout classifier had ZERO quality filters on ml_feature_store_v2 joins.
- Only vegas features (25-27) are allowed to be missing — they're excluded from `required_default_count` via OPTIONAL_FEATURES.

**Layer 3 — Docs/skill updated:**
- `.claude/skills/model-experiment/SKILL.md` updated with zero-tolerance training requirements

## What needs to happen this session

### 1. Commit and push Session 156 changes
Review the diff (`git diff --stat` shows 9 files, 215 additions), commit, and push to main. This triggers auto-deploy for the data processor services.

### 2. Run contamination diagnostic queries
Check if the current V9 model was trained on contaminated data:
```sql
-- How many records in training window have non-vegas defaults?
SELECT
  COUNT(*) as total,
  COUNTIF(COALESCE(required_default_count, default_feature_count, 0) = 0) as clean,
  COUNTIF(COALESCE(required_default_count, default_feature_count, 0) > 0) as contaminated,
  ROUND(100.0 * COUNTIF(COALESCE(required_default_count, default_feature_count, 0) > 0) / COUNT(*), 1) as contamination_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2025-11-02' AND '2026-02-06'
  AND feature_count >= 33
  AND data_source NOT IN ('phase4_partial', 'early_season')
  AND feature_quality_score >= 70;
```
If >5% contamination, V9 should be retrained with the new clean filters.

### 3. Decide on V9 retrain
If contaminated, use: `PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V9_CLEAN_RETRAIN" --train-start 2025-11-02 --train-end 2026-02-06`

### 4. Legacy training script cleanup
There are 20+ training scripts in `ml/` and `ml/experiments/` that query `ml_feature_store_v2` without quality filters. Many are from V6/V7/V8 era. Assess:
- Which are still used? (quick_retrain.py, breakout_*.py, evaluate_model.py, train_walkforward.py are active)
- Archive the rest or add quality filters
- Consider a shared base class or utility function for data loading with quality filters built in, so this class of bug can't recur

### 5. Feature store backfill (optional)
Re-run ML feature store processor for recent dates to produce cleaner records with the improved fallback:
```bash
# Pseudocode — use the actual backfill mechanism
for game_date in dates_with_high_defaults:
    ml_feature_store_processor.process(game_date, mode='backfill')
```
