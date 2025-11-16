# Upcoming Team Game Context Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 3 - Analytics (Forward-Looking) |
| **Schedule** | Multiple times daily (6 AM, noon, 6 PM, line changes) |
| **Duration** | 1-2 minutes (20-30 teams with games today) |
| **Priority** | **High** - Required for pace and betting context |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` | 1502 lines |
| **Schema** | `schemas/bigquery/analytics/upcoming_team_game_context_tables.sql` | 40 fields |
| **Tests** | `tests/processors/analytics/upcoming_team_game_context/` | **83 total** |
| | - Unit tests | 45 tests |
| | - Integration tests | 12 tests |
| | - Validation tests | 26 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 2 Raw Sources:
  ├─ nbac_schedule (CRITICAL) - Today's games, home/away
  ├─ odds_api_game_lines (OPTIONAL) - Betting spreads, totals
  └─ nbac_injury_report (OPTIONAL) - Starters out count

Phase 3 Self-Join:
  └─ team_offense_game_summary (SELF) - Recent performance

Consumers (Phase 4):
  ├─ player_composite_factors - Pace score calculation
  └─ ml_feature_store_v2 - Team win percentage
```

---

## What It Does

1. **Primary Function**: Provides team-level context for TODAY'S games (fatigue, betting, streaks)
2. **Key Output**: 2 rows per game (home + away team perspectives)
3. **Value**: Enables pace adjustments, betting context, and team momentum factors in predictions

---

## Key Metrics Calculated

### 1. Team Days Rest
```python
# Days since team's last game
days_since_last_game = (today - last_game_date).days - 1
team_back_to_back = (days_since_last_game == 0)
```
- **Range**: 0 (back-to-back) to 7+ (long break)
- **Example**: Played yesterday = 0 rest, played 3 days ago = 2 days rest

### 2. Win/Loss Streak
```python
# Current streak entering this game
if last_N_games all wins:
    team_win_streak_entering = N
elif last_N_games all losses:
    team_loss_streak_entering = N
else:
    both = 0  # Not on streak
```
- **Range**: 0 (no streak) to 10+ (hot/cold streak)
- **Example**: Won last 5 = win_streak_entering: 5

### 3. Travel Miles
```python
# Miles traveled from last game to this game
if home_game:
    travel_miles = 0  # No travel for home games
else:
    travel_miles = calculate_distance(last_city, current_city)
```
- **Range**: 0 - 2800 miles
- **Example**: LAL → NYK = 2,451 miles

---

## Output Schema Summary

**Total Fields**: 40

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 4 | team_abbr, game_id, game_date |
| Game Context | 5 | opponent, home_game, is_back_to_back, days_since_last |
| Fatigue Metrics | 4 | team_days_rest, games_in_last_7/14_days |
| Betting Context | 7 | game_spread, game_total, spread_movement |
| Personnel Context | 2 | starters_out_count, questionable_players_count |
| Recent Performance | 4 | win_streak, loss_streak, last_game_margin |
| Travel Context | 1 | travel_miles |
| Source Tracking (v4.0) | 9 | 3 sources × 3 fields |
| Early Season | 2 | early_season_flag, insufficient_data_reason |
| Metadata | 2 | processed_at, created_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  game_date,
  COUNT(DISTINCT team_abbr) as teams_processed,
  COUNT(DISTINCT game_id) as games_scheduled,
  AVG(team_days_rest) as avg_rest,
  COUNT(CASE WHEN game_spread IS NOT NULL THEN 1 END) as games_with_odds,
  MAX(processed_at) as last_run
FROM `nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Expected Results:
-- teams_processed: 20-30 (2 × games scheduled)
-- games_scheduled: 10-15 games
-- avg_rest: 1-2 days
-- games_with_odds: 80-100% of games
-- last_run: < 2 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: Missing Betting Lines
**Symptom**: `game_spread` and `game_total` are NULL
**Diagnosis**:
```sql
-- Check odds availability
SELECT game_id, game_date,
       game_spread, game_total,
       source_odds_lines_completeness_pct
FROM `nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE()
  AND game_spread IS NULL
ORDER BY game_id;
```
**Fix**:
1. Check if `odds_api_game_lines` scraper ran successfully
2. Verify game_id mapping between schedule and odds tables
3. Betting lines may not be released yet (normal for future games)

### Issue 2: Incorrect Travel Miles
**Symptom**: Home team showing travel_miles > 0
**Diagnosis**:
```sql
-- Find home teams with travel miles
SELECT team_abbr, home_game, travel_miles
FROM `nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE()
  AND home_game = TRUE
  AND travel_miles > 0;
```
**Fix**:
1. Verify home_game flag is correct
2. Check travel miles calculation defaults to 0 for home games
3. Review team name mapping in travel distance calculation

### Issue 3: Streak Calculation Errors
**Symptom**: Team shows both win_streak > 0 AND loss_streak > 0
**Diagnosis**:
```sql
-- Find teams with both streaks
SELECT team_abbr, team_win_streak_entering,
       team_loss_streak_entering, last_game_result
FROM `nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE()
  AND team_win_streak_entering > 0
  AND team_loss_streak_entering > 0;
```
**Fix**: Logic error - should be mutually exclusive. Check streak calculation logic.

---

## Processing Flow

```
nbac_schedule ────────────┐
(today's games)          │
                         ├─→ UPCOMING TEAM CONTEXT ─┬─→ player_composite_factors
team_offense_summary ────┤   (2 rows per game)      └─→ ml_feature_store_v2
(recent performance)     │
                         │
odds_api_game_lines ─────┤
(betting context)        │
                         │
nbac_injury_report ──────┘
(personnel)
```

**Timing**:
- Runs: Multiple times per day (6 AM, noon, 6 PM, on line changes)
- Waits for: Team Offense Game Summary, Schedule
- Must complete before: Player Composite Factors
- Update frequency: When betting lines change

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Teams processed | < 20 (game day) | Critical |
| Games with odds | < 50% | Warning (early morning) |
| Games with odds | < 80% | Warning (afternoon) |
| Processing time | > 5 min | Warning |
| Home teams with travel | > 0 | Critical (logic error) |
| Source completeness | < 90% | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Upcoming Team Game Context Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/analytics/upcoming_team_game_context_tables.sql`
- 🧪 **Test Suite**: `tests/processors/analytics/upcoming_team_game_context/`
- 📊 **Related Processors**:
  - ↑ Upstream: Team Offense Game Summary, Schedule scraper
  - ↓ Downstream: Player Composite Factors (Phase 4)
  - 🔄 Peer: Upcoming Player Game Context

---

## Notes

- **Granularity**: 2 rows per game (home team view + away team view)
- **Betting Lines**: Optional - predictions still work without them (degraded)
- **Travel Distance**: Uses city-to-city distance calculation (not arena-specific)
- **Default Values**: Processor defaults starters_out, questionable_players to 0 if no injury data
- **Real-Time Updates**: Must re-run when betting lines move significantly

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
