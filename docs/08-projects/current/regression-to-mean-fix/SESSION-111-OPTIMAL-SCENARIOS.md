# Optimal Betting Scenarios - Session 111 Findings

**Created:** 2026-02-03 (Session 111)
**Status:** Ready for Implementation

## Executive Summary

Extensive analysis of 1,581 predictions over 60 days revealed **scenario-specific hit rate patterns**. The model performs dramatically better in certain Vegas line + edge combinations.

## Key Discovery

**The star under-prediction bias (-9 pts) is NOT hurting performance.**

The model's conservative predictions actually help find value:
- OVER on low lines when player scores 25+: **100% hit rate**
- UNDER on high lines (25+): **65-72% hit rate**

The problem is betting UNDER on players who might have breakout games.

---

## Optimal Scenarios (GREEN ZONE)

### Tier 1: Highest ROI

| Scenario | Bets | Hit Rate | ROI | Daily Volume |
|----------|------|----------|-----|--------------|
| **OVER + Line <12 + Edge ≥5** | 71 | **87.3%** | **+66.8%** | 1-2 |
| **OVER + Line <10 + Edge ≥7** | 40 | **90.0%** | +80%+ | 0-1 |

### Tier 2: Good ROI with More Volume

| Scenario | Bets | Hit Rate | ROI | Daily Volume |
|----------|------|----------|-----|--------------|
| OVER + Line <12 + Edge 3-5 | 123 | 61.0% | +17.2% | 2-3 |
| UNDER + Line ≥25 + Edge ≥3 | 88 | 65.9% | +25.8% | 1-2 |
| Any Direction + Edge ≥7 | 67 | 80.6% | +53.9% | 1-2 |

### Combined Strategy

| Filter | Bets | Hit Rate | ROI |
|--------|------|----------|-----|
| OVER <12 OR UNDER >20 + Edge ≥5 | 110 | 80.9% | +54.5% |

---

## Anti-Patterns (RED ZONE)

### Scenarios to AVOID

| Avoid | Bets | Hit Rate | Why |
|-------|------|----------|-----|
| **UNDER on lines <20** | 775 | 51.3% | Breakout risk |
| **Any pick with edge <3** | 1,190 | 51.6% | No real signal |
| **OVER on high lines (25+)** | 29 | 48.3% | Priced correctly |

### Players to AVOID for UNDER Bets

| Player | Hit Rate | Avg Error | Issue |
|--------|----------|-----------|-------|
| Luka Doncic | 45.5% | 6.9 | High variance |
| Tyrese Maxey | 40% | 9.7 | Explosive upside |
| Shaedon Sharpe | 20% | 7.1 | Breakout potential |
| James Harden | 20% | 7.2 | Inconsistent |
| Julius Randle | 20% | 10.2 | High variance |

### Opponents That Cause UNDER Failures

| Opponent | UNDER Losses | Avg Actual | Why |
|----------|--------------|------------|-----|
| CHA | 7 | 31.7 | Weak defense |
| MEM | 6 | 30.0 | Fast pace |
| HOU | 6 | 31.5 | Allows breakouts |
| WAS | 5 | 35.4 | Very weak defense |
| DET | 3 | 33.0 | Poor defense |

---

## Hit Rate by Vegas Line Range

### OVER Picks (3+ Edge)

| Line Range | Bets | Hit Rate |
|------------|------|----------|
| Under 5 pts | 47 | **68.1%** |
| 5-10 pts | 110 | **69.1%** |
| 10-20 pts | 157 | 61.1% |
| 20-30 pts | 86 | 62.8% |
| 30+ pts | 15 | 60.0% |

**Best:** Low lines (5-10 pts) with 3+ edge = 69.1%

### UNDER Picks (3+ Edge)

| Line Range | Bets | Hit Rate |
|------------|------|----------|
| <15 pts | 53 | 52.8% |
| 15-25 pts | 104 | 56.7% |
| **25+ pts** | 40 | **72.5%** |
| **30+ pts** | 25 | **72.0%** |

**Best:** High lines (25+) = 72%

---

## OVER vs UNDER Performance

| Direction | All Picks | 3+ Edge | Best Scenario |
|-----------|-----------|---------|---------------|
| OVER | 55.0% | **69.9%** | Low lines, high edge |
| UNDER | 54.7% | 58.3% | High lines only |

**OVER outperforms UNDER by 11.6% on 3+ edge picks.**

---

## Edge Threshold Analysis

| Min Edge | Bets | Hit Rate | Notes |
|----------|------|----------|-------|
| <1 pt | 78 | 62.8% | Close to Vegas |
| 1-2 pts | 769 | 50.6% | Losing |
| 2-3 pts | 343 | 50.4% | Losing |
| **3-5 pts** | 243 | **59.7%** | Good |
| **5-7 pts** | 84 | **69.0%** | Very good |
| **7+ pts** | 64 | **82.8%** | Excellent |

**Clear monotonic relationship:** Higher edge = higher hit rate.

---

## Implementation Plan

### Phase 1: Subset Definitions

Create these subsets in Phase 6 publishing:

```python
SUBSETS = {
    'optimal_over': {
        'name': 'Optimal OVER',
        'filters': {
            'recommendation': 'OVER',
            'line_max': 12,
            'edge_min': 5
        },
        'expected_hit_rate': 87.3,
        'priority': 1
    },
    'optimal_under': {
        'name': 'Optimal UNDER',
        'filters': {
            'recommendation': 'UNDER',
            'line_min': 25,
            'edge_min': 3
        },
        'expected_hit_rate': 66.0,
        'priority': 2
    },
    'ultra_high_edge': {
        'name': 'Ultra High Edge',
        'filters': {
            'edge_min': 7
        },
        'expected_hit_rate': 80.6,
        'priority': 1
    }
}
```

### Phase 2: Player Blacklist

```python
UNDER_BLACKLIST = [
    'lukadoncic',
    'tyresemaxey',
    'shaedonsharpe',
    'jamesharden',
    'juliusrandle'
]
```

### Phase 3: Opponent Risk Flags

```python
BREAKOUT_RISK_OPPONENTS = ['CHA', 'MEM', 'HOU', 'WAS', 'DET']
```

---

## Validation Queries

### Check Optimal Picks for Today

```sql
SELECT
  player_lookup,
  predicted_points,
  current_points_line as line,
  ABS(predicted_points - current_points_line) as edge,
  recommendation,
  CASE
    WHEN recommendation = 'OVER' AND current_points_line < 12
         AND ABS(predicted_points - current_points_line) >= 5 THEN 'OPTIMAL_OVER'
    WHEN recommendation = 'UNDER' AND current_points_line >= 25
         AND ABS(predicted_points - current_points_line) >= 3 THEN 'OPTIMAL_UNDER'
    WHEN ABS(predicted_points - current_points_line) >= 7 THEN 'ULTRA_HIGH_EDGE'
    ELSE 'STANDARD'
  END as scenario
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND recommendation IN ('OVER', 'UNDER')
ORDER BY
  CASE scenario
    WHEN 'OPTIMAL_OVER' THEN 1
    WHEN 'ULTRA_HIGH_EDGE' THEN 2
    WHEN 'OPTIMAL_UNDER' THEN 3
    ELSE 4
  END,
  edge DESC
```

### Verify Historical Performance

```sql
SELECT
  CASE
    WHEN recommendation = 'OVER' AND line_value < 12
         AND ABS(predicted_points - line_value) >= 5 THEN 'OPTIMAL_OVER'
    WHEN recommendation = 'UNDER' AND line_value >= 25
         AND ABS(predicted_points - line_value) >= 3 THEN 'OPTIMAL_UNDER'
    WHEN ABS(predicted_points - line_value) >= 7 THEN 'ULTRA_HIGH_EDGE'
    ELSE 'STANDARD'
  END as scenario,
  COUNT(*) as bets,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
  AND recommendation IN ('OVER', 'UNDER')
  AND prediction_correct IS NOT NULL
GROUP BY scenario
ORDER BY hit_rate DESC
```

---

## Expected Impact

| Metric | Current (All Picks) | Optimal Scenarios Only |
|--------|---------------------|------------------------|
| Daily Volume | 20-30 picks | 3-5 picks |
| Hit Rate (3+) | 55-60% | **75-87%** |
| ROI | +5-15% | **+50-65%** |
| Max Drawdown | Higher | Lower (fewer bets) |

**Trade-off:** Lower volume for much higher quality.
