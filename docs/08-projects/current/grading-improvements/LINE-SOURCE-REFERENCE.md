# Line Source Reference Guide

**Created:** 2026-01-23
**Purpose:** Definitive reference for betting line source types and grading semantics

---

## Line Source Types

### ACTUAL_PROP
**Definition:** Live betting line obtained from OddsAPI or BettingPros at prediction time.

| Attribute | Value |
|-----------|-------|
| `has_prop_line` | TRUE |
| `current_points_line` | Populated |
| Gradable for win rate | YES |
| Gradable for MAE | YES |
| Typical coverage | Star players, regular rotation players |

**When used:** Player has an active points prop on sportsbooks when prediction is generated.

### VEGAS_BACKFILL
**Definition:** Historical line from BettingPros, applied retroactively to predictions that originally had no line.

| Attribute | Value |
|-----------|-------|
| `has_prop_line` | TRUE |
| `current_points_line` | Populated |
| Gradable for win rate | YES |
| Gradable for MAE | YES |
| Typical coverage | Players who had lines but not captured at prediction time |

**When used:** Historical data patching when predictions were made before line was available but line existed pre-game.

### NO_PROP_LINE
**Definition:** No betting line available for this player at any source.

| Attribute | Value |
|-----------|-------|
| `has_prop_line` | FALSE |
| `current_points_line` | NULL |
| Gradable for win rate | NO |
| Gradable for MAE | YES (via mae_by_line_source view) |
| Typical coverage | Role players, deep bench, players with uncertain status |

**When used:** Player does not have a points prop offered by any sportsbook. Prediction is still made (for MAE tracking) but no OVER/UNDER recommendation is given.

**Recommendation:** `NO_LINE`

### NO_VEGAS_DATA
**Definition:** No Vegas data available at prediction time (API failure or data gap).

| Attribute | Value |
|-----------|-------|
| `has_prop_line` | FALSE |
| `current_points_line` | NULL |
| Gradable for win rate | NO |
| Gradable for MAE | YES (if actual points available) |
| Typical coverage | Data pipeline failures, early season games |

**When used:** OddsAPI and BettingPros both failed to return data for the game.

### ESTIMATED_AVG (DEPRECATED)
**Definition:** Fake line based on player's L5 average. **SHOULD NEVER APPEAR.**

| Attribute | Value |
|-----------|-------|
| Status | ELIMINATED as of 2026-01-23 |
| Count in database | 0 |
| Monitoring | CRITICAL alert if any appear |

**Why eliminated:** ESTIMATED_AVG contaminated grading by comparing predictions against a fake baseline that the model helped create. See `2026-01-23-ESTIMATED-LINE-DESIGN-FLAW.md` for full analysis.

---

## Data Flow

```
OddsAPI/BettingPros → Line available?
                        │
            ┌───────────┴───────────┐
            │                       │
           YES                      NO
            │                       │
    line_source=ACTUAL_PROP    line_source=NO_PROP_LINE
    has_prop_line=TRUE         has_prop_line=FALSE
    current_points_line=VALUE  current_points_line=NULL
    recommendation=OVER/UNDER  recommendation=NO_LINE
```

---

## Grading Logic

### prediction_accuracy Table
Only includes predictions with real betting lines:
- `line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')`
- `has_prop_line = TRUE`
- `current_points_line IS NOT NULL`

### mae_by_line_source View
Includes ALL predictions joined with actuals:
- Computes `absolute_error` and `signed_error` for all
- Flag `has_real_line` indicates which are bet-gradable
- Allows MAE comparison between players with/without props

### Key Metrics

| Metric | Source | What it measures |
|--------|--------|------------------|
| Win Rate | prediction_accuracy | OVER/UNDER accuracy vs real lines |
| MAE (with line) | prediction_accuracy | Point prediction accuracy for bet-gradable players |
| MAE (no line) | mae_by_line_source | Point prediction accuracy for role players |
| Bias | Both | Systematic over/under prediction tendency |

---

## Historical Coverage by Season

| Season | Total | With Real Line | Without Line | % Gradable |
|--------|-------|----------------|--------------|------------|
| 2021-22 | 116,734 | 60,052 | 56,682 | 51.4% |
| 2022-23 | 108,137 | 58,178 | 49,959 | 53.8% |
| 2023-24 | 109,035 | 64,074 | 44,961 | 58.8% |
| 2024-25 | 158,985 | 107,371 | 51,614 | 67.1% |

**Trend:** Line coverage improving over time as OddsAPI integration matured.

---

## Column Reference

### player_prop_predictions Table

| Column | Type | Description |
|--------|------|-------------|
| `current_points_line` | NUMERIC | Real Vegas line (NULL if none) |
| `estimated_line_value` | NUMERIC | Player's L5 average (always populated) |
| `has_prop_line` | BOOL | TRUE only for real lines |
| `line_source` | STRING | ACTUAL_PROP, NO_PROP_LINE, VEGAS_BACKFILL, NO_VEGAS_DATA |
| `recommendation` | STRING | OVER, UNDER, PASS, HOLD, NO_LINE |
| `is_active` | BOOL | TRUE for current predictions (excludes duplicates) |

### prediction_accuracy Table

| Column | Type | Description |
|--------|------|-------------|
| `absolute_error` | NUMERIC | \|predicted - actual\| |
| `signed_error` | NUMERIC | predicted - actual |
| `prediction_correct` | BOOL | TRUE/FALSE/NULL (NULL for non-bet recommendations) |
| `has_prop_line` | BOOL | Always TRUE (filtered at query time) |
| `line_source` | STRING | ACTUAL_PROP or related |

---

## Monitoring Alerts

### ESTIMATED_AVG Regression (CRITICAL)
- **Trigger:** Any prediction with `line_source = 'ESTIMATED_AVG'`
- **Action:** Immediate investigation of player_loader.py
- **Channel:** #app-error-alerts

### High NO_PROP_LINE Percentage (WARNING)
- **Trigger:** NO_PROP_LINE > 40% of daily predictions
- **Action:** Check OddsAPI/BettingPros availability
- **Channel:** #nba-alerts

---

## Useful Queries

### Check line source distribution
```sql
SELECT
  line_source,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE AND game_date = CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 2 DESC
```

### Compare MAE by line availability
```sql
SELECT
  has_real_line,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae
FROM nba_predictions.mae_by_line_source
WHERE game_date >= '2024-10-01'
  AND system_id = 'catboost_v8'
GROUP BY 1
```

### Daily MAE summary
```sql
SELECT *
FROM nba_predictions.daily_mae_summary
WHERE game_date >= CURRENT_DATE() - 7
  AND system_id = 'catboost_v8'
ORDER BY game_date DESC
```
