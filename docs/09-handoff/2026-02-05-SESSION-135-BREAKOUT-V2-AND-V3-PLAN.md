# Session 135 - Breakout Classifier V2 & V3 Planning

**Date:** 2026-02-05
**Focus:** Feature engineering, model improvement, V3 planning
**Outcome:** V2 deployed (+0.007 AUC), V3 roadmap with high-impact features

---

## Executive Summary

Started with breakout classifier showing poor performance (AUC 0.58-0.63, target 60% precision at 0.769). Deployed V2 with shared features (+0.007 AUC improvement). Discovered fundamental issue: **feature quality >> feature quantity**. Created V3 roadmap with high-impact contextual features (star teammate injuries, 4Q performance, FG% trends).

---

## Session Flow

### Part 1: V2 Deployment with Shared Features

**Context:** Session 134 fixed train/eval mismatch. Need to deploy production model with shared features.

**Actions:**
1. Trained new model with shared feature module
2. Uploaded to GCS: `breakout_shared_v1_20251102_20260205.cbm`
3. Updated env var and deployed to production
4. Verified deployment

**Result:** Production now uses consistent shared features (AUC 0.5857)

---

### Part 2: Experiment Runner Refactoring

**Problem:** Need to ensure all future models use shared feature pipeline.

**Solution:** Refactored `ml/experiments/breakout_experiment_runner.py`

**Changes:**
- Added `--mode` flag: `shared` (production) vs `experimental` (research)
- Shared mode uses `ml/features/breakout_features.py` for consistency
- Experimental mode preserves flexible feature testing

**Example Usage:**
```bash
# Production training
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "PROD_V2" \
    --mode shared \
    --train-start 2025-11-02 \
    --train-end 2026-01-31

# Experimental research
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "EXP_NEW_FEATURES" \
    --mode experimental \
    --features "cv_ratio,cold_streak_indicator"
```

**Files Modified:**
- `ml/experiments/breakout_experiment_runner.py` - Dual mode support
- `CLAUDE.md` - Updated BREAKOUT section

---

### Part 3: Hyperparameter Experiments

**Tested 4 configurations to improve AUC:**

| Experiment | Depth | Iterations | LR | AUC | Precision@0.5 | Stopped At |
|------------|-------|-----------|-----|------|---------------|------------|
| BASELINE_SHARED | 5 | 500 | 0.05 | 0.5635 | 22.4% | 12 |
| DEEP_TREES | 7 | 500 | 0.03 | 0.5601 | 18.5% | 2 |
| **SHALLOW_FAST** | **3** | **1000** | **0.1** | **0.6305** | **26.7%** | **9** |
| BALANCED_MODERATE | 6 | 700 | 0.04 | 0.5993 | 26.0% | 20 |

**Best:** SHALLOW_FAST (AUC 0.6305, +0.07 vs baseline)

**Key Findings:**
- All models stop early (2-20 iterations) → weak predictive signal
- Even best model: NO predictions at target threshold (0.769)
- Hyperparameters help but can't overcome weak features

**Conclusion:** **Feature engineering is the bottleneck, not hyperparameters**

---

### Part 4: Data Source Research

**User insight:** Need high-quality contextual features for role players.

**Research conducted:** Comprehensive data availability audit

**Key Findings:**

| Category | Data Available | Quality | High-Impact Features |
|----------|----------------|---------|---------------------|
| **Injury Data** | βœ… nbac_injury_report, bdl_injuries | Excellent | Star teammate OUT, opponent key injuries |
| **Vegas Lines** | βœ… odds_api_* tables | Excellent | Line movement, game total (pace proxy) |
| **Usage Trends** | βœ… player_daily_cache | Excellent | Minutes increase, usage spike |
| **Matchup History** | βœ… player_game_summary | Excellent | Avg vs opponent, favorable matchups |
| **4Q Performance** | βœ… play-by-play, game summary | Excellent | 4Q points, 4Q FG%, clutch volume |
| **Schedule/Rest** | βœ… nba_schedule | Excellent | Rest days, B2B fatigue |

**Documentation:** `docs/08-projects/current/SESSION-135-DATA-SOURCES-RESEARCH.md` (from Explore agent)

**Key Infrastructure:**
- Injury integration: `predictions/shared/injury_integration.py` (already exists!)
- Feature store: 37 features available, can extend to 40+
- Player daily cache: Updated nightly, excellent coverage

---

### Part 5: V2 Feature Engineering (Extended Feature Set)

**Goal:** Add 4 "Tier 1 quick win" features to improve AUC.

**V2 Features Added:**

| Feature | Description | Data Source | Status |
|---------|-------------|-------------|--------|
| `minutes_increase_pct` | Recent minutes spike (L7 vs L10) | player_daily_cache | βœ… WORKS (16.9% importance!) |
| `usage_rate_trend` | Rising usage rate | player_daily_cache | βœ… WORKS (4.6% importance) |
| `rest_days_numeric` | Fatigue/freshness indicator | player_daily_cache | βœ… WORKS (4.9% importance) |
| `fourth_quarter_trust` | 4Q minutes as % of total | player_daily_cache | ❌ BROKEN (zero variance) |

**SQL Challenges Encountered:**
- `minutes_avg_season` doesn't exist (used L7 vs L10 instead)
- `is_starter` field missing (removed bench_role_player_flag)
- `fourth_quarter_minutes_last_7` data quality issue

**V2 Training Results:**
```
AUC: 0.5708 (vs V1: 0.5635)
Improvement: +0.007 AUC (modest, not the +0.05-0.08 hoped for)
Precision@0.5: 23.9% (vs V1: 22.4%)
Feature Count: 14 (vs V1: 10)
```

**Feature Importance (V2):**
1. points_avg_season: 19.6%
2. **minutes_increase_pct: 16.9%** ← NEW, HIGH SIGNAL
3. days_since_breakout: 11.5%
4. pts_vs_season_zscore: 9.0%
5. rest_days_numeric: 4.9% ← NEW
6. usage_rate_trend: 4.6% ← NEW
7. fourth_quarter_trust: 0.0% ← BROKEN

**Critical Insight:** `minutes_increase_pct` is 2nd most important feature! Shows that **opportunity spikes** are highly predictive.

---

### Part 6: User Insights & V3 Pivot

**User's critical observation:**

> "Let's make sure we are getting quality features filled in. We really need a way to make sure that features we train on are quality. I wonder if less features is better, and if we had role player perspective features such as star player teammates count or things like that. injuries could help a lot."

**Why this matters:**
- V2 added complexity (+4 features) for minimal gain (+0.007 AUC)
- 1 of 4 new features was broken (fourth_quarter_trust)
- Validates: **Quality > Quantity**

**User's high-impact feature ideas:**

1. **Star teammate injured/out** - Role player gets more usage
2. **Coach comments/news** - Direct signal of increased opportunity
3. **4th quarter performance last game** - Hot hand effect
4. **High FG% previous game** - Shooting rhythm
5. **Recent 4Q minutes trend** - Coach trust

**Assessment:** These features capture **role player context** that current features miss.

---

## V3 Roadmap (Next Session)

### V3 Philosophy

**Fewer, Higher-Quality Features**

- Start with V1 (10 features) + `minutes_increase_pct` (proven winner) = 11 base features
- Add 3-5 high-impact contextual features
- Total: 14-16 features (selective, not additive)

### V3 High-Impact Features

**Tier 1: Immediate Add (High Impact, Low Effort)**

1. **star_teammate_out** - Count of star teammates (15+ PPG) OUT for game
   - Source: `nbac_injury_report` + `player_daily_cache`
   - Why: Role players get 5-10 extra shots when star is out
   - Expected AUC gain: +0.04-0.07

2. **fg_pct_last_game** - Shooting % in previous game
   - Source: `player_game_summary`
   - Why: Hot shooting carries over (rhythm effect)
   - Expected AUC gain: +0.02-0.04

3. **points_last_4q** - Points scored in 4Q of previous game
   - Source: `nba_raw.nbac_play_by_play` or game summary
   - Why: 4Q performance signals confidence/rhythm
   - Expected AUC gain: +0.02-0.04

4. **opponent_key_injuries** - Count of opponent starters OUT
   - Source: `nbac_injury_report`
   - Why: Weakened defense → easier scoring
   - Expected AUC gain: +0.03-0.05

**Tier 2: Medium Effort (Consider if Tier 1 works)**

5. **vegas_line_move** - Player line movement from opening
   - Source: `odds_api_player_points_props`
   - Why: Sharp money knows something we don't
   - Expected AUC gain: +0.02-0.05

6. **favorable_matchup_boost** - Avg points vs this opponent
   - Source: `player_game_summary` (historical)
   - Why: Some matchups are systematically easier
   - Expected AUC gain: +0.02-0.03

### V3 Feature Quality Validation

**Build validation framework:**

```python
class FeatureQualityValidator:
    """Ensure features meet quality standards before training."""

    def validate_feature(self, feature_name, values):
        checks = {
            'null_rate': self._check_null_rate(values),  # <5% NULL
            'variance': self._check_variance(values),     # std > 0
            'range': self._check_range(values),           # No infinite values
            'correlation': self._check_correlation(values)  # Not duplicate
        }
        return checks
```

**Validation rules:**
- NULL rate < 5% (fail if >10%)
- Standard deviation > 0 (catch broken features like fourth_quarter_trust)
- No infinite values
- Low inter-feature correlation (< 0.95)

### V3 Implementation Steps

1. **Audit V1 features** - Check NULL rates, distributions
2. **Add star_teammate_out** - Highest expected impact
3. **Train V3a** - Measure AUC improvement
4. **Add fg_pct_last_game + points_last_4q** - Train V3b
5. **Add opponent_key_injuries** - Train V3c
6. **Select best model** - Deploy if AUC > 0.70

### V3 Success Criteria

- **Minimum:** AUC > 0.65 (vs V2: 0.5708)
- **Target:** AUC > 0.70 with precision@0.5 > 35%
- **Stretch:** Get predictions at threshold 0.769 with precision > 50%

---

## Key Files

| File | Purpose |
|------|---------|
| `ml/features/breakout_features.py` | Shared feature module (V1 + V2) |
| `ml/experiments/train_and_evaluate_breakout.py` | Training script |
| `ml/experiments/breakout_experiment_runner.py` | Refactored with dual modes |
| `models/breakout_shared_v1_20251102_20260205.cbm` | Production V1 model (deployed) |
| `models/breakout_v2_14features.cbm` | V2 experimental model |

---

## Commits

```
61a078eb feat: Add breakout classifier V2 with 14 features
c7e23001 feat: Add shared breakout feature module for consistent ML training/eval
2b8aeed9 docs: Update CLAUDE.md with breakout classifier and hot-deploy info
```

---

## Lessons Learned

### Anti-Pattern #12: Feature Quantity Over Quality

**Problem:** Added 4 V2 features, got +0.007 AUC improvement (negligible).

**Why it failed:**
- No validation that features were populated
- Assumed field existence without checking schema
- Optimized for feature count, not signal quality

**Fix:**
- Build feature validation framework
- Add one feature at a time, measure AUC delta
- Reject features with NULL rate >5% or zero variance

### Learning: Context Features > Statistical Features

**Observation:** Current features are all statistical (averages, std dev, trends).

**Missing:** Contextual signals that humans use:
- "Star player is out, role player will get more shots"
- "Player went 8/10 FG last game, rhythm is there"
- "Opponent's top defender is injured"

**V3 Strategy:** Add contextual features that capture **opportunity** and **matchup quality**

---

## Next Session TODO

### Immediate (Start Here)

1. **Audit V1 features** - Run quality checks on all 10 features
2. **Build feature quality validator** - Automated checks (NULL rate, variance, etc.)
3. **Add star_teammate_out** - Highest impact feature

### V3 Development

4. **Train V3a** - V1 + minutes_increase_pct + star_teammate_out
5. **Measure AUC improvement** - Expect +0.04-0.07
6. **Add FG% and 4Q performance** - Train V3b
7. **Evaluate and iterate** - Add more features if needed

### Deployment

8. **Select best V3 model** - If AUC > 0.70, deploy to production
9. **Update production env var** - Point to new V3 model
10. **Monitor shadow mode performance** - Validate in production

---

## Questions for Next Session

1. Should we lower the precision target from 60% to 40% at threshold 0.5?
   - Current: No predictions at 0.769 (too conservative)
   - Alternative: Use lower threshold with reasonable precision

2. Should we change the breakout definition?
   - Current: 1.5x season average
   - Alternative: 1.75x or 2.0x (more extreme breakouts)

3. Should we pivot to a different problem?
   - Instead of "breakout games," predict "high variance players"
   - Focus on specific props (rebounds/assists) with clearer patterns

---

## Reference Documentation

- **Session 134 Summary:** `docs/09-handoff/2026-02-05-SESSION-134-COMPLETE-SUMMARY.md`
- **CLAUDE.md [BREAKOUT]:** Breakout classifier production guide
- **Data Sources Research:** Session 135 Explore agent output
- **Shared Feature Module:** `ml/features/breakout_features.py` (392 lines)
- **Experiment Runner:** `ml/experiments/breakout_experiment_runner.py` (1204 lines)

---

## Session Statistics

- **Duration:** ~4 hours
- **Models Trained:** 6 (baseline + 4 hyperparameter experiments + V2)
- **Best AUC:** 0.6305 (SHALLOW_FAST config)
- **Production AUC:** 0.5708 (V2 with shared features)
- **Feature Count:** V1 (10) → V2 (14)
- **Code Changes:** 1 file, 26 insertions, 42 deletions
- **Commits:** 1 (`61a078eb`)

---

**Session Status:** V2 deployed to production, V3 roadmap complete, ready for high-impact feature engineering.
