# Additional Angles for System Evolution

**Created:** 2025-12-11
**Purpose:** Comprehensive list of additional analyses and improvements to pursue after backfill

---

## Post-Backfill Analysis Priorities

### Immediate (Run First Week)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CRITICAL QUESTIONS TO ANSWER                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. Does the ensemble actually beat every individual system?                │
│     → If not, why have an ensemble at all?                                  │
│                                                                              │
│  2. What % of total error comes from worst 10% of predictions?              │
│     → If high, focus on avoiding catastrophic errors                        │
│                                                                              │
│  3. Which players are we worst at predicting?                               │
│     → Are they predictably unpredictable?                                   │
│                                                                              │
│  4. Are there contexts where we should NOT make predictions?                │
│     → Sometimes "no prediction" is better than bad prediction               │
│                                                                              │
│  5. How calibrated are our confidence scores?                               │
│     → When we say 70% confident, are we right 70% of time?                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Error Analysis Deep Dive

### 1.1 Catastrophic Error Analysis

Predictions off by 15+ points are catastrophic. Understanding these is critical.

```sql
-- Find catastrophic errors and look for patterns
SELECT
  pa.game_date,
  pa.player_lookup,
  pa.predicted_points,
  pa.actual_points,
  pa.absolute_error,
  p.scoring_tier,
  mlfs.minutes_recent_avg,
  mlfs.is_back_to_back,
  -- What happened?
  CASE
    WHEN pa.actual_points < 5 AND pa.predicted_points > 15 THEN 'EARLY_EXIT'  -- Injury, foul trouble, blowout
    WHEN pa.actual_points > pa.predicted_points + 15 THEN 'EXPLOSION'         -- Career game
    WHEN pa.actual_points < pa.predicted_points - 15 THEN 'COLLAPSE'          -- Bad game
  END as error_type
FROM prediction_accuracy pa
JOIN player_prop_predictions p USING (player_lookup, game_date, system_id)
LEFT JOIN ml_feature_store_v2 mlfs USING (player_lookup, game_date)
WHERE pa.absolute_error > 15
  AND pa.system_id = 'ensemble_v1'
ORDER BY pa.absolute_error DESC;
```

**Questions to answer:**
- Are catastrophic errors caused by minutes variance (injury, blowout)?
- Are certain player types more prone to explosions/collapses?
- Can we predict when we'll be wrong?

### 1.2 Error Distribution Analysis

```sql
-- Error distribution by bucket
SELECT
  CASE
    WHEN absolute_error <= 2 THEN '0-2 (excellent)'
    WHEN absolute_error <= 5 THEN '2-5 (good)'
    WHEN absolute_error <= 8 THEN '5-8 (acceptable)'
    WHEN absolute_error <= 12 THEN '8-12 (poor)'
    ELSE '12+ (catastrophic)'
  END as error_bucket,
  COUNT(*) as n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct,
  ROUND(SUM(absolute_error) / SUM(SUM(absolute_error)) OVER () * 100, 1) as pct_of_total_error
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

**Key insight:** If 10% of predictions cause 40% of total error, focus on avoiding those cases.

---

## 2. Player-Level Patterns

### 2.1 Predictability Score by Player

Some players are inherently harder to predict.

```sql
-- Player predictability ranking
SELECT
  player_lookup,
  COUNT(*) as games,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(STDDEV(absolute_error), 2) as error_volatility,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate,
  -- Predictability score (lower MAE + lower volatility = more predictable)
  ROUND(AVG(absolute_error) + STDDEV(absolute_error), 2) as unpredictability_score
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
GROUP BY 1
HAVING games >= 20
ORDER BY unpredictability_score DESC
LIMIT 50;
```

**Actions:**
- Consider excluding highly unpredictable players from high-confidence recommendations
- Apply different models to high-volatility players
- Use predictability score as confidence modifier

### 2.2 Player Streakiness

Some players are hot/cold, others are consistent.

```sql
-- Detect streaky players (high autocorrelation in errors)
WITH player_errors AS (
  SELECT
    player_lookup,
    game_date,
    signed_error,
    LAG(signed_error) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_error
  FROM prediction_accuracy
  WHERE system_id = 'ensemble_v1'
)
SELECT
  player_lookup,
  COUNT(*) as games,
  -- Correlation between consecutive errors (positive = streaky)
  CORR(signed_error, prev_error) as error_autocorrelation
FROM player_errors
WHERE prev_error IS NOT NULL
GROUP BY 1
HAVING games >= 20
ORDER BY error_autocorrelation DESC;
```

**Insight:** If a player has high autocorrelation, recent performance is more predictive. Weight recency higher for streaky players.

### 2.3 Role Change Detection

Players whose role changes mid-season need different handling.

```sql
-- Detect role changes (minutes variance)
WITH monthly_minutes AS (
  SELECT
    player_lookup,
    DATE_TRUNC(game_date, MONTH) as month,
    AVG(minutes_played) as avg_minutes,
    COUNT(*) as games
  FROM ml_feature_store_v2
  GROUP BY 1, 2
)
SELECT
  player_lookup,
  COUNT(DISTINCT month) as months,
  MAX(avg_minutes) - MIN(avg_minutes) as minutes_swing,
  STDDEV(avg_minutes) as minutes_volatility
FROM monthly_minutes
WHERE games >= 5
GROUP BY 1
HAVING months >= 3
ORDER BY minutes_swing DESC
LIMIT 50;
```

---

## 3. Temporal Patterns Deep Dive

### 3.1 Day of Week Effects

```sql
-- Performance by day of week
SELECT
  EXTRACT(DAYOFWEEK FROM game_date) as day_of_week,
  FORMAT_DATE('%A', game_date) as day_name,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
GROUP BY 1, 2
ORDER BY 1;
```

### 3.2 Schedule Density Effects

Beyond single back-to-backs, look at 3-in-4, 4-in-6 patterns.

```sql
-- Performance by schedule density
WITH game_density AS (
  SELECT
    player_lookup,
    game_date,
    COUNT(*) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      RANGE BETWEEN INTERVAL 6 DAY PRECEDING AND CURRENT ROW
    ) as games_in_7_days
  FROM ml_feature_store_v2
)
SELECT
  d.games_in_7_days,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae,
  ROUND(AVG(pa.signed_error), 3) as bias
FROM prediction_accuracy pa
JOIN game_density d USING (player_lookup, game_date)
WHERE pa.system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

### 3.3 Month-Over-Month Degradation

Does our model get worse as the season progresses?

```sql
-- Monthly performance (check for degradation)
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias,
  -- Compare to prior month
  LAG(ROUND(AVG(absolute_error), 3)) OVER (ORDER BY DATE_TRUNC(game_date, MONTH)) as prev_month_mae
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

---

## 4. Confidence Calibration Analysis

### 4.1 Calibration Curve

Are our confidence scores meaningful?

```sql
-- Calibration by confidence decile
SELECT
  confidence_decile,
  COUNT(*) as n,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as actual_win_rate,
  -- Expected: decile 10 should have ~90% win rate, decile 1 ~50%
  (confidence_decile * 5 + 45) as expected_win_rate_approx
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
  AND confidence_decile IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

**Ideal:** Actual win rate should increase monotonically with confidence decile.

### 4.2 Confidence vs MAE

```sql
-- Do high-confidence predictions have lower MAE?
SELECT
  confidence_decile,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
  AND confidence_decile IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

### 4.3 System Agreement as Confidence Signal

When all 4 systems agree, are we more accurate?

```sql
-- Agreement analysis (requires joining individual predictions)
WITH system_predictions AS (
  SELECT
    player_lookup,
    game_date,
    MAX(CASE WHEN system_id = 'xgboost_v1' THEN predicted_points END) as xgb,
    MAX(CASE WHEN system_id = 'moving_average_baseline_v1' THEN predicted_points END) as ma,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN predicted_points END) as sim,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN predicted_points END) as zone
  FROM player_prop_predictions
  GROUP BY 1, 2
),
agreement AS (
  SELECT
    player_lookup,
    game_date,
    -- Spread between systems
    GREATEST(xgb, ma, sim, zone) - LEAST(xgb, ma, sim, zone) as system_spread
  FROM system_predictions
  WHERE xgb IS NOT NULL AND ma IS NOT NULL AND sim IS NOT NULL AND zone IS NOT NULL
)
SELECT
  CASE
    WHEN system_spread < 2 THEN 'TIGHT (<2pt spread)'
    WHEN system_spread < 4 THEN 'MODERATE (2-4pt)'
    WHEN system_spread < 6 THEN 'WIDE (4-6pt)'
    ELSE 'VERY WIDE (6+pt)'
  END as agreement_level,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae
FROM prediction_accuracy pa
JOIN agreement a USING (player_lookup, game_date)
WHERE pa.system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

**Hypothesis:** Tight agreement = more confident = lower MAE.

---

## 5. Matchup-Specific Patterns

### 5.1 Division/Conference Effects

```sql
-- Performance by matchup type
SELECT
  CASE
    WHEN team_division = opponent_division THEN 'SAME_DIVISION'
    WHEN team_conference = opponent_conference THEN 'SAME_CONFERENCE'
    ELSE 'CROSS_CONFERENCE'
  END as matchup_type,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae
FROM prediction_accuracy_enriched  -- Needs team metadata
WHERE system_id = 'ensemble_v1'
GROUP BY 1;
```

### 5.2 Revenge Games

Players often have elevated performance against former teams.

```sql
-- Would need to track player team history
-- Flag games where player faces former team
SELECT
  is_revenge_game,
  COUNT(*) as n,
  ROUND(AVG(signed_error), 3) as bias  -- Expect negative bias (under-predicting)
FROM prediction_accuracy_enriched
WHERE system_id = 'ensemble_v1'
GROUP BY 1;
```

---

## 6. Minutes Variance as Key Driver

### 6.1 Minutes Prediction Accuracy

Points are highly correlated with minutes. How well do we predict minutes (implicitly)?

```sql
-- Points per minute analysis
SELECT
  p.scoring_tier,
  ROUND(AVG(pa.actual_points / NULLIF(pa.minutes_played, 0)), 2) as actual_ppm,
  ROUND(AVG(pa.predicted_points / NULLIF(mlfs.minutes_recent_avg, 0)), 2) as expected_ppm,
  ROUND(CORR(pa.minutes_played, mlfs.minutes_recent_avg), 3) as minutes_correlation
FROM prediction_accuracy pa
JOIN player_prop_predictions p USING (player_lookup, game_date, system_id)
JOIN ml_feature_store_v2 mlfs USING (player_lookup, game_date)
WHERE pa.system_id = 'ensemble_v1'
  AND pa.minutes_played > 0
GROUP BY 1;
```

### 6.2 Blowout Risk

In blowouts, starters sit and bench players get garbage time.

```sql
-- Performance in blowouts vs close games
SELECT
  CASE
    WHEN ABS(final_margin) > 20 THEN 'BLOWOUT (20+)'
    WHEN ABS(final_margin) > 10 THEN 'COMFORTABLE (10-20)'
    ELSE 'CLOSE (<10)'
  END as game_closeness,
  p.scoring_tier,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae,
  ROUND(AVG(pa.signed_error), 3) as bias
FROM prediction_accuracy pa
JOIN player_prop_predictions p USING (player_lookup, game_date, system_id)
JOIN game_results g ON pa.game_date = g.game_date AND pa.team_id = g.team_id  -- Needs game results
WHERE pa.system_id = 'ensemble_v1'
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Insight:** Starters likely over-predicted in blowouts (pulled early). Bench under-predicted (garbage time).

---

## 7. Meta-Learning Opportunities

### 7.1 Learn to Predict Our Own Errors

Train a model to predict when we'll be wrong.

```python
# Conceptual: train error prediction model
features = [
    'system_spread',           # Agreement between systems
    'player_predictability',   # Historical MAE for this player
    'minutes_volatility',      # How variable are this player's minutes
    'is_back_to_back',
    'games_in_7_days',
    'scoring_tier',
    'age_group'
]

target = 'absolute_error > 8'  # Binary: will this be a bad prediction?

# If we can predict bad predictions, we can:
# 1. Lower confidence for those predictions
# 2. Exclude from recommendations
# 3. Use different models for "risky" predictions
```

### 7.2 Player Embeddings

Learn dense representations of players for similarity matching.

```python
# Train embeddings based on:
# - Scoring patterns
# - Shot distribution
# - Usage patterns
# - Team context

# Use embeddings for:
# - Better similarity matching
# - Transfer learning for new players
# - Cluster-based modeling
```

---

## 8. External Data Opportunities

### 8.1 Vegas Lines as Features

Vegas lines encode expert knowledge.

| Feature | Use Case |
|---------|----------|
| Player prop line | Use as anchor/feature |
| Line movement | Signal for injuries, news |
| Game total | Pace prediction |
| Spread | Blowout risk |

### 8.2 Injury Report Integration

Game-time decisions are a major source of error.

| Signal | Impact |
|--------|--------|
| Questionable tag | Higher uncertainty |
| Key teammate out | Role change |
| Returning from injury | Rust factor |

### 8.3 News/Social Signals (Future)

- Trade rumors (player distracted)
- Coach comments (rotation hints)
- Player social media (motivation)

---

## 9. Operational Improvements

### 9.1 Real-Time Performance Dashboard

Track daily performance to catch issues quickly.

```sql
-- Daily performance monitoring
SELECT
  game_date,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate,
  -- Alert flags
  CASE WHEN AVG(absolute_error) > 5.5 THEN 'HIGH_ERROR' END as alert
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
  AND game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 1 DESC;
```

### 9.2 Anomaly Detection

Flag when predictions are unusually far from actuals.

```sql
-- Flag anomalous days
WITH daily_mae AS (
  SELECT
    game_date,
    AVG(absolute_error) as mae
  FROM prediction_accuracy
  WHERE system_id = 'ensemble_v1'
  GROUP BY 1
),
stats AS (
  SELECT AVG(mae) as avg_mae, STDDEV(mae) as std_mae FROM daily_mae
)
SELECT
  d.game_date,
  d.mae,
  (d.mae - s.avg_mae) / s.std_mae as z_score,
  CASE WHEN (d.mae - s.avg_mae) / s.std_mae > 2 THEN 'ANOMALY' END as flag
FROM daily_mae d
CROSS JOIN stats s
ORDER BY d.game_date DESC;
```

---

## 10. Long-Term Research Directions

### 10.1 Sequence Models

Player performance is a time series. Consider:
- LSTM for capturing momentum/trends
- Transformer attention over historical games
- State-space models for regime detection

### 10.2 Causal Inference

Move from correlation to causation:
- Why do predictions fail?
- What's the causal effect of rest on performance?
- Counterfactual: "What would this player have scored with more rest?"

### 10.3 Hierarchical Bayesian Models

Model structure:
```
League-level priors
    └── Team-level effects
        └── Player-level parameters
            └── Game-level predictions
```

Benefits: Better handling of small samples, uncertainty quantification.

---

## Summary: Priority Actions Post-Backfill

### Week 1: Core Analysis
- [ ] Run error distribution analysis (Section 1.2)
- [ ] Run catastrophic error analysis (Section 1.1)
- [ ] Run confidence calibration analysis (Section 4)
- [ ] Document findings

### Week 2: Player Patterns
- [ ] Build player predictability scores (Section 2.1)
- [ ] Identify streaky players (Section 2.2)
- [ ] Analyze minutes variance as error driver (Section 6)

### Week 3: Temporal & Context
- [ ] Run schedule density analysis (Section 3.2)
- [ ] Run system agreement analysis (Section 4.3)
- [ ] Identify contexts to avoid predicting

### Ongoing: Infrastructure
- [ ] Set up daily performance monitoring
- [ ] Build anomaly detection
- [ ] Create player predictability table

---

## New Tables to Consider

| Table | Purpose | Priority |
|-------|---------|----------|
| `player_predictability` | Store predictability scores by player | High |
| `daily_performance_log` | Track daily MAE, bias, win rate | High |
| `catastrophic_errors` | Log predictions off by 15+ for analysis | Medium |
| `system_agreement` | Store system spread per prediction | Medium |
| `context_exclusions` | Contexts where we shouldn't predict | Low |
