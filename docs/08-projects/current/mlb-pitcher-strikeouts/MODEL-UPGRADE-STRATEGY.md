# MLB Pitcher Strikeouts Model Upgrade Strategy

**Created:** 2026-01-14
**Status:** Decision Required

---

## Current Model Performance

**Model:** `mlb_pitcher_strikeouts_v1`
**Algorithm:** XGBoost
**Features:** 19
**Hit Rate:** 67.27% (validated on 7,196 picks)

The model is **profitable** but shows:
- Performance decline in late 2025 (56-59% vs 70-73% earlier)
- 14 unused features from the original roadmap
- Some pitcher-specific weaknesses

---

## Options

### Option A: Upgrade V1 In-Place

**Description:** Retrain the existing model with additional features and 2025 data.

**Pros:**
- Simpler deployment (one model)
- No comparison overhead
- Immediate benefit

**Cons:**
- Lose ability to compare old vs new
- Risk of regression without baseline
- Can't A/B test

**Effort:** Medium (1-2 sessions)

---

### Option B: Champion-Challenger Framework (Recommended)

**Description:** Create V2 as a "challenger" model running alongside V1 "champion". Compare performance before promoting.

**Architecture:**
```
                    ┌─────────────────┐
                    │  Game Schedule  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Feature Engine  │
                    │  (shared data)  │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼────────┐          ┌────────▼────────┐
     │  V1 (Champion)  │          │  V2 (Challenger)│
     │  19 features    │          │  33 features    │
     │  XGBoost        │          │  XGBoost/CatBoost│
     └────────┬────────┘          └────────┬────────┘
              │                             │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │  Predictions    │
                    │  (both models)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Grading &     │
                    │   Comparison    │
                    └─────────────────┘
```

**Pros:**
- Safe comparison with existing baseline
- Can run both in production
- Data-driven promotion decision
- Easy rollback if V2 underperforms

**Cons:**
- More complex deployment
- Need to track two models
- Slightly higher compute cost

**Effort:** Medium-High (2-3 sessions)

---

### Option C: Ensemble Model

**Description:** Create V2 and combine predictions with V1 using weighted average or stacking.

**Pros:**
- Potentially higher accuracy
- Diversified predictions
- Reduces model-specific errors

**Cons:**
- Most complex to implement
- Harder to interpret
- Overkill for current stage

**Effort:** High (3-4 sessions)

---

## Recommendation: Option B (Champion-Challenger)

This mirrors the NBA approach and provides:
1. **Safety:** V1 continues as production model
2. **Validation:** V2 gets real-world testing
3. **Flexibility:** Promote V2 when proven better

---

## V2 Model Design

### Additional Features (14 new)

| Feature | Category | Data Source | Priority |
|---------|----------|-------------|----------|
| `f11_home_away_k_split` | Splits | pitcher_game_summary | High |
| `f12_day_night_split` | Splits | pitcher_game_summary | Medium |
| `f13_vs_opponent_history` | Matchup | pitcher_vs_team | High |
| `f15_opponent_team_k_rate` | Matchup | team_batting_stats | High |
| `f16_opponent_obp` | Matchup | team_batting_stats | Medium |
| `f17_ballpark_k_factor` | Context | ballpark_factors | High |
| `f27_platoon_advantage` | MLB-specific | lineup_analysis | High |
| `f28_umpire_k_adjustment` | Context | umpire_stats | Medium |
| `f29_projected_ip` | Prediction | workload_model | High |
| `f30_velocity_trend` | Advanced | statcast | Medium |
| `f31_whiff_rate` | Advanced | statcast | High |
| `f32_put_away_rate` | Advanced | statcast | High |
| `f18_game_total_line` | Context | odds_api | Low |
| `f34_matchup_edge_composite` | Composite | calculated | Medium |

### Algorithm Options

| Algorithm | Pros | Cons |
|-----------|------|------|
| **XGBoost** | Consistent with V1, proven | May not capture all patterns |
| **CatBoost** | Better categorical handling, NBA success | Different hyperparameters |
| **LightGBM** | Fast training, good accuracy | Less tested in this domain |

**Recommendation:** Try CatBoost (mirrors NBA success) with XGBoost as fallback.

### Training Data

| Dataset | Records | Date Range | Use |
|---------|---------|------------|-----|
| Training | ~6,000 | 2024-04 to 2025-06 | Model fitting |
| Validation | ~1,500 | 2025-07 to 2025-08 | Hyperparameter tuning |
| Test | ~1,000 | 2025-08 to 2025-09 | Final evaluation |

**Note:** Include 2025 data to address performance decline.

---

## Implementation Plan

### Phase 1: Feature Engineering (1 session)

1. Check which features are already available in analytics tables
2. Create missing features (umpire stats, ballpark factors)
3. Build feature extraction pipeline for V2

### Phase 2: Model Training (1 session)

1. Prepare training dataset with all 33 features
2. Train XGBoost and CatBoost models
3. Hyperparameter tuning
4. Evaluate on test set

### Phase 3: Integration (1 session)

1. Create `pitcher_strikeouts_predictor_v2.py`
2. Update prediction worker to run both models
3. Add `model_version` tracking in predictions table
4. Set up comparison dashboard

### Phase 4: Forward Validation (2-4 weeks)

1. Run both models on live games
2. Track performance by model version
3. Decision point: promote V2 if better

---

## Database Schema Updates

### Predictions Table

```sql
-- Add model comparison fields
ALTER TABLE mlb_predictions.pitcher_strikeouts
ADD COLUMN IF NOT EXISTS model_version STRING,
ADD COLUMN IF NOT EXISTS v2_predicted_strikeouts FLOAT,
ADD COLUMN IF NOT EXISTS v2_confidence FLOAT,
ADD COLUMN IF NOT EXISTS v2_recommendation STRING;
```

### Model Comparison View

```sql
CREATE OR REPLACE VIEW mlb_predictions.model_comparison AS
SELECT
    game_date,
    model_version,
    COUNT(*) as picks,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate,
    ROUND(AVG(ABS(actual_strikeouts - predicted_strikeouts)), 2) as mae
FROM mlb_predictions.pitcher_strikeouts
WHERE is_correct IS NOT NULL
GROUP BY game_date, model_version;
```

---

## Success Criteria for V2 Promotion

V2 becomes champion if (after 100+ picks):

| Metric | Threshold |
|--------|-----------|
| Hit Rate | >= V1 hit rate (67.27%) |
| MAE | <= V1 MAE (1.46) |
| High Edge Win Rate | >= 85% (edge > 1.5) |
| Sample Size | >= 100 picks |

---

## Timeline

| Week | Activity |
|------|----------|
| Pre-Season | Feature engineering, model training |
| Week 1 (Apr) | Deploy V1 + V2 in parallel |
| Week 2-3 | Collect comparison data |
| Week 4 | Evaluation and promotion decision |

---

## Decision Required

**Which approach should we take?**

- [ ] **Option A:** Upgrade V1 in-place (simpler, riskier)
- [x] **Option B:** Champion-Challenger framework (recommended)
- [ ] **Option C:** Ensemble model (complex, overkill)

**Next action:** Confirm approach, then start Phase 1 (feature engineering).
