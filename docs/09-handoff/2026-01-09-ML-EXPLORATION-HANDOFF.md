# ML Exploration Handoff: Can We Do Better Than 4.14 MAE?

**Date**: January 9, 2026
**Current Best**: XGBoost v6 at 4.14 MAE (13.6% better than mock's 4.80)
**Question**: What else can we try to push MAE lower?

---

## Current State

### What We Have
- **XGBoost v6**: 4.14 MAE on 2024-25 season (unseen data)
- **Training data**: 77,666 samples with 25 features from ml_feature_store_v2
- **Feature completeness**: 100% (up from 77-89% in v4/v5)

### What We Tried (No Improvement)
| Approach | Result | Why It Failed |
|----------|--------|---------------|
| High-scorer calibration | No change | Regression to mean is correct behavior |
| Ensemble v6 + mock | No change | v6 already beats mock everywhere |
| Volatility-segmented models | +0.002 | Unified model already captures this |
| Tier-segmented models | -0.002 | Same - features handle this |

### Error Breakdown (Current)
| Player Type | MAE | Samples | Notes |
|-------------|-----|---------|-------|
| Low volatility (std < 3) | 1.81 | 3,726 | Very predictable |
| Medium volatility (3-5) | 3.37 | 18,267 | Moderate |
| High volatility (5-7) | 4.64 | 10,294 | Harder |
| Very high volatility (7+) | 6.90 | 6,454 | Near-random |

---

## UNEXPLORED OPPORTUNITIES

### Category 1: Alternative Model Architectures

| Model | Why Try It | Expected Impact | Effort |
|-------|-----------|-----------------|--------|
| **LightGBM** | Faster, different splitting | ±0.05 MAE | 1 hr |
| **CatBoost** | Better categorical handling | ±0.05 MAE | 1 hr |
| **Neural Network** | Non-linear patterns | ±0.1 MAE | 3-4 hrs |
| **Stacked Ensemble** | Combine multiple models | -0.05 to -0.1 | 2-3 hrs |

**Quick test**: Train LightGBM and CatBoost with same features, compare to XGBoost.

### Category 2: Feature Engineering (Not Yet Done)

| Feature Idea | Rationale | Data Source |
|--------------|-----------|-------------|
| **Minutes prediction** | Predict minutes first, then points/min | Existing data |
| **Player vs Team history** | How does player perform vs specific teams? | player_game_summary |
| **Teammate availability** | More shots when star teammate out | roster data |
| **Opponent player matchups** | Guard vs guard defense | player positions |
| **Streak features** | Win/loss streaks, hot hand | game results |
| **Rest advantage delta** | Days rest vs opponent rest | schedule |
| **Travel distance** | Cross-country games harder | team locations |
| **Game importance** | Playoff implications | standings |
| **Previous meeting recency** | How long since last played this team | schedule |

**Quick win**: Add player-vs-team historical average as feature.

### Category 3: External Data Integration

| Data Source | What It Adds | Availability | Impact |
|-------------|--------------|--------------|--------|
| **Vegas player props** | Market consensus | Odds API | HIGH |
| **Injury reports** | Filter DNPs | ESPN/official | HIGH |
| **Starting lineups** | Confirmed starters | Rotowire/ESPN | MEDIUM |
| **Advanced stats** | PER, BPM, RAPTOR | Basketball Reference | MEDIUM |
| **Play-by-play** | Shot quality, usage patterns | NBA API | LOW |

**Highest ROI**: Vegas lines as feature - market is often well-calibrated.

### Category 4: Segmentation Approaches (Not Fully Explored)

| Segment By | Hypothesis | Test |
|------------|------------|------|
| **Team** | Some teams more predictable | Train per-team or team-cluster models |
| **Game context** | B2B, home/away combos | Segment by context buckets |
| **Opponent quality** | Elite D vs weak D | Segment by opponent tier |
| **Season phase** | Early vs late vs playoffs | Time-based segments |
| **Player archetype** | Scorers vs facilitators vs 3&D | Cluster players, train per cluster |
| **Prediction confidence** | Apply different logic by confidence | Use prediction uncertainty |

**Interesting test**: Cluster players by playing style, train models per cluster.

### Category 5: Target Engineering

| Approach | Description | Rationale |
|----------|-------------|-----------|
| **Predict points/minute** | Separate efficiency from minutes | Minutes is easier to predict |
| **Predict deviation** | Predict (actual - season_avg) | Remove baseline, focus on variance |
| **Two-stage model** | Stage 1: Minutes, Stage 2: Points given minutes | Cleaner separation |
| **Quantile regression** | Predict 10th/50th/90th percentile | Capture uncertainty |

**Recommended**: Two-stage model (minutes → points) - cleaner separation of concerns.

### Category 6: Hyperparameter Optimization

| What | Current | Range to Explore |
|------|---------|------------------|
| max_depth | 6 | 4-10 |
| learning_rate | 0.03 | 0.01-0.1 |
| n_estimators | 500 | 200-1000 |
| min_child_weight | 10 | 5-20 |
| subsample | 0.7 | 0.6-0.9 |
| colsample_bytree | 0.7 | 0.5-0.9 |
| reg_alpha | 0.5 | 0-2 |
| reg_lambda | 5.0 | 1-10 |

**Tool**: Use Optuna for Bayesian hyperparameter search.

### Category 7: Deep Error Analysis

| Analysis | Question | Method |
|----------|----------|--------|
| **Worst players** | Which players are most unpredictable? | MAE by player |
| **Worst games** | What game contexts cause errors? | Error by game features |
| **Temporal patterns** | Do errors change over season? | Error by month |
| **Systematic bias** | Are we consistently wrong somewhere? | Bias by segment |
| **Feature importance by segment** | Do different features matter for different players? | SHAP by segment |

---

## RECOMMENDED EXPLORATION ORDER

### Phase 1: Quick Wins (2-3 hours)
1. **Train LightGBM and CatBoost** - Compare to XGBoost
2. **Add Vegas lines as feature** - If available, major signal
3. **Player-vs-team history feature** - Easy to compute

### Phase 2: Architecture Changes (3-4 hours)
4. **Two-stage model** - Predict minutes, then points/minute
5. **Stacked ensemble** - Combine XGB + LightGBM + CatBoost
6. **Hyperparameter tuning** - Optuna search

### Phase 3: Deep Segmentation (4-6 hours)
7. **Player clustering** - K-means on play style, train per cluster
8. **Team-specific models** - 30 micro-models
9. **Context-specific models** - Home/away, B2B, etc.

### Phase 4: External Data (4-8 hours)
10. **Injury integration** - Filter DNPs
11. **Lineup data** - Confirmed starters
12. **Vegas lines** - As feature or benchmark

---

## SPECIFIC EXPERIMENTS TO RUN

### Experiment 1: Alternative Gradient Boosters
```python
# Compare XGBoost vs LightGBM vs CatBoost
# Same features, same splits, same evaluation

from lightgbm import LGBMRegressor
from catboost import CatBoostRegressor

models = {
    'xgboost': XGBRegressor(**xgb_params),
    'lightgbm': LGBMRegressor(**lgb_params),
    'catboost': CatBoostRegressor(**cat_params)
}

for name, model in models.items():
    model.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, model.predict(X_test))
    print(f"{name}: {mae:.3f}")
```

### Experiment 2: Two-Stage Model
```python
# Stage 1: Predict minutes
minutes_model = XGBRegressor()
minutes_model.fit(X_train, minutes_train)
pred_minutes = minutes_model.predict(X_test)

# Stage 2: Predict points per minute
ppm_model = XGBRegressor()
ppm_model.fit(X_train, points_per_min_train)
pred_ppm = ppm_model.predict(X_test)

# Final prediction
pred_points = pred_minutes * pred_ppm
```

### Experiment 3: Player Clustering
```python
# Cluster players by style
from sklearn.cluster import KMeans

player_features = df.groupby('player_lookup').agg({
    'points_avg_season': 'mean',
    'usage_rate': 'mean',
    'pct_three': 'mean',
    'pct_paint': 'mean',
    'minutes_played': 'mean'
})

kmeans = KMeans(n_clusters=5)
player_features['cluster'] = kmeans.fit_predict(player_features)

# Train model per cluster
for cluster in range(5):
    cluster_mask = train_df['cluster'] == cluster
    cluster_model.fit(X_train[cluster_mask], y_train[cluster_mask])
```

### Experiment 4: Vegas Lines as Feature
```python
# If we have odds_api data
query = """
SELECT
    player_lookup,
    game_date,
    points_line as vegas_points
FROM nba_raw.odds_api_player_props
WHERE prop_type = 'points'
"""

# Add as feature
X['vegas_points'] = vegas_lines
# Retrain and compare
```

### Experiment 5: Player-vs-Team History
```python
# Calculate how player performs vs each team historically
query = """
SELECT
    player_lookup,
    opponent_team_abbr,
    AVG(points) as avg_vs_team,
    COUNT(*) as games_vs_team
FROM player_game_summary
GROUP BY player_lookup, opponent_team_abbr
"""

# Add as feature for each prediction
X['avg_vs_opponent'] = player_vs_team_lookup
```

---

## DATA SOURCES TO CHECK

### Existing Tables That May Help
```sql
-- Check what's in odds_api
SELECT table_name FROM nba_raw.INFORMATION_SCHEMA.TABLES WHERE table_name LIKE 'odds%';

-- Check injury data
SELECT table_name FROM nba_raw.INFORMATION_SCHEMA.TABLES WHERE table_name LIKE '%injury%';

-- Check lineup data
SELECT table_name FROM nba_raw.INFORMATION_SCHEMA.TABLES WHERE table_name LIKE '%lineup%' OR table_name LIKE '%roster%';
```

### Player-vs-Team History Query
```sql
SELECT
    player_lookup,
    opponent_team_abbr,
    AVG(points) as avg_vs_team,
    STDDEV(points) as std_vs_team,
    COUNT(*) as games_vs_team,
    MAX(game_date) as last_meeting
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year >= 2021
GROUP BY player_lookup, opponent_team_abbr
HAVING games_vs_team >= 3
```

---

## SUCCESS CRITERIA

| Milestone | Target MAE | Improvement |
|-----------|------------|-------------|
| Current v6 | 4.14 | Baseline |
| Quick wins | 4.05 | -2% |
| Architecture | 3.95 | -5% |
| Full optimization | 3.85 | -7% |
| Theoretical floor | ~3.50 | -15% |

**Note**: The theoretical floor is limited by inherent game variance. Players' actual performance has natural variability that no model can predict.

---

## QUESTIONS TO ANSWER

1. **Can LightGBM/CatBoost beat XGBoost?** (Probably marginal)
2. **Does two-stage modeling help?** (Separates minutes from efficiency)
3. **Are there player clusters with different patterns?** (Scorers vs role players)
4. **Do Vegas lines add signal?** (If available, likely yes)
5. **Can we reduce high-scorer underprediction?** (Maybe with different target)
6. **What's the true error floor?** (Inherent variance analysis)

---

## GETTING STARTED

### Quick Start Commands
```bash
# Load the current best model
PYTHONPATH=. python -c "
import xgboost as xgb
model = xgb.Booster()
model.load_model('models/xgboost_v6_25features_20260108_193546.json')
print('Model loaded successfully')
"

# Run existing analysis
PYTHONPATH=. python ml/comprehensive_improvement_analysis.py

# Check available data
bq ls nba-props-platform:nba_raw | head -20
```

### Key Files
- `ml/train_xgboost_v6.py` - Current training script (template for new experiments)
- `ml/comprehensive_improvement_analysis.py` - Analysis framework
- `models/xgboost_v6_25features_20260108_193546.json` - Current best model
- `docs/09-handoff/2026-01-09-SESSION-HANDOFF.md` - Full session context

---

## SUMMARY

**Current state**: 4.14 MAE (excellent, 13.6% better than mock)

**Remaining opportunities**:
1. Alternative models (LightGBM, CatBoost) - Quick test
2. Two-stage modeling - Promising architecture change
3. Player clustering - Different models for different player types
4. Vegas lines - External signal (if available)
5. Hyperparameter tuning - Systematic optimization

**Realistic expectation**: Could potentially reach 3.9-4.0 MAE with effort. Getting below 3.8 would require significant new data sources or breakthrough in modeling.

**Recommended first step**: Train LightGBM and CatBoost on same data, see if they beat XGBoost.

---

**Ready for exploration!** Start with quick wins, then go deeper based on results.
