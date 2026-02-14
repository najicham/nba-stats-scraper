# Shooting Efficiency Features - V13 Proposal

## Executive Summary

**Proposal:** Add 6 new shooting efficiency features to V13 feature store

**Rationale:**
- Field goal percentage (FG%) and three-point percentage (3PT%) are available in raw data but NOT in ML features
- Analysis shows shooting efficiency has strong CONTINUATION signal (cold shooting predicts continued cold performance)
- Complements V12 streak features which already capture continuation effects
- Provides TRUE performance quality indicator independent of shot volume

**Impact:**
- Expected to improve model accuracy for players in shooting slumps/hot streaks
- Addresses blind spot in current feature set (we have shot LOCATION but not shot EFFICIENCY)
- Natural complement to existing V12 features: `prop_under_streak`, `consecutive_games_below_avg`, `scoring_trend_slope`

---

## Background: The Mean Reversion Analysis

### Theory Tested
"Players with 2+ consecutive low FG% games are due for a bounce-back" (common betting wisdom)

### Results (2025-11-01 to 2026-02-12, N=11,020 games)

| Scenario | Games | Avg FG% | vs Baseline |
|----------|-------|---------|-------------|
| **All Games (5+ FGA)** | 11,020 | **47.0%** | — |
| **After Avg FG% < 40% in Last 2** | 2,784 | **44.4%** | **-2.6pp** |

**Finding:** Cold shooting CONTINUES rather than reverting to mean (-2.6 percentage points worse than baseline)

### Why This Matters

**FG% is a better performance indicator than points alone:**
- ✅ 20 points on 8/12 shooting (67% FG%) = Efficient, in rhythm
- ❌ 20 points on 5/20 shooting (25% FG%) = Inefficient, forcing shots
- Both score 20 points, but very different underlying performance

**Continuation effect is real and predictive:**
- Low FG% → Continued low FG% (not mean reversion)
- This aligns with "hot hand" / "cold hand" research
- Captures player state that points alone miss

---

## Current Feature Set Gaps

### What We Have (V9/V12)

**Points-Based Features:**
- `points_avg_last_5`, `points_avg_last_10`, `points_avg_season`
- `points_avg_last_3` (V12)
- `scoring_trend_slope` (V12)
- `deviation_from_avg_last3` (V12)

**Shot Location Percentages:**
- `pct_paint`, `pct_mid_range`, `pct_three`, `pct_free_throw`
- These show WHERE players shoot, not HOW WELL they shoot

**Streak Features (V12 only):**
- `prop_over_streak`, `prop_under_streak`
- `consecutive_games_below_avg`

### What We're Missing

**Shooting Efficiency:**
- ❌ No field goal percentage (FG%)
- ❌ No three-point percentage (3PT%)
- ❌ No shooting efficiency trends
- ❌ No cold/hot streak indicators

**This is a blind spot:** We know WHERE players shoot and HOW MUCH they score, but not HOW EFFICIENTLY they're scoring.

---

## Proposed V13 Features

### Feature List

| Feature Name | Description | Computation | Expected Signal |
|--------------|-------------|-------------|-----------------|
| `fg_pct_last_3` | Field goal % average (last 3 games) | AVG(FG%) over 3 games | Recent shooting efficiency |
| `fg_pct_last_5` | Field goal % average (last 5 games) | AVG(FG%) over 5 games | Short-term trend |
| `fg_pct_vs_season_avg` | Deviation from season FG% | (recent_fg_pct - season_fg_pct) | Hot/cold indicator |
| `three_pct_last_3` | Three-point % average (last 3 games) | AVG(3PT%) over 3 games | Outside shooting state |
| `three_pct_last_5` | Three-point % average (last 5 games) | AVG(3PT%) over 5 games | 3PT trend |
| `fg_cold_streak` | Consecutive games below 40% FG% | Counter resets at > 40% | Cold shooting persistence |

### Data Source

**Available in:** `nba_raw.nbac_gamebook_player_stats`

```sql
-- Already collected and available
SELECT
  player_name,
  game_date,
  field_goal_percentage,      -- e.g., 0.476 (47.6%)
  three_point_percentage,     -- e.g., 0.333 (33.3%)
  field_goals_attempted,      -- For volume filter
  three_pointers_attempted    -- For 3PT reliability
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= '2025-11-01';
```

**No new data collection needed** — this is transformation only.

---

## Implementation Details

### Phase 4 Processor: `shooting_efficiency_processor.py`

**Location:** `data_processors/precompute/shooting_efficiency/`

**Pseudocode:**
```python
def compute_shooting_efficiency_features(player_id, game_date):
    """Compute shooting efficiency features for a player-game."""

    # Get last N games with 5+ FGA (quality filter)
    recent_games = get_recent_games(
        player_id=player_id,
        end_date=game_date,
        min_fga=5,
        limit=10
    )

    # FG% averages
    fg_pct_last_3 = mean([g.field_goal_percentage for g in recent_games[:3]])
    fg_pct_last_5 = mean([g.field_goal_percentage for g in recent_games[:5]])

    # Season baseline (20-game rolling average)
    season_games = get_recent_games(player_id, game_date, min_fga=5, limit=20)
    fg_pct_season = mean([g.field_goal_percentage for g in season_games])

    # Deviation from season avg
    fg_pct_vs_season_avg = fg_pct_last_3 - fg_pct_season

    # Three-point percentages (filter games with 2+ 3PA)
    three_pt_games = [g for g in recent_games if g.three_pointers_attempted >= 2]
    three_pct_last_3 = mean([g.three_point_percentage for g in three_pt_games[:3]])
    three_pct_last_5 = mean([g.three_point_percentage for g in three_pt_games[:5]])

    # Cold streak counter
    fg_cold_streak = 0
    for game in reversed(recent_games):
        if game.field_goal_percentage < 0.40:
            fg_cold_streak += 1
        else:
            break  # Streak ended

    return {
        'fg_pct_last_3': fg_pct_last_3,
        'fg_pct_last_5': fg_pct_last_5,
        'fg_pct_vs_season_avg': fg_pct_vs_season_avg,
        'three_pct_last_3': three_pct_last_3,
        'three_pct_last_5': three_pct_last_5,
        'fg_cold_streak': fg_cold_streak,
    }
```

### Quality Filters

**Minimum shot attempts:**
- FG% features: Require 5+ FGA in game (excludes garbage time, DNPs)
- 3PT% features: Require 2+ 3PA in game (excludes non-shooters)

**Missing data handling:**
- If < 3 qualifying games available → Use NaN (CatBoost handles natively)
- Never use defaults for shooting % (zero-tolerance principle)

---

## Relationship to V12 Streak Features

### V12 Features (Already Implemented)

1. **`prop_over_streak`** — Consecutive games over prop line
2. **`prop_under_streak`** — Consecutive games under prop line
3. **`consecutive_games_below_avg`** — Games below season points average
4. **`scoring_trend_slope`** — OLS slope of last 7 games (points)
5. **`deviation_from_avg_last3`** — Z-score of L3 vs season avg

### How New FG% Features Complement V12

| V12 Feature | New FG% Feature | Complementary Signal |
|-------------|-----------------|----------------------|
| `consecutive_games_below_avg` | `fg_cold_streak` | Points below avg + Shooting below avg = STRONG cold signal |
| `prop_under_streak` | `fg_pct_last_3` | Consecutive unders + Low FG% = Continuation signal |
| `scoring_trend_slope` | `fg_pct_vs_season_avg` | Points trending down + FG% trending down = True slump |
| `deviation_from_avg_last3` | `fg_pct_last_3` | Low recent points + Low FG% = Quality not volume issue |

### Expected Interactions

**Cold Shooting + Under Streak = STRONG UNDER Signal:**
```python
if fg_pct_last_3 < 0.40 and prop_under_streak >= 2:
    # Player in true slump (efficiency + results)
    # Model should predict UNDER with higher confidence
```

**Low Points + Good FG% = Volume Issue (Not Quality):**
```python
if points_avg_last_3 < points_avg_season and fg_pct_last_3 > fg_pct_season:
    # Player shooting well but getting fewer shots
    # Could bounce back if usage increases
```

**High Points + Low FG% = Unsustainable (Bet UNDER):**
```python
if points_avg_last_3 > points_avg_season and fg_pct_last_3 < 0.40:
    # High volume but poor efficiency
    # Likely regression to lower scoring
```

---

## Expected Model Impact

### Hypothesis 1: Improved Accuracy for Players in Slumps

**Current Limitation:**
- Model sees `points_avg_last_3 = 18.5` and `points_avg_season = 22.0`
- But doesn't know if low scoring is due to:
  - Poor shot-making (FG% = 35%) → Real slump, likely continues
  - Fewer shot attempts (FG% = 52%) → Volume issue, could bounce back

**With FG% Features:**
- Model can distinguish quality vs. quantity
- Better predictions for players in shooting slumps
- Reduced false positives on "bounce-back" games

### Hypothesis 2: Better Continuation Signal Detection

**Analysis Finding:** FG% < 40% in last 2 games → Next game FG% = 44.4% (vs 47.0% baseline)

**Model Can Now Learn:**
- Low `fg_pct_last_3` → Predict lower scoring (continuation)
- High `fg_pct_last_3` → Predict higher scoring (hot hand)
- Interaction with `prop_under_streak` for compound signal

### Hypothesis 3: Improved Edge Calibration

**Current Edge Calculation:**
```python
edge = abs(predicted_points - vegas_line)
```

**With FG% Features:**
- Model has better signal for TRUE player state
- Should reduce prediction errors for players in extreme states (very hot/cold)
- Could improve high-edge (5+) hit rate by reducing false confidence

---

## Validation Plan

### Phase 1: Historical Backtest (Pre-Deployment)

**Test Dataset:** 2025-11-01 to 2026-02-12 (full season to date)

**Metrics:**
1. **Overall MAE** — Should maintain or improve vs V12
2. **Edge 3+ Hit Rate** — Target >= 65% (current V9 champion decayed to 39.9%)
3. **Edge 5+ Hit Rate** — Target >= 70%
4. **Bias Check** — `pred_vs_vegas` within +/- 1.5 points
5. **Cold Shooter Accuracy** — MAE for players with `fg_pct_last_3 < 0.40`

**SQL Query for Validation:**
```sql
-- Compare V13 predictions to V12 on cold shooters
WITH cold_shooters AS (
  SELECT
    game_date,
    player_id,
    -- Compute FG% last 3 (what V13 would see)
    AVG(field_goal_percentage) OVER (
      PARTITION BY player_id
      ORDER BY game_date
      ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
    ) as fg_pct_last_3
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE field_goals_attempted >= 5
)
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(CASE WHEN hit THEN 1.0 ELSE 0.0 END) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
INNER JOIN cold_shooters cs
  ON pa.player_id = cs.player_id
  AND pa.game_date = cs.game_date
WHERE cs.fg_pct_last_3 < 0.40
  AND pa.game_date BETWEEN '2026-01-01' AND '2026-02-12'
GROUP BY 1;
```

### Phase 2: Shadow Testing (2+ days)

**Deploy V13 in shadow mode alongside V12:**
- Both models make predictions
- Compare performance on same games
- Monitor feature quality (% with valid FG% values)

**Key Metrics:**
- Feature completeness: `fg_pct_last_3` should be non-null for 80%+ of predictions
- Distribution check: FG% values should be realistic (25-65% range)
- No systematic bias vs V12

### Phase 3: Production Promotion (If Passing)

**Governance Gates (from CLAUDE.md):**
1. ✅ Duplicate check (different training dates from V12)
2. ✅ Vegas bias within +/- 1.5 points
3. ✅ High-edge (3+) hit rate >= 60%
4. ✅ Sample size >= 50 graded edge 3+ bets
5. ✅ No critical tier bias
6. ✅ MAE improvement vs baseline

**Only promote after ALL gates pass + user approval.**

---

## Feature Engineering Best Practices

### 1. Consistency Across Train/Eval

**CRITICAL:** Use same computation logic for training and prediction.

```python
# ✅ CORRECT - Use shared module
from ml.features.shooting_efficiency import compute_shooting_features

# Training
train_features = compute_shooting_features(train_data)

# Prediction
pred_features = compute_shooting_features(game_data)
```

```python
# ❌ WRONG - Different logic
# Training: uses all games
# Prediction: uses only 5+ FGA games
# Result: Train/eval mismatch → poor holdout performance
```

### 2. Handle Missing Data Properly

**Use NaN for missing data, not defaults:**
```python
# ✅ CORRECT
if len(recent_games) < 3:
    fg_pct_last_3 = np.nan  # CatBoost handles natively

# ❌ WRONG
if len(recent_games) < 3:
    fg_pct_last_3 = 0.45  # League average
    # This fabricates data and violates zero-tolerance
```

### 3. Quality Filters

**Apply consistent minimum thresholds:**
- FG%: Require 5+ FGA (filters garbage time)
- 3PT%: Require 2+ 3PA (filters non-shooters)
- Season baseline: Use 20-game rolling average (not full season)

### 4. Feature Store Schema

**Add to `ml_feature_store_v2` (extends to 60 features):**

```sql
-- New columns
fg_pct_last_3 FLOAT64,
fg_pct_last_5 FLOAT64,
fg_pct_vs_season_avg FLOAT64,
three_pct_last_3 FLOAT64,
three_pct_last_5 FLOAT64,
fg_cold_streak INT64,

-- Quality tracking
fg_pct_last_3_source STRING,  -- 'computed', 'insufficient_data', 'default'
fg_pct_last_3_quality FLOAT64  -- 0-100 quality score
```

---

## Alternative Approaches Considered

### Option A: Add FG% to V12 (Incremental Update)

**Pros:**
- Smaller change, faster to deploy
- Can validate on existing V12 infrastructure

**Cons:**
- V12 is still in shadow (not production)
- Disrupts ongoing V12 validation
- Better to bundle into V13 with other improvements

**Decision:** Create V13 with full feature set

### Option B: Use True Shooting % (TS%) Instead

**True Shooting %:** Accounts for FT value: `TS% = PTS / (2 * (FGA + 0.44 * FTA))`

**Pros:**
- More comprehensive efficiency metric
- Used by NBA analytics professionals

**Cons:**
- More complex to compute
- Harder to interpret (what's "good" TS%?)
- FG% is more intuitive and directly observable

**Decision:** Start with FG% and 3PT% (simpler, more interpretable)

### Option C: Effective FG% (eFG%)

**Effective FG%:** Adjusts for 3PT value: `eFG% = (FGM + 0.5 * 3PM) / FGA`

**Pros:**
- Weights three-pointers appropriately
- Single metric vs. separate FG% and 3PT%

**Cons:**
- Loses information (can't distinguish 2PT vs 3PT efficiency)
- Model can learn this interaction from separate features

**Decision:** Use separate FG% and 3PT% (more granular signal)

---

## Risk Assessment

### Risk 1: Feature Quality Issues

**Risk:** FG% data missing or incorrect in raw data

**Mitigation:**
- Validate source data quality before implementation
- Add quality scores: `fg_pct_last_3_quality` (0-100)
- Monitor feature completeness in production

**Validation Query:**
```sql
-- Check FG% data completeness
SELECT
  game_date,
  COUNT(*) as total_players,
  COUNTIF(field_goal_percentage IS NOT NULL) as with_fg_pct,
  ROUND(COUNTIF(field_goal_percentage IS NOT NULL) / COUNT(*) * 100, 1) as pct_complete
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= CURRENT_DATE() - 30
  AND field_goals_attempted > 0
GROUP BY 1
ORDER BY 1 DESC;
```

### Risk 2: Train/Eval Mismatch

**Risk:** Different FG% computation in training vs prediction

**Mitigation:**
- Use shared feature module (e.g., `ml/features/shooting_efficiency.py`)
- Unit tests for feature computation
- Integration tests comparing train vs predict outputs

### Risk 3: Multicollinearity

**Risk:** FG% features correlated with existing points features

**Mitigation:**
- Check correlation matrix in training
- CatBoost handles correlated features well (tree-based)
- Monitor feature importance to validate independent signal

**Expected Correlations:**
- `fg_pct_last_3` vs `points_avg_last_3`: Moderate (~0.5)
- `fg_pct_last_3` vs `pct_three`: Low (~0.2) - Different concepts
- These are acceptable levels for tree-based models

### Risk 4: Model Doesn't Use New Features

**Risk:** Model ignores FG% features (low importance)

**Mitigation:**
- Check feature importance after training
- If importance < 1%, investigate:
  - Is data quality sufficient?
  - Is computation correct?
  - Does signal exist in holdout data?
- May need feature engineering (e.g., interaction terms)

---

## Success Criteria

**V13 considered successful if:**

1. ✅ **MAE <= V12 MAE** (maintain or improve)
2. ✅ **Edge 3+ hit rate >= 65%** (vs V9 champion 39.9% decayed)
3. ✅ **Edge 5+ hit rate >= 70%** (vs V9 champion 79.0% at launch)
4. ✅ **Passes all governance gates** (bias, sample size, etc.)
5. ✅ **FG% features show positive importance** (> 1% in SHAP values)
6. ✅ **Improved accuracy on cold shooters** (MAE for `fg_pct_last_3 < 0.40`)

**If criteria not met:**
- Investigate root cause (feature quality, computation, etc.)
- Consider removing FG% features and deploying V12 baseline
- Document findings for future iteration

---

## Next Steps

### Implementation Phases

**Phase 1: Development (Est. 1 session)**
1. Create `shooting_efficiency_processor.py` in Phase 4
2. Update `feature_contract.py` with V13 features
3. Update BigQuery schema: `ml_feature_store_v2`
4. Write unit tests for feature computation

**Phase 2: Data Pipeline (Est. 1 session)**
5. Deploy shooting efficiency processor
6. Backfill features for historical dates (2025-11-01 to present)
7. Validate feature quality and completeness
8. Check distributions (FG% should be 25-65% range)

**Phase 3: Model Training (Est. 1 session)**
9. Train V13 on same dates as V12 (with FG% features)
10. Run walkforward validation
11. Compare V13 vs V12 on holdout data
12. Check feature importance (SHAP values)

**Phase 4: Shadow Testing (2+ days)**
13. Deploy V13 in shadow mode
14. Monitor performance vs V12
15. Collect 50+ edge 3+ graded predictions
16. Run governance gates

**Phase 5: Production Promotion (If passing)**
17. User review and approval
18. Update production environment variable
19. Monitor performance
20. Document results

---

## References

- Analysis: `docs/08-projects/current/mean-reversion-analysis/01-FRIEND-THEORY-TEST-RESULTS.md`
- Feature Contract: `shared/ml/feature_contract.py`
- V12 Features: `docs/08-projects/current/model-improvement-analysis/16-MASTER-IMPLEMENTATION-PLAN.md`
- Governance: `CLAUDE.md` - Model Governance section

---

**Session:** 242
**Date:** 2026-02-13
**Author:** Claude Sonnet 4.5
**Status:** PROPOSAL - Awaiting Review
