# Session 375 Handoff — Feature Store Backfill + Distribution Health Validation

**Date:** 2026-03-01
**Commits:** `7ed7a21b`
**Status:** Committed and pushed. Auto-deploy in progress.

## What Was Done

### P1: Feature 41/42 Backfill (COMPLETE)

Feature 41 (spread_magnitude) was ALL ZEROS for the entire season (Nov 4, 2025 - Feb 28, 2026). Root cause: `odds_api_game_lines` stores both sides of each spread (+4.0 and -4.0), and the median query without filtering always returned 0.

**Backfill executed:**
- `ml_feature_store_v2`: 23,245 rows updated with correct Feature 41/42 values
- `upcoming_player_game_context`: 27,618 rows updated with correct `game_spread`
- Zero Feature 41 = 0 rows remaining
- Backfill script: `backfill_jobs/feature_store/fix_spread_features.py`

### P1b: Distribution Health Validation (COMPLETE)

Built comprehensive validation to prevent this class of bug ("plausible but wrong" values):

1. **`bin/validation/feature_distribution_health.py`** — CLI tool that audits all 57 features for:
   - Constant-value bugs (stddev + distinct count thresholds)
   - Zero-rate anomalies (>threshold% zeros)
   - NULL-rate anomalies
   - Distribution drift (mean shifted >3 sigma vs baseline)
   - Source cross-validation (raw table comparison for features 25, 41)
   - Tested PASS on live data

2. **`FEATURE_VARIANCE_THRESHOLDS` expanded 10 → 20 features** in `ml_feature_store_processor.py`:
   - Added Feature 41, 42, 38, 43, 47, 48, 13, 14, 32, 3
   - These run at write-time and would have caught the F41 bug immediately
   - Fixed Feature 47 range from (0,0) → (0,100) — it's NOT dead (avg=44)

3. **Three skills updated:**
   - `spot-check-features`: Added "Distribution Health Audit" section
   - `validate-feature-drift`: Rewrote ALL deprecated `features[OFFSET(N)]` → `feature_N_value`, added Check 3B (constant-value detection), expanded monitored features from 5 → 11
   - `validate-daily`: Added Phase 0.493

## What Still Needs Doing (Priority Order)

### P2: Urgent Retrain
All models are BLOCKED/degrading. Now that Feature 41/42 has real data, retrain will let the model learn from actual spread information.
- **Window:** 49 days (Jan 10 - Feb 27), V12_NOVEG, vw015
- **Command:** `PYTHONPATH=. python ml/experiments/quick_retrain.py --feature-set v12_noveg --category-weight vegas=0.15 --training-start 2026-01-10 --training-end 2026-02-27`
- Feature 41/42 now has real values — first time model can learn from spread data

### P3: Monitor New Signals in Production
Session 374/374b signals should be firing. Verify with:
```sql
SELECT signal_name, COUNT(*) as fires
FROM `nba-props-platform.nba_predictions.pick_signal_tags`,
UNNEST(signal_tags) as signal_name
WHERE game_date >= '2026-02-28'
GROUP BY signal_name ORDER BY fires DESC
```
Expected new signals: `fast_pace_over`, `volatile_scoring_over`, `low_line_over`, `line_rising_over`

### P4: Fleet Triage
Models to kill (from Session 374b strategy analysis):
- `catboost_v12_q43_train1225_0205` (33.3% edge 5+ HR)
- `catboost_v12_noveg_q57_train1225_0209` (25.0% HR N=4)
- `catboost_v12_train1225_0205` (40.9% HR N=22)

Models to watch:
- `catboost_v9_low_vegas_train0106_0205` — best UNDER model (59.6% HR N=47)
- `catboost_v9_50f_noveg_train1225_0205` — 61.5% HR (N=13), needs more data

### P5: Experiment Ideas (Not Previously Tried)
1. **Direction-specific models** — Separate OVER/UNDER regression models
2. **Dynamic edge threshold by model age** — `edge >= 3 + 0.5 * weeks_since_training`
3. **Post-All-Star-Break regime training** — Train exclusively on post-ASB data
4. **Ensemble of time windows** — Average predictions from 35d/49d/63d models
5. **Line-level segmentation** — Different edge floors for low (<15) vs high (25+) lines

## Deployment Status
- Push auto-deploys `nba-phase4-precompute-processors` (expanded variance thresholds)
- Run `./bin/check-deployment-drift.sh --verbose` to verify
- `prediction-coordinator` may need manual deploy if signal changes aren't in its trigger path

## Files Changed
```
backfill_jobs/feature_store/fix_spread_features.py  — NEW: F41/42 backfill script
bin/validation/feature_distribution_health.py       — NEW: Distribution health CLI
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py — Expanded thresholds
ml/experiments/quick_retrain.py                     — Minor updates
.claude/skills/spot-check-features/SKILL.md         — Distribution audit section
.claude/skills/validate-daily/SKILL.md              — Phase 0.493
.claude/skills/validate-feature-drift/SKILL.md      — Full rewrite (deprecated queries fixed)
```
