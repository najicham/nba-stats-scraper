# MLB Pitcher Strikeouts: Phase 1 Implementation Plan

**Created**: 2026-01-15
**Status**: Active - Executing
**Session**: 53

---

## Overview

Implementing leading indicator features (SwStr%, velocity trends) and red flag filters to improve the pitcher strikeouts prediction model from 59.2% → 63-65% high-confidence hit rate.

---

## Phase 1A: Audit & Data Infrastructure (Days 1-2)

### Tasks

- [ ] **1.1** Audit existing statcast scraper (`scrapers/mlb/statcast/mlb_statcast_pitcher.py`)
  - What metrics does it collect?
  - How is it invoked?
  - What's the output format?

- [ ] **1.2** Check BigQuery for existing statcast data
  - Is there a `mlb_raw.statcast_*` table?
  - What historical data exists?

- [ ] **1.3** Design statcast data storage
  - Create `mlb_raw.statcast_pitcher_game_stats` table if needed
  - Fields: player_lookup, game_date, swstr_pct, csw_pct, fb_velo_avg, fb_velo_max, whiff_rate, chase_rate

- [ ] **1.4** Backfill historical statcast data (2024-2025)
  - Use pybaseball for bulk historical data
  - ~300 qualified starters × 30 starts = ~9,000 records per season
  - Estimate: 2-3 hours for full backfill

### Deliverables
- Statcast data available in BigQuery for all 2024-2025 pitcher starts
- Documentation of data availability and quality

---

## Phase 1B: Feature Engineering (Days 3-5)

### New Features for pitcher_game_summary

#### SwStr% Features (Swinging Strike Rate)
```
swstr_pct_season        -- Season baseline SwStr%
swstr_pct_last_3        -- Recent 3-game SwStr%
swstr_pct_last_5        -- Recent 5-game SwStr%
swstr_delta             -- (last_3 - season) regression signal
swstr_vs_k_gap          -- Expected K/9 from SwStr% minus actual K/9
```

#### Velocity Features
```
fb_velo_season          -- Season average fastball velocity
fb_velo_last_3          -- Recent 3-game fastball velocity
fb_velo_drop            -- (season - last_3) decline signal
fb_velo_trend           -- 5-game velocity trend (slope)
```

#### CSW% Features (Called Strike + Whiff)
```
csw_pct_season          -- Season baseline
csw_pct_last_3          -- Recent trend
csw_delta               -- Regression signal
```

### Tasks

- [ ] **2.1** Update `pitcher_game_summary_processor.py`
  - Add CTEs to join statcast data
  - Calculate rolling SwStr%, velocity stats
  - Add delta/gap calculations

- [ ] **2.2** Create feature transformation logic
  - SwStr% → expected K/9 mapping (research correlation)
  - Velocity drop → risk score mapping

- [ ] **2.3** Update training scripts
  - Add new features to feature list
  - Update FEATURE_ORDER in predictor

- [ ] **2.4** Backfill pitcher_game_summary with new features
  - Re-run analytics processor for 2024-2025

### Deliverables
- pitcher_game_summary updated with 8-10 new statcast features
- Training data ready with new features

---

## Phase 1C: Red Flag System (Days 4-6)

### Hard Skip Rules (Do Not Bet)

| Condition | Detection Method | Action |
|-----------|------------------|--------|
| First start off IL | Join injury table, check days since IL | SKIP |
| Velocity drop >2.5 mph | fb_velo_drop > 2.5 | SKIP OVER |
| Bullpen/Opener game | projected_ip < 4.0 OR is_opener flag | SKIP |
| MLB debut (first 2 starts) | career_starts < 3 | SKIP |
| Doubleheader | game_type = 'doubleheader' | SKIP |
| Line moved >1.5 K | abs(line_open - line_current) > 1.5 | SKIP |

### Soft Rules (Reduce Confidence)

| Condition | Detection | Confidence Multiplier |
|-----------|-----------|----------------------|
| Line moved 1+ K against model | line_movement direction | 0.5 |
| Velocity drop 1.5-2.5 mph | fb_velo_drop range | 0.3 for OVER |
| Public >85% one side | betting_splits data | 0.7 |
| First 3 starts of season | season_games < 3 | 0.7 |
| SwStr% declining >2% | swstr_delta < -0.02 | 0.7 for OVER |

### Tasks

- [ ] **3.1** Add red flag detection to predictor
  - Create `check_red_flags()` method
  - Return skip reason or confidence multiplier

- [ ] **3.2** Integrate IL/injury data
  - Check `bdl_injuries` table for recent IL stints
  - Flag first start after IL return

- [ ] **3.3** Add line movement tracking
  - Compare opening line to current line
  - Detect sharp money signals

- [ ] **3.4** Implement confidence adjustment
  - Multiply base confidence by soft rule factors
  - Cap minimum confidence at 30%

### Deliverables
- Red flag system integrated into predictor
- Skip/reduce decisions logged for analysis

---

## Phase 1D: Validation (Days 6-8)

### Validation Requirements

- [ ] **4.1** Walk-forward validation with new features
  - Same 10-month test period
  - Compare: baseline vs +SwStr% vs +velocity vs +both vs +red_flags

- [ ] **4.2** SHAP analysis
  - Verify SwStr% features have meaningful contribution
  - Check for redundancy with existing K features

- [ ] **4.3** Correlation analysis
  - SwStr% vs k_per_9_rolling_10 (want <0.7)
  - SwStr% vs k_avg_last_5 (want <0.7)
  - If too correlated, use delta features only

- [ ] **4.4** Calibration check
  - 60% confidence should hit ~60%
  - Check across confidence buckets

- [ ] **4.5** Red flag impact analysis
  - How many bets skipped?
  - What was hit rate on skipped bets? (should be <50%)

### Success Criteria

| Metric | Baseline | Target | Must Beat |
|--------|----------|--------|-----------|
| Overall hit rate | 55.5% | 57-59% | 56% |
| High confidence | 59.2% | 62-65% | 60% |
| Monthly variance | ±4.9% | ±4% | ±5% |
| Bets skipped by red flags | 0% | 5-10% | - |
| Hit rate on skipped bets | - | <48% | <50% |

### Deliverables
- Validation report with lift measurements
- Go/no-go decision for production deployment

---

## Phase 2: Context Features (After Phase 1 Validated)

### 2A: Weather × Breaking Ball

```python
# Only applies: April, late September, October
# Only for outdoor venues
if temp < 50 and not is_dome and breaking_ball_pct > 0.40:
    weather_k_adjustment = -0.5 to -1.0
```

**Data needed**: Weather API integration, pitcher pitch mix from statcast

### 2B: Umpire Effects (With 2026 Challenge Rule)

**Important**: 2026 MLB season introduces ball/strike challenges
- Teams get limited challenges per game
- Bad calls can be overturned
- This REDUCES umpire impact on outcomes

**Adjusted approach**:
```python
# Base umpire effect (reduced weight due to challenges)
ump_k_adjustment = (ump_k_per_9 - league_avg) * 0.3  # Was 0.5

# New signal: Umpire reversal rate
# High reversal rate = less reliable zone = more variance
if ump_reversal_rate > 0.15:
    confidence_reduction = 0.9

# Interaction still valuable (harder to challenge borderline calls)
if breaking_ball_pct > 0.40 and ump_breaking_ball_k_rate > avg:
    interaction_bonus = +0.2
```

**Data needed**: UmpScorecards, 2026 challenge data when available

### 2C: Opponent 7-Day K Trends

```python
opp_k_rate_7d = opponent_team_k_rate_last_7_days
opp_k_rate_season = opponent_team_k_rate_season
k_trend = opp_k_rate_7d - opp_k_rate_season

if k_trend > 0.03:  # Team striking out more lately
    opp_k_adjustment = +0.3
elif k_trend < -0.03:  # Team making better contact
    opp_k_adjustment = -0.3
```

**Data needed**: Team-level rolling K rates (can derive from batter_game_summary)

---

## Phase 3: Advanced Features (Future)

### 3A: Actual Lineup K-Rates
- Scrape lineups 2-3 hours before game
- Calculate lineup-specific expected K
- Compare to line (set earlier)
- **Challenge**: Tight betting window

### 3B: Catcher Framing
- Elite framers: +0.3-0.5 K boost
- Poor framers: -0.2-0.4 K penalty
- Data from Baseball Savant framing metrics

### 3C: Feature Interactions
- Cold + Breaking Ball + Tight Ump = Strong UNDER
- High SwStr% + Bad Luck + Elite Framer = Strong OVER
- **Warning**: Need 30+ occurrences to validate

---

## Data Sources Summary

| Data | Source | Status | Action Needed |
|------|--------|--------|---------------|
| SwStr%, CSW% | Baseball Savant | Scraper exists | Verify + backfill |
| Velocity | Baseball Savant | Scraper exists | Same as above |
| Injuries/IL | Ball Don't Lie | In BigQuery | Join in processor |
| Weather | OpenWeather API | Not integrated | Phase 2 |
| Umpires | UmpScorecards | Not integrated | Phase 2 |
| Challenge data | TBD (2026 rule) | Not available | Monitor for source |
| Lineups | MLB Stats API | Scraper exists | Phase 3 |

---

## Timeline

```
Day 1-2: Phase 1A - Audit & Infrastructure
Day 3-5: Phase 1B - Feature Engineering
Day 4-6: Phase 1C - Red Flag System (parallel with 1B)
Day 6-8: Phase 1D - Validation
Day 9+:  Deploy if validated, begin Phase 2
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| SwStr% highly correlated with existing features | Use delta features (recent vs season) instead of raw |
| Historical statcast data gaps | Fall back to season averages for missing games |
| Red flags skip too many bets | Set minimum threshold (skip <15% of bets) |
| New features don't lift performance | Keep existing model as fallback, A/B test |
| 2026 challenge rule changes umpire dynamics | Reduce umpire feature weight, monitor early season |

---

## Questions to Resolve

1. **Statcast historical availability**: How far back can we get game-level SwStr%?
2. **IL return detection**: How to reliably identify "first start off IL"?
3. **Line movement data**: Do we have opening lines, or just current?
4. **Pitch mix data**: Do we have breaking ball % by pitcher?

---

*Plan created Session 53 - Ready for execution*
