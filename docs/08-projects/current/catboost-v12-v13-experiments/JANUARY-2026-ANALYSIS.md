# January 2026 Deep Analysis

**Date:** 2026-01-31
**Purpose:** Understand why January 2026 was different and what drives prediction accuracy

---

## Key Findings

### 1. January Had Higher Variance

| Metric | December 2025 | January 2026 |
|--------|---------------|--------------|
| Avg points per player | 12.54 | 12.04 |
| Std dev of points | 8.98 | 8.54 |
| Games with >10pt swing from L5 avg | 8.3% | **10.0%** |
| 30+ point games | ~5% | **3.3%** |
| <10 point games | ~40% | **45%** |

**Interpretation:** Players were less predictable in January. More games with unexpected outcomes.

### 2. Scoring Trends by Week

| Week | Avg Pts | 30+ Games | <10 Games | Notes |
|------|---------|-----------|-----------|-------|
| Dec 28 | 12.47 | 5.0% | 41.9% | |
| Jan 4 | 11.87 | 3.3% | **45.9%** | Lowest scoring |
| Jan 11 | 12.18 | 4.3% | 45.2% | |
| Jan 18 | 12.19 | 4.4% | 43.8% | |
| Jan 25 | 11.53 | **2.8%** | 45.1% | Very few explosions |

**Pattern:** January had fewer high-scoring games and more low-scoring games. This favors UNDER bets.

### 3. Player Tier Analysis

| Tier | Games | Avg Pts | vs L5 Avg | vs Season Avg | Hit Rate |
|------|-------|---------|-----------|---------------|----------|
| Stars (25+) | 177 | 27.18 | +0.02 | **-1.10** | 46.2% |
| Starters (18-25) | 465 | 19.82 | -0.64 | -0.81 | 41.7% |
| Rotation (12-18) | 961 | 14.17 | +0.13 | -0.29 | 44.5% |
| Bench (<12) | 2820 | 6.38 | +0.22 | +0.37 | 40.0% |

**Key Insight:** Stars are underperforming their season averages by 1.1 points! The model doesn't capture this mid-season regression.

### 4. Most Mispredicted Players

Players the model **OVERPREDICTED** (predicted too high):

| Player | Games | Predicted | Actual | Bias | Why? |
|--------|-------|-----------|--------|------|------|
| Jerami Grant | 5 | 22.8 | 12.6 | -10.2 | Injury/role change |
| Domantas Sabonis | 5 | 18.9 | 10.0 | -8.9 | Limited sample/outliers |
| Lauri Markkanen | 9 | 24.9 | 16.8 | -8.2 | Slump |
| Tyler Herro | 6 | 19.9 | 13.5 | -6.4 | Role change |
| Jalen Brunson | 10 | 23.3 | 17.7 | -5.6 | Slump |

Players the model **UNDERPREDICTED** (predicted too low):

| Player | Games | Predicted | Actual | Bias | Why? |
|--------|-------|-----------|--------|------|------|
| Kyshawn George | 5 | 12.9 | 18.2 | +5.3 | Breakout |
| Mikal Bridges | 10 | 12.5 | 17.6 | +5.1 | Hot streak |
| Anfernee Simons | 11 | 11.9 | 16.7 | +4.9 | Increased role |

---

## Why High-Confidence Picks Work

### Comparison: High-Conf vs Low-Conf Picks

| Metric | High-Conf (5+ edge) | Low-Conf (1-3 edge) |
|--------|---------------------|---------------------|
| Number of picks | 47 | 1,144 |
| Hit rate | **66.0%** | 49.0% |
| Avg player std (L10) | 6.85 | 5.78 |
| Avg player season avg | 20.1 pts | 13.4 pts |
| Avg |actual - L5| | 8.11 pts | 5.42 pts |

**Insight:** High-confidence picks target **higher-scoring, more variable players**. When the model has high conviction about these players, it's usually right.

### Direction Analysis (High-Conf Only)

| Direction | Picks | Hit Rate | Avg Actual vs Line |
|-----------|-------|----------|-------------------|
| OVER | 13 | 69.2% | +1.37 pts |
| UNDER | 34 | 64.7% | -3.00 pts |

**Insight:** Both directions work, but UNDER has more volume because January players were underperforming.

---

## Why Recency Weighting Helps

### The Problem
The model was trained on 2021-2024 data. January 2026 had different patterns:
- Stars slumping (mid-season fatigue?)
- Higher variance overall
- Fewer explosive games

### The Solution
60-day recency weighting gives:
- 16x weight to games from last week
- 8x weight to games from 2 months ago
- 0.25x weight to games from 1 year ago
- Near-zero weight to games from 2+ years ago

This lets the model **adapt to current patterns** while still using historical data for baseline relationships.

### Why 60 Days?

| Half-Life | High-Conf Hit% | Interpretation |
|-----------|----------------|----------------|
| 30d | 60.0% | Too aggressive - not enough history |
| 45d | 59.6% | |
| **60d** | **65.0%** | **Sweet spot** |
| 90d | 61.1% | |
| 180d | 58.8% | Too much stale data |
| None | 56.9% | All historical data equal |

60 days captures approximately:
- Last ~25 games for active players
- Recent form and matchups
- Current rotation patterns

---

## Feature Importance

Top 10 features (60-day recency model):

| Rank | Feature | Importance | Notes |
|------|---------|------------|-------|
| 1 | points_avg_last_5 | 27.7% | Recent form most important |
| 2 | vegas_points_line | 17.3% | Market signal |
| 3 | points_avg_last_10 | 12.2% | |
| 4 | points_std_last_10 | 5.8% | Consistency matters |
| 5 | vegas_opening_line | 4.8% | |
| 6 | vegas_line_move | 4.4% | Line movement signal |
| 7 | ppm_avg_last_10 | 4.0% | Efficiency |
| 8 | points_avg_season | 3.9% | Baseline |
| 9 | minutes_avg_last_10 | 2.7% | Playing time |
| 10 | avg_points_vs_opponent | 2.4% | Matchup history |

**Key:** Recent performance (L5, L10) and Vegas signals are most predictive.

---

## Weekly Performance (Best Model)

| Week | All Bets (1+ edge) | Hit% | High-Conf (5+) | Hit% |
|------|-------------------|------|----------------|------|
| 1 | 175 | 49.1% | 2 | 0.0% |
| 2 | 337 | 53.1% | 4 | 50.0% |
| 3 | 308 | 51.0% | 12 | **75.0%** |
| 4 | 348 | 53.2% | 19 | **68.4%** |
| 5 | 157 | 42.0% | 3 | 66.7% |

**Pattern:** Weeks 3-4 had the most high-confidence picks and the best hit rates. Early January had too few picks.

---

## Recommendations Based on Analysis

### 1. Use 60-Day Recency Weighting
Captures current patterns while maintaining historical baselines.

### 2. Focus on High-Confidence Picks Only
5+ point edge filters out noise and keeps profitable signals.

### 3. Don't Avoid Any Direction
Both OVER and UNDER work when confidence is high.

### 4. Be Cautious with Stars
Stars underperformed their season averages in January. Model may overpredicthem.

### 5. Retrain Monthly
January patterns may not persist. Fresh training adapts to new trends.

---

*Analysis completed: 2026-01-31*
