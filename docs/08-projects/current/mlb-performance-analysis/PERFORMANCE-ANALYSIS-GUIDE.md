# MLB Pitcher Strikeouts - Performance Analysis Guide

**Created:** 2026-01-14
**Purpose:** Track model performance, identify patterns, and guide future improvements
**Current Champion:** V1 XGBoost (67.27% overall hit rate)

---

## Table of Contents

1. [Quick Reference Commands](#quick-reference-commands)
2. [Current Performance Summary](#current-performance-summary)
3. [Seasonal Performance Patterns](#seasonal-performance-patterns)
4. [Edge Bucket Analysis](#edge-bucket-analysis)
5. [Direction Analysis (OVER vs UNDER)](#direction-analysis)
6. [Known Issues & Patterns](#known-issues--patterns)
7. [Future Feature Ideas](#future-feature-ideas)
8. [Model Comparison Framework](#model-comparison-framework)

---

## Quick Reference Commands

### Check Overall Hit Rate
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    COUNT(*) as picks,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL
'''
for row in client.query(query):
    print(f'Hit Rate: {row.hit_rate}% ({row.wins}/{row.picks})')
"
```

### Check Monthly Performance
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    FORMAT_DATE(\"%Y-%m\", game_date) as month,
    COUNT(*) as picks,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
'''
for row in client.query(query):
    print(f'{row.month}: {row.hit_rate}% ({row.wins}/{row.picks})')
"
```

### Check Edge Bucket Performance
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    CASE
        WHEN ABS(edge) >= 2.5 THEN \"1. 2.5+\"
        WHEN ABS(edge) >= 2.0 THEN \"2. 2.0-2.5\"
        WHEN ABS(edge) >= 1.5 THEN \"3. 1.5-2.0\"
        WHEN ABS(edge) >= 1.0 THEN \"4. 1.0-1.5\"
        WHEN ABS(edge) >= 0.5 THEN \"5. 0.5-1.0\"
        ELSE \"6. <0.5\"
    END as edge_bucket,
    COUNT(*) as picks,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 1) as hit_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL AND recommendation IN (\"OVER\", \"UNDER\")
GROUP BY 1 ORDER BY 1
'''
for row in client.query(query):
    print(f'{row.edge_bucket}: {row.hit_rate}% ({row.picks} picks)')
"
```

### Check OVER vs UNDER Performance
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    recommendation,
    COUNT(*) as picks,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL AND recommendation IN (\"OVER\", \"UNDER\")
GROUP BY 1
'''
for row in client.query(query):
    print(f'{row.recommendation}: {row.hit_rate}% ({row.picks} picks)')
"
```

---

## Current Performance Summary

### V1 Model (Champion)

| Metric | Value | Context |
|--------|-------|---------|
| **Overall Hit Rate** | 67.27% | +14.89pp over breakeven |
| **Total Picks** | 7,196 | 2024-2025 seasons |
| **Mean Absolute Error** | 1.46 K | Average prediction error |
| **Implied ROI** | ~28.5% | Highly profitable |
| **Algorithm** | XGBoost | 19 features |

### V2-Lite Model (Challenger - Not Ready)

| Metric | Value | vs V1 |
|--------|-------|-------|
| **Test Set Hit Rate** | 54.90% | -4.62pp worse |
| **MAE** | 1.75 K | -19.7% worse |
| **Algorithm** | CatBoost | 21 features |
| **Status** | Not production-ready | V1 remains champion |

---

## Seasonal Performance Patterns

### Critical Discovery: Mid-Season Decline

The model shows a clear seasonal pattern with performance declining from spring through summer:

```
                  Hit Rate
Month      Picks  V1      Trend
─────────────────────────────────
2024-04+   ~3000  70-73%  Strong (early season)
2025-03     110   75.45%  Peak
2025-04     662   70.09%  Strong
2025-05     715   69.65%  Strong
2025-06     668   65.27%  Declining
2025-07     628   58.92%  ⚠️ Worst
2025-08     715   56.64%  ⚠️ Worst
2025-09     614   62.87%  Partial recovery
```

### Visualization

```
Hit Rate by Month (2025)
80% ┤
75% ┤     ●
70% ┤       ●──●
65% ┤            ╲
60% ┤              ●────●
55% ┤                    ╲●
    └────┬───┬───┬───┬───┬───┬
        Mar Apr May Jun Jul Aug Sep
```

### Hypotheses for Mid-Season Decline

1. **Pitcher Fatigue**
   - Starters accumulate innings through summer
   - Velocity/stuff declines affect K rates unpredictably
   - Model may not capture fatigue effects properly

2. **Roster Changes**
   - Trade deadline (late July) shuffles pitchers
   - New team/park factors not yet learned
   - Lineup compositions change

3. **Weather Effects**
   - Summer heat may affect pitcher performance
   - Ball carries differently in hot/humid conditions
   - Day games more common (hotter)

4. **Market Adaptation**
   - Bookmakers may adjust lines mid-season
   - "Sharp" bettors may have identified our edges
   - Lines become more efficient over time

5. **Sample Variance**
   - Could partially be statistical noise
   - More data needed to confirm pattern

### Recommended Actions

1. **Add Season Progress Feature** - `games_into_season` or `month_of_season`
2. **Add Fatigue Indicators** - `season_innings_pct_of_avg`, `velocity_trend`
3. **Retrain Mid-Season** - Consider updating model in June with fresh data
4. **Seasonal Thresholds** - Use stricter edge thresholds in Jul-Aug

---

## Edge Bucket Analysis

### V1 Edge-to-Win-Rate Correlation (Strong)

| Edge Bucket | Picks | Win Rate | ROI Potential |
|-------------|-------|----------|---------------|
| **2.5+** | 129 | 92.2% | Excellent |
| **2.0-2.5** | 247 | 89.9% | Excellent |
| **1.5-2.0** | 253 | 81.4% | Very Good |
| **1.0-1.5** | 558 | 79.2% | Good |
| **0.5-1.0** | 977 | 68.2% | Marginal |
| **<0.5** | 1,357 | 52.5% | Breakeven |

### Key Insight: Minimum Edge Threshold

**Recommendation:** Raise minimum edge from 0.5 to 1.0

| Threshold | Picks | Win Rate | Trade-off |
|-----------|-------|----------|-----------|
| 0.5+ | 5,839 | 67.3% | More volume |
| **1.0+** | **2,427** | **79.8%** | **Optimal** |
| 1.5+ | 1,329 | 83.7% | Less volume |

At 1.0 edge threshold:
- Win rate jumps from 67% to 80%
- Still 2,400+ picks per season
- Much higher ROI

---

## Direction Analysis

### OVER vs UNDER Performance

| Direction | Picks | Win Rate | Difference |
|-----------|-------|----------|------------|
| **UNDER** | 2,883 | **70.0%** | +4.6pp |
| OVER | 4,313 | 65.4% | Baseline |

### Why UNDER Outperforms

1. **Bookmaker Bias** - Lines may be set slightly high (public bets OVER)
2. **Model Strength** - Model better at identifying low-K situations
3. **Downside Limited** - 0 is a floor for strikeouts

### Recommendations

1. Consider weighting UNDER picks higher in bankroll allocation
2. Use different edge thresholds: OVER 1.0, UNDER 0.75
3. Track OVER/UNDER separately for seasonal patterns

---

## Known Issues & Patterns

### 1. August Performance Drop

**Status:** Confirmed, needs investigation

**Symptoms:**
- Win rate drops from 70% to 56% in August
- Affects both OVER and UNDER predictions
- Partial recovery in September

**Mitigation Options:**
- Raise edge threshold to 1.5 during Jul-Aug
- Add seasonal adjustment factor
- Retrain model with Jun-Aug weighted data

### 2. High-K Pitcher Over-Prediction

**Status:** Suspected, needs analysis

**Symptoms:**
- Elite pitchers (Cole, deGrom) may be over-predicted
- Lines already account for their dominance
- Less edge available

**Query to Investigate:**
```sql
SELECT
    pitcher_name,
    COUNT(*) as picks,
    ROUND(AVG(predicted_strikeouts), 1) as avg_pred,
    ROUND(AVG(actual_strikeouts), 1) as avg_actual,
    ROUND(AVG(predicted_strikeouts - actual_strikeouts), 2) as avg_error,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 1) as hit_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE is_correct IS NOT NULL
GROUP BY pitcher_name
HAVING COUNT(*) >= 20
ORDER BY avg_error DESC
LIMIT 20
```

### 3. Rookie Pitcher Uncertainty

**Status:** Needs investigation

**Hypothesis:**
- Rookies have limited historical data
- Model relies on defaults more
- Predictions may be less accurate

---

## Future Feature Ideas

### High Priority (Data Available)

| Feature | Source | Expected Impact |
|---------|--------|-----------------|
| `month_of_season` | game_date | Capture seasonal pattern |
| `days_since_season_start` | game_date | Linear season progress |
| `pitcher_season_ip_pct` | bdl_pitcher_stats | Fatigue indicator |
| `team_bullpen_usage_last_7` | bdl_pitcher_stats | Starter hook risk |

### Medium Priority (Need Data Collection)

| Feature | Source | Expected Impact |
|---------|--------|-----------------|
| `home_k_per_9` | Pitcher splits | Home/away adjustment |
| `away_k_per_9` | Pitcher splits | Home/away adjustment |
| `day_k_per_9` | Pitcher splits | Day/night adjustment |
| `night_k_per_9` | Pitcher splits | Day/night adjustment |
| `vs_opponent_k_rate` | Historical matchups | Opponent-specific |
| `game_total_line` | Odds API | Scoring environment |

### Lower Priority (Research Needed)

| Feature | Source | Notes |
|---------|--------|-------|
| `umpire_k_rate` | Umpire stats | Umpire strike zone tendencies |
| `weather_temp` | Weather API | Heat effects on pitchers |
| `humidity` | Weather API | Ball movement effects |
| `pitcher_velocity_trend` | Statcast | Fatigue/injury indicator |
| `spin_rate_trend` | Statcast | Stuff quality indicator |
| `barrel_rate_allowed` | Statcast | Contact quality |

### Implementation Priority

```
Phase 1: Add from existing data
├── month_of_season
├── days_since_season_start
└── pitcher_season_ip_pct

Phase 2: Scrape pitcher splits
├── home_k_per_9, away_k_per_9
├── day_k_per_9, night_k_per_9
└── vs_opponent_k_rate

Phase 3: External data integration
├── game_total_line (Odds API)
├── umpire_k_rate
└── weather data

Phase 4: Advanced metrics
├── Statcast velocity/spin
└── Barrel rate / contact quality
```

---

## Model Comparison Framework

### Champion-Challenger Setup

```
Incoming Predictions
        │
        ▼
┌───────────────────────────────────┐
│  V1 (Champion)  │  V2 (Challenger) │
│  XGBoost 19f    │  CatBoost 21f    │
│  67.27% proven  │  Testing         │
└───────────────────────────────────┘
        │
        ▼
Both write to predictions table with model_version
        │
        ▼
Daily comparison dashboard
```

### Promotion Criteria

V2 becomes champion if (after 100+ picks, 7+ days):

| Metric | V1 Baseline | V2 Must Achieve |
|--------|-------------|-----------------|
| Hit Rate | 67.27% | >= 67.27% |
| MAE | 1.46 | <= 1.46 |
| High Edge (1.5+) Win Rate | 85% | >= 85% |
| Edge Correlation | Strong | Preserved |

### Comparison Query

```sql
SELECT
    COALESCE(model_version, 'v1') as version,
    COUNT(*) as picks,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE is_correct IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
```

---

## Performance Monitoring

### Daily Check (Recommended)

```bash
# Run after games complete
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    game_date,
    COUNT(*) as picks,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 1) as hit_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1 DESC
'''
print('Last 7 Days Performance:')
for row in client.query(query):
    status = '✅' if row.hit_rate >= 60 else '⚠️' if row.hit_rate >= 52 else '❌'
    print(f'{status} {row.game_date}: {row.hit_rate}% ({row.wins}/{row.picks})')
"
```

### Weekly Analysis Checklist

- [ ] Check overall hit rate trend
- [ ] Review edge bucket performance (correlation preserved?)
- [ ] Compare OVER vs UNDER
- [ ] Identify worst-performing pitchers
- [ ] Check for data quality issues

### Monthly Deep Dive

- [ ] Full seasonal pattern analysis
- [ ] Feature importance changes
- [ ] Model drift detection
- [ ] Consider retraining if performance < 60%

---

## Related Documentation

- [SESSION-42-V2-DATA-AUDIT.md](../mlb-pitcher-strikeouts/2026-01-14-SESSION-42-V2-DATA-AUDIT.md) - V2 training analysis
- [SESSION-41-COMPLETE-HANDOFF.md](../mlb-pitcher-strikeouts/2026-01-14-SESSION-41-COMPLETE-HANDOFF.md) - System architecture
- [MODEL-UPGRADE-STRATEGY.md](../mlb-pitcher-strikeouts/MODEL-UPGRADE-STRATEGY.md) - V2 roadmap
- [PROJECT-ROADMAP.md](../mlb-pitcher-strikeouts/PROJECT-ROADMAP.md) - Full project plan
