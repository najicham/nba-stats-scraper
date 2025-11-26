# Player Game Summary Processor - Quick Reference

**Last Updated**: 2025-11-25
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 3 - Analytics |
| **Schedule** | After each game + nightly at 2:00 AM |
| **Duration** | 2-5 minutes (10 games × 20 players) |
| **Priority** | **High** - Foundation for all Phase 4/5 processors |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | 798 lines |
| **Schema** | `schemas/bigquery/analytics/player_game_summary_tables.sql` | 72 fields |
| **Tests** | `tests/processors/analytics/player_game_summary/` | **96 total** |
| | - Unit tests | 41 tests |
| | - Integration tests | 22 tests |
| | - Validation tests | 33 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 2 Raw Sources:
  ├─ nbac_gamebook_player_stats (CRITICAL) - Player stats, advanced metrics
  ├─ nbac_player_boxscore (CRITICAL) - Basic boxscore stats
  ├─ bdl_player_boxscores (OPTIONAL) - Fallback for missing data
  ├─ nbac_team_boxscore (CRITICAL) - Team totals for usage calc
  ├─ nbac_schedule (CRITICAL) - Game context, home/away
  └─ nbac_advanced_stats (OPTIONAL) - Advanced metrics fallback

Phase 3 Self-Join:
  └─ player_game_summary (SELF) - Season averages calculation

Consumers (Phase 4):
  ├─ player_daily_cache - Caches aggregated stats
  ├─ player_shot_zone_analysis - Uses shooting data
  └─ ml_feature_store_v2 - Phase 3 fallback source
```

---

## What It Does

1. **Primary Function**: Transforms raw Phase 2 game stats into clean per-player-per-game analytics records
2. **Key Output**: One row per player per game with 72 fields (stats, metrics, tracking)
3. **Value**: Single source of truth for player performance; feeds all downstream analytics and predictions

---

## Key Metrics Calculated

### 1. True Shooting Percentage
```python
# More accurate than FG% - accounts for FTs and 3PT value
ts_pct = points / (2 * (fga + 0.44 * fta))
```
- **Range**: 0.400 - 0.700 (typical)
- **Example**: 28 pts on 18 FGA + 6 FTA = 0.609 TS%

### 2. Usage Rate
```python
# % of team possessions used while on court
usage_rate = 100 * ((fga + 0.44*fta + tov) * (team_min/5)) /
              (minutes * (team_fga + 0.44*team_fta + team_tov))
```
- **Range**: 15.0 - 40.0 (typical)
- **Example**: Star player = 32.5%, role player = 18.2%

### 3. Game Score (Efficiency)
```python
# Weighted composite efficiency metric
game_score = pts + 0.4*fg - 0.7*fga - 0.4*(fta-ft) +
             0.7*oreb + 0.3*dreb + stl + 0.7*ast +
             0.7*blk - 0.4*pf - tov
```
- **Range**: -10 to 40+ (typical)
- **Example**: Excellent game = 28.5, poor game = 3.2

---

## Output Schema Summary

**Total Fields**: 72

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | player_lookup, game_id, game_date |
| Basic Stats | 18 | points, rebounds, assists, steals, blocks |
| Shooting Metrics | 15 | fg_pct, three_pt_pct, ts_pct, efg_pct |
| Advanced Metrics | 12 | usage_rate, game_score, per, ortg |
| Shot Zones | 12 | paint_makes/attempts, mid_range, three_pt |
| Game Context | 4 | home_game, win_flag, plus_minus |
| Source Tracking (v4.0) | 18 | 6 sources × 3 fields each |
| Metadata | 2 | processed_at, created_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players_processed,
  COUNT(DISTINCT game_id) as games_processed,
  AVG(source_gamebook_completeness_pct) as avg_completeness,
  MAX(processed_at) as last_run
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Expected Results:
-- players_processed: 200-300 per game day (10 games × 20-30 players)
-- games_processed: 8-15 games per day
-- avg_completeness: > 95%
-- last_run: < 6 hours old (for recent games)
```

---

## Common Issues & Quick Fixes

### Issue 1: Low Completeness (<90%)
**Symptom**: `source_gamebook_completeness_pct < 90%`
**Diagnosis**:
```sql
-- Find which games have incomplete data
SELECT game_id, game_date,
       source_gamebook_completeness_pct,
       primary_source_used
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE()
  AND source_gamebook_completeness_pct < 90
ORDER BY source_gamebook_completeness_pct;
```
**Fix**:
1. Check if `nbac_gamebook_player_stats` scraper completed
2. Verify game finished (not in-progress)
3. Re-run processor after scraper completes

### Issue 2: Missing Advanced Metrics
**Symptom**: `usage_rate`, `ts_pct`, or `game_score` are NULL
**Diagnosis**:
```sql
-- Check team totals availability
SELECT game_id,
       COUNT(*) as players,
       COUNT(usage_rate) as has_usage,
       COUNT(ts_pct) as has_ts
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE()
GROUP BY game_id
HAVING COUNT(usage_rate) < COUNT(*);
```
**Fix**:
1. Verify `nbac_team_boxscore` has team totals for this game
2. Check for division-by-zero edge cases (overtime games)
3. Re-run processor with `--force` flag

### Issue 3: Stale Data (>24 hours)
**Symptom**: Last game from yesterday not processed
**Fix**:
1. Check Phase 2 scrapers completed: `bin/orchestration/quick_health_check.sh`
2. Manually trigger: `python player_game_summary_processor.py --date YYYY-MM-DD`
3. Check Cloud Scheduler enabled

---

## Processing Flow

```
nbac_gamebook_player_stats ─┐
nbac_player_boxscore ────────┤
bdl_player_boxscores ────────┼─→ PLAYER GAME SUMMARY ─┬─→ player_daily_cache
nbac_team_boxscore ──────────┤                          ├─→ player_shot_zone_analysis
nbac_schedule ───────────────┤                          ├─→ upcoming_player_game_context
nbac_advanced_stats ─────────┘                          └─→ ml_feature_store_v2 (fallback)
```

**Timing**:
- Waits for: Phase 2 scrapers (30-60 min after game ends)
- Must complete before: Phase 4 precompute processors can run
- Total window: Process within 2 hours of game completion

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Players processed | < 100 (game day) | Critical |
| Avg completeness | < 85% | Warning |
| Avg completeness | < 70% | Critical |
| Processing time | > 10 min | Warning |
| Source age | > 24 hrs | Warning |
| Source age | > 72 hrs | Critical |
| Data quality tier | > 20% low | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Player Game Summary Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/analytics/player_game_summary_tables.sql`
- 🧪 **Test Suite**: `tests/processors/analytics/player_game_summary/`
- 📊 **Related Processors**:
  - ↑ Upstream: Phase 2 Scrapers (nbac_gamebook, bdl_player_boxscores)
  - ↓ Downstream: Player Daily Cache, Player Shot Zone Analysis
  - 🔄 Peer: Team Offense Game Summary, Team Defense Game Summary

---

## Notes

- **Multi-Source Strategy**: Tries gamebook → BDL → player boxscore in priority order
- **Self-Join**: Uses own data to calculate season averages (requires historical data)
- **Graceful Degradation**: Continues with partial data when optional sources unavailable
- **Critical for Week 1**: All Phase 5 prediction systems depend on this processor

---

**Card Version**: 1.1
**Created**: 2025-11-15
**Last Updated**: 2025-11-25
