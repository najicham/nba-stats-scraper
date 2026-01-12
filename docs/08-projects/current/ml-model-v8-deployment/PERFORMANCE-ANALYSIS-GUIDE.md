# Performance Analysis & Grading Guide

**Created:** 2026-01-11
**Purpose:** How to run grading, analyze season performance, and identify problem tiers

---

## Table of Contents

1. [Quick Reference Commands](#quick-reference-commands)
2. [Understanding the Grading Pipeline](#understanding-the-grading-pipeline)
3. [Running Grading Manually](#running-grading-manually)
4. [Analyzing Season Performance](#analyzing-season-performance)
5. [Identifying Problem Tiers](#identifying-problem-tiers)
6. [Troubleshooting](#troubleshooting)

---

## Quick Reference Commands

### Check Grading Status
```bash
# Latest graded date
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as latest_graded
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'catboost_v8'
"

# Check grading coverage for recent dates
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as graded_picks
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND system_id = 'catboost_v8'
GROUP BY game_date
ORDER BY game_date
"
```

### Run Grading for a Specific Date
```bash
# From project root
python orchestration/cloud_functions/grading/main.py --date 2026-01-10
```

### Get Season Performance Summary
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
"
```

---

## Understanding the Grading Pipeline

### Data Flow

```
Phase 2 (Raw)              Phase 3 (Analytics)        Phase 5B (Grading)
─────────────              ────────────────────       ──────────────────
bdl_player_boxscores  ──►  player_game_summary  ──►  prediction_accuracy
                                    │
Phase 5A (Predictions)              │
─────────────────────               │
player_prop_predictions  ───────────┘
```

### Key Tables

| Table | Dataset | Purpose |
|-------|---------|---------|
| `player_prop_predictions` | nba_predictions | Pre-game predictions from all systems |
| `player_game_summary` | nba_analytics | Actual game results (points scored) |
| `prediction_accuracy` | nba_predictions | Graded predictions with win/loss |
| `system_daily_performance` | nba_predictions | Daily aggregated system performance |

### Grading Schedule

The grading pipeline runs daily:
- **Scheduler:** `grading-daily` at 11:00 UTC (6 AM ET)
- **Trigger:** Pub/Sub topic `nba-grading-trigger`
- **Cloud Function:** `orchestration/cloud_functions/grading/main.py`

---

## Running Grading Manually

### Prerequisites Check

Before running grading, verify data exists:

```bash
# Check if predictions exist for the date
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-10'
  AND system_id = 'catboost_v8'
"

# Check if actuals exist (player_game_summary)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as actuals
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-10'
"
```

### If Actuals Are Missing

The grading pipeline depends on `player_game_summary`. If missing:

1. **Check raw box scores:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
   WHERE game_date = '2026-01-10'
   "
   ```

2. **If raw box scores missing, scrape them:**
   ```bash
   python scrapers/balldontlie/bdl_box_scores.py --date 2026-01-10
   ```

3. **Run Phase 3 analytics:**
   ```bash
   # Option 1: Via Cloud Run (production)
   curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
     -H "Content-Type: application/json" \
     -d '{"start_date": "2026-01-10", "end_date": "2026-01-10", "processors": ["PlayerGameSummaryProcessor"]}'

   # Option 2: Locally
   python -c "
   from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
   from datetime import date
   p = PlayerGameSummaryProcessor()
   p.process_date(date(2026, 1, 10))
   "
   ```

### Run Grading

```bash
# Single date
python orchestration/cloud_functions/grading/main.py --date 2026-01-10

# Date range (backfill)
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-08 --end-date 2026-01-10
```

---

## Analyzing Season Performance

### Overall Season Summary

```sql
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 - 52.4, 1) as edge_over_breakeven
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'  -- Season start
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
```

### Performance by Confidence Tier

```sql
WITH picks_with_tier AS (
  SELECT
    *,
    CASE
      WHEN confidence_score >= 0.90 THEN 'VERY HIGH (90%+)'
      WHEN confidence_score >= 0.70 THEN 'HIGH (70-90%)'
      WHEN confidence_score >= 0.55 THEN 'MEDIUM (55-70%)'
      ELSE 'LOW (<55%)'
    END as confidence_tier
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2025-10-01'
    AND system_id = 'catboost_v8'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  confidence_tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM picks_with_tier
GROUP BY confidence_tier
ORDER BY
  CASE confidence_tier
    WHEN 'VERY HIGH (90%+)' THEN 1
    WHEN 'HIGH (70-90%)' THEN 2
    WHEN 'MEDIUM (55-70%)' THEN 3
    ELSE 4
  END
```

### OVER vs UNDER Performance

```sql
SELECT
  recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY recommendation
```

### Daily Performance Trend

```sql
SELECT
  game_date,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date
```

---

## Identifying Problem Tiers

### Step 1: Granular Confidence Breakdown

Look for tiers with significantly lower win rates:

```sql
WITH picks_with_tier AS (
  SELECT
    *,
    CASE
      WHEN confidence_score >= 0.92 THEN '1. 92%+'
      WHEN confidence_score >= 0.90 THEN '2. 90-92%'
      WHEN confidence_score >= 0.88 THEN '3. 88-90%'
      WHEN confidence_score >= 0.86 THEN '4. 86-88%'
      WHEN confidence_score >= 0.84 THEN '5. 84-86%'
      WHEN confidence_score >= 0.80 THEN '6. 80-84%'
      ELSE '7. <80%'
    END as confidence_tier
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2025-10-01'
    AND system_id = 'catboost_v8'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  confidence_tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM picks_with_tier
GROUP BY confidence_tier
ORDER BY confidence_tier
```

**Red flags to look for:**
- Win rate significantly below adjacent tiers (>10% difference)
- High error rate compared to similar confidence levels
- Sample size > 50 picks (statistically meaningful)

### Step 2: Analyze OVER vs UNDER in Problem Tier

```sql
-- Replace 0.88/0.90 with your identified problem tier
SELECT
  recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(ABS(predicted_margin)), 2) as avg_edge,
  ROUND(AVG(predicted_points / NULLIF(line_value, 0)), 2) as pred_to_line_ratio
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND confidence_score >= 0.88 AND confidence_score < 0.90
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY recommendation
```

### Step 3: Check for Extreme Predictions

Problem tiers often have **extreme predictions** (predicting far from line):

```sql
SELECT
  player_lookup,
  game_date,
  recommendation,
  line_value,
  predicted_points,
  actual_points,
  ROUND(predicted_margin, 1) as pred_margin,
  ROUND(actual_margin, 1) as actual_margin,
  ROUND(absolute_error, 1) as error,
  prediction_correct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND confidence_score >= 0.88 AND confidence_score < 0.90
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
  AND prediction_correct = FALSE
ORDER BY absolute_error DESC
LIMIT 20
```

### Step 4: Check Calibration Metrics

Compare prediction-to-line ratios across tiers:

```sql
WITH all_picks AS (
  SELECT
    *,
    CASE
      WHEN confidence_score >= 0.90 THEN 'Very High (90%+)'
      WHEN confidence_score >= 0.88 THEN 'Problem (88-90%)'
      ELSE 'Normal (<88%)'
    END as conf_band
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2025-10-01'
    AND system_id = 'catboost_v8'
    AND recommendation = 'UNDER'  -- Focus on UNDER if that's problematic
    AND has_prop_line = TRUE
)
SELECT
  conf_band,
  COUNT(*) as picks,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(line_value), 1) as avg_line,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points / NULLIF(line_value, 0)), 2) as pred_to_line_ratio
FROM all_picks
GROUP BY conf_band
ORDER BY conf_band
```

**Expected ranges:**
- Healthy pred-to-line ratio: 0.70-0.80 for UNDER, 1.10-1.30 for OVER
- Problem indicator: < 0.60 for UNDER (predicting too low)
- Problem indicator: > 1.40 for OVER (predicting too high)

---

## Troubleshooting

### Grading Not Running

1. **Check scheduler:**
   ```bash
   gcloud scheduler jobs describe grading-daily --location=us-west2
   ```

2. **Check Cloud Function logs:**
   ```bash
   gcloud functions logs read grading --limit=50
   ```

3. **Check prerequisites:**
   - Are predictions available for the date?
   - Are actuals (player_game_summary) available?

### Missing Actuals

If `player_game_summary` is empty for a date:

1. Check if box scores were scraped:
   ```sql
   SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
   WHERE game_date = 'YYYY-MM-DD'
   ```

2. If box scores exist but analytics missing, run Phase 3 manually (see above)

3. If box scores missing, check workflow executor logs:
   ```bash
   gcloud run services logs read nba-phase1-scrapers --limit=100
   ```

### Grading Results Look Wrong

1. **Spot-check grading accuracy:**
   ```sql
   SELECT
     pa.player_lookup,
     pa.actual_points as graded_actual,
     pgs.points as source_actual,
     CASE WHEN pa.actual_points = pgs.points THEN 'MATCH' ELSE 'MISMATCH' END as verify
   FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
   JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
     ON pa.player_lookup = pgs.player_lookup AND pa.game_id = pgs.game_id
   WHERE pa.game_date = 'YYYY-MM-DD'
     AND pa.system_id = 'catboost_v8'
   LIMIT 10
   ```

2. **Check for duplicate grading:**
   ```sql
   SELECT player_lookup, game_id, COUNT(*) as cnt
   FROM `nba-props-platform.nba_predictions.prediction_accuracy`
   WHERE game_date = 'YYYY-MM-DD'
   GROUP BY player_lookup, game_id
   HAVING cnt > 1
   ```

---

## Sportsbook Analysis

### Hit Rate by Sportsbook

Use this query to analyze performance against different sportsbooks' lines:

```sql
WITH latest_lines AS (
  -- Get latest line per player/game/bookmaker
  SELECT
    player_lookup,
    game_date,
    bookmaker,
    points_line as line_value,
    ROW_NUMBER() OVER (PARTITION BY player_lookup, game_date, bookmaker ORDER BY created_at DESC) as rn
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= '2025-10-01'
    AND bookmaker IN ('DraftKings', 'FanDuel', 'BetMGM', 'Caesars', 'ESPN Bet')
    AND bet_side = 'over'  -- Just need one side for the line value
),
predictions AS (
  SELECT
    player_lookup,
    game_date,
    predicted_points,
    actual_points,
    prediction_correct,
    absolute_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2025-10-01'
    AND system_id = 'catboost_v8'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
    AND line_value != 20  -- CRITICAL: Exclude default lines
),
joined AS (
  SELECT
    p.*,
    ll.bookmaker,
    ll.line_value as sportsbook_line,
    CASE
      WHEN p.predicted_points > ll.line_value AND p.actual_points > ll.line_value THEN TRUE
      WHEN p.predicted_points < ll.line_value AND p.actual_points < ll.line_value THEN TRUE
      ELSE FALSE
    END as would_win_vs_this_sportsbook
  FROM predictions p
  JOIN latest_lines ll ON p.player_lookup = ll.player_lookup AND p.game_date = ll.game_date AND ll.rn = 1
)
SELECT
  bookmaker,
  COUNT(*) as picks,
  COUNTIF(would_win_vs_this_sportsbook = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(would_win_vs_this_sportsbook = TRUE), COUNT(*)) * 100, 1) as win_rate
FROM joined
GROUP BY bookmaker
ORDER BY picks DESC
```

### Sportsbook Performance Baseline (Jan 2026)

| Sportsbook | Picks | Wins | Win Rate |
|------------|-------|------|----------|
| Caesars | 1,528 | 1,098 | **71.9%** |
| DraftKings | 1,506 | 1,080 | **71.7%** |
| BetMGM | 1,550 | 1,109 | **71.5%** |
| FanDuel | 1,503 | 1,073 | **71.4%** |
| ESPN Bet | 1,629 | 1,160 | **71.2%** |

**Key findings:**
- Performance is consistent across sportsbooks (71-72%)
- No significant edge at any single book
- Caesars has slightly better value (71.9%)
- After deploying sportsbook tracking (v3.3), use `line_source_api` and `sportsbook` columns for analysis

### Important: Default Line Filter

**Always filter out `line_value = 20`** when analyzing performance. This is the default line used when no actual betting line exists.

Before the normalization fix (Jan 2026), 78% of predictions used default lines due to player name mismatch. Use this query to check default line contamination:

```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(line_value = 20) as default_lines,
  ROUND(COUNTIF(line_value = 20) * 100.0 / COUNT(*), 1) as default_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-12-01'
  AND system_id = 'catboost_v8'
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 15
```

---

## Known Issues

### 88-90% Confidence Problem Tier

**Status:** Identified and filtered (Jan 2026)

**Symptoms:**
- Win rate ~62% vs ~75% for adjacent tiers
- Predominantly affects UNDER picks
- Model predicts ~51% of line (too aggressive)

**Root cause:** Confidence calibration issue for extreme UNDER predictions

**Mitigation:** Filtered in prediction worker with `is_actionable = false` and `filter_reason = 'confidence_tier_88_90'`

**Tracking:** See `docs/08-projects/current/pipeline-reliability-improvements/CONFIDENCE-TIER-FILTERING-IMPLEMENTATION.md`

---

## Related Documentation

- [FAIR-COMPARISON-ANALYSIS.md](./FAIR-COMPARISON-ANALYSIS.md) - System comparison methodology
- [MODEL-SUMMARY.md](./MODEL-SUMMARY.md) - CatBoost V8 technical details
- [CHAMPION-CHALLENGER-FRAMEWORK.md](./CHAMPION-CHALLENGER-FRAMEWORK.md) - Model comparison framework
