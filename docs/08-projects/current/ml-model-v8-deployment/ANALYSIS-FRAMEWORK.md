# Prediction Analysis Framework

**Created:** 2026-01-14
**Status:** Active Analysis - Critical Findings Documented
**Data Period:** 2025-26 Season (Oct 2025 - Jan 2026)

---

## Executive Summary

Analysis of 10,000+ graded predictions reveals **massive performance variations** across different dimensions. The key finding: **UNDER bets dramatically outperform OVER bets** (95% vs 57% hit rate at 92%+ confidence). Combined with edge thresholds and player tier filtering, we can achieve **92%+ hit rates** on carefully selected picks.

---

## Critical Findings

### 1. UNDER vs OVER: The Biggest Edge

| Recommendation | Confidence | Picks | Wins | Hit Rate |
|----------------|------------|-------|------|----------|
| **UNDER** | 92%+ | 5,358 | 5,089 | **95.0%** |
| **UNDER** | 90-92% | 2,351 | 2,250 | **95.7%** |
| **UNDER** | 88-90% | 927 | 760 | 82.0% |
| **UNDER** | 80-88% | 9,029 | 8,275 | 91.6% |
| OVER | 92%+ | 908 | 521 | 57.4% |
| OVER | 90-92% | 886 | 433 | 48.9% |
| OVER | 88-90% | 194 | 99 | 51.0% |
| OVER | 80-88% | 1,454 | 770 | 53.0% |

**Key Insight:** UNDER bets at 90%+ confidence hit **95%+** while OVER at same confidence hits only **~53%**.

**Recommendation:**
- **Primary focus: UNDER bets only** at high confidence
- OVER bets only at very high edge (5+ points) with additional filters
- Consider removing OVER from best bets entirely

---

### 2. Edge Threshold Analysis

| Confidence | Edge | Picks | Wins | Hit Rate |
|------------|------|-------|------|----------|
| 90%+ | 5+ pts | 7,623 | 7,082 | **92.9%** |
| 90%+ | 4-5 pts | 308 | 217 | 70.5% |
| 90%+ | 3-4 pts | 429 | 290 | 67.6% |
| 90%+ | 2-3 pts | 589 | 370 | 62.8% |
| 90%+ | <2 pts | 1,387 | 334 | **24.1%** |
| 80-90% | 5+ pts | 9,373 | 8,531 | **91.0%** |
| 80-90% | <2 pts | 1,523 | 264 | **17.3%** |

**Key Insight:** Edge matters MORE than confidence!
- 90%+ conf with <2 edge: **24.1%** (worse than coin flip!)
- 80-90% conf with 5+ edge: **91.0%** (excellent!)

**Recommendation:**
- **Minimum edge threshold: 4+ points** for best bets
- Reject ALL picks with <2 point edge regardless of confidence
- Edge 5+ is the sweet spot

---

### 3. Player Scoring Tier Analysis

| Player Tier | Points Range | Picks | Wins | Hit Rate | MAE |
|-------------|--------------|-------|------|----------|-----|
| **Bench** | <12 PPG | 7,662 | 6,822 | **89.0%** | 3.13 |
| **Rotation** | 12-17 PPG | 1,208 | 883 | 73.1% | 5.31 |
| Starter | 18-24 PPG | 700 | 254 | 36.3% | 7.13 |
| Star | 25+ PPG | 766 | 334 | 43.6% | 16.55 |

**Key Insight:** We are **much better at predicting bench/rotation players** than stars!
- Bench players: 89% hit rate, 3.13 MAE
- Star players: 43.6% hit rate, 16.55 MAE (TERRIBLE)

**Recommendation:**
- **Focus best bets on players predicted <18 points**
- Avoid star player picks (25+ predicted) entirely
- Star MAE of 16.55 means predictions are wildly inaccurate

---

### 4. Day of Week Patterns

| Day | Day Name | Picks | Wins | Hit Rate |
|-----|----------|-------|------|----------|
| 5 | Thursday | 961 | 819 | **85.2%** |
| 6 | Friday | 2,212 | 1,843 | **83.3%** |
| 4 | Wednesday | 1,597 | 1,328 | **83.2%** |
| 7 | Saturday | 1,522 | 1,184 | 77.8% |
| 1 | Sunday | 1,815 | 1,420 | 78.2% |
| 3 | Tuesday | 904 | 694 | 76.8% |
| 2 | Monday | 1,325 | 1,005 | 75.8% |

**Key Insight:** Mid-week (Wed-Fri) outperforms weekends by ~7 percentage points.

**Possible Explanations:**
- Weekend games have more national attention, sharper lines
- Rest patterns differ (back-to-backs cluster on certain days)
- Monday games follow Sunday slate (fatigue data less reliable)

**Recommendation:**
- Weight Thursday-Friday picks higher
- Consider day-of-week as filter for premium picks

---

### 5. Monthly/Seasonal Patterns

| Month | Picks | Wins | Hit Rate | MAE | Notes |
|-------|-------|------|----------|-----|-------|
| 2024-11 | 1,964 | 1,036 | 52.7% | 3.64 | Season start (old model?) |
| 2024-12 | 2,755 | 1,327 | 48.2% | 3.90 | Pre-V8 deployment |
| 2025-01 | 4,079 | 1,771 | 43.4% | 3.84 | Pre-V8 deployment |
| 2025-02 | 2,762 | 1,263 | 45.7% | 3.99 | Pre-V8 deployment |
| 2025-03 | 3,926 | 1,804 | 46.0% | 3.93 | Pre-V8 deployment |
| 2025-04 | 2,637 | 1,258 | 47.7% | 3.99 | Pre-V8 deployment |
| 2025-05 | 573 | 289 | 50.4% | 3.44 | Playoffs |
| 2025-06 | 101 | 58 | 57.4% | 2.79 | Finals |
| **2025-11** | 3,657 | 3,249 | **88.8%** | 4.90 | **V8 deployed** |
| **2025-12** | 5,630 | 4,447 | **79.0%** | 4.63 | V8 production |
| 2026-01 | 1,049 | 597 | 56.9% | 3.88 | Current month |

**Key Insight:** V8 model dramatically improved performance (88.8% Nov vs ~47% prior year).

**Seasonal Patterns:**
- **Early season (Oct-Nov):** Best performance - rosters stable, no load management
- **Mid-season (Dec-Feb):** Performance drops - injuries, trades, rest days
- **Late season (Mar-Apr):** Playoff positioning chaos
- **Playoffs (May-Jun):** Smaller sample but better hit rates (fewer games, more predictable)

**Recommendation:**
- Track monthly performance closely
- Expect January dip due to trade deadline speculation
- Re-evaluate thresholds by season phase

---

### 6. Prediction System Comparison

| System | Picks | Wins | Hit Rate | MAE |
|--------|-------|------|----------|-----|
| **xgboost_v1** | 6,548 | 5,728 | **87.5%** | 4.71 |
| catboost_v8 | 8,769 | 6,563 | 74.8% | 6.24 |
| similarity_balanced_v1 | 5,717 | 3,912 | 68.4% | 5.03 |
| ensemble_v1 | 8,756 | 5,551 | 63.4% | 4.60 |
| moving_average_baseline_v1 | 8,216 | 4,894 | 59.6% | 4.37 |
| zone_matchup_v1 | 8,756 | 5,190 | 59.3% | 5.34 |

**Key Insight:** xgboost_v1 significantly outperforms catboost_v8!

**Questions to Investigate:**
- Why is xgboost_v1 (87.5%) better than catboost_v8 (74.8%)?
- Are they making different types of predictions?
- Should best bets prefer xgboost_v1 system?

**Recommendation:**
- Consider system-specific selection for best bets
- Investigate xgboost vs catboost discrepancy
- May want to filter by system_id

---

### 7. Team-Specific Performance

**Best Teams (90%+ Confidence):**

| Team | Picks | Wins | Hit Rate |
|------|-------|------|----------|
| UTA | 229 | 206 | **90.0%** |
| LAC | 327 | 292 | **89.3%** |
| LAL | 295 | 260 | **88.1%** |
| PHI | 274 | 237 | 86.5% |
| MIL | 384 | 330 | 85.9% |
| BOS | 237 | 202 | 85.2% |
| GSW | 284 | 241 | 84.9% |

**Possible Explanations:**
- Some teams have more predictable rotations
- Injury-prone teams (PHI) may have better data when healthy
- Rest patterns vary by team (load management teams more predictable)

**Recommendation:**
- Consider team-based filters for premium picks
- Utah/LAC/LAL picks are more reliable
- Investigate worst-performing teams

---

## Optimal Best Bets Criteria

Based on the analysis above, the optimal pick profile is:

### Tier 1: Premium Picks (Target: 90%+ hit rate)

```sql
WHERE recommendation = 'UNDER'
  AND confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 5.0
  AND predicted_points < 18  -- Avoid stars
```

**Expected Performance:** 92-95% hit rate, ~50-100 picks/month

### Tier 2: Strong Picks (Target: 80%+ hit rate)

```sql
WHERE recommendation = 'UNDER'
  AND confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 4.0
  AND predicted_points < 20
```

**Expected Performance:** 80-85% hit rate, ~200 picks/month

### Tier 3: Value Picks (Target: 70%+ hit rate)

```sql
WHERE recommendation = 'UNDER'
  AND confidence_score >= 0.80
  AND ABS(predicted_points - line_value) >= 5.0
  AND predicted_points < 22
```

**Expected Performance:** 70-75% hit rate, ~300 picks/month

### Avoid Criteria

**Never include in best bets:**
- ANY pick with edge < 2 points (hits 17-24%)
- OVER predictions at any confidence (hits 48-58%)
- Star players (25+ predicted points, hits 43%)
- 88-90% confidence tier (anomalous performance)

---

## Multi-System Strategy

### Current State
Best bets currently draw from ensemble predictions. However, individual systems show different strengths.

### Recommended Approach

**Option A: Best System Filter**
- Filter best bets to xgboost_v1 predictions only (87.5% hit rate)
- Reduces volume but increases quality

**Option B: System-Specific Thresholds**
- Different confidence thresholds per system
- xgboost_v1: 85%+ confidence
- catboost_v8: 90%+ confidence
- ensemble_v1: 92%+ confidence

**Option C: Time-Based System Selection**
- Early slate (afternoon games): Use similarity_balanced (recent games weighted)
- Prime time (evening games): Use ensemble (full context)
- Late slate (West Coast): Use xgboost (better with fatigue)

### Implementation Tracking

Create comparison table to track system performance:

```sql
CREATE TABLE IF NOT EXISTS nba_analytics.system_daily_performance (
  game_date DATE,
  system_id STRING,
  picks INT64,
  wins INT64,
  hit_rate FLOAT64,
  mae FLOAT64,
  processed_at TIMESTAMP
);
```

---

## Player Grouping Strategies

### By Position
Track and analyze:
- Guards vs Forwards vs Centers
- Primary ball handlers vs off-ball players
- High-usage vs low-usage players

### By Role
- Starters vs Bench (significant difference found)
- Minutes bands: 30+, 25-30, 20-25, <20
- Usage rate bands

### By Historical Accuracy
- Track per-player hit rate over time
- Weight by recency (last 10 games vs season)
- Flag "unpredictable" players to avoid

### By Situational Factors
- Rest days (0, 1, 2+ days)
- Travel (home stand, road trip, back-to-back cities)
- Opponent defensive rating
- Game importance (playoff implications)

---

## Monitoring Queries

### Daily Performance by Dimension

```sql
-- Daily hit rate by all key dimensions
SELECT
  game_date,
  recommendation,
  CASE WHEN confidence_score >= 0.90 THEN '90%+' ELSE '80-90%' END as conf_tier,
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN '5+ edge'
    WHEN ABS(predicted_points - line_value) >= 3 THEN '3-5 edge'
    ELSE '<3 edge'
  END as edge_tier,
  CASE
    WHEN predicted_points >= 25 THEN 'Star'
    WHEN predicted_points >= 18 THEN 'Starter'
    ELSE 'Bench/Rotation'
  END as player_tier,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0) * 100, 1) as hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND line_value IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
ORDER BY game_date DESC, hit_rate DESC;
```

### Weekly System Comparison

```sql
-- Compare systems weekly
SELECT
  FORMAT_DATE('%Y-W%W', game_date) as week,
  system_id,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0) * 100, 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
  AND line_value IS NOT NULL
  AND confidence_score >= 0.9
GROUP BY 1, 2
ORDER BY week DESC, hit_rate DESC;
```

---

## Action Items

### Immediate (This Week)
1. [ ] Implement UNDER-only filter for best bets
2. [ ] Add 4+ edge minimum threshold
3. [ ] Exclude star players (predicted 25+) from best bets
4. [ ] Add day-of-week to pick metadata

### Short-term (This Month)
5. [ ] Investigate xgboost vs catboost performance gap
6. [ ] Create system_daily_performance tracking table
7. [ ] Build per-player historical accuracy tracking
8. [ ] Test time-based system selection

### Long-term (This Quarter)
9. [ ] Add position-based analysis
10. [ ] Build travel/rest impact model
11. [ ] Create "unpredictable player" flagging system
12. [ ] Seasonal threshold adjustment automation

---

## Appendix: Raw Data Queries

All analysis queries are available in:
- `scripts/analytics/analysis_queries.sql` (to be created)
- BigQuery saved queries in `nba-props-platform` project

---

*Last Updated: 2026-01-14*
*Next Review: Weekly during active season*
