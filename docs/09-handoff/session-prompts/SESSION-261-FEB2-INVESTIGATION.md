# Parallel Chat: Investigate the February 2 Week Collapse

**Created:** 2026-02-15 (Session 261)
**Purpose:** Deep investigation into why picks performed catastrophically the week of Feb 1-7
**Priority:** High — findings inform automated decay detection thresholds

---

## Context

The champion model (catboost_v9) crashed from 57.3% edge 3+ HR on Feb 1 to 42.3% on Feb 2 (7-day rolling). This was the worst single-day collapse in the model's history. The entire week of Feb 1-7 produced devastating results.

**Key data points from Session 261 replay analysis:**
- Feb 2: 33 edge 3+ picks, only 5 hit (15.2% daily HR)
- High_edge signal went from 84.6% to 22.1% HR that week
- Edge_spread_optimal went from 92.3% to 16.7%
- prop_value_gap_extreme went from 93.1% to 0.0%
- catboost_v8 also crashed in the same window (66.5% → 47.0%)
- This suggests a broader market regime shift, not just model-specific decay

---

## Investigation Questions

### 1. What Happened on Feb 2 Specifically?
- Which games were played? Any unusual schedule (back-to-backs, travel)?
- Which players were predicted? Were they playing normal minutes?
- Were there late injury reports or lineup changes after predictions were generated?
- Did the prop lines move significantly between prediction time and game time?

### 2. Was There a Directional Bias?
- Did the model systematically predict OVER when players went UNDER (or vice versa)?
- Was there a systematic bias in magnitude (predicting 25 pts when players scored 18)?
- Did specific prop types (points vs rebounds vs assists) fail differently?

### 3. Why Did Multiple Models Crash Simultaneously?
- V8 (4-year track record) also dropped from 66.5% to 47.0%
- This suggests something external changed, not just model staleness
- Possible causes:
  - Trade deadline activity changing team compositions?
  - All-Star break roster decisions affecting player effort?
  - Sportsbooks adjusting lines based on sharp money?
  - Seasonal pattern (post-January market adjustment)?

### 4. Were There Warning Signs in the Data Pipeline?
- Feature quality scores for that week — any anomalies?
- Vegas line coverage — did we have fewer/worse lines?
- Injury report completeness — any gaps?
- Game completion times — any delayed games affecting data freshness?

### 5. Could We Have Made Better Picks That Week?
- If we had filtered to only 2+ signal picks, would results improve?
- If we had excluded model-dependent signals (high_edge, edge_spread), would the remaining behavioral signals (cold_snap, 3pt_bounce) have been profitable?
- Would a higher edge threshold (5+ instead of 3+) have filtered out the losers?

---

## How to Investigate

### Quick Start
```bash
# Read the replay analysis first
cat docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md

# Read the handoff for context
cat docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md
```

### Key Queries

```sql
-- Detailed Feb 2 picks: who was predicted, what happened
SELECT
  pa.game_date, pa.player_name, pa.stat_type,
  pa.predicted_points, pa.line_value,
  ABS(pa.predicted_points - pa.line_value) as edge,
  pa.prediction_direction, pa.actual_value,
  pa.prediction_correct,
  pa.predicted_points - pa.actual_value as prediction_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date = '2026-02-02'
  AND ABS(pa.predicted_points - pa.line_value) >= 3.0
  AND pa.prediction_correct IS NOT NULL
ORDER BY ABS(pa.predicted_points - pa.actual_value) DESC

-- Feature quality for the crash week
SELECT
  game_date, AVG(feature_quality_score) as avg_quality,
  COUNTIF(quality_alert_level = 'red') as red_count,
  COUNTIF(default_feature_count > 0) as defaults_count,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2026-01-30' AND '2026-02-05'
GROUP BY 1 ORDER BY 1

-- Vegas line movement: were lines stale?
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(line_source = 'ACTUAL_PROP') as actual_prop,
  COUNTIF(line_source = 'ODDS_API') as odds_api,
  COUNTIF(line_source = 'NO_PROP_LINE') as no_prop
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN '2026-01-30' AND '2026-02-05'
  AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1

-- Games that day — check for any unusual patterns
SELECT game_id, away_team_tricode, home_team_tricode, game_status
FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-02'

-- Compare prediction error distribution: good week vs crash week
SELECT
  CASE WHEN game_date BETWEEN '2026-01-12' AND '2026-01-18' THEN 'good_week'
       WHEN game_date BETWEEN '2026-02-01' AND '2026-02-07' THEN 'bad_week'
  END as period,
  ROUND(AVG(predicted_points - actual_value), 2) as avg_bias,
  ROUND(STDDEV(predicted_points - actual_value), 2) as std_error,
  ROUND(AVG(ABS(predicted_points - actual_value)), 2) as avg_abs_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v9'
  AND prediction_correct IS NOT NULL
  AND (game_date BETWEEN '2026-01-12' AND '2026-01-18'
       OR game_date BETWEEN '2026-02-01' AND '2026-02-07')
GROUP BY 1
```

### Subset Analysis
```bash
# Use the subset-performance skill for structured analysis
/subset-performance

# Or the hit-rate-analysis skill for grouping breakdowns
/hit-rate-analysis
```

---

## Expected Deliverables

1. **Root cause analysis** — What specifically caused the crash? External market shift, model staleness, data quality issue, or combination?
2. **Counterfactual analysis** — Could better filtering have avoided the worst losses?
3. **Early warning indicators** — What data signals could have predicted the crash 1-3 days earlier?
4. **Recommendations** — Specific filter changes or monitoring additions to prevent recurrence

---

## Files to Reference

| File | Purpose |
|------|---------|
| `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md` | Full replay analysis |
| `ml/signals/signal_health.py` | Signal health computation |
| `ml/signals/aggregator.py` | Best bets scoring logic |
| `shared/config/model_selection.py` | Model selection mechanism |
| `data_processors/publishing/signal_best_bets_exporter.py` | Best bets export pipeline |
