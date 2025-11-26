# Player Daily Cache Processor - Quick Reference

**Last Updated**: 2025-11-25
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 4 - Optimization/Cache |
| **Schedule** | Nightly at 12:00 AM (runs LAST in Phase 4) |
| **Duration** | 5-10 minutes (450 players) |
| **Priority** | **Medium** - Performance optimization (not critical Week 1) |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` | 1087 lines |
| **Schema** | `schemas/bigquery/precompute/player_daily_cache.sql` | 43 fields |
| **Tests** | `tests/processors/precompute/player_daily_cache/` | **50 total** |
| | - Unit tests | 26 tests |
| | - Integration tests | 8 tests |
| | - Validation tests | 16 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 3 Analytics:
  ├─ player_game_summary (CRITICAL) - Performance metrics
  ├─ team_offense_game_summary (CRITICAL) - Team pace, offensive rating
  └─ upcoming_player_game_context (CRITICAL) - Fatigue metrics

Phase 4 Precompute:
  └─ player_shot_zone_analysis (CRITICAL) - Shot zone tendencies

Consumers (Phase 5):
  └─ All prediction systems - Load cache once, reuse all day
```

---

## What It Does

1. **Primary Function**: Pre-computes and caches static daily player stats that won't change during the day
2. **Key Output**: One snapshot per player with aggregated performance, fatigue, and shot zone data
3. **Value**: **79% cost reduction** + **2000x speed improvement** for real-time prediction updates

**ROI**: Eliminates $27/month in repeated BigQuery queries. Cache once at midnight, reuse hundreds of times.

---

## Performance Impact

### Without Cache (Old Approach)
- **Cost**: $34/month (repeated queries throughout day)
- **Speed**: 2-3 seconds per query
- **Pattern**: Phase 5 queries BigQuery on every odds update (every 5 min)

### With Cache (New Approach)
- **Cost**: $7/month (single nightly query)
- **Speed**: <1 millisecond (dict lookup)
- **Pattern**: Phase 5 loads cache at startup, reuses all day
- **Savings**: $27/month (79% reduction), 2000x faster

---

## Key Data Cached

### 1. Recent Performance (Won't Change)
```python
# Yesterday's games are yesterday's games
points_avg_last_5 = avg(last_5_games.points)
points_avg_last_10 = avg(last_10_games.points)
points_avg_season = avg(all_games.points)
points_std_last_10 = std(last_10_games.points)  # Volatility
```
- **Updates**: Only when new game processed (not intraday)

### 2. Team Context (Won't Change)
```python
# Team's recent pace is fixed for the day
team_pace_last_10 = avg(last_10_team_games.pace)
team_off_rating_last_10 = avg(last_10_team_games.off_rating)
```
- **Updates**: Only after team plays (not intraday)

### 3. Fatigue Metrics (Direct Copy from Phase 3)
```python
# Simply copy pre-calculated fatigue from upcoming_player_game_context
games_in_last_7_days = context.games_in_last_7_days
minutes_in_last_7_days = context.minutes_in_last_7_days
back_to_backs_last_14_days = context.back_to_backs_last_14_days
```
- **No calculation**: Already computed in Phase 3

### 4. Shot Zone Tendencies (Direct Copy from Phase 4)
```python
# Copy from player_shot_zone_analysis
primary_scoring_zone = shot_zones.primary_scoring_zone
paint_rate_last_10 = shot_zones.paint_rate_last_10
three_pt_rate_last_10 = shot_zones.three_pt_rate_last_10
```
- **No calculation**: Already computed in Phase 4

---

## Output Schema Summary

**Total Fields**: 43

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 3 | player_lookup, universal_player_id, cache_date |
| Recent Performance | 8 | points_avg_last_5/10/season, minutes_avg, usage_rate |
| Team Context | 3 | team_pace, team_off_rating, player_usage_rate_season |
| Fatigue Metrics | 7 | games_in_last_7/14_days, minutes_in_last_7/14_days |
| Shot Zone Tendencies | 4 | primary_scoring_zone, paint_rate, three_pt_rate |
| Player Demographics | 1 | player_age |
| Source Tracking (v4.0) | 12 | 4 sources × 3 fields |
| Early Season | 2 | early_season_flag, insufficient_data_reason |
| Cache Metadata | 3 | cache_version, created_at, processed_at |

---

## Health Check Query

```sql
-- Run this to verify cache health
SELECT
  COUNT(*) >= 100 as enough_players,
  AVG(games_played_season) >= 15 as enough_games,
  COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season_count,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),
      source_player_game_last_updated, HOUR)) as max_source_age_hrs
FROM `nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE();

-- Expected Results:
-- enough_players: TRUE (100+ on game day)
-- enough_games: TRUE (mid-season)
-- early_season_count: < 30 (after week 3)
-- max_source_age_hrs: < 24
```

---

## Common Issues & Quick Fixes

### Issue 1: No Players Cached (Game Day)
**Symptom**: Cache empty on game day
**Diagnosis**:
```sql
-- Check if games scheduled today
SELECT COUNT(*) as expected_players
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
```
**Fix**:
1. If games scheduled but cache empty → Check processor logs
2. If no games scheduled → Normal (off-day, cache will be empty)
3. Verify Phase 4 dependencies (player_shot_zone) completed

### Issue 2: High Early Season Rate
**Symptom**: Many players with `early_season_flag = TRUE`
**Diagnosis**:
```sql
-- Check early season distribution
SELECT
  COUNT(*) as total_players,
  SUM(CASE WHEN early_season_flag THEN 1 END) as early_season_count,
  ROUND(100.0 * SUM(CASE WHEN early_season_flag THEN 1 END) / COUNT(*), 1) as pct
FROM `nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE();
```
**Fix**:
1. Expected first 3 weeks of season
2. After week 3: Check if player_game_summary has sufficient history
3. Run backfill if needed

### Issue 3: Stale Source Data
**Symptom**: Source timestamps >24 hours old
**Fix**:
1. Check Phase 3 processors completed successfully
2. Check Phase 4 player_shot_zone_analysis completed
3. Verify orchestration timing (should run at 12 AM)

---

## Processing Flow

```
player_game_summary ────────┐
team_offense_game_summary ──┤
upcoming_player_context ────┼─→ PLAYER DAILY CACHE ─→ Phase 5 loads once
player_shot_zone_analysis ──┘     (450 players)        at startup, reuses
                                                        all day (2000x faster!)
```

**Timing**:
- Runs: 12:00 AM nightly (LAST in Phase 4 - waits for all others)
- Waits for: 2 Phase 3 + 1 Phase 4 processors
- Update frequency: Once per day (static snapshot)
- Phase 5 usage: Load at 6 AM startup, never query BigQuery again

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Players cached | < 100 (game day) | Warning |
| Players cached | 0 (game day) | Critical |
| Early season rate | > 20% (after week 3) | Warning |
| Source age | > 24 hrs | Warning |
| Processing time | > 15 min | Warning |
| Assisted rate NULL | > 10% | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Player Daily Cache Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/precompute/player_daily_cache.sql`
- 🧪 **Test Suite**: `tests/processors/precompute/player_daily_cache/`
- 📊 **Related Processors**:
  - ↑ Upstream: Player Shot Zone Analysis (Phase 4)
  - → Consumers: All Phase 5 prediction systems
  - 🔄 Peer: ML Feature Store V2 (can run in parallel)

---

## Notes

- **Cost Savings**: $27/month saved by eliminating repeated queries
- **Speed Improvement**: 2000x faster (2.5s → 0.00125s)
- **Static Snapshot**: Data doesn't change during games (by design)
- **Four-Source Dependency**: Most complex Phase 4 processor (2 Phase 3 + 2 Phase 4)
- **Phase 5 Pattern**: Load once at startup (6 AM), convert to dict for O(1) lookups
- **30-Day Retention**: Auto-expires after 30 days to control storage costs

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
