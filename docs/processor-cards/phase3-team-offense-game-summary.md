# Team Offense Game Summary Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 3 - Analytics |
| **Schedule** | After each game + nightly at 2:30 AM |
| **Duration** | 1-2 minutes (10 games × 2 teams) |
| **Priority** | **High** - Required for team context and pace metrics |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py` | 692 lines |
| **Schema** | `schemas/bigquery/analytics/team_offense_game_summary_tables.sql` | 47 fields |
| **Tests** | `tests/processors/analytics/team_offense_game_summary/` | **97 total** |
| | - Unit tests | 57 tests |
| | - Integration tests | 9 tests |
| | - Validation tests | 31 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 2 Raw Sources:
  ├─ nbac_team_boxscore (CRITICAL) - Team offensive stats
  ├─ nbac_schedule (CRITICAL) - Game context, opponent
  └─ nbac_advanced_stats (OPTIONAL) - Advanced team metrics

Phase 3 Self-Join:
  └─ team_offense_game_summary (SELF) - Opponent context

Consumers (Phase 4):
  ├─ player_daily_cache - Team pace, offensive rating
  ├─ upcoming_team_game_context - Team performance trends
  └─ ml_feature_store_v2 - Team win percentage
```

---

## What It Does

1. **Primary Function**: Aggregates team-level offensive performance for each game
2. **Key Output**: One row per team per game with pace, efficiency, and shooting metrics
3. **Value**: Provides team context for player predictions; enables pace and usage adjustments

---

## Key Metrics Calculated

### 1. Pace (Possessions Per 48 Minutes)
```python
# Estimated team possessions, normalized to 48 minutes
possessions = 0.5 * ((fga + 0.4*fta - 1.07*(oreb/(oreb+opp_dreb)) *
                      (fga-fg) + tov) + (opp_fga + 0.4*opp_fta -
                      1.07*(opp_oreb/(opp_oreb+dreb)) * (opp_fga-opp_fg) + opp_tov))
pace = possessions * (48 / minutes_played)
```
- **Range**: 95.0 - 110.0 (typical)
- **Example**: Fast-paced team = 104.5, slow team = 97.2

### 2. Offensive Rating (Points Per 100 Possessions)
```python
# Team offensive efficiency
off_rating = (points / possessions) * 100
```
- **Range**: 100.0 - 125.0 (typical)
- **Example**: Elite offense = 118.5, poor offense = 105.2

### 3. Effective Field Goal Percentage
```python
# Adjusts FG% for 3PT value
efg_pct = (fg + 0.5 * three_pt_makes) / fga
```
- **Range**: 0.450 - 0.600 (typical)
- **Example**: Efficient shooting = 0.565, poor = 0.482

---

## Output Schema Summary

**Total Fields**: 47

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | game_id, team_abbr, game_date |
| Basic Stats | 13 | points, fga, rebounds, assists |
| Shooting Metrics | 8 | fg_pct, three_pt_pct, efg_pct, ts_pct |
| Advanced Metrics | 6 | pace, off_rating, possessions |
| Opponent Context | 6 | opponent_points, opponent_pace |
| Game Context | 3 | home_game, win_flag, overtime_periods |
| Source Tracking (v4.0) | 9 | 3 sources × 3 fields |
| Metadata | 2 | processed_at, created_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  game_date,
  COUNT(DISTINCT team_abbr) as teams_processed,
  COUNT(DISTINCT game_id) as games_processed,
  AVG(pace) as avg_pace,
  AVG(off_rating) as avg_off_rating,
  MAX(processed_at) as last_run
FROM `nba_analytics.team_offense_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Expected Results:
-- teams_processed: 20-30 per game day (2 teams × 10-15 games)
-- games_processed: 8-15 games per day
-- avg_pace: 98-102 (league average)
-- avg_off_rating: 110-115 (league average)
-- last_run: < 6 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: Pace Calculation Errors
**Symptom**: Pace > 120 or < 80 (unrealistic values)
**Diagnosis**:
```sql
-- Find games with unusual pace
SELECT game_id, team_abbr, pace, possessions,
       minutes_played, overtime_periods
FROM `nba_analytics.team_offense_game_summary`
WHERE game_date = CURRENT_DATE()
  AND (pace > 115 OR pace < 90)
ORDER BY pace DESC;
```
**Fix**:
1. Check for overtime games (48 min normalization issue)
2. Verify `nbac_team_boxscore` has correct minutes_played
3. Check possessions calculation for division by zero

### Issue 2: Missing Opponent Context
**Symptom**: `opponent_pace`, `opponent_off_rating` are NULL
**Diagnosis**:
```sql
-- Check self-join success
SELECT game_id,
       COUNT(*) as teams,
       COUNT(opponent_pace) as has_opponent_context
FROM `nba_analytics.team_offense_game_summary`
WHERE game_date = CURRENT_DATE()
GROUP BY game_id
HAVING COUNT(opponent_pace) < COUNT(*);
```
**Fix**:
1. Ensure both teams processed for each game
2. Check team abbreviation mapping is correct
3. Re-run processor after both teams available

### Issue 3: Team Win Percentage Incorrect
**Symptom**: Season win percentage doesn't match standings
**Fix**:
1. Verify self-join includes all historical games
2. Check `win_flag` calculation (points > opponent_points)
3. Ensure partition filters don't exclude historical data

---

## Processing Flow

```
nbac_team_boxscore ─┐
nbac_schedule ──────┼─→ TEAM OFFENSE SUMMARY ─┬─→ player_daily_cache
nbac_advanced_stats ─┘   (self-join for       ├─→ upcoming_team_game_context
                          opponent context)    └─→ ml_feature_store_v2
```

**Timing**:
- Waits for: Phase 2 team boxscore scraper (20-40 min after game ends)
- Must complete before: Player Daily Cache can run
- Total window: Process within 1 hour of game completion

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Teams processed | < 20 (game day) | Critical |
| Avg pace | < 90 or > 110 | Warning |
| Avg off_rating | < 100 or > 125 | Warning |
| Processing time | > 5 min | Warning |
| Source completeness | < 95% | Warning |
| Missing opponent data | > 10% | Critical |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Team Offense Game Summary Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/analytics/team_offense_game_summary_tables.sql`
- 🧪 **Test Suite**: `tests/processors/analytics/team_offense_game_summary/`
- 📊 **Related Processors**:
  - ↑ Upstream: Phase 2 Scrapers (nbac_team_boxscore)
  - ↓ Downstream: Player Daily Cache, Upcoming Team Game Context
  - 🔄 Peer: Team Defense Game Summary, Player Game Summary

---

## Notes

- **Self-Join Pattern**: Joins to itself to get opponent's offensive stats (for context)
- **Overtime Handling**: Normalizes pace to 48 minutes even for OT games
- **Possessions Estimation**: Uses Dean Oliver's formula (industry standard)
- **Required for Pace Adjustments**: All player predictions need team pace metrics

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
