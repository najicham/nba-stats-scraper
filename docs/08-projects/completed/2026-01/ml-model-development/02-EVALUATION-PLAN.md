# System Evaluation Plan - Analyzing 328k Graded Predictions

**Purpose**: Understand which existing prediction systems work best and identify improvement opportunities
**Data**: 328,027 graded predictions from `nba_predictions.prediction_accuracy`
**Timeline**: 1-2 weeks
**Difficulty**: ⭐ Beginner (SQL queries only)

---

## 🎯 Goals

By the end of this evaluation, you will know:
1. **Which prediction system performs best** (MAE, accuracy)
2. **When predictions fail** (scenarios, players, timing)
3. **Baseline to beat** (what performance to target with new models)
4. **Low-hanging fruit** (quick wins to improve accuracy)

---

## 📊 Phase 1: System Performance Comparison (Day 1)

### Query 1: Overall System Performance

```sql
-- Which prediction system is best overall?
SELECT
  system_id,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT game_id) as games_covered,
  COUNT(DISTINCT player_lookup) as players_covered,

  -- Accuracy metrics
  AVG(absolute_error) as mae,
  STDDEV(absolute_error) as mae_std,
  AVG(signed_error) as bias,

  -- Recommendation performance
  SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as correct_recommendations,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as recommendation_accuracy,

  -- Confidence calibration
  AVG(confidence_score) as avg_confidence,

  -- Distribution stats
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(50)] as median_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(25)] as p25_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(75)] as p75_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(90)] as p90_error

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2021-11-01' AND game_date < '2024-05-01'
GROUP BY system_id
ORDER BY mae ASC;
```

**What to Look For**:
- Best system: Lowest MAE
- Bias: Signed error close to 0 = unbiased, positive = over-predicts, negative = under-predicts
- Recommendation accuracy: >70% is good, >75% is excellent
- Confidence calibration: High confidence should correlate with low error

**Expected Output**:
```
system_id | predictions | mae  | bias | recommendation_accuracy | avg_confidence
----------|-------------|------|------|-------------------------|---------------
system_a  | 109,000     | 4.2  | -0.1 | 0.72                   | 0.68
system_b  | 109,000     | 4.8  | +0.3 | 0.68                   | 0.65
system_c  | 110,000     | 5.1  | -0.5 | 0.64                   | 0.62
```

**Action**: Document which system is best and by how much.

---

### Query 2: System Performance Over Time

```sql
-- Does system performance vary by month/season?
SELECT
  system_id,
  EXTRACT(YEAR FROM game_date) as year,
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(*) as predictions,
  AVG(absolute_error) as mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY system_id, year, month
ORDER BY system_id, year, month;
```

**What to Look For**:
- Seasonality: Are predictions worse early season? (Less data)
- Degradation: Does performance get worse over time? (Model staleness)
- Consistency: Which system is most stable?

**Visualization**: Create line chart of MAE over time per system

**Action**: Identify if models need frequent retraining.

---

### Query 3: System Performance by Recommendation Type

```sql
-- How accurate are OVER vs UNDER recommendations?
SELECT
  system_id,
  recommendation,
  COUNT(*) as total,
  AVG(absolute_error) as mae,
  SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as correct,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy,
  AVG(line_margin) as avg_line_margin
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE recommendation IN ('OVER', 'UNDER')
GROUP BY system_id, recommendation
ORDER BY system_id, accuracy DESC;
```

**What to Look For**:
- Directional bias: Does system prefer OVER or UNDER?
- Imbalance: Should be roughly 50/50 OVER vs UNDER
- Accuracy difference: Is one direction more accurate?

**Action**: Flag if system has directional bias to correct.

---

## 🎯 Phase 2: Player & Scenario Analysis (Days 2-3)

### Query 4: Easiest vs Hardest Players to Predict

```sql
-- Which players are predictable vs unpredictable?
WITH player_stats AS (
  SELECT
    player_lookup,
    COUNT(*) as predictions,
    AVG(absolute_error) as mae,
    STDDEV(absolute_error) as error_volatility,
    AVG(actual_points) as avg_points,
    STDDEV(actual_points) as point_volatility,
    AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  GROUP BY player_lookup
  HAVING predictions >= 50  -- Minimum sample size
)
SELECT
  player_lookup,
  predictions,
  mae,
  error_volatility,
  avg_points,
  point_volatility,
  accuracy,
  -- Predictability score (lower = more predictable)
  (mae / NULLIF(avg_points, 0)) as mae_relative
FROM player_stats
ORDER BY mae ASC
LIMIT 30;  -- Top 30 most predictable
```

**Then run for worst**:
```sql
-- Same query but ORDER BY mae DESC for hardest to predict
```

**What to Look For**:
- Easiest: Consistent players (low point volatility, low MAE)
- Hardest: Volatile scorers (high point volatility, high MAE)
- Surprise players: Low avg_points but high MAE (inconsistent role players)

**Action**:
- Focus on predictable players for high-confidence recommendations
- Flag unpredictable players for manual review or skip
- Identify if unpredictable players have common traits (bench players, injury-prone, etc.)

---

### Query 5: Performance by Player Scoring Tier

```sql
-- Do predictions work better for star players or role players?
WITH player_tiers AS (
  SELECT
    player_lookup,
    AVG(actual_points) as avg_points,
    CASE
      WHEN AVG(actual_points) >= 25 THEN 'Elite (25+)'
      WHEN AVG(actual_points) >= 20 THEN 'Star (20-25)'
      WHEN AVG(actual_points) >= 15 THEN 'Starter (15-20)'
      WHEN AVG(actual_points) >= 10 THEN 'Rotation (10-15)'
      ELSE 'Bench (<10)'
    END as tier
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  GROUP BY player_lookup
  HAVING COUNT(*) >= 20
)
SELECT
  pt.tier,
  COUNT(DISTINCT pa.player_lookup) as players,
  COUNT(*) as predictions,
  AVG(pa.absolute_error) as mae,
  AVG(CASE WHEN pa.was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
GROUP BY pt.tier
ORDER BY pt.tier;
```

**What to Look For**:
- Sweet spot: Which tier has best accuracy?
- Volume: Most predictions should be for starters/stars
- Avoid: If bench players have poor accuracy, consider filtering them out

**Action**: Set minimum minutes/points threshold for predictions.

---

### Query 6: Home vs Away Performance

```sql
-- Do predictions work better for home or away games?
SELECT
  pgs.home_game,
  COUNT(*) as predictions,
  AVG(pa.absolute_error) as mae,
  AVG(CASE WHEN pa.was_correct THEN 1.0 ELSE 0.0 END) as accuracy,
  AVG(pa.actual_points) as avg_points
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON pa.game_id = pgs.game_id AND pa.player_lookup = pgs.player_lookup
GROUP BY pgs.home_game;
```

**What to Look For**:
- Home advantage: Are home players easier to predict?
- Adjust features: May need home/away adjustment factor

---

### Query 7: Back-to-Back Game Performance

```sql
-- Are predictions worse on back-to-back games?
WITH game_schedule AS (
  SELECT
    player_lookup,
    game_date,
    game_id,
    LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_game_date,
    DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) as days_rest
  FROM `nba-props-platform.nba_analytics.player_game_summary`
)
SELECT
  CASE
    WHEN gs.days_rest = 0 THEN 'Back-to-back (0 days)'
    WHEN gs.days_rest = 1 THEN '1 day rest'
    WHEN gs.days_rest = 2 THEN '2 days rest'
    WHEN gs.days_rest >= 3 THEN '3+ days rest'
    ELSE 'First game / Unknown'
  END as rest_category,
  COUNT(*) as predictions,
  AVG(pa.absolute_error) as mae,
  AVG(CASE WHEN pa.was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN game_schedule gs
  ON pa.game_id = gs.game_id AND pa.player_lookup = gs.player_lookup
GROUP BY rest_category
ORDER BY rest_category;
```

**What to Look For**:
- Fatigue impact: Is MAE higher on back-to-backs?
- Rest advantage: Better predictions with more rest?

**Action**: Add rest/fatigue as model feature if significant.

---

## 🔍 Phase 3: Error Analysis (Days 4-5)

### Query 8: Largest Prediction Errors

```sql
-- What are the biggest misses? Learn from failures.
SELECT
  pa.game_date,
  pa.player_lookup,
  pa.system_id,
  pa.predicted_points,
  pa.actual_points,
  pa.absolute_error,
  pa.recommendation,
  pa.was_correct,
  pgs.minutes_played,
  pgs.game_started,
  -- Context
  CONCAT(pgs.opponent_abbr, CASE WHEN pgs.home_game THEN ' (H)' ELSE ' (A)' END) as opponent
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON pa.game_id = pgs.game_id AND pa.player_lookup = pgs.player_lookup
WHERE pa.absolute_error >= 15  -- Huge misses only
ORDER BY pa.absolute_error DESC
LIMIT 100;
```

**What to Look For**:
- Common patterns: Injury games (low minutes), blowouts, anomalies
- Systematic issues: Same player/opponent repeatedly
- Outliers: One-off events vs recurring problems

**Action**:
- Add filters: Skip players with <15 minutes played
- Detect anomalies: Flag blowouts or unusual circumstances
- Injury detection: Integrate injury reports

---

### Query 9: Confidence Score Calibration

```sql
-- Are high-confidence predictions actually more accurate?
SELECT
  CASE
    WHEN confidence_score >= 0.8 THEN 'Very High (0.8+)'
    WHEN confidence_score >= 0.7 THEN 'High (0.7-0.8)'
    WHEN confidence_score >= 0.6 THEN 'Medium (0.6-0.7)'
    WHEN confidence_score >= 0.5 THEN 'Low (0.5-0.6)'
    ELSE 'Very Low (<0.5)'
  END as confidence_bucket,
  COUNT(*) as predictions,
  AVG(absolute_error) as mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY confidence_bucket
ORDER BY confidence_bucket DESC;
```

**What to Look For**:
- Well-calibrated: Higher confidence → Lower MAE
- Poorly-calibrated: No correlation between confidence and accuracy
- Over-confident: High confidence but high error

**Action**:
- If well-calibrated: Use confidence for filtering (only show high-confidence predictions)
- If poorly-calibrated: Retrain confidence model or ignore it

---

### Query 10: Line Margin Analysis

```sql
-- How far off from the betting line should predictions be to be valuable?
SELECT
  CASE
    WHEN ABS(line_margin) < 2 THEN 'Close to line (<2 pts)'
    WHEN ABS(line_margin) < 4 THEN 'Moderate (2-4 pts)'
    WHEN ABS(line_margin) < 6 THEN 'Far (4-6 pts)'
    ELSE 'Very far (6+ pts)'
  END as margin_bucket,
  recommendation,
  COUNT(*) as predictions,
  AVG(absolute_error) as mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE recommendation IN ('OVER', 'UNDER')
GROUP BY margin_bucket, recommendation
ORDER BY margin_bucket, recommendation;
```

**What to Look For**:
- Edge quality: Are large margins more accurate? (They should be)
- Optimal threshold: What margin gives best accuracy?
- Risk/reward: More edge = more profit but fewer opportunities

**Action**: Set minimum line_margin threshold (e.g., only recommend if |margin| >= 3 pts)

---

## 📈 Phase 4: Synthesis & Recommendations (Days 6-7)

### Create Summary Report

**Template**: `results/baseline-evaluation-report.md`

```markdown
# Baseline System Evaluation Report

**Date**: [Today's date]
**Data**: 328,027 graded predictions (2021-2024)
**Analysis Period**: 1 week

## Executive Summary

Best System: [system_id]
- MAE: [X.X] points
- Recommendation Accuracy: [XX%]
- Predictions: [XXX,XXX]

## Key Findings

### 1. System Performance
- [System A]: MAE X.X, Accuracy XX%
- [System B]: MAE X.X, Accuracy XX%
- Winner: [System A] by X.X points

### 2. Player Insights
- Most predictable: [Player names]
- Least predictable: [Player names]
- Sweet spot: [Scoring tier]

### 3. Scenario Performance
- Home vs Away: [Findings]
- Rest impact: [Findings]
- Seasonality: [Findings]

### 4. Error Patterns
- Common failures: [List]
- Biggest misses: [Examples]
- Systematic issues: [List]

## Improvement Opportunities

### Quick Wins (Immediate)
1. Filter out players with <15 minutes expected
2. Set minimum line margin of 3 points
3. Skip bench players (<10 PPG average)
4. Use only high-confidence predictions (>0.7)

### Medium-term (Model Features)
1. Add rest/fatigue factor
2. Improve home/away adjustment
3. Better opponent defense rating
4. Injury probability score

### Long-term (New Models)
1. Train XGBoost on Phase 4 features
2. Neural network for complex interactions
3. Ensemble combining best systems
4. Continuous learning pipeline

## Target Performance

Current Best: MAE [X.X], Accuracy [XX%]
Target (New Model): MAE [X.X], Accuracy [XX%]
Improvement Goal: [X%] better

## Next Steps

1. Implement quick wins (filters)
2. Extract training data from Phase 4
3. Train baseline ML model
4. Validate on holdout set
5. Deploy if beats current best by 3%+
```

---

## 🎯 Deliverables Checklist

By end of evaluation phase:

- [ ] System performance comparison table
- [ ] Best system identified (baseline to beat)
- [ ] Player predictability rankings
- [ ] Scenario analysis (home/away, rest, etc.)
- [ ] Error pattern analysis
- [ ] Confidence calibration check
- [ ] Line margin analysis
- [ ] List of quick wins
- [ ] List of model improvements
- [ ] Target performance metrics
- [ ] Written evaluation report

---

## 🚀 Quick Start Script

**Save as** `scripts/evaluate_systems.sql`

```sql
-- Complete evaluation in one query
WITH system_performance AS (
  SELECT
    system_id,
    AVG(absolute_error) as mae,
    AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2021-11-01' AND game_date < '2024-05-01'
  GROUP BY system_id
),
player_difficulty AS (
  SELECT
    player_lookup,
    AVG(absolute_error) as player_mae,
    COUNT(*) as predictions
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  GROUP BY player_lookup
  HAVING predictions >= 50
)
SELECT
  'Best System' as metric,
  system_id as value,
  CAST(mae AS STRING) as detail
FROM system_performance
ORDER BY mae ASC
LIMIT 1

UNION ALL

SELECT
  'Hardest Player' as metric,
  player_lookup as value,
  CAST(player_mae AS STRING) as detail
FROM player_difficulty
ORDER BY player_mae DESC
LIMIT 1

UNION ALL

SELECT
  'Easiest Player' as metric,
  player_lookup as value,
  CAST(player_mae AS STRING) as detail
FROM player_difficulty
ORDER BY player_mae ASC
LIMIT 1;
```

---

## 📚 Additional Analysis Ideas

### Advanced Queries (Optional)

1. **Correlation analysis**: Which features correlate most with prediction error?
2. **Cluster analysis**: Group players by predictability profiles
3. **Time-to-line**: How quickly do predictions converge to betting line?
4. **Ensemble simulation**: Test weighted combination of systems
5. **Feature importance**: Which Phase 4 features matter most?

### Visualizations to Create

1. MAE distribution histogram
2. System performance over time (line chart)
3. Player predictability scatter (avg_points vs MAE)
4. Error vs confidence (calibration plot)
5. Home/away performance comparison

---

## ✅ Success Criteria

Evaluation is complete when you can answer:

1. ✅ Which system is best? (And by how much?)
2. ✅ What's the baseline MAE to beat?
3. ✅ Which players should we predict? (Filter criteria)
4. ✅ What scenarios reduce accuracy? (Avoid these)
5. ✅ What are 3 quick wins to implement?
6. ✅ What's the target for new models? (X% improvement)

---

**Next**: Use these insights in `03-TRAINING-PLAN.md` to build better models!
