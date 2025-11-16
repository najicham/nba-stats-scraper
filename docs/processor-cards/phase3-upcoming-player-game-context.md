# Upcoming Player Game Context Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 3 - Analytics (Forward-Looking) |
| **Schedule** | Multiple times daily (6 AM, noon, 6 PM, line changes) |
| **Duration** | 3-5 minutes (150-300 players with games today) |
| **Priority** | **High** - Critical for real-time predictions |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | 1198 lines |
| **Schema** | `schemas/bigquery/analytics/upcoming_player_game_context_tables.sql` | 64 fields |
| **Tests** | `tests/processors/analytics/upcoming_player_game_context/` | **89 total** |
| | - Unit tests | 43 tests |
| | - Integration tests | 9 tests |
| | - Validation tests | 37 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 2 Raw Sources:
  ├─ nbac_schedule (CRITICAL) - Today's games, opponents
  ├─ nbac_injury_report (OPTIONAL) - Player availability status
  └─ nba_raw.team_travel_data (OPTIONAL) - Miles traveled

Phase 3 Analytics:
  ├─ player_game_summary (SELF) - Historical performance (30-day lookback)
  └─ team_offense_game_summary (SELF) - Team context

Consumers (Phase 4):
  ├─ player_daily_cache - Fatigue metrics (direct copy)
  ├─ player_composite_factors - Usage spike, fatigue factors
  └─ ml_feature_store_v2 - Injury risk, rest advantage
```

---

## What It Does

1. **Primary Function**: Calculates player context for TODAY'S games (fatigue, usage, trends)
2. **Key Output**: One row per player per game with 30-day performance history and game context
3. **Value**: Enables real-time prediction updates when odds change; provides fatigue and trend data

---

## Key Metrics Calculated

### 1. Days Rest
```python
# Days between current game and last game
days_rest = (today_game_date - last_game_date).days - 1
```
- **Range**: 0 (back-to-back) to 7+ (long rest)
- **Example**: Played yesterday = 0 days, played 3 days ago = 2 days rest

### 2. Recent Usage Trend
```python
# Compare last 3 games vs season average
recent_usage = avg(last_3_games_usage_rate)
usage_spike = recent_usage - season_avg_usage
```
- **Range**: -10% to +15% (typical)
- **Example**: Teammate injury = +8% spike, returning star = -5% drop

### 3. Minutes Fatigue Score
```python
# Heavy workload in last 7 days
minutes_last_7 = sum(last_7_games_minutes)
fatigue_flag = minutes_last_7 > 245  # >35 min/game
```
- **Range**: 0-300 minutes in 7 days
- **Example**: Load management = 120 min, heavy load = 260 min

---

## Output Schema Summary

**Total Fields**: 64

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | player_lookup, game_id, game_date |
| Game Context | 5 | opponent, is_home, days_rest, back_to_back |
| Performance (Last 10) | 14 | points_avg, assists_avg, minutes_avg, usage_rate |
| Performance (Last 5) | 6 | points_avg_last_5, hot_streak_flag |
| Performance (Season) | 6 | points_avg_season, games_played |
| Fatigue Metrics | 12 | games_in_last_7/14_days, minutes_in_last_7/14_days |
| Trend Analysis | 4 | performance_trend, consistency_score |
| Injury/Availability | 3 | injury_status, minutes_projection |
| Source Tracking | 6 | 2 sources × 3 fields (manual tracking, not v4.0 auto) |
| Metadata | 3 | processed_at, created_at, early_season_flag |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players_with_context,
  AVG(days_rest) as avg_rest,
  COUNT(CASE WHEN back_to_back THEN 1 END) as back_to_back_count,
  AVG(minutes_in_last_7_days) as avg_recent_minutes,
  MAX(processed_at) as last_run
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Expected Results:
-- players_with_context: 150-300 (depends on games scheduled)
-- avg_rest: 1-2 days
-- back_to_back_count: 20-40 players
-- avg_recent_minutes: 100-180
-- last_run: < 2 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: Empty DataFrame Bug (Historical Issue - FIXED)
**Symptom**: Processor crashes with empty DataFrame error
**Diagnosis**: Lines 12-14 in processor document the fix
**Fix**: Already fixed in production code - empty DataFrame handling added

### Issue 2: Missing Games (Low Sample Size)
**Symptom**: `games_played_last_30` < 5 for most players
**Diagnosis**:
```sql
-- Check historical data availability
SELECT
  AVG(games_played_last_30) as avg_games,
  COUNT(CASE WHEN games_played_last_30 < 5 THEN 1 END) as low_sample
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
```
**Fix**:
1. Early season: Expected (< 30 days into season)
2. Mid-season: Check if player_game_summary has 30-day history
3. Run backfill for player_game_summary if needed

### Issue 3: Incorrect Days Rest
**Symptom**: Back-to-back players showing days_rest > 0
**Diagnosis**:
```sql
-- Find mismatched back-to-back flags
SELECT player_lookup, days_rest, back_to_back,
       last_game_date, game_date
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()
  AND ((back_to_back AND days_rest > 0) OR
       (NOT back_to_back AND days_rest = 0));
```
**Fix**:
1. Verify last_game_date calculation from player_game_summary
2. Check time zone handling (Eastern time for game dates)
3. Ensure schedule data is current

---

## Processing Flow

```
nbac_schedule ──────────┐
(today's games)        │
                       ├─→ UPCOMING PLAYER CONTEXT ─┬─→ player_daily_cache
player_game_summary ───┤   (30-day lookback)        ├─→ player_composite_factors
(historical perf)      │                             └─→ ml_feature_store_v2
                       │
nbac_injury_report ────┘
(optional)
```

**Timing**:
- Runs: Multiple times per day (6 AM, noon, 6 PM, on line changes)
- Waits for: Player Game Summary (historical data)
- Must complete before: Player Daily Cache, Player Composite Factors
- Update frequency: Every time betting lines change (real-time)

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Players processed | < 100 (game day) | Critical |
| Avg games in sample | < 5 (after week 4) | Warning |
| Processing time | > 10 min | Warning |
| Players with NULL days_rest | > 5% | Warning |
| Back-to-back rate | > 30% | Warning (unusual) |
| Empty DataFrame errors | > 0 | Critical |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Upcoming Player Game Context Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/analytics/upcoming_player_game_context_tables.sql`
- 🧪 **Test Suite**: `tests/processors/analytics/upcoming_player_game_context/`
- 📊 **Related Processors**:
  - ↑ Upstream: Player Game Summary (Phase 3)
  - ↓ Downstream: Player Daily Cache, Player Composite Factors (Phase 4)
  - 🔄 Peer: Upcoming Team Game Context

---

## Notes

- **Real-Time Critical**: Runs multiple times daily to support live odds updates
- **30-Day Lookback**: Uses rolling 30-day window (not season-long)
- **Quality Tiers**: High (≥10 games), Medium (5-9 games), Low (<5 games)
- **Manual Source Tracking**: Doesn't use v4.0 auto-tracking pattern (predates it)
- **Empty DataFrame Fix**: Lines 12-14 document the fix applied in production

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
