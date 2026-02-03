# Data Quality Runbook

Procedures for investigating and fixing data quality issues in the NBA Stats pipeline.

## Quick Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| 0% usage_rate | Team stats missing for all games | Check team_offense processor ran |
| Partial usage_rate | Some games missing team stats | Per-game - check specific games |
| 0% minutes | Box score data missing | Check Phase 2 scrapers |
| Low active players | Scraper didn't get all players | Check BDL/NBAC raw data |
| All NULL for a game | Game data completely missing | Check scraper logs, backfill |

---

## Issue: Usage Rate 0% or Low Coverage

### Symptoms
- `usage_rate` = NULL for all/most players
- `data_quality_flag` = 'partial_no_team_stats'
- ML feature quality drops below 85%

### Quick Diagnosis
```sql
-- Check usage_rate coverage by game
SELECT
    game_id,
    COUNTIF(is_dnp = FALSE) as active,
    COUNTIF(is_dnp = FALSE AND usage_rate > 0) as has_usage,
    ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate > 0) /
        NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) as pct
FROM nba_analytics.player_game_summary
WHERE game_date = 'YYYY-MM-DD'
GROUP BY game_id
ORDER BY pct ASC
```

### Check Team Data Exists
```sql
-- Verify team_offense_game_summary has data
SELECT game_id, team_abbr, possessions, fg_attempts
FROM nba_analytics.team_offense_game_summary
WHERE game_date = 'YYYY-MM-DD'
ORDER BY game_id
```

### Root Causes

1. **Team offense processor didn't run**
   - Check Cloud Run logs for `nba-phase3-analytics-processors`
   - Verify `team_offense_game_summary` triggered before `player_game_summary`

2. **Specific game(s) missing team data**
   - Session 96 fix: usage_rate now calculated per-game
   - Games WITH team data get usage_rate, games WITHOUT get NULL
   - This is expected behavior, not a bug

3. **Data race condition**
   - Player processor ran before team processor completed
   - Re-trigger player_game_summary processor

### Fix Procedures

**Reprocess player_game_summary:**
```bash
# Trigger reprocessing for specific date
curl -X POST "https://nba-phase3-analytics-processors-xxx.run.app/process" \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_game_summary", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}'
```

**Full Phase 3 reprocess:**
```bash
# Trigger all Phase 3 processors
gcloud pubsub topics publish phase2-complete \
  --message='{"data_date": "YYYY-MM-DD", "trigger_source": "manual_fix"}'
```

---

## Issue: Minutes Missing

### Symptoms
- `minutes_played` = NULL for active players
- Players marked as DNP incorrectly

### Quick Diagnosis
```sql
-- Check minutes coverage
SELECT
    game_id,
    COUNTIF(is_dnp = FALSE) as active,
    COUNTIF(is_dnp = FALSE AND minutes_played > 0) as has_minutes
FROM nba_analytics.player_game_summary
WHERE game_date = 'YYYY-MM-DD'
GROUP BY game_id
```

### Check Raw Data
```sql
-- Check gamebook data
SELECT game_id, COUNT(*) as players, SUM(minutes) as total_min
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = 'YYYY-MM-DD' AND player_status = 'active'
GROUP BY game_id
```

### Root Causes

1. **Gamebook not scraped yet**
   - Gamebooks available ~6 AM ET next day
   - Fallback to nbac_player_boxscores if enabled

2. **Scraper failed**
   - Check Phase 1 scraper logs
   - Verify schedule has game marked as Final (status=3)

### Fix Procedures

**Trigger scraper backfill:**
```bash
# Backfill gamebook scraper for specific date
PYTHONPATH=. python scrapers/nbac_gamebook_player_stats_scraper.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

---

## Issue: Game Completely Missing

### Symptoms
- Game in schedule with status=3 (Final)
- Zero records in raw tables for that game_id
- Zero records in analytics for that game_id

### Quick Diagnosis
```sql
-- Check schedule
SELECT game_id, game_status, away_team_tricode, home_team_tricode
FROM nba_reference.nba_schedule
WHERE game_date = 'YYYY-MM-DD'

-- Check raw data
SELECT game_id, COUNT(*) as records
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = 'YYYY-MM-DD'
GROUP BY game_id
```

### Root Causes

1. **API didn't return game data**
   - Game was in progress when scraper ran
   - API had temporary outage

2. **Scraper filtered out the game**
   - Game ID format issue
   - Status wasn't Final at scrape time

3. **Data race with schedule update**
   - Schedule updated to Final AFTER scraper ran

### Fix Procedures

**Manual backfill:**
```bash
# Run gamebook scraper for missing date
PYTHONPATH=. python scrapers/nbac_gamebook_player_stats_scraper.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD --force

# Or run BDL scraper
PYTHONPATH=. python scrapers/bdl_player_boxscores_scraper.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD --force
```

---

## Issue: Low ML Feature Quality

### Symptoms
- `feature_quality_score` < 85%
- Predictions in FIRST or RETRY mode stuck
- Quality gate blocking predictions

### Quick Diagnosis
```sql
-- Check feature quality distribution
SELECT
    game_date,
    ROUND(AVG(feature_quality_score), 1) as avg_quality,
    COUNTIF(feature_quality_score >= 85) as high,
    COUNTIF(feature_quality_score < 80) as low
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC
```

### Root Causes

1. **Phase 4 data not ready**
   - ML features depend on Phase 4 precompute
   - Check Phase 4 ran successfully

2. **Cache data stale**
   - `player_daily_cache` generated before box scores processed
   - Run cache backfill

3. **Timing misalignment**
   - ML feature store ran before Phase 4 completed
   - This was the Feb 2 root cause

### Fix Procedures

**Refresh ML feature store:**
```bash
# Trigger ML feature store refresh
gcloud pubsub topics publish ml-feature-store-refresh \
  --message='{"game_date": "YYYY-MM-DD"}'
```

**Backfill Phase 4:**
```bash
# Run Phase 4 precompute backfill
PYTHONPATH=. python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

---

## Monitoring & Prevention

### Daily Checks

1. **Morning (7:30 AM ET):** Analytics quality check runs automatically
2. **Before predictions:** Quality gate checks feature quality
3. **After grading:** Hit rate monitoring

### Automated Alerts

| Alert | Threshold | Channel |
|-------|-----------|---------|
| usage_rate 0% | Any game | #nba-alerts (CRITICAL) |
| usage_rate < 80% | Overall | #nba-alerts (WARNING) |
| minutes < 90% | Overall | #nba-alerts (WARNING) |
| Feature quality < 80% | Average | #nba-alerts (WARNING) |

### Key Queries

**Overall health check:**
```sql
SELECT
    game_date,
    COUNT(DISTINCT game_id) as games,
    COUNTIF(is_dnp = FALSE) as active_players,
    ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate > 0) /
        NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) as usage_pct,
    ROUND(100.0 * COUNTIF(is_dnp = FALSE AND minutes_played > 0) /
        NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) as minutes_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC
```

---

## Escalation

If issues persist after following this runbook:

1. Check Cloud Run service logs for errors
2. Verify no deployment drift (`./bin/check-deployment-drift.sh`)
3. Check Firestore for orchestration status
4. Review recent commits for regressions
5. Document in session handoff for next session

---

## Related Documents

- [Session Learnings](../session-learnings.md) - Historical issue patterns
- [Troubleshooting Matrix](../troubleshooting-matrix.md) - Quick reference
- [Phase 3 Documentation](../../03-phases/phase3-analytics.md) - Pipeline details
