# MLB Pitcher Strikeouts: Comprehensive TODO Analysis

**Created**: 2026-01-15 (Session 54)
**Purpose**: Deep analysis of all remaining work items with prioritization

---

## Executive Summary

After ultrathinking on all remaining items, here's the prioritized roadmap:

| Priority | Item | Expected Impact | Effort | Dependencies |
|----------|------|-----------------|--------|--------------|
| 🔴 #1 | Red Flag Backtest | Validate existing work | 1 hour | None |
| 🔴 #2 | Per-Game Statcast Pipeline | Unlocks #3 and #4 | 1-2 days | None |
| 🔴 #3 | Rolling SwStr% Features | +2-3% hit rate | 4 hours | #2 |
| 🔴 #4 | Velocity Trend Features | Avoid bad bets | 4 hours | #2 |
| 🟡 #5 | IL Return Detection | Avoid high variance | 4 hours | Injuries data ✅ |
| 🟡 #6 | Opening Line Capture | Sharp money signal | 1 day | Schema change |
| 🟢 #7 | Weather Integration | +1% April/Oct | 4 hours | Weather API |
| 🟢 #8 | Production Deployment | Go live | 2 hours | Testing |

---

## Part 1: Immediate Priorities

### 1.1 Red Flag Backtest Validation (HIGHEST PRIORITY)

**Why First**: We implemented red flags in Session 53 but never validated they work.

**Status**: Code complete, needs validation query

**Validation Query**:
```sql
WITH red_flag_analysis AS (
  SELECT
    game_date,
    player_lookup,
    strikeouts,
    strikeouts_line,

    -- Hard skip conditions
    CASE
      WHEN season_games_started = 0 THEN 'first_start'
      WHEN ip_avg_last_5 < 4.0 THEN 'bullpen_opener'
      WHEN rolling_stats_games < 2 THEN 'debut'
      ELSE 'keep'
    END as skip_reason,

    -- Soft reduce conditions
    season_games_started < 3 as early_season,
    k_std_last_10 > 4 as high_variance,
    days_rest < 4 as short_rest,
    games_last_30_days > 6 as high_workload,
    season_swstr_pct < 0.08 as low_swstr,

    -- Outcome
    IF(strikeouts > strikeouts_line, 1, 0) as hit_over,
    IF(strikeouts < strikeouts_line, 1, 0) as hit_under

  FROM mlb_analytics.pitcher_game_summary
  WHERE strikeouts_line IS NOT NULL
    AND game_date >= '2024-01-01'
)

SELECT
  skip_reason,
  COUNT(*) as count,
  ROUND(AVG(hit_over) * 100, 1) as over_hit_rate,
  ROUND(AVG(hit_under) * 100, 1) as under_hit_rate
FROM red_flag_analysis
GROUP BY skip_reason
ORDER BY count DESC
```

**Expected Results**:
- `first_start` → <48% hit rate (skip these)
- `bullpen_opener` → <45% hit rate (skip these)
- `keep` → >52% hit rate (bet these)

**Effort**: 1 hour

---

### 1.2 Per-Game Statcast Pipeline (CRITICAL PATH)

**Why Critical**: This unlocks BOTH rolling SwStr% AND velocity trends.

**Discovery from Research**:
- `mlb_game_feed` scraper ALREADY EXISTS and is registered
- Can extract pitch-by-pitch data with velocity and swing results
- NO external dependencies (uses official MLB Stats API)
- Much faster than Baseball Savant scraping

**Architecture**:
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  MLB Stats API  │────▶│  mlb_game_feed  │────▶│  New Processor  │
│  (already used) │     │    scraper      │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                              ┌─────────────────────────────────────┐
                              │  mlb_raw.game_feed_pitcher_stats    │
                              │  - game_id, pitcher_id, game_date   │
                              │  - swstr_count, swing_count         │
                              │  - swstr_pct (calculated)           │
                              │  - avg_velocity, max_velocity       │
                              │  - pitch_count                      │
                              └─────────────────────────────────────┘
```

**Implementation Steps**:
1. Create BigQuery schema for `mlb_raw.game_feed_pitcher_stats`
2. Build processor to parse game_feed JSON → extract per-pitcher metrics
3. Backfill 2024-2025 data (~5,200 games)
4. Add to daily orchestration

**Key Metrics to Extract**:
```python
# Per pitcher per game:
swstr_count = count(description == 'swinging_strike')
swing_count = count(description in ['swinging_strike', 'foul', 'in_play_*'])
swstr_pct = swstr_count / swing_count

avg_velocity = mean(release_speed) where pitch_type in ['FF', 'SI', 'FC']
max_velocity = max(release_speed)
pitch_count = count(all_pitches)
```

**Effort**: 1-2 days
**Dependencies**: None

---

## Part 2: Feature Engineering (After Pipeline)

### 2.1 Rolling SwStr% Features

**Why Important**: THE key "unlucky pitcher" signal from the strategy doc.

**The Edge**:
```
Pitcher with elite stuff but bad recent results:
  - SwStr% last 3 games > 13%
  - K avg last 3 games < betting line
  - Signal: VALUE OVER (great stuff, bad luck, expect regression)

Pitcher with declining stuff but good recent results:
  - SwStr% delta (recent - season) < -2%
  - K avg last 3 games >= betting line
  - Signal: FADE OVER (weakening stuff, expect regression down)
```

**Features to Create**:
```sql
-- In pitcher_game_summary:
swstr_pct_last_3       -- Rolling 3-game SwStr%
swstr_pct_last_5       -- Rolling 5-game SwStr%
swstr_pct_last_10      -- Rolling 10-game SwStr%
swstr_delta_vs_season  -- Recent - Season (regression signal)
swstr_vs_k_gap         -- SwStr% implies X K/9, actual is Y → gap
```

**Implementation**:
```sql
-- Add to pitcher_game_summary_processor.py:
AVG(gf.swstr_pct) OVER (
    PARTITION BY h.player_lookup
    ORDER BY game_date, game_id
    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
) as swstr_pct_last_3,

-- Delta calculation:
swstr_pct_last_3 - season_swstr_pct as swstr_delta_vs_season
```

**Expected Lift**: +2-3% on high confidence bets
**Effort**: 4 hours (after pipeline complete)
**Dependencies**: Per-game statcast pipeline (#1.2)

---

### 2.2 Velocity Trend Features

**Why Important**: Early warning for injury/fatigue BEFORE results decline.

**The Edge**:
```
Market adjusts to velocity drops AFTER performance suffers.
We can detect velocity drops 1-2 starts before K-rate declines.

Velocity drop > 2.5 mph → HARD SKIP (injury risk)
Velocity drop 1.5-2.5 mph → BIAS UNDER (fatigue)
Velocity UP > 1.0 mph → BIAS OVER (gaining strength)
```

**Features to Create**:
```sql
-- In pitcher_game_summary:
fb_velocity_last_3     -- Average FB velocity last 3 starts
fb_velocity_season     -- Season baseline
fb_velocity_drop       -- Season - Recent (positive = decline)
velocity_trend         -- Categorical: 'declining', 'stable', 'improving'
```

**Red Flag Integration**:
```python
# Add to _check_red_flags():
if fb_velocity_drop > 2.5:
    skip_bet = True
    skip_reason = f"Major velocity drop ({fb_velocity_drop:.1f} mph)"
elif fb_velocity_drop > 1.5 and recommendation == 'OVER':
    confidence_multiplier *= 0.7
    flags.append(f"REDUCE: Velocity drop ({fb_velocity_drop:.1f} mph)")
```

**Expected Lift**: Avoid 3-5% of losses by skipping bad spots
**Effort**: 4 hours (after pipeline complete)
**Dependencies**: Per-game statcast pipeline (#1.2)

---

## Part 3: Data Gaps to Fill

### 3.1 IL Return Detection

**Discovery**: Injuries table IS populated! `mlb_raw.bdl_injuries` has data.

**Gap**: Detection logic not implemented in predictor.

**Challenge**: BDL API only provides CURRENT injuries (snapshot).
- When pitcher returns from IL, they disappear from the injuries table
- Need to track when pitcher WAS on IL and compare to game dates

**Solution**: Historical injury tracking

```sql
-- Create view: mlb_raw.pitcher_il_history
-- Track when each pitcher was on IL

WITH injury_periods AS (
  SELECT
    player_lookup,
    injury_date,
    expected_return_date,
    snapshot_date,
    -- Detect return: player disappears from subsequent snapshots
    LEAD(snapshot_date) OVER (
      PARTITION BY player_lookup
      ORDER BY snapshot_date
    ) as next_snapshot,
    CASE
      WHEN LEAD(snapshot_date) OVER (...) IS NULL
           OR LEAD(snapshot_date) > snapshot_date + 7
      THEN snapshot_date  -- Last seen on IL
      ELSE NULL
    END as return_date
  FROM mlb_raw.bdl_injuries
  WHERE is_pitcher = TRUE
)

-- Then in predictor:
-- Check if game_date is within 10 days of return_date
-- If so, flag as IL return
```

**Implementation in Red Flags**:
```python
def _check_red_flags(self, features, recommendation):
    # Existing checks...

    # IL Return check (NEW)
    is_il_return = features.get('is_il_return', False)
    days_since_return = features.get('days_since_il_return')

    if is_il_return or (days_since_return and days_since_return <= 0):
        skip_bet = True
        skip_reason = "First start off IL - high variance"
        return RedFlagResult(skip_bet, 1.0, ["SKIP: IL return"], skip_reason)

    if days_since_return and days_since_return < 14:
        confidence_multiplier *= 0.8
        flags.append(f"REDUCE: Recent IL return ({days_since_return}d ago)")
```

**Expected Impact**: Skip ~5-10% of bets (high variance situations)
**Effort**: 4 hours
**Dependencies**: None (injuries data exists)

---

### 3.2 Opening Line Capture (Line Movement)

**Discovery**: MLB schema has NO opening line tracking.
- NBA has it implemented (can use as pattern)
- BettingPros API likely provides opening line data

**Why Important**: Detect when sharps disagree with model.
```
If line moved 1.5+ K against our model prediction:
  - Sharps disagree
  - Reduce confidence or skip
```

**Schema Changes Required**:
```sql
-- Add to mlb_raw.bp_pitcher_props:
opening_over_line FLOAT64,
opening_under_line FLOAT64,
opening_over_odds INT64,
opening_under_odds INT64,
opening_timestamp TIMESTAMP
```

**Scraper Modification**:
```python
# Check if BettingPros API returns opening_line in response
# Extract: prop.get("over", {}).get("opening_line")
```

**Feature Calculation**:
```sql
line_movement = over_line - opening_over_line
-- Positive = line moved UP (market expects more Ks)
-- Negative = line moved DOWN (market expects fewer Ks)
```

**Red Flag Integration**:
```python
if abs(line_movement) > 1.5:
    confidence_multiplier *= 0.5
    flags.append(f"REDUCE: Large line move ({line_movement:+.1f} K)")

if line_movement > 1.0 and recommendation == 'UNDER':
    flags.append("WARNING: Line moved toward OVER")
```

**Expected Impact**: +1-2% by avoiding sharp-opposed bets
**Effort**: 1 day
**Dependencies**: BettingPros API inspection

---

## Part 4: Lower Priority Items

### 4.1 Weather × Breaking Ball Integration

**Why Lower**: Only applicable April/October games.

**Implementation**:
```python
# Get weather data for game
if temp < 50 and not is_dome:
    if pitcher_breaking_ball_pct > 0.40:
        # Cold weather reduces spin/movement
        confidence_multiplier *= 0.8
        if recommendation == 'OVER':
            flags.append(f"REDUCE: Cold weather ({temp}°F) + breaking ball pitcher")
```

**Data Source**: OpenWeather API (free tier sufficient)

**Effort**: 4 hours
**Dependencies**: Weather API key

---

### 4.2 Umpire Integration

**Why Lower**: Base effect mostly priced in, only interactions add value.

**Data Source**: UmpScorecards.com (free, daily updates)

**Implementation**:
- Umpire K/9 baseline
- Interaction with breaking ball pitchers
- Interaction with cold weather

**Effort**: 1 day
**Dependencies**: UmpScorecards scraper needed

---

### 4.3 Actual Lineup K-Rates

**Why Lower**: Highest complexity, timing challenges.

**The Edge**: Lineups announced 2-3hr before game, lines set earlier.

**Challenges**:
- Need real-time lineup scraper
- Handle late scratches
- Short betting window
- Complex K-rate calculation per batter

**Expected Lift**: +2-3% (highest potential)
**Effort**: 1-2 weeks
**Dependencies**: Lineup API, batter K-rate data

---

## Part 5: Production Deployment

### Current State
- Model trained with SwStr% features
- Red flag system implemented in predictor
- NOT deployed to production

### Deployment Steps
1. Run final walk-forward validation
2. Update model path in production config
3. Test prediction endpoint
4. Monitor for 1 week
5. Enable for live betting

**Effort**: 2 hours
**Dependencies**: Validation complete

---

## Recommended Execution Order

### Session 54 (This Session)
1. ✅ Run red flag backtest validation query
2. ✅ Start per-game statcast pipeline design

### Session 55
3. Complete per-game statcast pipeline
4. Backfill 2024-2025 data

### Session 56
5. Implement rolling SwStr% features
6. Implement velocity trend features
7. Run walk-forward validation with new features

### Session 57
8. Implement IL return detection
9. Deploy to production

### Session 58+
10. Opening line capture
11. Weather integration
12. Umpire integration

---

## Risk Assessment

| Item | Risk | Mitigation |
|------|------|------------|
| Per-game pipeline | Slow backfill | Batch by month, parallelize |
| Rolling SwStr% | Correlates with existing | SHAP analysis, check <0.7 correlation |
| Velocity trends | Data quality | Validate against FanGraphs |
| IL return | Detection accuracy | Manual spot checks |
| Line movement | API doesn't have opening | Fall back to multi-snapshot approach |

---

## Success Metrics

| Phase | Target | Measurement |
|-------|--------|-------------|
| After Red Flags | Skip <50% hit rate bets | Backtest query |
| After Rolling SwStr% | +1-2% overall | Walk-forward |
| After Velocity | +1% by avoiding losses | Backtest |
| After All Phase 1 | 58-60% overall, 62-65% high conf | Walk-forward |

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-15 | Initial creation from ultrathink analysis |
