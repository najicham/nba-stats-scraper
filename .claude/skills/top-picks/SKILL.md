---
name: top-picks
description: Extract the best trading candidates based on confidence and edge
---

# Skill: Top Picks

Extract today's best bets picks — the actual trading candidates selected by the signal-based filter stack.

## Trigger
- User asks about "top picks", "best bets", "trading candidates", "what should I bet on"
- User types `/top-picks`

## Definition

**Top Picks** = Best bets picks from `signal_best_bets_picks` — already filtered through:
- Edge >= 3.0 (meaningful disagreement with Vegas)
- Signal count >= 4 (edge < 7) or >= 3 (edge 7+)
- 14+ negative filters (blacklist, direction affinity, quality floor, etc.)
- Signal density (base-only signals blocked unless edge >= 7)

These are the picks the system has highest conviction on. Do NOT re-filter by confidence — confidence was proven useless (Session 81).

## Main Query — Today's Best Bets

```sql
-- Today's best bets picks (the ACTUAL trading candidates)
SELECT
  bb.player_lookup,
  bb.recommendation,
  ROUND(bb.edge, 1) as edge,
  bb.signal_count,
  bb.system_id,
  bb.pick_angles,
  bb.ultra_tier,
  ROUND(p.predicted_points, 1) as predicted,
  ROUND(p.current_points_line, 1) as vegas_line
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p
  ON bb.player_lookup = p.player_lookup
  AND bb.game_date = p.game_date
  AND bb.system_id = p.system_id
WHERE bb.game_date = CURRENT_DATE()
ORDER BY bb.edge DESC
```

## With Recent Performance Context

```sql
-- Best bets picks with player's recent accuracy
WITH player_recent AS (
  SELECT
    player_lookup,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as recent_hit_rate,
    COUNT(*) as recent_games
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 21 DAY)
    AND game_date < CURRENT_DATE()
  GROUP BY player_lookup
)
SELECT
  bb.player_lookup,
  bb.recommendation,
  ROUND(bb.edge, 1) as edge,
  bb.signal_count,
  bb.system_id,
  bb.pick_angles,
  bb.ultra_tier,
  COALESCE(r.recent_hit_rate, 0) as player_21d_hr,
  COALESCE(r.recent_games, 0) as games_l21
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
LEFT JOIN player_recent r ON bb.player_lookup = r.player_lookup
WHERE bb.game_date = CURRENT_DATE()
ORDER BY bb.edge DESC
```

## Summary Stats

```sql
-- Best bets summary
SELECT
  COUNT(*) as total_picks,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  ROUND(AVG(edge), 1) as avg_edge,
  ROUND(MAX(edge), 1) as max_edge,
  ROUND(AVG(signal_count), 1) as avg_signals,
  COUNTIF(ultra_tier IS NOT NULL) as ultra_picks
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = CURRENT_DATE()
```

## Recent Best Bets Performance (21-day rolling)

```sql
-- How has the best bets system performed recently?
SELECT
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr_21d,
  COUNTIF(pa.prediction_correct) as wins,
  COUNT(*) - COUNTIF(pa.prediction_correct) as losses,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(bb.recommendation = 'OVER' AND pa.prediction_correct) /
    NULLIF(COUNTIF(bb.recommendation = 'OVER'), 0), 1) as over_hr,
  COUNTIF(bb.recommendation = 'OVER') as over_n,
  ROUND(100.0 * COUNTIF(bb.recommendation = 'UNDER' AND pa.prediction_correct) /
    NULLIF(COUNTIF(bb.recommendation = 'UNDER'), 0), 1) as under_hr,
  COUNTIF(bb.recommendation = 'UNDER') as under_n
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 21 DAY)
  AND pa.game_date < CURRENT_DATE()
WHERE bb.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 21 DAY)
  AND bb.game_date < CURRENT_DATE()
  AND pa.prediction_correct IS NOT NULL
  AND pa.is_voided IS NOT TRUE
```

## Output Format

```
Today's Best Bets (2026-03-03)
==============================

Found 8 trading candidates

| Player          | Rec   | Edge  | Signals | Model                    | Ultra |
|-----------------|-------|-------|---------|--------------------------|-------|
| lebron-james    | OVER  | +7.2  | 5       | catboost_v12_noveg_...   | v12_edge_6plus |
| jayson-tatum    | UNDER | +5.4  | 4       | catboost_v12_train_...   |       |

Summary:
  Total Picks: 8 (5 OVER / 3 UNDER)
  Avg Edge: 5.1 | Max Edge: 7.2
  Ultra Picks: 2

21-Day Performance: 62.5% HR (25W-15L)
  OVER: 68.0% (17/25) | UNDER: 53.3% (8/15)
```

## Filtering Options

- `/top-picks 5` → Only edge 5+ picks
- `/top-picks over` → Only OVER picks
- `/top-picks under` → Only UNDER picks
- `/top-picks ultra` → Only ultra-tier picks
