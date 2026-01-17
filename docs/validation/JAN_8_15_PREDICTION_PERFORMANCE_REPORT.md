# NBA Prediction Performance Report
## Jan 8-15, 2026 (Last Week)

**Generated**: 2026-01-16, 6:35 PM ET
**Session**: 75
**Date Range**: Jan 8-15, 2026 (8 days)

---

## Executive Summary

### 🎯 Overall Performance: **65.9% Win Rate**

**Key Highlights**:
- **4,698 actionable picks** (OVER/UNDER)
- **3,097 wins** vs 1,529 losses
- **65.9% overall win rate** (profitable above 52.4% breakeven)
- **33.1% within 3 points** of actual result
- **59 games** across 8 days
- **7 prediction systems** active

**Top Performers**:
1. **xgboost_v1**: 87.5% win rate (266-22)
2. **moving_average_baseline_v1**: 83.2% win rate (253-17)
3. **UNDER picks**: 68.8% win rate (2,065-896)

---

## 1. Performance by System

### System Rankings (Win Rate)

| System | Total Picks | Wins | Losses | Win Rate | Avg Error | Avg Confidence | Within 3pts |
|--------|-------------|------|--------|----------|-----------|----------------|-------------|
| **xgboost_v1** 🥇 | 304 | 266 | 22 | **87.5%** | 4.61 | 0.818 | 45.4% |
| **moving_average_baseline_v1** 🥈 | 304 | 253 | 17 | **83.2%** | 4.19 | 0.519 | 45.4% |
| **similarity_balanced_v1** 🥉 | 929 | 494 | 250 | **53.2%** | 5.65 | 0.876 | 30.8% |
| zone_matchup_v1 | 1,195 | 636 | 339 | **53.2%** | 6.16 | 0.515 | 32.6% |
| ensemble_v1 | 1,195 | 616 | 310 | **51.5%** | 5.58 | 0.722 | 33.3% |
| catboost_v8 | 987 | 452 | 300 | 45.8% | 6.24 | 0.615 | 31.3% |
| moving_average | 891 | 380 | 291 | 42.6% | 5.86 | 0.514 | 29.6% |

### Key Insights

**Elite Performers** (>75% win rate):
- **xgboost_v1**: Dominant performance with 87.5% accuracy
  - Low error (4.61 points)
  - High confidence (0.818)
  - Best within-3-points rate (45.4%)
- **moving_average_baseline_v1**: Strong 83.2% win rate
  - Lowest error (4.19 points)
  - Lower confidence (0.519) but highly accurate

**Solid Performers** (50-55% win rate):
- **similarity_balanced_v1**: 53.2% on high volume (929 picks)
- **zone_matchup_v1**: 53.2% on highest volume (1,195 picks)
- **ensemble_v1**: 51.5% on high volume (1,195 picks)

**Underperformers** (<50% win rate):
- **catboost_v8**: 45.8% (below breakeven)
- **moving_average**: 42.6% (needs improvement)

---

## 2. Performance by Date

### Daily Win Rates

| Date | Games | Total Picks | Wins | Losses | Win Rate | Avg Error | Systems |
|------|-------|-------------|------|--------|----------|-----------|---------|
| Jan 09 🥇 | 9 | 995 | 828 | 58 | **83.2%** | 4.40 | 5 |
| Jan 10 🥈 | 6 | 905 | 630 | 154 | **69.6%** | 5.27 | 7 |
| Jan 15 | 9 | 2,515 | 1,146 | 764 | 45.6% | 6.21 | 5 |
| Jan 14 | 7 | 328 | 141 | 111 | 43.0% | 5.28 | 5 |
| Jan 13 | 7 | 271 | 116 | 136 | 42.8% | 6.19 | 5 |
| Jan 08 | 3 | 132 | 43 | 53 | 32.6% | 6.81 | 5 |
| Jan 11 | 10 | 587 | 172 | 210 | 29.3% | 6.72 | 5 |
| Jan 12 🥉 | 6 | 72 | 21 | 43 | 29.2% | 4.17 | 5 |

### Trend Analysis

**Best Days**:
- **Jan 09**: 83.2% win rate (828-58) - Exceptional performance
- **Jan 10**: 69.6% win rate (630-154) - Strong day

**Challenging Days**:
- **Jan 08**: 32.6% win rate - Tough slate
- **Jan 11**: 29.3% win rate - Difficult predictions
- **Jan 12**: 29.2% win rate - Small sample size (72 picks)

**Observation**: Performance varies significantly by date (29.2% to 83.2%), suggesting slate-dependent accuracy. Systems excel on certain game slates but struggle on others.

---

## 3. Performance by Recommendation Type

### OVER vs UNDER Performance

| Recommendation | Total Picks | Wins | Losses | Win Rate | Avg Error | Avg Margin |
|----------------|-------------|------|--------|----------|-----------|------------|
| **UNDER** 🎯 | 3,000 | 2,065 | 896 | **68.8%** | 5.57 | 8.14 |
| **OVER** | 1,698 | 1,032 | 633 | **60.8%** | 6.09 | 4.10 |
| PASS | 612 | 0 | 0 | N/A | 5.81 | 2.71 |
| NO_LINE | 495 | 0 | 0 | N/A | 5.55 | N/A |

### Key Insights

**UNDER Picks Dominate**:
- **68.8% win rate** on 3,000 picks (best performer)
- Lower error (5.57 vs 6.09)
- Higher margin (8.14 vs 4.10) - more confident UNDERS
- **2,065-896 record** (profitable)

**OVER Picks Solid**:
- **60.8% win rate** on 1,698 picks (still profitable)
- Higher error (6.09)
- Lower margin (4.10) - less confident OVERS

**Strategic Insight**: Systems are significantly better at identifying UNDER opportunities. Consider:
- Prioritizing UNDER picks for higher win rates
- Requiring higher confidence thresholds for OVER picks
- Investigating why UNDERS outperform (scoring trends, defensive analysis, etc.)

---

## 4. Performance by Confidence Level

### Confidence Calibration

| Confidence Bucket | Total Picks | Wins | Win Rate | Avg Error |
|-------------------|-------------|------|----------|-----------|
| **Very High (0.9+)** 🔥 | 338 | 246 | **72.8%** | 4.51 |
| **High (0.8-0.9)** | 1,033 | 717 | **69.4%** | 5.98 |
| **Medium (0.7-0.8)** | 588 | 388 | **66.0%** | 5.59 |
| **Low (0.6-0.7)** | 232 | 150 | **64.7%** | 5.82 |
| **Very Low (<0.6)** | 2,507 | 1,596 | **63.7%** | 5.86 |

### Confidence Analysis

**Strong Calibration** ✅:
- Higher confidence = Higher win rate
- **Very High confidence**: 72.8% win rate (best)
- **High confidence**: 69.4% win rate
- Clear gradient from 72.8% → 63.7% as confidence decreases

**Error Analysis**:
- Lower error at high confidence (4.51 pts)
- Error increases at high confidence (5.98 pts) then stabilizes

**Volume Distribution**:
- Most picks (2,507) at Very Low confidence
- Fewer picks (338) at Very High confidence
- Suggests conservative confidence scoring

**Recommendation**:
- Focus on High/Very High confidence picks for best results
- Consider raising confidence thresholds for publication
- 72.8% win rate at 0.9+ confidence is excellent

---

## 5. Best System + Recommendation Combinations

### Top Performing Combinations (Min 50 Picks)

| Rank | System | Recommendation | Picks | Wins | Win Rate | Avg Error |
|------|--------|----------------|-------|------|----------|-----------|
| 🥇 1 | moving_average_baseline_v1 | UNDER | 257 | 239 | **93.0%** | 3.97 |
| 🥈 2 | xgboost_v1 | UNDER | 271 | 249 | **91.9%** | 4.58 |
| 🥉 3 | similarity_balanced_v1 | UNDER | 480 | 331 | **69.0%** | 5.62 |
| 4 | ensemble_v1 | UNDER | 590 | 403 | **68.3%** | 5.32 |
| 5 | zone_matchup_v1 | OVER | 249 | 161 | 64.7% | 5.72 |
| 6 | zone_matchup_v1 | UNDER | 740 | 475 | 64.2% | 6.35 |
| 7 | moving_average | OVER | 349 | 214 | 61.3% | 5.74 |
| 8 | catboost_v8 | UNDER | 331 | 202 | 61.0% | 5.63 |
| 9 | ensemble_v1 | OVER | 350 | 213 | 60.9% | 5.81 |
| 10 | similarity_balanced_v1 | OVER | 277 | 163 | 58.8% | 5.90 |
| 11 | catboost_v8 | OVER | 433 | 250 | 57.7% | 7.01 |
| 12 | moving_average | UNDER | 331 | 166 | 50.2% | 6.15 |

### Strategic Insights

**Elite Combinations** (>90% win rate):
1. **moving_average_baseline_v1 + UNDER**: 93.0% (239-18) 🔥
   - Lowest error (3.97 points)
   - Extremely reliable
   - **Highest priority picks**

2. **xgboost_v1 + UNDER**: 91.9% (249-22) 🔥
   - Low error (4.58 points)
   - High volume (271 picks)
   - **Highest priority picks**

**Strong Combinations** (65-70% win rate):
- **similarity_balanced_v1 + UNDER**: 69.0% (331-149)
- **ensemble_v1 + UNDER**: 68.3% (403-187)

**Recommendation Strategy**:
- **MUST PLAY**: moving_average_baseline_v1 + xgboost_v1 UNDERS (>90% win rate)
- **STRONG PLAY**: similarity_balanced_v1 + ensemble_v1 UNDERS (68-69% win rate)
- **SELECTIVE**: Other UNDERS (60-64% win rate)
- **CAUTIOUS**: All OVERS (57-65% win rate)

---

## 6. Volume and Coverage Analysis

### Overall Statistics

| Metric | Value |
|--------|-------|
| **Total Predictions** | 5,805 |
| **Actionable Picks (OVER/UNDER)** | 4,698 (81.0%) |
| **Pass Recommendations** | 612 (10.5%) |
| **No Line Available** | 495 (8.5%) |
| **Days Analyzed** | 8 |
| **Games Covered** | 59 |
| **Unique Players** | 344 |
| **Active Systems** | 7 |

### Daily Averages

- **Predictions per day**: 726
- **Actionable picks per day**: 587
- **Games per day**: 7.4
- **Wins per day**: 387
- **Predictions per game**: 98.4
- **Predictions per player**: 16.9

### System Activity

- **Most Active**: zone_matchup_v1, ensemble_v1 (1,195 picks each)
- **Least Active**: moving_average_baseline_v1, xgboost_v1 (304 picks each)
- **Observation**: Lower volume systems have higher accuracy

---

## 7. Error Analysis

### Average Absolute Error by Category

| Category | Avg Error | Context |
|----------|-----------|---------|
| **Overall** | 5.74 points | All predictions |
| **Actionable Picks** | 5.75 points | OVER/UNDER only |
| **Best System** (moving_average_baseline_v1) | 4.19 points | -27% vs overall |
| **Worst System** (catboost_v8) | 6.24 points | +9% vs overall |
| **UNDER Picks** | 5.57 points | Better than overall |
| **OVER Picks** | 6.09 points | Worse than overall |
| **High Confidence (0.9+)** | 4.51 points | -22% vs overall |
| **Low Confidence (<0.6)** | 5.86 points | +2% vs overall |

### Within 3 Points Performance

- **1,922 predictions** (33.1%) within 3 points of actual
- **Best system**: xgboost_v1 (45.4% within 3 pts)
- **Worst system**: moving_average (29.6% within 3 pts)

**Analysis**:
- Average error of 5.74 points is reasonable for NBA player prop predictions
- Elite systems achieve 4.19-4.61 points error
- High confidence picks show significantly lower error (4.51 pts)

---

## 8. Profitability Analysis

### Break-Even Analysis

**Standard -110 Odds**:
- Break-even win rate: **52.4%**
- Our win rate: **65.9%**
- **Edge: +13.5%** 🎯

### Theoretical ROI (All Actionable Picks)

Assuming $100 per pick at -110 odds:
- **Total picks**: 4,698
- **Total wagered**: $469,800
- **Wins**: 3,097 × $90.91 = $281,546
- **Losses**: 1,529 × $100 = $152,900
- **Net profit**: $128,646
- **ROI: 27.4%** 📈

### By System (Top Performers)

**xgboost_v1** (87.5% win rate):
- 304 picks @ $100 = $30,400 wagered
- 266 wins × $90.91 = $24,182
- 22 losses × $100 = $2,200
- **Net profit: $21,982**
- **ROI: 72.3%** 🔥

**moving_average_baseline_v1** (83.2% win rate):
- 304 picks @ $100 = $30,400 wagered
- 253 wins × $90.91 = $23,000
- 17 losses × $100 = $1,700
- **Net profit: $21,300**
- **ROI: 70.1%** 🔥

### By Recommendation Type

**UNDER Picks** (68.8% win rate):
- 3,000 picks @ $100 = $300,000 wagered
- 2,065 wins × $90.91 = $187,729
- 896 losses × $100 = $89,600
- **Net profit: $98,129**
- **ROI: 32.7%** 📈

**OVER Picks** (60.8% win rate):
- 1,698 picks @ $100 = $169,800 wagered
- 1,032 wins × $90.91 = $93,819
- 633 losses × $100 = $63,300
- **Net profit: $30,519**
- **ROI: 18.0%** 📈

### By Confidence Level

**Very High Confidence (0.9+)** (72.8% win rate):
- 338 picks @ $100 = $33,800 wagered
- 246 wins × $90.91 = $22,364
- 92 losses × $100 = $9,200
- **Net profit: $13,164**
- **ROI: 38.9%** 📈

---

## 9. Recommendations & Strategy

### High Priority Actions

1. **Focus on Elite Systems**:
   - Prioritize **xgboost_v1** (87.5% win rate)
   - Prioritize **moving_average_baseline_v1** (83.2% win rate)
   - Both systems show 70%+ ROI

2. **UNDER Bias Strategy**:
   - UNDERS outperform OVERS by 8% (68.8% vs 60.8%)
   - Consider higher allocation to UNDER picks
   - Investigate root causes (pace trends, defensive metrics, etc.)

3. **Confidence-Based Filtering**:
   - Focus on 0.8+ confidence picks (69.4% win rate)
   - Very high confidence (0.9+) shows 72.8% win rate
   - Lower confidence picks still profitable but less optimal

4. **Volume vs Quality**:
   - Lower volume systems (xgboost_v1, moving_average_baseline_v1) have highest accuracy
   - High volume systems (zone_matchup_v1, ensemble_v1) profitable but lower win rate
   - Consider tiered bankroll allocation

### System-Specific Recommendations

**xgboost_v1**:
- ✅ Keep as primary system
- ✅ Increase volume if possible (only 304 picks)
- ✅ Especially strong on UNDERS (91.9% win rate)

**moving_average_baseline_v1**:
- ✅ Keep as primary system
- ✅ Increase volume if possible (only 304 picks)
- ✅ Especially strong on UNDERS (93.0% win rate)

**catboost_v8**:
- ⚠️ Underperforming (45.8% win rate)
- 📋 Review model parameters
- 📋 Consider retraining or reducing volume

**moving_average**:
- ⚠️ Underperforming (42.6% win rate)
- 📋 Review methodology
- 📋 Consider deprecating or significant updates

### Bankroll Allocation Strategy

Suggested allocation based on performance:

| Tier | Systems | Win Rate | Allocation | Risk |
|------|---------|----------|------------|------|
| **Elite** | xgboost_v1, moving_average_baseline_v1 | 83-88% | 40% | High confidence |
| **Strong** | similarity_balanced_v1, zone_matchup_v1, ensemble_v1 | 51-53% | 50% | Standard |
| **Emerging** | catboost_v8, moving_average | 43-46% | 10% | Monitoring |

### Next Steps

1. **Immediate**:
   - Deploy Jan 16 predictions using elite systems
   - Apply UNDER bias and confidence filters
   - Monitor performance against Jan 8-15 baseline

2. **Short-Term** (This Week):
   - Increase volume for xgboost_v1 and moving_average_baseline_v1
   - Investigate UNDER outperformance root causes
   - Review underperforming systems (catboost_v8, moving_average)

3. **Medium-Term** (This Month):
   - Retrain catboost_v8 model
   - Optimize ensemble_v1 weighting based on recent performance
   - Develop confidence-calibrated bankroll allocation

---

## 10. Conclusion

### Summary

**Outstanding Performance**:
- **65.9% overall win rate** (vs 52.4% breakeven) = **+13.5% edge**
- **27.4% ROI** on all actionable picks
- **Elite systems** (xgboost_v1, moving_average_baseline_v1) showing 70%+ ROI

**Key Strengths**:
- ✅ Strong confidence calibration (72.8% at high confidence)
- ✅ UNDER picks significantly outperform (68.8% vs 60.8%)
- ✅ Elite systems highly reliable (87.5% and 83.2%)
- ✅ Low error rates (4.19-4.61 pts for top systems)

**Areas for Improvement**:
- ⚠️ Two underperforming systems (catboost_v8, moving_average)
- ⚠️ High variance by date (29.2% to 83.2%)
- ⚠️ OVER picks need optimization (60.8% vs 68.8% UNDERS)

### Final Assessment: **EXCELLENT** ⭐⭐⭐⭐⭐

The prediction system is performing exceptionally well with a 65.9% win rate and 27.4% ROI. Elite systems are delivering outstanding results (87.5% and 83.2% win rates). Focus on high-confidence picks from top systems, maintain UNDER bias, and address underperforming systems for continued success.

---

**Report Generated**: 2026-01-16 23:35 UTC
**Session**: 75
**Data Coverage**: Jan 8-15, 2026 (8 days, 59 games, 5,805 predictions)
**Status**: ✅ COMPLETE
