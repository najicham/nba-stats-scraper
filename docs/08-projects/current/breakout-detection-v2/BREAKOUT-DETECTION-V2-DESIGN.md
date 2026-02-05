# Breakout Detection System v2 - Design Document

**Created:** Session 126 (2026-02-05)
**Status:** ✅ Implementation Complete, Awaiting Deployment
**Previous:** Session 125B initial implementation (3 filters deployed)

> **Update (Session 126 End):** Core implementation complete. Feature store updated to v2_39features with breakout_risk_score (feature 37) and composite_breakout_signal (feature 38). Awaiting deployment of Phase 4 and other services.

---

## Executive Summary

This document extends the Session 125B breakout detection system with data-driven enhancements based on comprehensive analysis by three Opus agents. The key finding is that **several counter-intuitive patterns predict breakouts better than current features**.

### Key Discoveries

| Finding | Impact | Current System |
|---------|--------|----------------|
| **CV Ratio** (variance/avg) is strongest predictor | +20% breakout rate (29.5% vs 9%) | NOT USED |
| **Cold players break out MORE** (mean reversion) | +10% (27.1% vs 17.2%) | Uses hot streak only |
| **Usage trend** (rising usage) | +7% (23.5% vs 16.1%) | NOT USED |
| **Composite score** (4+ factors) | **37% breakout rate** (2x baseline) | NOT USED |
| Injured teammates 30+ PPG | +8% (24.5% vs 16.2%) | Placeholder only |

---

## 1. Current State (Session 125B)

### 1.1 Deployed Filters (Live in prediction-worker)

| Filter | Condition | Historical Hit Rate |
|--------|-----------|---------------------|
| `role_player_under_low_edge` | 8-16 PPG + UNDER + edge < 5 | 42% |
| `hot_streak_under_risk` | L5 > season + 3 + UNDER | **14%** |
| `low_data_quality` | quality_score < 80 | 39% |

### 1.2 Integration Status (Updated Session 126)

| Component | Status | Notes |
|-----------|--------|-------|
| `breakout_risk_score` (0-100) | ✅ Integrated | Feature 37 in v2_39features |
| `composite_breakout_signal` (0-5) | ✅ Integrated | Feature 38 in v2_39features |
| CV ratio in volatility | ✅ Integrated | Primary scoring signal |
| Cold streak bonus | ✅ Integrated | Mean reversion component |
| Usage trend | ✅ Integrated | In opportunity component |
| `opportunity_score` component | ⚠️ Partial | Uses usage trend; injury data still placeholder |
| Breakout classifier training | ⏳ Ready | Script exists, not trained |

### 1.3 Statistical Concern

**Sample sizes are small:**
- Edge 5-7: 11 predictions
- Edge 7+: 3 predictions
- Hot streak: 7 predictions

Need shadow mode to accumulate 100+ samples before full confidence.

---

## 2. New High-Impact Signals (Opus Agent Research)

### 2.1 CV Ratio (Coefficient of Variation) - STRONGEST SIGNAL

**Definition:** `cv_ratio = points_std_last_10 / points_avg_season`

**Correlation with breakout: +0.198** (strongest positive correlation found)

| CV Bucket | Breakout Rate | Games |
|-----------|---------------|-------|
| Very Consistent (<25%) | 9.0% | 100 |
| Low Variance (25-40%) | 13.7% | 469 |
| Medium Variance (40-60%) | 18.1% | 645 |
| **High Variance (60%+)** | **29.5%** | 526 |

**3.3x more likely** for high-variance players vs very consistent.

**Implementation:**
```python
def calculate_cv_ratio(phase4_data: Dict) -> float:
    """Coefficient of variation - volatility normalized by average."""
    std = phase4_data.get('points_std_last_10', 0)
    avg = phase4_data.get('points_avg_season', 0)
    if avg <= 0:
        return 0.5  # Default moderate
    return round(std / avg, 3)
```

### 2.2 Cold Streak Bonus (Mean Reversion) - COUNTER-INTUITIVE

**Finding:** Cold players are MORE likely to break out than hot players.

| Trend | Breakout Rate | Games |
|-------|---------------|-------|
| **Cold Streak (L5 20%+ below L10)** | **27.1%** | 207 |
| Hot Streak (L5 20%+ above L10) | 21.7% | 198 |
| Normal | 17-20% | ~1,300 |

**Current system filters hot players but misses this signal.**

**Implementation:**
```python
def is_cold_streak(phase4_data: Dict) -> bool:
    """Player on cold streak (mean reversion candidate)."""
    l5 = phase4_data.get('points_avg_last_5', 0)
    l10 = phase4_data.get('points_avg_last_10', 0)
    if l10 <= 0:
        return False
    return (l5 - l10) / l10 < -0.20  # L5 is 20%+ below L10
```

### 2.3 Usage Trend - HIGH IMPACT, EASY IMPLEMENTATION

**Definition:** `usage_trend = usage_rate_last_10 - player_usage_rate_season`

| Usage Trend | Breakout Rate | Games |
|-------------|---------------|-------|
| Falling (-3%+) | 19.0% | 63 |
| Declining (0 to -3%) | 16.1% | 1,526 |
| Stable (0-3%) | 18.8% | 1,507 |
| **Rising (+3%+)** | **23.5%** | 102 |

**Implementation:**
```python
def calculate_usage_trend(phase4_data: Dict) -> float:
    """Usage rate trend - rising usage = more opportunity."""
    usage_l10 = phase4_data.get('usage_rate_last_10', 0)
    usage_season = phase4_data.get('player_usage_rate_season', 0)
    return round(usage_l10 - usage_season, 3)
```

### 2.4 Injured Teammates PPG - REAL DATA IMPLEMENTATION

**Data Source:** `nba_raw.nbac_injury_report`

| Injury Bucket | Breakout Rate | Games |
|---------------|---------------|-------|
| < 10 PPG injured | 16.2% (baseline) | 1,951 |
| 10-20 PPG injured | 14.1% | 305 |
| 20-30 PPG injured | 14.5% | 282 |
| **30+ PPG injured** | **24.5%** (+51% vs baseline) | 665 |

**SQL Query:**
```sql
SELECT
    ir.team_abbr,
    ir.game_date,
    SUM(COALESCE(pdc.points_avg_season, 10.0)) as injured_teammates_ppg
FROM nba_raw.nbac_injury_report ir
JOIN nba_precompute.player_daily_cache pdc
    ON ir.player_lookup = pdc.player_lookup
    AND ir.game_date = pdc.cache_date + 1
WHERE ir.injury_status = 'Out'
GROUP BY ir.team_abbr, ir.game_date
```

### 2.5 Composite Signal Score (0-5)

Combining top factors yields dramatically better results:

| Composite Score | Breakout Rate | Games |
|-----------------|---------------|-------|
| 5 (all factors) | **57.1%** | 14 |
| 4 | **37.4%** | 107 |
| 3 | 29.6% | 334 |
| 2 | 24.8% | 448 |
| 1 | 15.4% | 298 |
| 0 | 2.9% | 35 |

**Components:**
1. High variance (CV >= 60%): +1
2. Cold streak (L5 20%+ below L10): +1
3. Starter status: +1
4. Home game: +1
5. Rested (<=2 games in 7 days): +1

**Players with 4+ factors have 37% breakout rate - 2x the baseline.**

---

## 3. Additional Patterns Discovered

### 3.1 Player Tier (Inverse Relationship)

| Tier | Breakout Rate | Games |
|------|---------------|-------|
| **Bench (5-8 PPG)** | **33.6%** | 432 |
| **Role (8-14 PPG)** | **19.3%** | 766 |
| Starters (15-24 PPG) | 10.5% | 428 |
| Stars (25+ PPG) | 6.1% | 114 |

**Insight:** Lower scorers have easier breakout thresholds (7.5 pts for 5 PPG vs 37.5 for 25 PPG).

### 3.2 Day of Week

| Day | Breakout Rate | Games |
|-----|---------------|-------|
| **Tuesday** | **26.3%** | 209 |
| **Wednesday** | **25.5%** | 243 |
| Monday | 19.4% | 284 |
| Saturday | 19.3% | 478 |
| Thursday | 17.7% | 147 |
| Friday | 14.7% | 170 |
| Sunday | 14.4% | 209 |

**Insight:** Mid-week games show highest breakout rates.

### 3.3 Shooting Efficiency (Mean Reversion)

| TS% | Breakout Rate | Games |
|-----|---------------|-------|
| **Cold Shooting (<50% TS)** | **28.4%** | 190 |
| Average (50-55% TS) | 19.7% | 294 |
| Above Avg (55-60% TS) | 20.5% | 440 |
| Hot Shooting (60%+ TS) | 17.0% | 772 |

**Insight:** Cold shooters regress up - another mean reversion signal.

---

## 4. Enhanced Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    BREAKOUT DETECTION v2                        │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 1: New Features (Phase 4 Feature Store)                   │
│   - cv_ratio (std/avg) - STRONGEST signal                       │
│   - usage_trend (L10 - season)                                  │
│   - cold_streak_flag (L5 20%+ below L10)                        │
│   - injured_teammates_ppg (real data)                           │
│   - is_midweek (Tue/Wed flag)                                   │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 2: Enhanced Breakout Risk Score (0-100)                   │
│   EXISTING COMPONENTS (adjusted weights):                       │
│   - Hot Streak (25% → 15%) - less weight, add cold bonus        │
│   - Volatility (20% → 25%) - add CV ratio                       │
│   - Opponent (20%) - keep as-is                                 │
│   - Opportunity (15%) - real injured_teammates_ppg              │
│   - Historical (15%) - keep as-is                               │
│   NEW COMPONENTS:                                               │
│   - Cold Streak Bonus (+10%) - mean reversion signal            │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 3: Composite Signal Score (0-5)                           │
│   +1 high variance (CV >= 60%)                                  │
│   +1 cold streak (L5 20%+ below L10)                            │
│   +1 starter status                                             │
│   +1 home game                                                  │
│   +1 rested (<=2 games in 7 days)                               │
│   Score 4+ = 37% breakout rate (2x baseline)                    │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 4: Prediction Worker Integration                          │
│   - Shadow mode: log decisions but don't filter                 │
│   - Configurable thresholds via env vars                        │
│   - Accumulate 100+ samples before enabling                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Implementation Plan

### Phase 1: Feature Store Integration (Today)

**Task 1: Integrate breakout_risk_score into feature store**
- File: `ml_feature_store_processor.py`
- Update FEATURE_COUNT to 38
- Import and call BreakoutRiskCalculator
- Add to FEATURE_NAMES

**Task 2: Add cv_ratio and usage_trend**
- File: `breakout_risk_calculator.py`
- Add `_calculate_cv_ratio()` method
- Add `_calculate_usage_trend_component()` method
- Update volatility component to use CV ratio

**Task 3: Implement real injured_teammates_ppg**
- File: `feature_extractor.py`
- Add `_batch_extract_team_injuries()` method
- Join nbac_injury_report with player PPG data
- Pass to breakout risk calculator

### Phase 2: Enhanced Score (Today)

**Task 4: Add cold_streak_bonus**
- File: `breakout_risk_calculator.py`
- Add mean reversion component
- Reduce hot streak weight from 30% to 20%
- Add cold streak bonus at 10%

**Task 5: Create composite_breakout_signal**
- File: `breakout_risk_calculator.py`
- Add `calculate_composite_signal()` method
- Return 0-5 score based on factor count
- Store as separate feature (#39)

### Phase 3: Validation & Monitoring

**Task 6: Shadow mode in prediction worker**
- Log filter decisions without actually filtering
- Track would-have-been outcomes
- Accumulate 100+ samples

**Task 7: Make thresholds configurable**
- Move magic numbers to config/env vars
- Enable tuning without redeployment

---

## 6. Updated Feature List

### Breakout Risk Score Components (v2)

| Component | Weight | Source | Change from v1 |
|-----------|--------|--------|----------------|
| Hot Streak | 15% | pts_vs_season_zscore | Reduced from 30% |
| **Cold Streak Bonus** | **10%** | L5 vs L10 trend | **NEW** |
| Volatility | 25% | **CV ratio** + explosion_ratio | Enhanced |
| Opponent Defense | 20% | opponent_def_rating | Unchanged |
| Opportunity | 15% | **real injured_teammates_ppg** | **Enhanced** |
| Historical | 15% | breakout rate L10 | Unchanged |

### New Features to Add

| Feature # | Name | Definition | Impact |
|-----------|------|------------|--------|
| 38 | breakout_risk_score | Composite 0-100 score | Integration |
| 39 | composite_breakout_signal | 0-5 factor count | 37% rate at 4+ |
| 40 | cv_ratio | std/avg | Strongest predictor |
| 41 | usage_trend | usage_L10 - usage_season | +7% for rising |
| 42 | cold_streak_flag | L5 20%+ below L10 | Mean reversion |

---

## 7. Expected Impact

| Metric | Current (125B) | With v2 Enhancements |
|--------|----------------|----------------------|
| Role UNDER Hit Rate | 55% | **62-65%** |
| Breakouts Detected | ~60% | **~80%** |
| False Positives | ~35% | **~20%** |
| Bets Skipped | 30% | **25%** (more targeted) |

### ROI Projection

| Scenario | Hit Rate | ROI |
|----------|----------|-----|
| No filter | 42% | -15% |
| Simple filter (125B) | 55% | +5% |
| **Breakout v2** | **62%** | **+15%** |
| With trained classifier | 65% | +18% |

---

## 8. Files to Modify

### Core Implementation

| File | Changes |
|------|---------|
| `ml_feature_store_processor.py` | Integrate breakout_risk_score, add new features |
| `breakout_risk_calculator.py` | Add CV ratio, cold streak, usage trend, composite |
| `feature_extractor.py` | Add real injured_teammates_ppg extraction |
| `feature_contract.py` | Update to v2_43features |

### Prediction Worker

| File | Changes |
|------|---------|
| `predictions/worker/worker.py` | Add shadow mode, configurable thresholds |

### Tests

| File | Changes |
|------|---------|
| `test_breakout_risk_calculator.py` | Add tests for new components |

---

## 9. Monitoring Queries

### Composite Signal Performance

```sql
-- Track composite signal effectiveness
SELECT
  composite_breakout_signal,
  COUNT(*) as games,
  COUNTIF(actual_points >= season_avg * 1.5) as breakouts,
  ROUND(100.0 * COUNTIF(actual_points >= season_avg * 1.5) / COUNT(*), 1) as breakout_rate
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_analytics.player_game_summary pgs USING (player_lookup, game_date)
WHERE f.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pgs.points_avg_season BETWEEN 5 AND 16
GROUP BY 1
ORDER BY 1
```

### CV Ratio Distribution

```sql
-- Validate CV ratio as predictor
SELECT
  CASE
    WHEN cv_ratio < 0.25 THEN '1_Very Low'
    WHEN cv_ratio < 0.40 THEN '2_Low'
    WHEN cv_ratio < 0.60 THEN '3_Medium'
    ELSE '4_High'
  END as cv_bucket,
  COUNT(*) as games,
  ROUND(100.0 * COUNTIF(actual_points >= season_avg * 1.5) / COUNT(*), 1) as breakout_rate
FROM feature_store_with_cv
GROUP BY 1
ORDER BY 1
```

---

## 10. Success Criteria

### Week 1
- [ ] breakout_risk_score integrated into feature store
- [ ] cv_ratio and usage_trend calculating correctly
- [ ] Real injured_teammates_ppg flowing

### Week 2
- [ ] composite_breakout_signal showing 35%+ rate at score 4+
- [ ] Cold streak bonus validated (mean reversion signal)
- [ ] Shadow mode accumulating samples

### Week 3
- [ ] 100+ samples per filter category
- [ ] Hit rate improvement validated
- [ ] Ready for production enable

---

*Document created by Session 126, incorporating Opus agent research findings.*
