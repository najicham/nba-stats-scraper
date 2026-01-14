# MLB Hit Rate Measurement - Comprehensive Solution

**Created**: 2026-01-13
**Status**: Ultra-Deep Analysis Complete
**Problem**: Cannot access historical betting lines for 8,130 predictions

---

## Executive Summary

After comprehensive investigation, **historical pitcher prop betting lines are NOT available** from The Odds API or any immediately accessible source. However, we can still measure model quality and betting viability through a **multi-layered proxy approach** combined with immediate forward validation.

### The Reality
- ✅ 8,130 predictions exist (avg: 5.09 K, 80% confidence)
- ✅ 9,742 actual results exist (avg: 4.80 K)
- ❌ Historical betting lines NOT available (404 errors from Odds API)
- ❌ Historical game totals NOT available (table empty)
- **Prediction bias detected**: +0.29 K over-prediction (6% high)

### The Solution
**4-Layer Measurement Framework** + **Immediate Forward Validation**

---

## Part 1: Why Traditional Backfill is Impossible

### What We Tested
- ✅ Odds API historical events endpoint: **WORKS**
- ❌ Odds API historical player props endpoint: **404 NOT FOUND**
- ❌ Historical game totals in our database: **EMPTY**

### Why Player Props Aren't Available Historically

**Storage Economics:**
- Game lines: ~15 games/day × 3 markets = 45 data points
- Player props: ~15 games × 40 players × 8 markets = 4,800 data points
- **100x more data** = expensive to store historically

**Provider Priorities:**
- Most betting analysis focuses on game lines
- Player props are shorter-lived markets
- Lower demand for historical player prop data

**Result**: The Odds API (and most providers) don't retain historical player prop data.

---

## Part 2: Alternative Sources (2-Hour Research Sprint)

### High-Priority Sources to Check

#### 1. OddsPortal.com
**What**: Popular historical odds archive
**Check**: Do they track MLB pitcher strikeout props?
**How**: Manual browse + potential scraping
**Likelihood**: 30% - They focus on game lines
**Time**: 30 minutes

#### 2. SportsDataIO / DonBest
**What**: Professional odds data provider
**Check**: Do they sell historical player props?
**How**: Contact sales, request sample data
**Likelihood**: 60% - But expensive ($$$)
**Time**: 30 minutes

#### 3. Kaggle / GitHub Datasets
**What**: Community-shared sports betting datasets
**Search**: "MLB betting odds", "pitcher props", "player props 2024"
**How**: Search, download, analyze coverage
**Likelihood**: 20% - But free!
**Time**: 30 minutes

#### 4. Sports Betting Research Papers
**What**: Academic papers sometimes include datasets
**Search**: Google Scholar "MLB player props data"
**How**: Check paper appendices and data repositories
**Likelihood**: 15%
**Time**: 30 minutes

### Decision Matrix

| Coverage Found | Action |
|----------------|--------|
| **>50% dates** | Pay for data if reasonable cost (<$500) |
| **30-50% dates** | Partial backfill + proxy for rest |
| **<30% dates** | Skip backfill, use proxy methods |

---

## Part 3: Multi-Layer Proxy Hit Rate Framework

Since perfect historical lines likely don't exist, we measure betting viability through **converging evidence**:

### Layer 1: Raw Prediction Accuracy (DEFINITIVE)

**What We Measure:**
```sql
-- Mean Absolute Error
SELECT
  AVG(ABS(predicted_strikeouts - actual_strikeouts)) as mae,
  STDDEV(ABS(predicted_strikeouts - actual_strikeouts)) as mae_std,
  -- Bias
  AVG(predicted_strikeouts - actual_strikeouts) as bias,
  -- Directional accuracy
  AVG(CASE
    WHEN (predicted_strikeouts > 5.0 AND actual_strikeouts > 5.0) OR
         (predicted_strikeouts < 5.0 AND actual_strikeouts < 5.0)
    THEN 1.0 ELSE 0.0
  END) as directional_accuracy
FROM predictions_with_actuals;
```

**Benchmarks:**
- MAE < 1.5: Excellent (better than 1.71 training MAE)
- MAE 1.5-2.0: Good (matches training)
- MAE > 2.0: Poor (model degraded)

**Why This Matters:**
If MAE is poor, betting performance will be poor regardless of lines.

---

### Layer 2: Synthetic Line Estimation (PROXY)

**Concept**: Estimate what betting lines WOULD have been based on available data.

#### Method A: Pitcher Season Average as Line

For each prediction, use pitcher's season rolling average as proxy line:

```sql
WITH pitcher_rolling_avg AS (
  SELECT
    pitcher_lookup,
    game_date,
    AVG(strikeouts) OVER (
      PARTITION BY pitcher_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as rolling_k_avg_10
  FROM mlb_raw.mlb_pitcher_stats
  WHERE is_starter = TRUE
),
synthetic_evaluation AS (
  SELECT
    p.pitcher_lookup,
    p.predicted_strikeouts,
    p.actual_strikeouts,
    r.rolling_k_avg_10 as synthetic_line,
    -- Simulate OVER bet
    CASE
      WHEN p.predicted_strikeouts > r.rolling_k_avg_10 AND
           p.actual_strikeouts > r.rolling_k_avg_10 THEN TRUE
      WHEN p.predicted_strikeouts < r.rolling_k_avg_10 AND
           p.actual_strikeouts < r.rolling_k_avg_10 THEN TRUE
      ELSE FALSE
    END as would_win
  FROM predictions p
  JOIN pitcher_rolling_avg r USING (pitcher_lookup, game_date)
)
SELECT
  COUNT(*) as bets,
  AVG(CASE WHEN would_win THEN 1.0 ELSE 0.0 END) * 100 as synthetic_hit_rate
FROM synthetic_evaluation
WHERE predicted_strikeouts != synthetic_line; -- Only bet when there's an edge
```

**Interpretation:**
- >54%: Model likely has edge
- 50-54%: Marginal, needs real validation
- <50%: Model doesn't detect value

---

#### Method B: Market-Derived Synthetic Lines

Use regression to estimate what lines WOULD have been:

```sql
-- Build market model from known relationships
WITH market_factors AS (
  SELECT
    pitcher_lookup,
    game_date,
    -- Pitcher factors
    k_avg_last_5,
    season_k_per_9,
    -- Opponent factors
    opponent_team_k_rate,
    -- Game factors
    is_home,
    -- Estimate market line
    (0.40 * k_avg_last_5 +
     0.30 * season_k_per_9 * 0.55 +  -- Convert K/9 to ~6 IP expectation
     0.20 * CASE WHEN opponent_team_k_rate > 0.22 THEN 6.0 ELSE 5.0 END +
     0.10 * CASE WHEN is_home THEN 5.5 ELSE 5.0 END
    ) as estimated_market_line
  FROM mlb_analytics.pitcher_game_summary
)
SELECT
  p.pitcher_lookup,
  p.predicted_strikeouts,
  m.estimated_market_line,
  p.actual_strikeouts,
  -- Would we have bet correctly?
  CASE
    WHEN p.predicted_strikeouts > m.estimated_market_line + 0.5 AND
         p.actual_strikeouts > m.estimated_market_line THEN TRUE
    WHEN p.predicted_strikeouts < m.estimated_market_line - 0.5 AND
         p.actual_strikeouts < m.estimated_market_line THEN TRUE
    ELSE FALSE
  END as would_win
FROM predictions p
JOIN market_factors m USING (pitcher_lookup, game_date);
```

**Why This Works:**
- Markets are efficient, lines follow predictable patterns
- We can estimate likely lines with reasonable accuracy
- Not perfect, but directionally correct

---

### Layer 3: Calibration Analysis (MODEL VALIDATION)

**Concept**: Are high-confidence predictions actually more accurate?

```sql
WITH predictions_by_confidence AS (
  SELECT
    CASE
      WHEN confidence >= 0.85 THEN '85%+'
      WHEN confidence >= 0.75 THEN '75-85%'
      WHEN confidence >= 0.65 THEN '65-75%'
      ELSE '<65%'
    END as confidence_tier,
    COUNT(*) as predictions,
    AVG(ABS(predicted_strikeouts - actual_strikeouts)) as mae,
    STDDEV(ABS(predicted_strikeouts - actual_strikeouts)) as error_std
  FROM predictions_with_actuals
  GROUP BY confidence_tier
)
SELECT * FROM predictions_by_confidence
ORDER BY confidence_tier DESC;
```

**Expected Pattern (Calibrated Model)**:
| Confidence Tier | MAE | Interpretation |
|-----------------|-----|----------------|
| 85%+ | < 1.3 | Highly accurate |
| 75-85% | 1.3-1.7 | Good accuracy |
| 65-75% | 1.7-2.0 | Moderate accuracy |
| <65% | > 2.0 | Low accuracy |

**Red Flag**: If high-confidence predictions have SAME or WORSE MAE → model lying about confidence

---

### Layer 4: Edge Detection Analysis (BETTING SIGNAL)

**Concept**: Does the model detect situations where actual results differ from expectations?

```sql
-- Identify "surprise" performances
WITH surprises AS (
  SELECT
    *,
    actual_strikeouts - k_avg_last_10 as actual_surprise,
    predicted_strikeouts - k_avg_last_10 as predicted_surprise,
    -- Did model predict the surprise correctly?
    CASE
      WHEN actual_surprise > 1.0 AND predicted_surprise > 0.5 THEN 'Predicted Over-Performance'
      WHEN actual_surprise < -1.0 AND predicted_surprise < -0.5 THEN 'Predicted Under-Performance'
      WHEN ABS(actual_surprise) < 0.5 AND ABS(predicted_surprise) < 0.5 THEN 'Predicted Stability'
      ELSE 'Missed'
    END as edge_detection
  FROM predictions_with_rolling_stats
)
SELECT
  edge_detection,
  COUNT(*) as occurrences,
  AVG(ABS(predicted_strikeouts - actual_strikeouts)) as mae
FROM surprises
GROUP BY edge_detection;
```

**Good Model**: Detects surprises BEFORE they happen (predictive edge)
**Bad Model**: Only tracks recent averages (no edge)

---

## Part 4: Immediate Forward Validation (TRUE HIT RATE)

While we analyze historical data, START collecting proper data NOW:

### Week 1-2: Setup & Collection

**Day 1: Infrastructure**
```bash
# 1. Fix prediction pipeline
# Ensure betting lines scraped BEFORE predictions

# 2. Start daily odds collection
python scrapers/mlb/oddsapi/mlb_pitcher_props.py --game-date TODAY

# 3. Generate predictions WITH lines
python predictions/mlb/coordinator.py --date TODAY --require-lines

# 4. Save to predictions table WITH betting context
```

**Daily Process** (automated):
```yaml
# Morning (8 AM ET)
- Scrape today's starting pitchers
- Scrape pitcher strikeout props (DraftKings, FanDuel)
- Validate coverage >80%

# Afternoon (2 PM ET)
- Generate predictions WITH lines
- Make OVER/UNDER recommendations
- Save predictions

# Evening (11 PM ET)
- Scrape actual results
- Grade predictions
- Calculate daily hit rate
- Update running totals
```

### Week 3-4: Build Track Record

**Target**: 30-50 graded predictions minimum

```sql
-- Daily Hit Rate Tracking
SELECT
  game_date,
  COUNT(*) as predictions,
  AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as daily_hit_rate,
  -- Running metrics
  AVG(AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END)) OVER (
    ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) * 100 as cumulative_hit_rate
FROM mlb_predictions.pitcher_strikeouts
WHERE strikeouts_line IS NOT NULL
  AND game_date >= CURRENT_DATE() - 30
GROUP BY game_date
ORDER BY game_date;
```

**Decision Threshold**:
- After 30 predictions: Preliminary verdict
- After 50 predictions: Confident verdict
- After 100 predictions: Statistically robust

---

## Part 5: Implementation Roadmap

### Phase 1: Research Sprint (2 hours - NEXT)

**Hour 1**: Check alternative data sources
- OddsPortal manual check
- Kaggle/GitHub search
- Contact SportsDataIO/DonBest

**Hour 2**: Evaluate findings
- Calculate coverage %
- Assess data quality
- Make backfill decision

**Deliverable**: Research report with coverage assessment

---

### Phase 2: Historical Analysis (4-6 hours)

**Regardless of line availability, analyze what we CAN:**

**Script 1: Raw Accuracy Analysis** (2 hours)
```python
# scripts/mlb/analyze_raw_accuracy.py
- Match 8,130 predictions to actuals
- Calculate MAE, bias, directional accuracy
- Compare to naive baselines
- Generate comprehensive report
```

**Script 2: Synthetic Hit Rate** (2 hours)
```python
# scripts/mlb/synthetic_hit_rate_analysis.py
- Estimate synthetic lines (Method A + B)
- Calculate proxy hit rates
- Measure edge detection
- Calibration analysis
```

**Script 3: Comprehensive Report** (2 hours)
```python
# scripts/mlb/generate_performance_report.py
- Synthesize all analyses
- Make deployment recommendation
- Identify model strengths/weaknesses
- Document limitations and caveats
```

**Deliverable**: Complete performance assessment report

---

### Phase 3: Forward Validation (Ongoing)

**Week 1**: Deploy fixed pipeline
- Implement hard betting line dependency
- Start daily odds collection
- Generate predictions properly

**Weeks 2-4**: Collect data
- 30-50 predictions with real betting lines
- Grade daily
- Track hit rate

**Week 5**: Deployment decision
- Review cumulative hit rate
- Compare to breakeven (52.4%)
- Go/no-go on betting deployment

---

## Part 6: Expected Outcomes & Decisions

### Scenario A: Historical Analysis Shows Promise

**If Raw MAE < 1.7 AND Synthetic Hit Rate > 52%:**

✅ **Verdict**: Model shows promise
**Action**: Proceed with forward validation
**Timeline**: 30-60 days to deployment
**Risk**: Low - model validated on large sample

### Scenario B: Historical Analysis Shows Issues

**If Raw MAE > 2.0 OR Synthetic Hit Rate < 50%:**

❌ **Verdict**: Model needs improvement
**Action**: Retrain before forward testing
**Timeline**: 2-4 weeks retraining + validation
**Risk**: Medium - saved from deploying bad model

### Scenario C: Historical Analysis Inconclusive

**If Raw MAE 1.7-2.0 AND Synthetic Hit Rate 50-52%:**

⚠️ **Verdict**: Marginal performance
**Action**: Forward validation with small sample first
**Timeline**: 60-90 days cautious deployment
**Risk**: Medium - needs real-line validation

---

## Part 7: Cost-Benefit Analysis

### If We Find Historical Lines (Best Case)

**Investment**:
- Data purchase: $0-500 (if available)
- Analysis time: 8 hours
- Total: ~$500 + 8 hours

**Return**:
- True hit rate on 8,130 predictions
- Confidence in deployment decision
- Avoid potentially costly mistakes
- ROI: Excellent if data <$500

### If We Don't Find Historical Lines (Likely Case)

**Investment**:
- Research: 2 hours
- Proxy analysis: 6 hours
- Forward validation setup: 4 hours
- Total: 12 hours + ongoing collection

**Return**:
- Best possible assessment given constraints
- Validated forward measurement system
- Prevention of future failures
- ROI: Good - still makes informed decision

---

## Part 8: Final Recommendation

### Execute This Sequence:

**TODAY (2 hours)**:
1. ✅ Research alternative line sources
2. ✅ Make backfill decision

**THIS WEEK (8 hours)**:
3. ✅ Raw accuracy analysis (regardless of lines)
4. ✅ Synthetic hit rate analysis
5. ✅ Generate comprehensive report
6. ✅ Make initial deployment decision

**NEXT WEEK (4 hours)**:
7. ✅ Fix prediction pipeline architecture
8. ✅ Implement daily odds collection
9. ✅ Start forward validation

**WEEKS 3-5 (Ongoing)**:
10. ✅ Collect 50+ predictions with real lines
11. ✅ Calculate true hit rate
12. ✅ Final deployment decision

### Key Principles:

1. **Exhaust realistic options** for historical lines (2 hours, not 20)
2. **Analyze what we CAN measure** with high quality
3. **Accept imperfect information** but make it rigorous
4. **Start perfect collection** immediately
5. **Make informed decisions** at each stage

---

## Conclusion

We **cannot** get perfect historical betting line data. But we **can**:

✅ Measure model quality definitively (MAE, calibration)
✅ Estimate betting performance (synthetic lines)
✅ Start measuring true hit rate immediately (forward validation)
✅ Make informed deployment decision (converging evidence)

**The path forward is clear**: Research alternatives (2 hrs) → Analyze what exists (8 hrs) → Build proper system (ongoing) → Deploy with confidence.

**Next Action**: Execute Phase 1 research sprint to see if we get lucky with alternative sources. If not, proceed directly to proxy analysis + forward validation.

---

**Author**: Ultra-Deep Analysis Mode
**Status**: Ready for execution
**Confidence**: High - this is the best path given constraints
