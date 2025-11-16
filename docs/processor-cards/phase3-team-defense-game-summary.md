# Team Defense Game Summary Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 3 - Analytics |
| **Schedule** | After each game + nightly at 2:45 AM |
| **Duration** | 2-3 minutes (defensive actions from player stats) |
| **Priority** | **High** - Required for defensive matchup analysis |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py` | 740 lines |
| **Schema** | `schemas/bigquery/analytics/team_defense_game_summary_tables.sql` | 54 fields |
| **Tests** | `tests/processors/analytics/team_defense_game_summary/` | **39 total** |
| | - Unit tests | 26 tests |
| | - Integration tests | 5 tests |
| | - Validation tests | 3 tests |
| | - Mocking verification | 5 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 2 Raw Sources:
  ├─ nbac_team_boxscore (CRITICAL) - Opponent offensive stats
  ├─ nbac_gamebook_player_stats (PRIMARY) - Defensive actions (blocks, steals)
  └─ bdl_player_boxscores (FALLBACK) - Defensive actions backup

Consumers (Phase 4):
  ├─ team_defense_zone_analysis - Aggregates defensive metrics by zone
  └─ player_composite_factors - Opponent defensive strength factor
```

---

## What It Does

1. **Primary Function**: Flips opponent's offense to calculate team defensive performance
2. **Key Output**: One row per defending team per game with points allowed and defensive actions
3. **Value**: Enables defensive matchup analysis for player prop predictions

---

## Key Metrics Calculated

### 1. Defensive Rating (Points Allowed Per 100 Possessions)
```python
# Team defensive efficiency
defensive_rating = (points_allowed / possessions) * 100
```
- **Range**: 100.0 - 120.0 (typical)
- **Example**: Elite defense = 106.5, poor defense = 116.8

### 2. Opponent True Shooting % Allowed
```python
# How efficiently opponent scored against this defense
opponent_ts_pct = opponent_points /
                  (2 * (opponent_fga + 0.44 * opponent_fta))
```
- **Range**: 0.500 - 0.650 (typical)
- **Example**: Strong defense allows 0.535, weak allows 0.618

### 3. Turnovers Forced Per Game
```python
# Defensive playmaking metric
turnovers_forced = opponent_turnovers
```
- **Range**: 8 - 20 (typical)
- **Example**: Aggressive defense forces 16, passive forces 11

---

## Output Schema Summary

**Total Fields**: 54

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | game_id, defending_team_abbr, game_date |
| Opponent Stats Allowed | 11 | points_allowed, opp_fg_attempts, opp_rebounds |
| Shot Zone Defense | 9 | paint_attempts_allowed, mid_range_makes_allowed |
| Defensive Actions | 5 | blocks, steals, defensive_rebounds |
| Advanced Metrics | 3 | defensive_rating, opponent_pace, opponent_ts_pct |
| Game Context | 4 | home_game, win_flag, overtime_periods |
| Source Tracking (v4.0) | 9 | 3 sources × 3 fields |
| Data Quality | 3 | data_quality_tier, primary_source_used |
| Metadata | 2 | processed_at, created_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  game_date,
  COUNT(DISTINCT defending_team_abbr) as teams_processed,
  AVG(defensive_rating) as avg_def_rating,
  AVG(source_gamebook_players_completeness_pct) as avg_completeness,
  COUNT(CASE WHEN data_quality_tier = 'high' THEN 1 END) as high_quality_count,
  MAX(processed_at) as last_run
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Expected Results:
-- teams_processed: 20-30 per game day
-- avg_def_rating: 108-115 (league average)
-- avg_completeness: > 90%
-- high_quality_count: > 80% of teams
-- last_run: < 6 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: Low Data Quality Tier
**Symptom**: `data_quality_tier = 'low'` (missing defensive actions)
**Diagnosis**:
```sql
-- Check which source provided data
SELECT game_id, defending_team_abbr,
       primary_source_used,
       data_quality_tier,
       source_gamebook_players_completeness_pct
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE()
  AND data_quality_tier = 'low'
ORDER BY defending_team_abbr;
```
**Fix**:
1. High = gamebook available (best)
2. Medium = BDL fallback used (acceptable)
3. Low = only opponent stats, no defensive actions
4. Re-run after `nbac_gamebook_player_stats` completes

### Issue 2: Missing Blocks/Steals
**Symptom**: `steals` or `blocks` are NULL or 0 for all players
**Diagnosis**:
```sql
-- Check defensive actions availability
SELECT COUNT(*) as total_teams,
       COUNT(steals) as has_steals,
       COUNT(CASE WHEN steals > 0 THEN 1 END) as non_zero_steals
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE();
```
**Fix**:
1. Verify gamebook has player-level defensive stats
2. Check aggregation logic not filtering out defensive actions
3. Confirm BDL fallback is enabled

### Issue 3: Perspective Flip Errors
**Symptom**: Defensive stats look like offensive stats
**Fix**:
1. Verify opponent identification logic (home/away flip)
2. Check team abbreviation mapping
3. Ensure reading opponent's offensive stats, not own team's

---

## Processing Flow

```
nbac_team_boxscore ────────┐
(opponent's offense)       │
                           ├─→ TEAM DEFENSE SUMMARY ─→ team_defense_zone_analysis
nbac_gamebook_player_stats─┤
(defensive actions)        │
                           │
bdl_player_boxscores ──────┘
(fallback)
```

**Timing**:
- Waits for: Team boxscore + gamebook player stats (30-60 min after game)
- Must complete before: Team Defense Zone Analysis can run
- Total window: Process within 2 hours of game completion

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Teams processed | < 20 (game day) | Critical |
| Data quality 'low' | > 20% of teams | Warning |
| Avg defensive rating | < 100 or > 125 | Warning |
| Source completeness | < 85% | Warning |
| Missing defensive actions | > 30% | Critical |
| Processing time | > 10 min | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Team Defense Game Summary Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/analytics/team_defense_game_summary_tables.sql`
- 🧪 **Test Suite**: `tests/processors/analytics/team_defense_game_summary/`
- 📊 **Related Processors**:
  - ↑ Upstream: Phase 2 Scrapers (nbac_team_boxscore, nbac_gamebook_player_stats)
  - ↓ Downstream: Team Defense Zone Analysis
  - 🔄 Peer: Team Offense Game Summary

---

## Notes

- **Perspective Flip**: Opponent's offense = this team's defense (key design pattern)
- **Multi-Source Strategy**: Gamebook (best) → BDL (fallback) → Team stats only (degraded)
- **v2.0 Architecture**: Now reads Phase 2 directly (was Phase 3 in v1.0, caused circular deps)
- **Shot Zones Deferred**: Paint/mid-range defense requires play-by-play data (future enhancement)

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
