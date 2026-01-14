# Model Improvement Exploration Plan

**Date**: January 9, 2026
**Current State**: XGBoost v6 at 4.14 MAE (13.6% better than mock's 4.80)
**Goal**: Identify high-impact improvements through systematic exploration

---

## Current Model Performance

| Metric | v6 Value | Mock Baseline |
|--------|----------|---------------|
| Overall MAE | 4.14 | 4.80 |
| Within 3 pts | 49.4% | 40.6% |
| Within 5 pts | 70.1% | 61.7% |

### Known Issues
1. **DNP errors** - Predicting for players who don't play (832 predictions with 15+ error)
2. **High-scorer underprediction** - Regression toward mean (inherent to model)
3. **High-minute player variance** - More playing time = more variance

---

## EXPLORATION CATEGORIES

### Category 1: New Data Sources

| Data Source | Description | Expected Impact | Effort | Priority |
|-------------|-------------|-----------------|--------|----------|
| **Injury reports** | Daily injury status (out/questionable/probable) | HIGH - eliminates DNP errors | Medium | 🔴 HIGH |
| **Vegas player props** | Betting lines for points | MEDIUM - market wisdom | Low | 🟡 MEDIUM |
| **Lineup data** | Starting lineups, rotation patterns | HIGH - context for role | Medium | 🔴 HIGH |
| **Matchup history** | Player performance vs specific teams | MEDIUM - opponent-specific | Medium | 🟡 MEDIUM |
| **Play-by-play derived** | Shot quality, shot selection patterns | MEDIUM - more signal | High | 🟢 LOW |
| **Travel/schedule** | Distance traveled, timezone changes | LOW - minor factor | Low | 🟢 LOW |
| **Game importance** | Playoff implications, rivalry games | LOW - motivational | Low | 🟢 LOW |

### Category 2: Feature Engineering

| Feature Idea | Description | Hypothesis | Priority |
|--------------|-------------|------------|----------|
| **Minutes prediction** | Predict minutes first, then points/min | Separates playing time from efficiency | 🔴 HIGH |
| **Role stability** | How consistent is player's role? | Stable roles = more predictable | 🟡 MEDIUM |
| **Opponent pace matchup** | Team pace vs opponent pace delta | High pace delta = more variance | 🟡 MEDIUM |
| **Recent usage trend** | Is usage increasing or decreasing? | Trend matters for projections | 🟡 MEDIUM |
| **Blowout probability** | Expected game margin | Blowouts = reduced minutes for stars | 🟡 MEDIUM |
| **Hot hand indicator** | Streakiness detection | Momentum might matter | 🟢 LOW |
| **Teammate availability** | Key teammates in/out | More shots if star teammate out | 🔴 HIGH |

### Category 3: Model Architecture

| Approach | Description | Expected Benefit | Priority |
|----------|-------------|------------------|----------|
| **Ensemble v6 + mock** | Weighted average of both models | Best of both worlds | 🔴 HIGH |
| **Two-stage model** | Stage 1: Minutes, Stage 2: Points | Separate concerns | 🟡 MEDIUM |
| **Position-specific** | Train separate models by position | Position-specific patterns | 🟡 MEDIUM |
| **Player-cluster models** | Cluster similar players, train per cluster | Archetype-specific | 🟡 MEDIUM |
| **Quantile regression** | Predict 25th/50th/75th percentile | Uncertainty quantification | 🟢 LOW |
| **Neural network** | Deep learning approach | May find non-linear patterns | 🟢 LOW |

### Category 4: Error Analysis Deep Dives

| Analysis | Question to Answer | Priority |
|----------|-------------------|----------|
| **By player archetype** | Do guards/forwards/centers have different error patterns? | 🔴 HIGH |
| **By team context** | Do certain teams' players have higher error? | 🟡 MEDIUM |
| **By opponent defense** | Are errors correlated with defensive quality? | 🟡 MEDIUM |
| **By game script** | Do blowout games have different patterns? | 🟡 MEDIUM |
| **Temporal patterns** | Do errors increase as season progresses? | 🟢 LOW |
| **Day of week** | Any patterns by game day? | 🟢 LOW |

### Category 5: Data Quality Improvements

| Improvement | Description | Priority |
|-------------|-------------|----------|
| **DNP filtering** | Pre-filter unlikely-to-play players | 🔴 HIGH |
| **Outlier handling** | Detect and handle extreme games differently | 🟡 MEDIUM |
| **Season normalization** | Account for season-to-season drift | 🟡 MEDIUM |
| **Missing data imputation** | Better methods than median fill | 🟢 LOW |

---

## RECOMMENDED EXPLORATION ORDER

### Phase A: Quick Wins (1-2 hours each)

1. **A1: Ensemble v6 + Mock**
   - Combine predictions: `final = α * v6 + (1-α) * mock`
   - Test α values from 0.5 to 0.9
   - Expected: 2-5% improvement

2. **A2: Error Analysis by Player Type**
   - Segment errors by position, usage tier, minutes tier
   - Identify if certain player types are more predictable
   - May reveal opportunities for specialized models

3. **A3: DNP Impact Quantification**
   - Calculate MAE with DNPs excluded
   - Estimate potential improvement from perfect DNP detection
   - Prioritize injury data integration

### Phase B: Feature Engineering (2-4 hours each)

4. **B1: Minutes Prediction Model**
   - Build separate model to predict minutes
   - Use predicted minutes as feature for points
   - Or: predict points/minute and multiply

5. **B2: Teammate Availability Features**
   - When star player is out, teammates score more
   - Add features for key teammate status
   - Requires roster/lineup data

6. **B3: Role Stability Features**
   - Calculate variance in recent minutes/usage
   - Stable role = more predictable performance
   - Variable role = higher uncertainty

### Phase C: New Data Integration (4-8 hours each)

7. **C1: Injury Report Integration**
   - Parse injury reports for player status
   - Filter predictions for OUT players
   - Adjust for QUESTIONABLE/DOUBTFUL

8. **C2: Vegas Lines Integration**
   - Fetch player prop lines
   - Use as feature or benchmark
   - Market is often well-calibrated

9. **C3: Lineup Data Integration**
   - Starting lineup announcements
   - Historical lineup patterns
   - Rotation predictions

### Phase D: Advanced Modeling (4-8 hours each)

10. **D1: Position-Specific Models**
    - Train separate XGBoost for G/F/C
    - Different features may matter by position
    - Ensemble the results

11. **D2: Two-Stage Prediction**
    - Model 1: Predict minutes played
    - Model 2: Predict points given minutes
    - May improve on high-variance cases

12. **D3: Player Clustering + Cluster Models**
    - Cluster players by style/role
    - Train model per cluster
    - May capture archetype-specific patterns

---

## QUICK ANALYSIS QUERIES

### Query 1: MAE Excluding DNPs
```sql
-- What's our MAE if we perfectly filter DNPs?
SELECT
  AVG(ABS(predicted - actual)) as mae_all,
  AVG(CASE WHEN actual > 0 THEN ABS(predicted - actual) END) as mae_no_dnp,
  SUM(CASE WHEN actual = 0 THEN 1 ELSE 0 END) as dnp_count
FROM predictions
```

### Query 2: Error by Position
```sql
SELECT
  position,
  AVG(ABS(predicted - actual)) as mae,
  COUNT(*) as games
FROM predictions p
JOIN players pl ON p.player_lookup = pl.player_lookup
GROUP BY position
ORDER BY mae
```

### Query 3: Error by Usage Tier
```sql
SELECT
  CASE
    WHEN usage_rate < 15 THEN 'Low (<15%)'
    WHEN usage_rate < 25 THEN 'Medium (15-25%)'
    ELSE 'High (>25%)'
  END as usage_tier,
  AVG(ABS(predicted - actual)) as mae,
  AVG(predicted - actual) as bias,
  COUNT(*) as games
FROM predictions
GROUP BY 1
ORDER BY 1
```

### Query 4: Mock vs v6 by Segment
```sql
SELECT
  segment,
  AVG(ABS(mock_pred - actual)) as mock_mae,
  AVG(ABS(v6_pred - actual)) as v6_mae,
  COUNT(*) as games
FROM predictions
GROUP BY segment
-- Find where mock beats v6
```

---

## IMPLEMENTATION CHECKLIST

### Immediate (Today)
- [ ] Run ensemble v6 + mock experiment
- [ ] Quantify DNP impact on MAE
- [ ] Error analysis by player type

### Short-term (This Week)
- [ ] Build minutes prediction model
- [ ] Analyze teammate availability impact
- [ ] Research injury data sources

### Medium-term (Next 2 Weeks)
- [ ] Integrate injury reports
- [ ] Test position-specific models
- [ ] Explore Vegas lines as feature

### Long-term (Month+)
- [ ] Build comprehensive lineup model
- [ ] Player clustering system
- [ ] Production A/B testing framework

---

## SUCCESS METRICS

| Milestone | Target MAE | Improvement vs Mock |
|-----------|------------|---------------------|
| Current v6 | 4.14 | 13.6% |
| Phase A complete | 4.00 | 16.7% |
| Phase B complete | 3.85 | 19.8% |
| Phase C complete | 3.70 | 22.9% |
| Ultimate goal | 3.50 | 27.1% |

---

## NEXT STEPS

1. **Start with A1**: Ensemble v6 + mock (30 min)
2. **Then A3**: Quantify DNP impact (30 min)
3. **Based on findings**: Prioritize next experiments

Would you like to start with the ensemble experiment?
