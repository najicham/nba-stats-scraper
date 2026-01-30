# Session 23 Setup - CatBoost V8 Performance Analysis

**Date:** 2026-01-29
**Previous Session:** 22 (Line Validation and Cleanup)
**Status:** READY TO START

---

## Recommendation

**One session with Sonnet** is sufficient. This is data analysis work (queries, metrics, charts) rather than complex code changes. Sonnet is faster, cheaper, and fully capable of:
- Running BigQuery analysis queries
- Calculating hit rates and accuracy metrics
- Identifying anomalies
- Creating summary reports

Use Opus only if you discover issues requiring complex code fixes.

---

## Context from Session 22

### Data Quality Now Clean
- 0 active sentinel values (was 156)
- 0 contradictory flags (was 369)
- line_source_api populated for 99.97% of ACTUAL_PROP predictions
- Validation added to prevent future issues

### Key Tables
- `nba_predictions.player_prop_predictions` - All predictions (system_id='catboost_v8')
- `nba_raw.odds_api_player_points_props` - Raw betting lines (OddsAPI)
- `nba_raw.bettingpros_player_points_props` - Raw betting lines (BettingPros)
- `nba_analytics.player_game_summary` - Actual game results

### Line Source Fields (Now Reliable)
- `line_source`: 'ACTUAL_PROP', 'ESTIMATED_AVG', 'NO_PROP_LINE', 'VEGAS_BACKFILL'
- `line_source_api`: 'ODDS_API', 'BETTINGPROS', 'ESTIMATED'
- `has_prop_line`: TRUE/FALSE

---

## Analysis Questions to Answer

### 1. Overall Performance
- What's the overall hit rate for CatBoost V8?
- How does it compare to baseline (50%)?
- What's the ROI assuming -110 odds?

### 2. Performance by Line Source
- Hit rate for ODDS_API lines vs BETTINGPROS lines?
- Are certain sportsbooks more predictable?
- How do VEGAS_BACKFILL predictions perform?

### 3. Performance by Confidence Tier
- Does higher confidence correlate with higher hit rate?
- What's the optimal confidence threshold?
- How does the 88-90% tier (filtered) compare?

### 4. Recent Trends
- Are predictions improving or degrading over time?
- Any specific dates with anomalous performance?
- How did Jan 21 backfilled predictions perform?

### 5. Edge Detection
- Which players are most predictable?
- Which matchups have highest edge?
- Time-of-day or day-of-week patterns?

---

## Key Queries to Run

### Hit Rate Calculation
```sql
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN
    (recommendation = 'OVER' AND actual_points > current_points_line) OR
    (recommendation = 'UNDER' AND actual_points < current_points_line)
  THEN 1 ELSE 0 END) as hits,
  ROUND(SUM(CASE WHEN
    (recommendation = 'OVER' AND actual_points > current_points_line) OR
    (recommendation = 'UNDER' AND actual_points < current_points_line)
  THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary g
  ON p.player_lookup = g.player_lookup AND p.game_date = g.game_date
WHERE p.system_id = 'catboost_v8'
  AND p.has_prop_line = TRUE
  AND p.recommendation IN ('OVER', 'UNDER')
  AND p.game_date < CURRENT_DATE()  -- Only graded games
```

### Performance by Line Source API
```sql
SELECT
  line_source_api,
  COUNT(*) as predictions,
  -- hit rate calculation
FROM ...
GROUP BY line_source_api
```

---

## Success Criteria

After this session, you should know:
- [ ] Overall CatBoost V8 hit rate and ROI
- [ ] Best performing line source (ODDS_API vs BETTINGPROS)
- [ ] Optimal confidence threshold
- [ ] Any concerning trends or anomalies
- [ ] Recommendations for improving performance

---

## Files to Reference

| File | Purpose |
|------|---------|
| `monitoring/daily_prediction_quality.py` | Daily quality checks |
| `bin/audit/audit_historical_lines.py` | Line data audit |
| `docs/09-handoff/2026-01-29-SESSION-22-LINE-CLEANUP-COMPLETE.md` | Previous session details |

---

*Created: 2026-01-29*
