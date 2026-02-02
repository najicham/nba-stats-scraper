# Session 73: Create Evening Schedulers + Validate Signals

## Context

Session 72 identified a critical gap: completed games aren't processed until 6 AM next day (6-18 hour delay). Created script and documentation to fix this.

## Read First

```bash
cat docs/09-handoff/2026-02-02-SESSION-72-HANDOFF.md
cat docs/08-projects/current/evening-analytics-processing/IMPLEMENTATION-PLAN.md
```

## Priority Tasks

### 1. Create Evening Analytics Schedulers

```bash
# Dry run first
./bin/orchestrators/setup_evening_analytics_schedulers.sh --dry-run

# Then create the jobs
./bin/orchestrators/setup_evening_analytics_schedulers.sh
```

This creates 4 jobs:
- `evening-analytics-6pm-et` (Sat/Sun) - Weekend matinees
- `evening-analytics-10pm-et` (daily) - 7 PM games
- `evening-analytics-1am-et` (daily) - West Coast games
- `morning-analytics-catchup-9am-et` (daily) - Safety net

### 2. Check Feb 1 Games & Validate RED Signal

```sql
-- Check if all Feb 1 games are final
SELECT game_id, away_team_tricode || '@' || home_team_tricode, game_status
FROM nba_reference.nba_schedule WHERE game_date = DATE('2026-02-01');

-- Check if player_game_summary populated
SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = DATE('2026-02-01');

-- If populated, validate RED signal hit rate (expect 50-65%)
SELECT COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.game_date = DATE('2026-02-01')
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 5;
```

### 3. Check Feb 2 Predictions Have Lines

After 7 AM ET, betting data should be scraped:

```sql
SELECT system_id, COUNT(*) as predictions,
  COUNTIF(current_points_line IS NOT NULL) as has_lines
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-02')
GROUP BY system_id;
```

### 4. Game Completion Detection (Optional)

If time permits, investigate NBA.com game_status latency:
- See: `docs/08-projects/current/evening-analytics-processing/GAME-COMPLETION-DETECTION.md`
- Feb 2 has 4 games - good test opportunity

## Recent Deployments (Session 72)

All services up to date:
- prediction-coordinator (00127-79d) - Slack alerts enabled
- nba-phase3-analytics-processors (00170-gpc)
- nba-phase4-precompute-processors (00093-sx7)
- prediction-worker (00062-j8l) - execution_logger fix

## Key Files

- `bin/orchestrators/setup_evening_analytics_schedulers.sh` - Run this first
- `docs/08-projects/current/evening-analytics-processing/` - Full documentation
