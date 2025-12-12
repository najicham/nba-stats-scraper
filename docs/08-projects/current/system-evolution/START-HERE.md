# START HERE: Post-Backfill Action Plan

**When to use:** As soon as the four-season backfill completes.

---

## Pre-Flight Check

Before starting, verify backfill is complete:

```sql
-- Check prediction coverage
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    ELSE '2024-25'
  END as season,
  COUNT(DISTINCT game_date) as dates_with_predictions,
  COUNT(*) as total_predictions
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

**Expected:** 4 seasons, 500+ dates total, 50,000+ predictions.

---

## Day 1: The Big Question

**Goal:** Determine if context-aware weighting is worth building.

### Step 1: Get Baseline (5 min)

```sql
-- Overall system performance
SELECT
  system_id,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate
FROM `nba_predictions.prediction_accuracy`
GROUP BY 1
ORDER BY mae;
```

**Record:** Ensemble MAE = ______

### Step 2: The Oracle Test (10 min)

This tells you the maximum improvement possible from context-aware weights.

```sql
-- Compare static ensemble vs always picking the best system per context
WITH base AS (
  SELECT
    player_lookup,
    game_date,
    CASE
      WHEN EXTRACT(MONTH FROM game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM game_date) IN (12, 1, 2) THEN 'MID'
      ELSE 'LATE'
    END as season_phase,
    system_id,
    absolute_error
  FROM `nba_predictions.prediction_accuracy`
),
-- Find best system per phase
best_per_phase AS (
  SELECT season_phase, system_id, AVG(absolute_error) as mae
  FROM base WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
  QUALIFY RANK() OVER (PARTITION BY season_phase ORDER BY mae) = 1
),
-- Simulate using best system per context
oracle AS (
  SELECT b.absolute_error
  FROM base b
  JOIN best_per_phase p ON b.season_phase = p.season_phase AND b.system_id = p.system_id
)
SELECT
  'Static Ensemble' as approach,
  ROUND(AVG(absolute_error), 4) as mae
FROM base WHERE system_id = 'ensemble_v1'
UNION ALL
SELECT 'Oracle (Best Per Phase)', ROUND(AVG(absolute_error), 4) FROM oracle;
```

### Step 3: Make the Decision

| Oracle Gap | Decision |
|------------|----------|
| < 0.05 MAE | **STOP** - Context-aware not worth it. Focus on Quick Wins only. |
| 0.05 - 0.10 MAE | **PROCEED WITH CAUTION** - Some value, but keep it simple. |
| > 0.10 MAE | **FULL SPEED** - Significant opportunity, build adaptive system. |

**Your result:** Gap = ______ → Decision: ______

---

## Day 1-2: Quick Wins (No Code Changes)

Regardless of the Oracle Test result, do these analyses:

### Win 1: System Agreement Analysis

```sql
-- Do predictions agree? Does agreement predict accuracy?
WITH preds AS (
  SELECT
    player_lookup, game_date,
    MAX(CASE WHEN system_id = 'xgboost_v1' THEN predicted_points END) as xgb,
    MAX(CASE WHEN system_id = 'moving_average_baseline_v1' THEN predicted_points END) as ma,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN predicted_points END) as sim,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN predicted_points END) as zone
  FROM `nba_predictions.player_prop_predictions`
  WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
),
with_spread AS (
  SELECT *, GREATEST(xgb,ma,sim,zone) - LEAST(xgb,ma,sim,zone) as spread
  FROM preds
  WHERE xgb IS NOT NULL AND ma IS NOT NULL AND sim IS NOT NULL AND zone IS NOT NULL
)
SELECT
  CASE
    WHEN spread < 2 THEN '1_TIGHT (<2)'
    WHEN spread < 4 THEN '2_MODERATE (2-4)'
    WHEN spread < 6 THEN '3_WIDE (4-6)'
    ELSE '4_VERY_WIDE (6+)'
  END as agreement,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae
FROM with_spread s
JOIN `nba_predictions.prediction_accuracy` pa
  ON s.player_lookup = pa.player_lookup AND s.game_date = pa.game_date
WHERE pa.system_id = 'ensemble_v1'
GROUP BY 1 ORDER BY 1;
```

**Expected:** Tight agreement → lower MAE. If true, use spread as confidence signal.

### Win 2: Find Worst Predicted Players

```sql
SELECT
  player_lookup,
  COUNT(*) as games,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
HAVING games >= 30
ORDER BY mae DESC
LIMIT 15;
```

**Action:** Consider lowering confidence for these players.

### Win 3: Veteran B2B Effect

```sql
SELECT
  CASE WHEN mlfs.is_back_to_back THEN 'B2B' ELSE 'Normal' END as rest,
  CASE WHEN mlfs.player_age >= 32 THEN 'Veteran' ELSE 'Young/Prime' END as age_group,
  COUNT(*) as n,
  ROUND(AVG(pa.signed_error), 3) as bias,
  ROUND(AVG(pa.absolute_error), 3) as mae
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
WHERE pa.system_id = 'ensemble_v1'
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Expected:** Veteran + B2B has negative bias (we over-predict). Note the adjustment needed.

---

## Day 3-4: Deeper Analysis

### Season Phase Patterns

```sql
SELECT
  CASE
    WHEN EXTRACT(MONTH FROM game_date) IN (10, 11) THEN '1_EARLY'
    WHEN EXTRACT(MONTH FROM game_date) = 12 THEN '2_DEC'
    WHEN EXTRACT(MONTH FROM game_date) IN (1, 2) THEN '3_MID'
    ELSE '4_LATE'
  END as phase,
  system_id,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae
FROM `nba_predictions.prediction_accuracy`
WHERE system_id != 'ensemble_v1'
GROUP BY 1, 2
ORDER BY 1, mae;
```

**Look for:** Does xgboost win mid-season? Does similarity win early?

### Scoring Tier Patterns

```sql
SELECT
  p.scoring_tier,
  pa.system_id,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.player_prop_predictions` p USING (player_lookup, game_date, system_id)
WHERE p.scoring_tier IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, mae;
```

**Look for:** Different best systems for BENCH vs STAR players?

---

## Day 5: Player Deep Dives

Pick 3-5 players to investigate using `PLAYER-INVESTIGATION-TEMPLATE.md`:

1. **Best predicted player** - What makes them easy?
2. **Worst predicted player** - Why do we fail?
3. **High-volume star** (LeBron/Jokic) - Important to get right
4. **Player with high bias** - Systematic error to fix
5. **Veteran you care about** - Validate B2B patterns

---

## Week 2: Implement Quick Wins

Based on Day 1-4 findings, implement (see `QUICK-WINS.md`):

| If You Found... | Implement |
|-----------------|-----------|
| System agreement predicts accuracy | Add `system_spread` to confidence |
| Unpredictable players identified | Create `player_predictability` table |
| Veteran B2B bias confirmed | Add adjustment to prediction pipeline |
| Season phase patterns exist | Context-aware weights (if Oracle gap > 0.05) |

---

## Decision Tree Summary

```
                    Backfill Complete
                          │
                          ▼
                  Run Oracle Test (Step 2)
                          │
              ┌───────────┴───────────┐
              │                       │
         Gap < 0.05              Gap >= 0.05
              │                       │
              ▼                       ▼
    Focus on Quick Wins        Build Adaptive System
    • System agreement         • Context-aware weights
    • Player predictability    • Season phase weights
    • B2B adjustments          • Tier-specific weights
    • Skip DESIGN.md           • Follow IMPLEMENTATION-PLAN.md
```

---

## Files Reference

| When | Use This File |
|------|---------------|
| Running aggregate queries | `ANALYSIS-QUERIES.md` |
| Understanding dimensions | `CONTEXT-DIMENSIONS.md` |
| Deep-diving a player | `PLAYER-INVESTIGATION-TEMPLATE.md` |
| Testing weight combinations | `EXPERIMENT-WITHOUT-BACKFILL.md` |
| Implementing quick wins | `QUICK-WINS.md` |
| Building adaptive system | `DESIGN.md` + `IMPLEMENTATION-PLAN.md` |
| Exploring more angles | `ADDITIONAL-ANGLES.md` |

---

## Checklist

### Day 1
- [ ] Verify backfill complete (pre-flight check)
- [ ] Run baseline query - record ensemble MAE
- [ ] Run Oracle Test - record gap
- [ ] Make decision: Quick Wins only OR Adaptive System

### Days 2-4
- [ ] Run system agreement analysis
- [ ] Find worst predicted players
- [ ] Run veteran B2B analysis
- [ ] Run season phase analysis
- [ ] Run scoring tier analysis
- [ ] Document findings

### Day 5
- [ ] Pick 3-5 players for deep dive
- [ ] Run PLAYER-INVESTIGATION-TEMPLATE queries
- [ ] Document insights

### Week 2
- [ ] Implement top 2-3 quick wins
- [ ] Validate improvements
- [ ] If Oracle gap > 0.05: Start IMPLEMENTATION-PLAN.md Phase 2
