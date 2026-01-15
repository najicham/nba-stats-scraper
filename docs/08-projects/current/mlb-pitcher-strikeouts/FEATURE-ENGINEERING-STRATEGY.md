# MLB Pitcher Strikeouts: Feature Engineering Strategy

**Created**: 2026-01-15
**Status**: Active - Phase 1 Implementation
**Last Updated**: Session 52

---

## Table of Contents

1. [Current Model Performance](#current-model-performance)
2. [Market Efficiency Findings](#market-efficiency-findings)
3. [Feature Analysis Matrix](#feature-analysis-matrix)
4. [Recommended Features](#recommended-features)
5. [Features to Skip](#features-to-skip)
6. [Implementation Priority](#implementation-priority)
7. [Data Sources](#data-sources)
8. [Validation Requirements](#validation-requirements)

---

## Current Model Performance

### Walk-Forward Validated (10 Months, 4,672 Samples)

| Metric | Value | Notes |
|--------|-------|-------|
| **Overall Hit Rate** | 55.5% | Across all predictions |
| **High Confidence** | 59.2% | When P>60% or P<40% |
| **Very High Over** | 60.7% | When P>65% |
| **Breakeven** | 52.4% | At -110 odds |
| **Monthly Variance** | ±4.9% | Expect 50-66% monthly |
| **Sample Size** | 2,018 | High confidence bets |

### Current Features (28 Total)

**V1 Core Features (20):**
- Rolling K averages (last 3, 5, 10 games)
- Season stats (K/9, ERA, WHIP)
- Context (home/away, opponent K-rate, ballpark)
- Workload (days rest, games last 30, pitch count)

**V1.5 BettingPros Features (8):**
- Betting line, projection, projection diff
- Performance tracking (perf_last_5, etc.) - **BROKEN, DO NOT USE**
- Implied probability from odds

---

## Market Efficiency Findings

### Critical Discovery: Simple Signals Don't Work

We tested calculating our own rolling over/under performance:

| Confidence Tier | BP's Broken Data | Our Correct Calculation |
|-----------------|------------------|-------------------------|
| Strong Over (80%+) | 60.7% hit rate | **50.1%** hit rate |
| Strong Under (0-19%) | 63.9% hit rate | **51.9%** hit rate |

**Why?** Vegas adjusts lines based on recent performance:
- Pitchers trending OVER: Line set **1.16 K BELOW** recent average
- Pitchers trending UNDER: Line set **1.31 K ABOVE** recent average

**Implication:** We need LEADING indicators, not trailing indicators.

### What the Market Already Prices In

| Signal | Market Adjustment | Our Edge |
|--------|-------------------|----------|
| Recent K totals | Fully priced | None |
| Recent O/U trends | Fully priced | None |
| Umpire K-rate (raw) | Mostly priced | Minimal |
| Basic projections | Mostly priced | Minimal |

### Where Edge May Still Exist

| Signal | Why Underweighted | Expected Edge |
|--------|-------------------|---------------|
| SwStr% (stuff quality) | Process vs results gap | +2-3% |
| Velocity decline | Market adjusts after results | +1.5-2% |
| Weather interactions | Multi-variable effects | +1-2% |
| Lineup-specific K rates | Timing advantage (2-3hr) | +2-3% |

---

## Feature Analysis Matrix

### All Features Evaluated (40+)

| Feature | Category | Expected Lift | Effort | Market Priced? | Priority |
|---------|----------|---------------|--------|----------------|----------|
| **SwStr%** | Stuff | +2-3% | Medium | Partially | 🟢 **#1** |
| **Velocity Trends** | Stuff | +1.5-2% | Medium | No | 🟢 **#2** |
| **Red Flag Filters** | Risk | Avoid losses | Low | N/A | 🟢 **#3** |
| Weather × Breaking | Context | +1-2% | Low | No | 🟡 #4 |
| Umpire Interactions | Context | +0.5-1% | Low | Partially | 🟡 #5 |
| Opponent 7-Day Trend | Opponent | +1% | Medium | Partially | 🟡 #6 |
| Actual Lineup K-Rates | Lineup | +2-3% | **High** | No (timing) | 🟡 #7 |
| Catcher Framing | Context | +0.5% | Low | Mostly | 🔵 #8 |
| Feature Interactions | Compound | +1-2% | High | No | 🔵 #9 |
| CSW% | Stuff | +1-2% | Medium | Partially | 🔵 #10 |
| Times Through Order | Context | +0.5% | Medium | Mostly | ⚪ Skip |
| Bullpen Workload | Context | +0.5% | Medium | Mostly | ⚪ Skip |
| Our Rolling O/U | Trend | 0% | Low | **Fully** | ❌ Skip |
| Historical vs Team | History | +0.2% | Low | Mostly | ❌ Skip |

**Legend:** 🟢 Must Do | 🟡 Should Do | 🔵 Nice to Have | ⚪ Low Priority | ❌ Skip

---

## Recommended Features

### Phase 1: Must Implement (Weeks 1-2)

#### 1. Swinging Strike Rate (SwStr%) ⭐⭐⭐

**What:** Percentage of pitches that result in swinging strikes

**Why Priority #1:**
- LEADING indicator - measures stuff quality, not results
- Identifies "unlucky" pitchers: elite SwStr% + poor recent Ks = regression candidate
- Market focuses on K totals (results), not SwStr% (process)
- Available from Baseball Savant

**Implementation:**
```python
# Key features to create
swstr_pct_season      # Season baseline
swstr_pct_last_3      # Recent trend
swstr_delta           # Recent vs season (regression signal)

# Thresholds
ELITE_SWSTR = 0.13    # 13%+ = elite strikeout stuff
WEAK_SWSTR = 0.08     # 8%- = weak strikeout stuff

# Value signal
if swstr_last_3 > 0.13 and k_avg_last_3 < betting_line:
    signal = "VALUE_OVER"  # Great stuff, bad luck

if swstr_delta < -0.02 and k_avg_last_3 >= betting_line:
    signal = "FADE_OVER"   # Declining stuff, good luck
```

**Data Source:** Baseball Savant (daily updates, CSV available)

**Expected Lift:** +2-3% hit rate

---

#### 2. Velocity Trend Detection ⭐⭐⭐

**What:** Track fastball velocity changes vs season baseline

**Why Priority #2:**
- Early warning for injury/fatigue
- Velocity loss of 1.5+ mph precedes K-rate decline by 1-2 starts
- Market adjusts after results deteriorate, not during velocity decline
- Critical red flag to AVOID bad bets

**Implementation:**
```python
# Key features
fb_velo_season        # Season baseline
fb_velo_last_3        # Recent average
fb_velo_drop          # Season - Recent

# Thresholds
CONCERN = 1.5         # -1.5 mph = concern
RED_FLAG = 2.5        # -2.5 mph = DO NOT BET OVER

# Action rules
if fb_velo_drop > 2.5:
    action = "SKIP_OVER"      # Major injury risk
elif fb_velo_drop > 1.5:
    action = "BIAS_UNDER"     # Fatigue concern
elif fb_velo_drop < -1.0:     # Velocity INCREASING
    action = "BIAS_OVER"      # Gaining strength
```

**Data Source:** Baseball Savant (velocity by pitch type)

**Expected Lift:** +1.5-2% hit rate, critical for avoiding traps

---

#### 3. Red Flag Filter System ⭐⭐⭐

**What:** Hard rules to skip bad betting spots

**Why Priority #3:**
- Avoid predictable losses
- Model confidence doesn't account for these scenarios
- Risk management, not prediction

**Implementation:**
```python
# HARD RULES - Skip Bet Entirely
SKIP_CONDITIONS = [
    'pitcher_first_start_off_il',    # Rust, pitch limits
    'velocity_drop > 2.5',           # Injury risk
    'is_bullpen_game',               # Not a traditional start
    'pitcher_career_starts < 3',     # No baseline
    'is_doubleheader',               # Roster chaos
    'abs(line_movement) > 1.5',      # Sharps disagree
    'temp < 40 or rain > 60%',       # Extreme weather
]

# SOFT RULES - Reduce Confidence
REDUCE_CONDITIONS = {
    'line_moved_against_model > 1.0': 0.5,   # 50% confidence
    'velocity_drop 1.5-2.5': 0.3,            # 30% for OVER
    'public_betting > 85%': 0.7,             # 70% confidence
    'first_3_starts_of_season': 0.7,         # 70% confidence
}
```

**Data Sources:** Various (velocity, lineup, odds APIs)

**Expected Lift:** Avoid 3-5% of losses by skipping bad spots

---

### Phase 2: Should Implement (Weeks 3-4)

#### 4. Weather × Breaking Ball Interaction

**What:** Temperature effect on breaking ball-heavy pitchers

**Why:** Physics-based - cold weather (<50°F) reduces spin and movement

**Implementation:**
```python
if temp < 50 and not is_dome and breaking_ball_pct > 0.40:
    weather_penalty = -0.8 * (50 - temp) / 20
    signal = "UNDER"
```

**When Useful:** April, late September, October (limited applicability)

**Expected Lift:** +1-2% on applicable games

---

#### 5. Umpire Interaction Effects

**What:** Umpire strike zone combined with pitcher style and weather

**Why:** Base umpire effect is priced in, but INTERACTIONS are not

**Implementation:**
```python
# Base effect (market has this, reduce weight)
ump_base = (ump_k_per_9 - 8.5) / 9 * 0.4

# Interaction effects (where edge exists)
if breaking_ball_pct > 0.40 and ump_breaking_ball_strike_rate > 0.50:
    interaction_bonus = +0.3  # Ump calls breaking balls

if temp < 50 and breaking_ball_pct > 0.40 and ump_tight_zone:
    interaction_penalty = -0.6  # Compound effect
```

**Data Source:** UmpScorecards.com (free, daily)

**Expected Lift:** +0.5-1% (interactions only)

---

#### 6. Opponent 7-Day K-Rate Trends

**What:** Is opponent team striking out more/less than usual recently?

**Why:** Teams go through slumps in contact quality

**Implementation:**
```python
opp_k_rate_7d = opponent_stats['k_rate_last_7_days']
opp_k_rate_season = opponent_stats['k_rate_season']
k_trend_delta = opp_k_rate_7d - opp_k_rate_season

if k_trend_delta > 0.03:  # 3%+ more K-prone
    signal = "OVER"
elif k_trend_delta < -0.03:  # 3%+ better contact
    signal = "UNDER"
```

**Data Source:** FanGraphs, Baseball Savant

**Expected Lift:** +1%

---

### Phase 3: Nice to Have (Weeks 5-8)

#### 7. Actual Lineup K-Rates

**What:** Today's specific lineup K-rate vs team average

**Why:** Timing advantage - lineups announced 2-3hr before game, lines set earlier

**Complexity:** HIGH
- Requires real-time scraper
- Late scratches need handling
- Short betting window

**Expected Lift:** +2-3% (highest potential, hardest to implement)

---

#### 8. Catcher Framing

**What:** Elite framers steal 0.5-1.5 called strikes per game

**Implementation:**
```python
if catcher_framing_runs_per_game > 0.15:
    k_boost = +0.4
elif catcher_framing_runs_per_game < -0.10:
    k_boost = -0.3
```

**Expected Lift:** +0.5%

---

#### 9. Feature Interactions

**What:** Compound effects across multiple features

**Key Interactions:**
1. Cold + Breaking Ball + Tight Ump = Strong UNDER
2. High SwStr% + Poor Results + Elite Framer = Strong OVER
3. Velocity Loss + High IP + Late Season = Strong UNDER

**Warning:** Need 30+ occurrences to validate (rare events)

**Expected Lift:** +1-2% (but high overfitting risk)

---

## Features to Skip

### ❌ Our Own Rolling O/U Calculation

**Why Skip:**
- We tested this thoroughly
- Signal DISAPPEARS when calculated correctly
- Market is fully efficient on simple trends

---

### ❌ Times Through Order Splits

**Why Skip:**
- Effect partially captured by IP features
- Manager decisions are unpredictable
- Marginal value (+0.5%)

---

### ❌ Bullpen Workload

**Why Skip:**
- Indirect effect on Ks
- Hard to quantify precisely
- Manager variance high

---

### ❌ Historical Pitcher vs Team

**Why Skip:**
- Small sample sizes
- Roster turnover makes history less relevant
- Noise, not signal

---

## Implementation Priority

### Priority Matrix

```
                    HIGH IMPACT
                         │
    Phase 3: Lineup ────┼──── Phase 1: SwStr%
                         │         Phase 1: Velocity
                         │
    LOW ─────────────────┼───────────────────── HIGH
    EFFORT               │                      EFFORT
                         │
    Phase 2: Weather ────┼──── Skip: Bullpen
    Phase 2: Umpire      │     Skip: TTO
    Phase 2: Opponent    │
                         │
                    LOW IMPACT
```

### Recommended Order

1. **SwStr% / CSW%** - Highest ROI, leading indicator
2. **Velocity Trends** - Critical red flag detection
3. **Red Flag Filters** - Risk management
4. **Weather × Breaking Ball** - Easy win for April/Oct
5. **Umpire Interactions** - Table stakes + edge in interactions
6. **Opponent 7-Day Trends** - Team-level signal
7. **Actual Lineup** - Highest impact, save for last (hard)

---

## Data Sources

| Data | Source | Frequency | Method | Cost |
|------|--------|-----------|--------|------|
| SwStr%, CSW% | Baseball Savant | Daily | Scrape/CSV | Free |
| Velocity | Baseball Savant | Per-game | Scrape/CSV | Free |
| Umpires | UmpScorecards | Daily | Scrape | Free |
| Weather | OpenWeather API | Real-time | API | Free tier |
| Lineups | MLB.com | 2-3hr pre | Scrape | Free |
| Odds | The Odds API | Real-time | API | Free tier |

### Baseball Savant Scraping Notes

```
Rate Limit: 1 request per 2-3 seconds
Bulk CSV: Available for season data (faster)
Key Endpoint: statcast_search for pitch-level data
Metrics Available: SwStr%, CSW%, velocity, spin_rate, etc.
```

---

## Validation Requirements

### Minimum Sample Sizes

| Analysis | Minimum | Why |
|----------|---------|-----|
| Feature validation | 200+ games | Statistical significance |
| Walk-forward split | 100+ games | Reliable accuracy |
| Interaction effect | **30+ occurrences** | Rare events need patience |
| Bet simulation | 50+ bets | ROI stabilization |

### Before Deploying Any Feature

1. ✅ Lift > 1% on holdout data (200+ games)
2. ✅ SHAP values show meaningful contribution
3. ✅ Not highly correlated (>0.7) with existing features
4. ✅ Walk-forward consistent across time periods
5. ✅ Calibration error < 5%
6. ✅ Bet simulation shows positive ROI

---

## Realistic Expectations

### Performance Targets

| Phase | Overall | High Confidence | Timeline |
|-------|---------|-----------------|----------|
| Current | 55.5% | 59.2% | Validated |
| After Phase 1 | 57-59% | 61-64% | +2 weeks |
| After Phase 2 | 58-61% | 63-66% | +4 weeks |
| Best Case | 60-62% | 65-68% | +8 weeks |

### Why Not 70%+

The web chat documents suggested 67-70% is achievable. I'm more conservative:

1. **Market is efficient** - Our walk-forward proved simple signals don't work
2. **BP's "signals" were broken** - 60%+ hit rates based on stale data
3. **Sharp bettors exist** - SwStr%/velocity already used by pros
4. **Diminishing returns** - Each feature adds less than the last

**Realistic ceiling: 65-68% high confidence**

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-15 | Initial creation from Session 52 analysis |

---

*This document is actively maintained. Update as features are validated.*
