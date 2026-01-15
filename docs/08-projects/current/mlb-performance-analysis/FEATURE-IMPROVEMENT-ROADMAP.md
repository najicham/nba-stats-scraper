# MLB Pitcher Strikeouts - Feature Improvement Roadmap

**Created:** 2026-01-14
**Purpose:** Prioritized list of features and improvements to enhance model performance
**Target:** Improve from 67% hit rate to 70%+ with better seasonal stability

---

## Current State

### V1 Model Features (19)

```python
# Rolling Performance (5)
'f00_k_avg_last_3',      # Recent 3-game K average
'f01_k_avg_last_5',      # Recent 5-game K average
'f02_k_avg_last_10',     # Recent 10-game K average
'f03_k_std_last_10',     # K volatility
'f04_ip_avg_last_5',     # Recent innings pitched

# Season Stats (5)
'f05_season_k_per_9',    # Season K rate
'f06_season_era',        # Season ERA
'f07_season_whip',       # Season WHIP
'f08_season_games',      # Games started
'f09_season_k_total',    # Total season Ks

# Context (1)
'f10_is_home',           # Home/away indicator

# Workload (5)
'f20_days_rest',         # Days since last start
'f21_games_last_30_days',# Recent workload
'f22_pitch_count_avg',   # Avg pitches per game
'f23_season_ip_total',   # Season innings
'f24_is_postseason',     # Playoff indicator

# Bottom-Up Model (3)
'f25_bottom_up_k_expected',  # Lineup-based K prediction
'f26_lineup_k_vs_hand',      # Lineup K rate vs pitcher hand
'f33_lineup_weak_spots',     # High-K batters in lineup
```

### V2-Lite Added Features (2)

```python
'f15_opponent_team_k_rate',  # Team strikeout tendency (100% populated)
'f17_ballpark_k_factor',     # Park strikeout factor (100% populated)
```

**Result:** V2-Lite underperformed V1 despite these additions. The issue may be:
1. CatBoost algorithm needs tuning
2. These 2 features alone aren't impactful enough
3. Missing the other 8 planned V2 features

---

## Priority 1: Seasonal Adjustment Features

**Goal:** Address the July-August performance decline (57-59% vs 70%+ spring)

### 1.1 Month of Season Indicator

```python
'f40_month_of_season'  # Integer 1-12 or categorical

# Implementation:
# game_date.month -> 4 (April) through 10 (October)
```

**Rationale:**
- Clear seasonal pattern exists
- Model can learn month-specific adjustments
- Simple to implement from existing data

### 1.2 Days Into Season

```python
'f41_days_into_season'  # Integer 0-180

# Implementation:
# (game_date - season_start_date).days
# Season start: ~April 1
```

**Rationale:**
- Linear representation of season progress
- Captures gradual fatigue accumulation
- More granular than month

### 1.3 Season Progress Percentage

```python
'f42_season_progress_pct'  # Float 0.0-1.0

# Implementation:
# days_into_season / total_season_days (~180)
```

**Rationale:**
- Normalized version of days_into_season
- Easier for model to learn patterns
- Comparable across shortened seasons

### Implementation Query

```sql
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary`
SET
    month_of_season = EXTRACT(MONTH FROM game_date),
    days_into_season = DATE_DIFF(game_date, DATE(season_year, 4, 1), DAY),
    season_progress_pct = DATE_DIFF(game_date, DATE(season_year, 4, 1), DAY) / 180.0
WHERE game_date >= '2024-01-01'
```

---

## Priority 2: Pitcher Fatigue Indicators

**Goal:** Capture mid-season fatigue effects that V1 misses

### 2.1 Season Innings Percentage

```python
'f43_season_innings_pct'  # Float

# Implementation:
# current_season_ip / pitcher_avg_season_ip
# If pitcher typically throws 180 IP and has 120, this = 0.67
```

**Rationale:**
- Pitchers approaching their innings limit often decline
- Some are shut down or limited late season
- Need historical pitcher innings data

### 2.2 Workload Trend

```python
'f44_workload_trend_30d'  # Float

# Implementation:
# (avg_ip_last_15_days - avg_ip_prev_15_days) / avg_ip_prev_15_days
# Positive = increasing workload, Negative = decreasing
```

**Rationale:**
- Sudden workload increases can affect performance
- Indicates manager confidence/concern

### 2.3 Pitch Count Accumulation

```python
'f45_season_pitch_count_pct'  # Float

# Implementation:
# season_total_pitches / expected_season_pitches
```

**Rationale:**
- Total arm stress indicator
- Complementary to innings percentage

---

## Priority 3: Pitcher Splits (Requires Data Collection)

**Goal:** Add situational performance data that V1 lacks entirely

### 3.1 Home/Away K Differential

```python
'f11_home_away_k_diff'  # Float

# Implementation:
# home_k_per_9 - away_k_per_9
# Positive = better at home
```

**Data Source:** Ball Don't Lie API pitcher splits endpoint

**Rationale:**
- Some pitchers significantly better at home
- Park familiarity, crowd support, travel fatigue
- Currently 0% populated - need to scrape

### 3.2 Day/Night K Differential

```python
'f13_day_night_k_diff'  # Float

# Implementation:
# day_k_per_9 - night_k_per_9
# Positive = better in day games
```

**Rationale:**
- Visibility differences affect pitch effectiveness
- Temperature effects (day games hotter in summer)
- Currently 0% populated - need to scrape

### 3.3 Is Day Game Indicator

```python
'f12_is_day_game'  # Boolean

# Implementation:
# game_time < 5:00 PM local
```

**Data Source:** MLB schedule with game times

**Rationale:**
- Simple interaction term for day/night splits
- Currently 0% populated - need game times

### 3.4 Vs Opponent K Rate

```python
'f14_vs_opponent_k_rate'  # Float

# Implementation:
# pitcher's historical K/9 against this specific team
```

**Rationale:**
- Some pitchers dominate certain teams
- Lineup familiarity effects
- Currently 0% populated - need historical calculation

---

## Priority 4: External Data Integration

**Goal:** Add market and environmental factors

### 4.1 Game Total Line (Vegas)

```python
'f18_game_total_line'  # Float (e.g., 8.5)

# Implementation:
# Vegas over/under for total runs
```

**Data Source:** The Odds API game lines

**Rationale:**
- High-scoring games = more plate appearances = more K opportunities
- Market proxy for offensive/defensive quality
- Currently 0% populated - oddsa_game_lines empty

### 4.2 Team Implied Runs

```python
'f46_team_implied_runs'  # Float

# Implementation:
# (game_total_line - run_line_spread) / 2 + adjustment
```

**Rationale:**
- More granular than game total
- Reflects starting pitcher quality perception

### 4.3 Umpire Strike Zone Tendency

```python
'f47_umpire_k_factor'  # Float

# Implementation:
# umpire's historical K rate above/below league average
```

**Data Source:** Umpire assignment + historical data

**Rationale:**
- Umpires have consistent strike zone biases
- Large zones = more Ks
- We have umpire_game_assignment table

---

## Priority 5: Advanced Metrics (Statcast)

**Goal:** Add stuff quality indicators for elite predictions

### 5.1 Velocity Trend

```python
'f48_velocity_trend_5g'  # Float

# Implementation:
# (avg_velocity_last_5 - season_avg_velocity) / season_avg_velocity
```

**Rationale:**
- Velocity decline signals fatigue/injury
- Leading indicator of poor performance

### 5.2 Spin Rate Trend

```python
'f49_spin_rate_trend_5g'  # Float

# Implementation:
# Similar to velocity trend
```

**Rationale:**
- Spin rate affects pitch movement
- Decline may indicate grip/mechanics issues

### 5.3 Whiff Rate

```python
'f50_whiff_rate_season'  # Float

# Implementation:
# swings_and_misses / total_swings
```

**Rationale:**
- Direct measure of strikeout ability
- Better than K/9 for pitch quality

### 5.4 Chase Rate

```python
'f51_chase_rate_season'  # Float

# Implementation:
# swings_at_pitches_outside_zone / pitches_outside_zone
```

**Rationale:**
- Pitcher's ability to get batters to expand
- Key to generating strikeouts

---

## Implementation Roadmap

### Phase 1: Quick Wins (This Week)

```
[ ] Add month_of_season to pitcher_game_summary
[ ] Add days_into_season to pitcher_game_summary
[ ] Retrain V1 XGBoost with these 2 features
[ ] Compare: Does seasonal feature help?
```

**Effort:** 2-4 hours
**Expected Impact:** May reduce July-August decline

### Phase 2: Scrape Pitcher Splits (Next 1-2 Weeks)

```
[ ] Research Ball Don't Lie splits endpoints
[ ] Create scraper for home/away splits
[ ] Create scraper for day/night splits
[ ] Backfill historical splits data
[ ] Populate pitcher_game_summary columns
[ ] Retrain model with splits features
```

**Effort:** 1-2 days
**Expected Impact:** 2-3pp hit rate improvement potential

### Phase 3: External Data (2-3 Weeks)

```
[ ] Set up game total line scraping
[ ] Integrate umpire assignment data
[ ] Add weather data pipeline
[ ] Train model with external features
```

**Effort:** 3-5 days
**Expected Impact:** 1-2pp hit rate improvement potential

### Phase 4: Statcast Integration (Month+)

```
[ ] Research Statcast data access
[ ] Build velocity/spin tracking
[ ] Calculate advanced metrics
[ ] Full V2 model with all features
```

**Effort:** 1-2 weeks
**Expected Impact:** Unknown, potentially significant

---

## Feature Priority Matrix

| Feature | Data Available | Effort | Impact Estimate | Priority |
|---------|---------------|--------|-----------------|----------|
| month_of_season | Yes | Low | Medium | P1 |
| days_into_season | Yes | Low | Medium | P1 |
| season_innings_pct | Yes | Medium | Medium | P2 |
| home_away_k_diff | Need scrape | Medium | High | P2 |
| day_night_k_diff | Need scrape | Medium | Medium | P2 |
| game_total_line | Need scrape | Medium | Medium | P3 |
| umpire_k_factor | Partial | Medium | Low-Medium | P3 |
| velocity_trend | Need Statcast | High | High | P4 |
| whiff_rate | Need Statcast | High | High | P4 |

---

## Success Metrics

### Minimum Success

- Hit rate >= 68% (1pp improvement)
- July-August hit rate >= 62% (5pp improvement from 57%)
- Edge correlation preserved

### Target Success

- Hit rate >= 70%
- July-August hit rate >= 65%
- Consistent performance across all months

### Stretch Goal

- Hit rate >= 72%
- No month below 65%
- Clear edge correlation (2.0+ edge = 85%+ win rate)

---

## Notes & Observations

### Why V2-Lite Failed

1. **CatBoost vs XGBoost:** Algorithm change may need different hyperparameters
2. **Only 2 new features:** opponent_team_k_rate and ballpark_k_factor alone weren't enough
3. **Feature interaction:** New features may need others to be effective
4. **Test period:** Aug-Sep 2025 is challenging for all models

### Lessons Learned

1. Add features incrementally - don't change algorithm and features together
2. Test on multiple time periods, not just holdout
3. Seasonal patterns are real and need explicit handling
4. ballpark_k_factor is valuable (10% importance) - keep it

### Open Questions

1. Is the July-August decline market adaptation or model drift?
2. Would retraining monthly help or hurt?
3. Are there pitcher-specific patterns we're missing?
4. How much does umpire really matter?
