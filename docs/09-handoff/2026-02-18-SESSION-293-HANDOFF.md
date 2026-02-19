# Session 293 Handoff — Feature Store Validation, Feb Diagnosis, New Signal Discovery

**Date:** 2026-02-18
**Previous:** Session 292 — NaN-safe features, publishing enhancements, feature store backfill

## Current State

| Component | Status |
|-----------|--------|
| Production model | `catboost_v9_33f_train20251102-20260205` — **12 days old, STRUGGLING in Feb** |
| Feature store | **Validated & fixed** — 99 game dates (Nov 4 → Feb 12), 70%+ quality-ready Dec-Feb |
| Shadow models | **V12 (56.0% HR), Q45 (60.0% HR), Q43 (54.1% HR) all outperforming champion in Feb** |
| New signal | **OVER + line_dropped_3+ = 79.0% HR (N=81)** — strongest new signal found |
| Games | Resume Feb 19 — All-Star break ends |

## Start Here

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-18-SESSION-293-HANDOFF.md

# 2. Check if games have been played
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as games, COUNTIF(game_status = 3) as final
FROM nba_reference.nba_schedule
WHERE game_date >= '2026-02-19'
GROUP BY 1 ORDER BY 1 LIMIT 5"

# 3. If games exist, check model performance
bq query --use_legacy_sql=false "
SELECT system_id,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3,
  ROUND(100.0 * COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct) / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hr_edge3
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-19'
GROUP BY 1 HAVING COUNTIF(ABS(predicted_margin) >= 3) >= 3
ORDER BY hr_edge3 DESC"
```

## What Was Done This Session

### 1. Feature Store Validation & Fixes (COMPLETE)

**Fixed:**
- **Feb 6-7 matchup gap** — `team_defense_zone_analysis` was missing for those dates. Backfilled 60 team records, re-ran ML feature store. Quality jumped from 3.6% → 74.3% quality-ready.
- **21 December ghost rows** — Orphaned backfill artifacts with ALL features NULL. Deleted via DML.

**Validated (post-fix):**
- 27/33 features fully CLEAN (up from 25/33)
- All calculated features (f9-f12, f15-f17, f21, f24, f28-f30) now ALL POPULATED — zero NULLs
- f13/f14 matchup features: CLEAN (all NULLs are legitimate source-missing)

| Month | Dates | Rows | Quality-Ready % | Avg Quality |
|-------|-------|------|-----------------|-------------|
| Nov | 26 | 7,130 | 25.9% | 66.1 |
| Dec | 30 | 7,068 | 70.0% | 83.5 |
| Jan | 31 | 8,071 | 72.0% | 85.7 |
| Feb | 12 | 3,158 | 70.0% | 86.2 |

**Known issues (upstream, do NOT fix):**
- f4 (`games_in_last_7_days`): 411 bugs — upstream cache gap
- f32 (`ppm_avg_last_10`): 524 bugs — bench players lack PPM
- f5-f8 (composite factors): 18 bugs — specific player-date gaps

### 2. plus_minus Already Populated (NO ACTION NEEDED)

98.4% coverage (15,989/16,245 non-DNP rows). The handoff from Session 292 said "expect ~0%" but it was already done.

### 3. Feature Store Already Extends to Nov 4 (NO ACTION NEEDED)

Handoff said "only Jan 6+" — actually covers Nov 4 through Feb 12 (99 game dates). Nov 2-3 are intentionally skipped (bootstrap period). No gaps exist.

## February Model Collapse — Root Cause Analysis

### The Problem

| Period | Edge 3+ HR | Edge 5+ HR | MAE |
|--------|-----------|-----------|-----|
| January | **59.8%** | **75.5%** | 5.4-6.0 |
| February | **36.7%** | **28.1%** | 6.7-8.5 |

### Root Cause: Systematic UNDER Bias

| Period | OVER HR (edge 3+) | UNDER HR (edge 3+) |
|--------|-------------------|---------------------|
| Jan | 63.3% | 55.9% |
| Feb | 43.3% | **33.3%** |

The model is systematically underestimating scoring for UNDER picks (avg predicted 12.3, actual 19.6, residual +7.4).

**NOT caused by:**
- Feature drift (distributions stable Jan vs Feb)
- League-wide scoring shift (avg actual DECREASED from 13.0 to 11.5)
- Data quality (feature store is clean)

**Likely caused by:**
- Model calibration decay (training ended Feb 5, market shifted post-training)
- Pre-All-Star scheduling effects (different game contexts)
- V9 specific — other models handled Feb better

### Shadow Models Outperforming Champion

| Model | Feb HR (edge 3+) | N | MAE |
|-------|------------------|---|-----|
| **v9_q45 (train→Jan 31)** | **60.0%** | 25 | 4.6 |
| **catboost_v12** | **56.0%** | 50 | 5.0 |
| **v9_q43 (train→Jan 31)** | **54.1%** | 37 | 4.6 |
| v9_train→Jan 8 | 53.8% | 13 | 4.9 |
| catboost_v8 (legacy) | 44.8% | 377 | 5.7 |
| **catboost_v9 (champion)** | **39.4%** | 193 | 5.3 |

**Key takeaway:** V12 and quantile models all beat the champion. V12 has the best combination of HR (56%) and sample size (50). Q45 has highest HR (60%) but only 25 picks.

## NEW SIGNAL DISCOVERY: Prop Line Delta

### Game-to-Game Prop Line Movement

When a player's prop line changes significantly from their previous game:

| Line Movement | N (total) | Edge 3+ | HR Edge 3+ |
|---------------|-----------|---------|------------|
| **Line dropped 3+** | 203 | 93 | **74.2%** |
| Line dropped 1-3 | 675 | 100 | 55.0% |
| Line stable (-1 to +1) | 1,382 | 141 | 58.2% |
| Line up 1-3 | 712 | 112 | 50.9% |
| Line jumped 3+ | 228 | 66 | **42.4%** |

### Direction Interaction (THE MONEY SIGNAL)

| Direction + Line Movement | N | Edge 3+ HR |
|---------------------------|---|------------|
| **OVER + line dropped 3+** | 81 | **79.0%** |
| OVER + line normal | 153 | 57.5% |
| OVER + line jumped 3+ | 7 | 28.6% |
| UNDER + line dropped 3+ | 11 | 45.5% |
| UNDER + line normal | 201 | 52.2% |
| UNDER + line jumped 3+ | 55 | 49.1% |

**OVER + line dropped 3+ = 79.0% HR on 81 picks.** This means: when Vegas lowers a player's line significantly but our model still predicts OVER, we're right 4 out of 5 times.

**Intuition:** Vegas is being cautious (maybe injury concern, matchup, rest) but the player's fundamentals (what our model sees) haven't actually degraded → the market overreacted to the downside.

### Implementation Plan

**As a Signal (`prop_line_drop_over`):**
```python
# In ml/signals/
class PropLineDropOverSignal:
    """OVER + line dropped 3+ from previous game = strong conviction."""
    direction = 'OVER'
    conditions:
        - recommendation == 'OVER'
        - edge >= 3
        - current_line - previous_game_line <= -3
    # 79.0% HR, N=81
```

**As a Feature (`prop_line_delta`, f55):**
```python
# In player_daily_cache or feature_calculator:
# current_game_line - previous_game_line
# Numeric: lets the model learn the non-linear relationship
```

**As a Pre-Filter:**
```python
# AVOID: OVER + line jumped 3+ (28.6% HR)
# Add to aggregator pre-filters alongside existing blacklist, bench_under_block
```

## Other Feature Ideas Explored

### FG% Cold Streak — WEAK SIGNAL

| Cold Streak | N | FG% Next Game | Avg Points |
|-------------|---|---------------|------------|
| Not cold | 6,858 | 46.9% | 14.6 |
| 1 game cold | 2,515 | 47.0% | 14.4 |
| 2 games cold | 788 | 46.9% | 13.5 |
| 3+ games cold | 335 | 47.2% | 13.6 |

**Conclusion:** Minimal bounce-back effect. FG% cold streaks don't predict next-game scoring. The regression to mean on FG% is real (47.2% after 3+ cold vs 35.9% season avg) but doesn't translate to meaningfully more points. **Low priority as a feature.**

### 3PT% Cold Streak — MILD SIGNAL

| Cold Streak | N | 3PT% Next Game | Their Avg | Avg Points |
|-------------|---|---------------|-----------|------------|
| Not cold | 4,487 | 36.2% | 36.5% | 15.5 |
| 3+ cold | 208 | 37.1% | 35.9% | 15.4 |

**Conclusion:** Small bounce-back in 3PT% (37.1% vs 35.9% avg after 3+ cold games) but no impact on points. The existing `3pt_bounce` signal already captures the best version of this. **Low priority as new feature.**

### Minutes Streak — INFORMATIONAL BUT NOT PREDICTIVE

| Min Streak | N | Avg Min Next Game | Avg Points | Their Avg Min |
|------------|---|-------------------|------------|---------------|
| 3+ below | 476 | 15.3 | 6.5 | 19.1 |
| 2 below | 639 | 17.9 | 7.7 | 20.7 |
| Normal | 7,239 | 26.5 | 13.6 | 26.6 |
| 2+ above | 1,392 | 22.8 | 9.4 | 19.0 |

**Conclusion:** Minutes streaks are persistent, not mean-reverting. Players with declining minutes keep declining (no bounce-back). **Could be useful as a feature for the model** (capturing lineup changes) but not as a signal.

## Priority Actions for Next Session

### Priority 1: Implement Prop Line Delta Signal (HIGH VALUE)

The `OVER + line_dropped_3+` finding at 79.0% HR is too strong to ignore.

```bash
# 1. Create the signal
# File: ml/signals/definitions/prop_line_drop_over.py
# Pattern: check prediction_accuracy for same player's previous line_value

# 2. Add as aggregator pre-filter (avoid OVER + line jumped 3+)
# File: ml/signals/aggregator.py — add to pre-filter chain

# 3. Add prop_line_delta as feature (f55)
# File: data_processors/precompute/player_daily_cache/aggregators/
# Compute: current_line - prev_game_line (NULL if no prev line)

# 4. Backtest the signal across full season
/replay  # Use replay skill to test
```

### Priority 2: Promote V12 or Q45 as Champion

V12 is the safest bet (56% HR, N=50, MAE 5.0, residual 0.0). Q45 has higher HR but smaller N.

```bash
# Option A: Promote V12 immediately (if post-All-Star data confirms)
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://path/to/v12/model.cbm"

# Option B: Wait for Feb 19+ data, compare V12 vs Q45 vs V9
# Run after 3+ days of post-ASB games (Feb 22+)
```

### Priority 3: Retrain With Updated Feature Store

The cleaned feature store should improve training. Use rolling 42-day window.

```bash
# After Feb 22+ (need eval data)
./bin/retrain.sh --promote --eval-days 3
```

### Priority 4: Add New Features to V13/V14

Based on exploration results, prioritized by expected value:

| Feature | Type | Priority | Expected Impact |
|---------|------|----------|-----------------|
| `prop_line_delta` (game-to-game) | Feature (f55) | **HIGH** | 79.0% HR when OVER+drop3+ |
| `minutes_streak_below` | Feature | MEDIUM | Captures lineup changes |
| `fg_cold_streak` | Feature | LOW | Weak signal in isolation |
| `three_pt_cold_streak` | Feature | LOW | Existing signal covers this |

### Priority 5: Tonight Player Exports Backfill (DEFERRED)

Too slow for interactive session (~8s/player, 28K total). Resumable:
```bash
PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --skip-existing
```

## Key Technical Context

### Feature Store Validation Script
```bash
PYTHONPATH=. python bin/validate_feature_sources.py --start-date 2025-11-02 --end-date 2026-02-17 --sample-days 5
```
Checks each feature against its upstream source, distinguishes legitimate NULLs (source missing) from bugs (source exists but feature NULL).

### Prop Line Delta Query (for further analysis)
```sql
WITH prop_lines AS (
  SELECT p.player_lookup, p.game_date, p.line_value,
    LAG(p.line_value) OVER (PARTITION BY p.player_lookup ORDER BY p.game_date) as prev_line,
    p.actual_points, p.prediction_correct, p.recommendation,
    ABS(p.predicted_margin) as edge
  FROM nba_predictions.prediction_accuracy p
  WHERE p.system_id = 'catboost_v9'
    AND p.game_date >= '2025-12-01'
    AND p.line_value IS NOT NULL AND p.actual_points IS NOT NULL
)
SELECT *,
  line_value - prev_line as line_delta
FROM prop_lines
WHERE prev_line IS NOT NULL
```

### Model Performance Quick Check
```sql
SELECT system_id,
  CASE WHEN game_date < '2026-02-01' THEN 'Jan' ELSE 'Feb' END as period,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3,
  ROUND(100.0 * COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct) / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hr_edge3
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-01-01'
GROUP BY 1, 2
HAVING COUNTIF(ABS(predicted_margin) >= 3) >= 10
ORDER BY 2, hr_edge3 DESC
```

## Recent Commits

```
4dfe3627 docs: Session 292 handoff — validate, backfill, retrain roadmap
c2c4dffb feat: add ft_attempts to last 10 games in tonight exports
e8c202a0 docs: Session 291+292 handoff
720520fc feat: add box score detail to player exports, date-keyed player pages
f96eb275 fix: NaN-safe feature helpers prevent BQ NULL → pandas NaN inconsistencies
```

## Known Issues (Do NOT Investigate)

- **f4/f32 bugs**: Upstream cache/PPM gaps. Blocked by quality gates. Not worth fixing.
- **features array column**: Deprecated, dual-written. Removal deferred (Phase 8).
- **Nov quality 25.9%**: Expected — early season, no history. CatBoost handles NaN.
- **Tonight exports backfill**: ~60+ hours. Run on VM or optimize exporter batching.
