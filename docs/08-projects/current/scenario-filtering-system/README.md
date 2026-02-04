# Scenario Filtering System

**Created**: Session 112 (2026-02-03)
**Status**: Active - Phase 1 Complete

## Overview

A data-driven system for identifying optimal and anti-pattern betting scenarios based on Session 111-112 analysis of 1,581+ predictions.

## Key Insight

**The model's star under-prediction bias (-9 pts) is NOT the problem.**

The real insight: Different **scenarios** have dramatically different hit rates:
- OVER + Low Lines + High Edge = **87.3%** hit rate
- UNDER + Low Lines = **53.8%** hit rate (coin flip)

Scenario filtering provides +30-40% ROI improvement vs unfiltered betting.

## Optimal Scenarios (GREEN ZONE)

| Subset ID | Filters | Hit Rate | ROI | Volume |
|-----------|---------|----------|-----|--------|
| `optimal_over` | OVER + Line <12 + Edge ≥5 | **87.3%** | +66.8% | 1-2/day |
| `ultra_high_edge_over` | OVER + Edge ≥7 | **88.5%** | +69.0% | 1/day |
| `optimal_under` | UNDER + Line ≥25 + Edge ≥3 | **70.7%** | +35.0% | 1-2/day |
| `under_safe` | UNDER + Line ≥20 + Blacklist | **65.0%** | +24.0% | 2-3/day |

## Anti-Patterns (RED ZONE)

| Subset ID | Filters | Hit Rate | Action |
|-----------|---------|----------|--------|
| `anti_under_low_line` | UNDER + Line <15 + Edge ≥3 | 53.8% | **AVOID** |
| `anti_low_edge` | Any + Edge <3 | 51.5% | **SKIP** |

## Player Blacklist

Do NOT bet UNDER on these players (all <50% UNDER hit rate):

| Player | UNDER HR | Reason |
|--------|----------|--------|
| Jaren Jackson Jr | 28.6% | Explosive games |
| Dillon Brooks | 40.0% | Inconsistent |
| Michael Porter Jr | 40.0% | High variance |
| Julius Randle | 42.9% | Breakout prone |
| LaMelo Ball | 44.4% | Explosive guard |
| Luka Doncic | 45.5% | Star variance |

## Opponent Risk List

UNDER bets against these teams have <40% hit rate:

| Team | UNDER HR | Reason |
|------|----------|--------|
| PHI | 36.4% | Allows big games |
| MIN | 37.5% | Fast pace |
| DET | 37.5% | Weak defense |
| MIA | 38.5% | Exploitable |
| DEN | 40.0% | High scoring |

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `dynamic_subset_definitions` | Subset configurations with scenario filters |
| `player_betting_risk` | Player blacklist with hit rates |
| `opponent_betting_risk` | Opponent risk flags |

### New Columns in dynamic_subset_definitions

| Column | Type | Purpose |
|--------|------|---------|
| `recommendation_filter` | STRING | OVER/UNDER filter |
| `line_min` | FLOAT64 | Minimum Vegas line |
| `line_max` | FLOAT64 | Maximum Vegas line |
| `exclude_players` | STRING | JSON array of blacklisted players |
| `exclude_opponents` | STRING | JSON array of risky opponents |
| `scenario_category` | STRING | optimal/anti_pattern/signal_based |
| `expected_hit_rate` | FLOAT64 | Session 112 validated rate |
| `expected_roi` | FLOAT64 | Expected return |
| `sample_size_source` | INT64 | Bets used for calculation |
| `validation_period` | STRING | Date range of validation |
| `last_validated_at` | TIMESTAMP | When last verified |

## Skills Updated

- `/hit-rate-analysis` - Added Queries 8-11 for scenario analysis
- `/subset-picks` - Works with new scenario subsets
- `/subset-performance` - Compares scenario performance

## Quick Commands

```bash
# Check today's picks by scenario
bq query --use_legacy_sql=false "
SELECT player_lookup, recommendation, current_points_line as line,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  CASE
    WHEN recommendation = 'OVER' AND current_points_line < 12 AND ABS(predicted_points - current_points_line) >= 5 THEN 'OPTIMAL_OVER'
    WHEN recommendation = 'UNDER' AND current_points_line >= 25 AND ABS(predicted_points - current_points_line) >= 3 THEN 'OPTIMAL_UNDER'
    WHEN recommendation = 'OVER' AND ABS(predicted_points - current_points_line) >= 7 THEN 'ULTRA_HIGH'
    ELSE 'STANDARD'
  END as scenario
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9' AND is_active = TRUE
  AND recommendation IN ('OVER', 'UNDER')
ORDER BY scenario, edge DESC"

# Validate scenario performance (last 30 days)
/hit-rate-analysis --query 8

# Check player blacklist effectiveness
/hit-rate-analysis --query 9
```

## Validation Results (Session 112)

| Claim | Expected | Actual | Status |
|-------|----------|--------|--------|
| OPTIMAL_OVER | 87.3% | 87.3% | ✅ Verified |
| OPTIMAL_UNDER | 66.0% | 70.7% | ✅ Better |
| ULTRA_HIGH_EDGE_OVER | 90.0% | 88.5% | ✅ Close |
| Low Edge <3 | 51-52% | 51.5% | ✅ Verified |

## Signal + Scenario Integration

The system uses TWO complementary filtering approaches:

| System | Level | Purpose |
|--------|-------|---------|
| **Daily Signal (RED/GREEN)** | Day-level | Overall prediction mix quality |
| **Scenario Classification** | Pick-level | Individual pick characteristics |

**Example workflow:**
1. Check daily signal: GREEN → proceed normally, RED → be cautious
2. Filter picks by scenario: optimal_over, optimal_under, ultra_high_edge
3. Check player blacklist and opponent risk for UNDER bets

## Files

| File | Purpose |
|------|---------|
| `schemas/bigquery/predictions/04b_scenario_subset_extensions.sql` | Schema extensions |
| `predictions/worker/worker.py` | Scenario classification (`_classify_scenario`) |
| `predictions/coordinator/signal_calculator.py` | Daily signal + scenario counts |
| `.claude/skills/hit-rate-analysis/SKILL.md` | Updated skill with queries 8-11 |
| `docs/08-projects/current/scenario-filtering-system/` | This documentation |

## Database Changes (Session 112)

### New Columns in player_prop_predictions
- `scenario_category` - Classification: optimal_over, optimal_under, etc.
- `scenario_flags` - JSON with edge, blacklist, opponent risk details

### New Columns in daily_prediction_signals
- `optimal_over_count` - Count of optimal OVER picks
- `optimal_under_count` - Count of optimal UNDER picks
- `ultra_high_edge_count` - Count of edge 7+ OVER picks
- `anti_pattern_count` - Count of anti-pattern picks (avoid)

### New Columns in dynamic_subset_definitions
- `recommendation_filter` - OVER/UNDER filter
- `line_min`, `line_max` - Line range filters
- `exclude_players` - JSON array of blacklisted players
- `exclude_opponents` - JSON array of risky opponents
- `scenario_category` - optimal/anti_pattern/signal_based
- `expected_hit_rate`, `expected_roi` - Validated rates
- `sample_size_source`, `validation_period`, `last_validated_at` - Audit trail

### New Tables
- `player_betting_risk` - Player blacklist with hit rates
- `opponent_betting_risk` - Opponent risk flags

## Related Documentation

- Session 111: `docs/09-handoff/2026-02-03-SESSION-111-HANDOFF.md`
- Session 112: `docs/09-handoff/2026-02-03-SESSION-112-HANDOFF.md`
- Original investigation: `docs/08-projects/current/regression-to-mean-fix/`
