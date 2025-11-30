# Single Entity Debugging Guide

**File:** `docs/monitoring/07-single-entity-debugging.md`
**Created:** 2025-11-18 15:45 PST
**Last Updated:** 2025-11-18 15:45 PST
**Purpose:** Trace individual players, teams, or games through the entire pipeline
**Status:** Current
**Audience:** Engineers debugging specific entities, on-call engineers

---

## 🎯 Overview

**This document covers:**
- ✅ Player trace queries (follow LeBron through all 5 phases)
- ✅ Team trace queries (follow Lakers through pipeline)
- ✅ Game trace queries (follow specific game)
- ✅ "Why didn't this entity process?" diagnostic checklist
- ✅ Cross-date dependency checks for entities
- ✅ Common issues and resolutions

**Use this when:**
- "Why doesn't LeBron have data for Nov 18?"
- "Lakers team stats missing for specific game"
- "Game GSW vs LAL shows incomplete data"
- "Player processed in Phase 2 but missing in Phase 3"

---

## 👤 Player Trace

### Query 1: Full Player Pipeline Trace

**Purpose:** See everywhere a player appears (or doesn't) for a specific date

```sql
-- Trace LeBron James through all phases for Nov 18, 2024
DECLARE target_date DATE DEFAULT '2024-11-18';
DECLARE target_player STRING DEFAULT 'LeBron James';

-- Phase 1: Scraper (check if game existed)
WITH phase1_games AS (
  SELECT
    'Phase 1: Scraper' as phase,
    game_id,
    home_team,
    away_team,
    'Game scraped' as status
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = target_date
    AND (home_team = 'LAL' OR away_team = 'LAL')  -- LeBron plays for Lakers
),

-- Phase 2: Raw data
phase2_raw AS (
  SELECT
    'Phase 2: Raw' as phase,
    game_id,
    player_name,
    team,
    minutes_played,
    points,
    'Player in raw data' as status
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date = target_date
    AND player_name = target_player
),

-- Phase 3: Analytics
phase3_analytics AS (
  SELECT
    'Phase 3: Analytics' as phase,
    game_id,
    player_name,
    team,
    minutes_played,
    points,
    'Player in analytics' as status
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = target_date
    AND player_name = target_player
),

-- Phase 4: Precompute
phase4_precompute AS (
  SELECT
    'Phase 4: Precompute' as phase,
    player_id,
    quality_score,
    early_season_flag,
    'Player in precompute' as status
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date = target_date
    AND player_id IN (
      SELECT DISTINCT player_id
      FROM `nba-props-platform.nba_analytics.player_game_summary`
      WHERE player_name = target_player
      LIMIT 1
    )
),

-- Phase 5: Predictions
phase5_predictions AS (
  SELECT
    'Phase 5: Predictions' as phase,
    player_id,
    prediction_type,
    predicted_value,
    confidence_score,
    'Player has predictions' as status
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date = target_date
    AND player_id IN (
      SELECT DISTINCT player_id
      FROM `nba-props-platform.nba_analytics.player_game_summary`
      WHERE player_name = target_player
      LIMIT 1
    )
)

-- Combine all phases
SELECT * FROM phase1_games
UNION ALL
SELECT phase, game_id, NULL as player_name, NULL as team, NULL as minutes_played, NULL as points, status FROM phase2_raw
UNION ALL
SELECT phase, game_id, player_name, team, minutes_played, points, status FROM phase3_analytics
UNION ALL
SELECT phase, NULL as game_id, NULL, NULL, NULL, NULL, status FROM phase4_precompute
UNION ALL
SELECT phase, NULL as game_id, NULL, NULL, NULL, NULL, status FROM phase5_predictions
ORDER BY phase;
```

**Example Output:**
```
phase                | game_id     | player_name   | status
---------------------|-------------|---------------|------------------------
Phase 1: Scraper     | 0022400234  | NULL          | Game scraped
Phase 2: Raw         | 0022400234  | LeBron James  | Player in raw data
Phase 3: Analytics   | 0022400234  | LeBron James  | Player in analytics
Phase 4: Precompute  | NULL        | NULL          | Player in precompute
Phase 5: Predictions | NULL        | NULL          | ❌ NO PREDICTIONS FOUND
```

**Interpretation:**
- ✅ Player exists in Phases 1-4
- ❌ Missing in Phase 5 → Investigate prediction system

---

### Query 2: Player Processing History (Last 10 Games)

**Purpose:** See player's processing history over time

```sql
-- LeBron's last 10 games with processing status
DECLARE target_player STRING DEFAULT 'LeBron James';

WITH player_games AS (
  SELECT
    game_date,
    game_id,
    team,
    opponent,
    minutes_played,
    points,
    rebounds,
    assists
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE player_name = target_player
  ORDER BY game_date DESC
  LIMIT 10
),

precompute_status AS (
  SELECT
    game_date,
    quality_score,
    early_season_flag
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE player_id IN (
    SELECT DISTINCT player_id FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE player_name = target_player
    LIMIT 1
  )
),

prediction_status AS (
  SELECT
    game_date,
    COUNT(DISTINCT prediction_type) as prediction_count
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE player_id IN (
    SELECT DISTINCT player_id FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE player_name = target_player
    LIMIT 1
  )
  GROUP BY game_date
)

SELECT
  pg.game_date,
  pg.team,
  pg.opponent,
  pg.minutes_played,
  pg.points,
  CASE WHEN pc.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase4_complete,
  IFNULL(pc.quality_score, 0) as quality_score,
  CASE WHEN pred.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase5_complete,
  IFNULL(pred.prediction_count, 0) as predictions
FROM player_games pg
LEFT JOIN precompute_status pc ON pg.game_date = pc.game_date
LEFT JOIN prediction_status pred ON pg.game_date = pred.game_date
ORDER BY pg.game_date DESC;
```

**Example Output:**
```
game_date  | team | opponent | points | phase4_complete | quality_score | phase5_complete | predictions
-----------|------|----------|--------|-----------------|---------------|-----------------|------------
2024-11-18 | LAL  | GSW      | 28     | ✅              | 100           | ❌              | 0
2024-11-17 | LAL  | SAS      | 32     | ✅              | 95            | ✅              | 5
2024-11-15 | LAL  | MEM      | 25     | ✅              | 92            | ✅              | 5
```

**Interpretation:**
- Nov 18: Phase 4 complete, but Phase 5 missing → Check prediction coordinator
- Nov 17-15: Fully processed → Use as reference

---

## 🏀 Team Trace

### Query 3: Full Team Pipeline Trace

**Purpose:** See everywhere a team appears for a specific date

```sql
-- Trace Lakers through all phases for Nov 18, 2024
DECLARE target_date DATE DEFAULT '2024-11-18';
DECLARE target_team STRING DEFAULT 'LAL';

WITH phase1_games AS (
  SELECT
    'Phase 1: Scraper' as phase,
    game_id,
    home_team,
    away_team,
    CASE
      WHEN home_team = target_team THEN 'Home'
      WHEN away_team = target_team THEN 'Away'
    END as team_role,
    'Game scheduled' as status
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = target_date
    AND (home_team = target_team OR away_team = target_team)
),

phase2_team AS (
  SELECT
    'Phase 2: Raw' as phase,
    game_id,
    team,
    points,
    field_goals_made,
    field_goals_attempted,
    'Team boxscore available' as status
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
  WHERE game_date = target_date
    AND team = target_team
),

phase3_team AS (
  SELECT
    'Phase 3: Analytics' as phase,
    game_id,
    team,
    offensive_rating,
    defensive_rating,
    pace,
    'Team analytics calculated' as status
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_date = target_date
    AND team = target_team
)

SELECT
  phase,
  game_id,
  CASE
    WHEN team IS NOT NULL THEN team
    WHEN home_team = target_team THEN home_team
    WHEN away_team = target_team THEN away_team
  END as team,
  status
FROM (
  SELECT phase, game_id, NULL as team, home_team, away_team, NULL as team_role, status FROM phase1_games
  UNION ALL
  SELECT phase, game_id, team, NULL as home_team, NULL as away_team, NULL as team_role, status FROM phase2_team
  UNION ALL
  SELECT phase, game_id, team, NULL, NULL, NULL, status FROM phase3_team
)
ORDER BY phase;
```

---

## 🏟️ Game Trace

### Query 4: Full Game Pipeline Trace

**Purpose:** See all processing for a specific game

```sql
-- Trace game GSW @ LAL on Nov 18, 2024
DECLARE target_game_id STRING DEFAULT '0022400234';

WITH phase1_schedule AS (
  SELECT
    'Phase 1: Scraper' as phase,
    game_id,
    game_date,
    home_team,
    away_team,
    'Game scheduled' as status,
    created_at
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_id = target_game_id
),

phase2_players AS (
  SELECT
    'Phase 2: Raw Players' as phase,
    game_id,
    COUNT(DISTINCT player_id) as player_count,
    'Players processed' as status,
    MAX(created_at) as processed_at
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_id = target_game_id
  GROUP BY game_id
),

phase2_teams AS (
  SELECT
    'Phase 2: Raw Teams' as phase,
    game_id,
    COUNT(DISTINCT team) as team_count,
    'Teams processed' as status,
    MAX(created_at) as processed_at
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
  WHERE game_id = target_game_id
  GROUP BY game_id
),

phase3_players AS (
  SELECT
    'Phase 3: Analytics Players' as phase,
    game_id,
    COUNT(DISTINCT player_id) as player_count,
    'Players analyzed' as status,
    MAX(processed_at) as processed_at
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_id = target_game_id
  GROUP BY game_id
),

phase3_teams AS (
  SELECT
    'Phase 3: Analytics Teams' as phase,
    game_id,
    COUNT(DISTINCT team) as team_count,
    'Teams analyzed' as status,
    MAX(processed_at) as processed_at
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_id = target_game_id
  GROUP BY game_id
)

SELECT
  phase,
  game_id,
  CAST(player_count AS STRING) as entity_count,
  status,
  processed_at
FROM (
  SELECT phase, game_id, NULL as player_count, NULL as team_count, status, created_at as processed_at FROM phase1_schedule
  UNION ALL
  SELECT phase, game_id, player_count, NULL, status, processed_at FROM phase2_players
  UNION ALL
  SELECT phase, game_id, NULL, team_count, status, processed_at FROM phase2_teams
  UNION ALL
  SELECT phase, game_id, player_count, NULL, status, processed_at FROM phase3_players
  UNION ALL
  SELECT phase, game_id, NULL, team_count, status, processed_at FROM phase3_teams
)
ORDER BY processed_at;
```

**Example Output:**
```
phase                      | game_id     | entity_count | status             | processed_at
---------------------------|-------------|--------------|--------------------|-----------------------
Phase 1: Scraper           | 0022400234  | NULL         | Game scheduled     | 2024-11-17 15:30:00
Phase 2: Raw Players       | 0022400234  | 28           | Players processed  | 2024-11-18 03:45:12
Phase 2: Raw Teams         | 0022400234  | 2            | Teams processed    | 2024-11-18 03:45:18
Phase 3: Analytics Players | 0022400234  | 28           | Players analyzed   | 2024-11-18 04:12:35
Phase 3: Analytics Teams   | 0022400234  | 2            | Teams analyzed     | 2024-11-18 04:12:40
```

**Interpretation:**
- ✅ All phases completed successfully
- ✅ Player count consistent (28 in both Phase 2 and 3)
- ✅ Team count correct (2 teams)
- ✅ Processing timestamps show normal flow

---

## ❓ "Why Didn't This Entity Process?" Checklist

### Player Missing from Phase 3

**Checklist:**

1. **Does player exist in Phase 2?**
   ```sql
   SELECT * FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
   WHERE game_date = '2024-11-18' AND player_name = 'LeBron James';
   ```
   - ❌ No rows → Problem is in Phase 1 or 2 (scraper or raw processing)
   - ✅ Has rows → Continue to step 2

2. **Did player play? (Minutes > 0)**
   ```sql
   SELECT player_name, minutes_played
   FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
   WHERE game_date = '2024-11-18' AND player_name = 'LeBron James';
   ```
   - minutes_played = 0 → Player DNP, may be filtered out by Phase 3
   - minutes_played = NULL → Data quality issue
   - minutes_played > 0 → Continue to step 3

3. **Check Phase 3 processor logs**
   ```bash
   gcloud run jobs logs read phase3-player-game-summary \
     --region us-central1 --limit=100 | grep "LeBron James"
   ```
   - Look for errors, exceptions, or filters

4. **Check Phase 3 execution for that date**
   ```sql
   SELECT * FROM `nba-props-platform.nba_orchestration.processor_execution_log`
   WHERE processor_name = 'phase3-player-game-summary'
     AND DATE(processed_at) = '2024-11-18'
     AND status = 'failed';
   ```
   - If failed → Check error message
   - If success → Player was filtered intentionally

5. **Common reasons players filtered:**
   - Minutes played < 5 (minimum threshold)
   - Invalid stats (NULL values in required fields)
   - Duplicate player_id (data quality issue)
   - Team not in roster (two-way player edge case)

---

### Player Missing from Phase 4

**Checklist:**

1. **Does player exist in Phase 3?**
   ```sql
   SELECT * FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date = '2024-11-18' AND player_name = 'LeBron James';
   ```
   - ❌ No rows → Problem is in Phase 3 (see above)
   - ✅ Has rows → Continue to step 2

2. **Does player have sufficient historical data?**
   ```sql
   -- Check last 10 games for LeBron
   SELECT COUNT(DISTINCT game_date) as historical_games
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE player_name = 'LeBron James'
     AND game_date < '2024-11-18'
     AND game_date >= DATE_SUB('2024-11-18', INTERVAL 30 DAY);
   ```
   - historical_games < 5 → Early season, may skip or degrade
   - historical_games >= 5 → Continue to step 3

3. **Check Phase 4 processor logs**
   ```bash
   gcloud run jobs logs read phase4-player-composite-factors \
     --region us-central1 --limit=100 | grep "LeBron"
   ```

4. **Check cross-date dependency blockers**
   ```sql
   -- Are any required historical dates missing?
   WITH required_dates AS (
     SELECT DISTINCT game_date
     FROM `nba-props-platform.nba_raw.nbac_schedule`
     WHERE game_date BETWEEN DATE_SUB('2024-11-18', INTERVAL 30 DAY)
       AND DATE_SUB('2024-11-18', INTERVAL 1 DAY)
   ),
   available_dates AS (
     SELECT DISTINCT game_date
     FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date BETWEEN DATE_SUB('2024-11-18', INTERVAL 30 DAY)
       AND DATE_SUB('2024-11-18', INTERVAL 1 DAY)
   )
   SELECT r.game_date as missing_date
   FROM required_dates r
   LEFT JOIN available_dates a ON r.game_date = a.game_date
   WHERE a.game_date IS NULL
   ORDER BY r.game_date;
   ```
   - Missing dates → Backfill Phase 3 first
   - No missing dates → Continue to step 5

5. **Common reasons players filtered in Phase 4:**
   - Insufficient historical games (< minimum threshold)
   - Early season flag enabled (processor skipped)
   - Quality score too low to process
   - Dependency check failed

**Reference:** `docs/01-architecture/cross-date-dependencies.md`

---

### Player Missing from Phase 5

**Checklist:**

1. **Does player exist in Phase 4?**
   ```sql
   SELECT * FROM `nba-props-platform.nba_precompute.player_composite_factors`
   WHERE game_date = '2024-11-18'
     AND player_id IN (
       SELECT player_id FROM `nba-props-platform.nba_analytics.player_game_summary`
       WHERE player_name = 'LeBron James' LIMIT 1
     );
   ```
   - ❌ No rows → Problem is in Phase 4 (see above)
   - ✅ Has rows → Continue to step 2

2. **Did prediction coordinator run for that date?**
   ```bash
   gcloud run jobs logs read phase5-prediction-coordinator \
     --region us-central1 --limit=100 | grep "2024-11-18"
   ```
   - No logs → Coordinator didn't run
   - Has logs → Continue to step 3

3. **Check worker execution for player**
   ```bash
   gcloud run jobs logs read phase5-prediction-worker \
     --region us-central1 --limit=200 | grep "LeBron"
   ```
   - Look for prediction tasks for this player

4. **Check prediction eligibility**
   ```sql
   -- Does player have a game scheduled for prediction date?
   SELECT * FROM `nba-props-platform.nba_raw.nbac_schedule`
   WHERE game_date = '2024-11-18'
     AND (home_team = 'LAL' OR away_team = 'LAL');
   ```
   - No game scheduled → Player won't have predictions (correct behavior)
   - Game scheduled → Should have predictions

5. **Common reasons predictions missing:**
   - No game scheduled for that date
   - Coordinator filtered player (injured, not in rotation)
   - Worker failed for this specific player
   - Insufficient feature data (Phase 4 quality score too low)

**Reference:** `docs/predictions/operations/03-troubleshooting.md`

---

## 🔍 Historical Data Availability Check

### Query 5: Check If Player Has Enough Historical Games

**Purpose:** Verify player has sufficient history for Phase 4 processing

```sql
-- Check if LeBron has enough games for Phase 4 to run on Nov 18
DECLARE target_date DATE DEFAULT '2024-11-18';
DECLARE target_player STRING DEFAULT 'LeBron James';
DECLARE required_games INT64 DEFAULT 10;
DECLARE lookback_days INT64 DEFAULT 30;

WITH player_history AS (
  SELECT
    player_name,
    COUNT(DISTINCT game_date) as available_games,
    ARRAY_AGG(game_date ORDER BY game_date DESC LIMIT 10) as last_10_dates,
    MIN(game_date) as first_game,
    MAX(game_date) as most_recent_game
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE player_name = target_player
    AND game_date < target_date
    AND game_date >= DATE_SUB(target_date, INTERVAL lookback_days DAY)
  GROUP BY player_name
)

SELECT
  player_name,
  available_games,
  required_games,
  first_game,
  most_recent_game,
  CASE
    WHEN available_games >= required_games THEN '✅ Can process normally'
    WHEN available_games >= 5 THEN FORMAT('⚠️ Degraded mode (%d games)', available_games)
    ELSE FORMAT('❌ Insufficient data (%d games)', available_games)
  END as processing_status,
  last_10_dates
FROM player_history;
```

**Example Output:**
```
player_name  | available_games | required_games | processing_status         | last_10_dates
-------------|-----------------|----------------|---------------------------|------------------
LeBron James | 12              | 10             | ✅ Can process normally   | [2024-11-17, 2024-11-15, ...]
```

---

## 🐛 Common Issues & Resolutions

### Issue 1: Player in Phase 2 but Not Phase 3

**Cause:** Player filtered due to minimum minutes threshold

**Diagnosis:**
```sql
SELECT player_name, minutes_played
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date = '2024-11-18' AND minutes_played < 5;
```

**Resolution:**
- If minutes < 5 → Expected behavior (low-minute players filtered)
- If minutes >= 5 → Check Phase 3 processor logs for errors

---

### Issue 2: Team Data Complete but Player Data Missing

**Cause:** Player-specific processing failure

**Diagnosis:**
```bash
# Check Phase 3 player processor logs
gcloud run jobs logs read phase3-player-game-summary \
  --region us-central1 --limit=100 | grep ERROR
```

**Resolution:**
- Fix error in processor
- Re-run Phase 3 for that date
- Validate player appears after re-run

---

### Issue 3: Entire Game Missing Across All Phases

**Cause:** Phase 1 scraper never ran or failed

**Diagnosis:**
```sql
SELECT * FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) = '2024-11-18'
  AND scraper_name = 'nbac_schedule_scraper';
```

**Resolution:**
- If scraper failed → Check error logs
- If scraper didn't run → Check Cloud Scheduler
- Re-run scraper for that date
- Trigger downstream processing

---

### Issue 4: Player Has Predictions for Some Games, Not Others

**Cause:** Game-specific prediction eligibility (opponent, home/away, etc.)

**Diagnosis:**
```sql
-- Compare games with predictions vs without
WITH player_games AS (
  SELECT game_date, opponent, home_away
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE player_name = 'LeBron James'
  ORDER BY game_date DESC
  LIMIT 10
),
predictions AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE player_id IN (
    SELECT player_id FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE player_name = 'LeBron James' LIMIT 1
  )
)
SELECT
  pg.game_date,
  pg.opponent,
  pg.home_away,
  CASE WHEN p.game_date IS NOT NULL THEN '✅' ELSE '❌' END as has_predictions
FROM player_games pg
LEFT JOIN predictions p ON pg.game_date = p.game_date;
```

**Resolution:**
- Check prediction coordinator logic
- May be intentional (certain opponents filtered)
- Review prediction eligibility criteria

---

## 🔗 Related Documentation

**Operations:**
- `docs/operations/01-backfill-operations-guide.md` - Backfill missing data
- `docs/operations/02-dlq-recovery-guide.md` - DLQ recovery

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - System-wide monitoring
- `docs/monitoring/05-data-completeness-validation.md` - Validation queries
- `docs/monitoring/06-alerting-strategy-and-escalation.md` - Alert response

**Architecture:**
- `docs/01-architecture/cross-date-dependencies.md` - Historical data requirements

**Processors:**
- `docs/processors/01-phase2-operations-guide.md` - Phase 2 operations
- `docs/processors/04-phase3-troubleshooting.md` - Phase 3 troubleshooting

**Predictions:**
- `docs/predictions/operations/03-troubleshooting.md` - Phase 5 troubleshooting

---

## 📝 Quick Reference

### Debug Workflow

```
1. Find phase where entity appears
   ↓
2. Find phase where entity disappears
   ↓
3. Check logs for that phase
   ↓
4. Check processing conditions (filters, thresholds)
   ↓
5. Verify historical data if Phase 4+
   ↓
6. Fix root cause and re-process
```

---

### Quick Commands

```bash
# Check if player exists in Phase 2
bq query "SELECT * FROM nba_raw.nbac_gamebook_player_stats WHERE game_date='2024-11-18' AND player_name='LeBron James'"

# Check if player exists in Phase 3
bq query "SELECT * FROM nba_analytics.player_game_summary WHERE game_date='2024-11-18' AND player_name='LeBron James'"

# Check Phase 3 logs
gcloud run jobs logs read phase3-player-game-summary --region us-central1 --limit=100 | grep "LeBron"

# Check historical games
bq query "SELECT COUNT(DISTINCT game_date) FROM nba_analytics.player_game_summary WHERE player_name='LeBron James' AND game_date < '2024-11-18' AND game_date >= DATE_SUB('2024-11-18', INTERVAL 30 DAY)"
```

---

**Created:** 2025-11-18 15:45 PST
**Next Review:** After debugging first entity issue
**Status:** ✅ Ready to use
