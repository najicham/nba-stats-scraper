# Future Edge Exploration Ideas

**Date:** 2026-02-19 (Session 309)
**Status:** Research backlog — none started yet

Ideas for finding additional edge in the best bets system. Organized by category and estimated impact. Each idea should be validated with a discovery query before committing to feature engineering.

---

## Category 1: Player-Level Intelligence

### 1A. Player-Specific Edge Calibration (Player Affinity Score)

**Hypothesis:** Some players are systematically easier for the model to predict. A player who hits OVER 80% of the time at edge 5+ is genuinely more predictable than one at 55%. Building a per-player "model affinity" score could create a whitelist — prioritize picks on these players.

**What we have:** `prediction_accuracy` has full per-player grading history.

**Discovery query:**
```sql
SELECT player_lookup, recommendation,
       COUNT(*) as n,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_points - line_value) >= 5
  AND system_id = 'catboost_v9'
  AND game_date >= '2025-11-02'
GROUP BY 1, 2
HAVING COUNT(*) >= 8
ORDER BY hr DESC
```

**If validated:** Add `player_model_affinity` as a feature or a positive filter (whitelist) in the aggregator. Could also become a signal.

**Estimated impact:** HIGH — directly targets the selection problem.

---

### 1B. Player Direction Bias (Structural OVER/UNDER Players)

**Hypothesis:** Some players reliably go OVER (volume scorers with high floors, consistent 20+ minute roles) and others reliably go UNDER (streaky 3PT-dependent scorers). The model treats all players the same, but a player-level direction multiplier could help.

**What we have:** `prediction_accuracy` with `recommendation` column.

**Discovery query:**
```sql
SELECT player_lookup,
       COUNTIF(recommendation = 'OVER' AND prediction_correct) as over_wins,
       COUNTIF(recommendation = 'OVER' AND NOT prediction_correct) as over_losses,
       COUNTIF(recommendation = 'UNDER' AND prediction_correct) as under_wins,
       COUNTIF(recommendation = 'UNDER' AND NOT prediction_correct) as under_losses
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_points - line_value) >= 3
  AND system_id = 'catboost_v9'
  AND game_date >= '2025-11-02'
GROUP BY 1
HAVING (over_wins + over_losses) >= 5 AND (under_wins + under_losses) >= 5
ORDER BY player_lookup
```

**What to look for:** Players where OVER HR is >65% but UNDER HR is <45% (or vice versa). If common, the model could learn "trust this player for OVER but not UNDER."

**Estimated impact:** MEDIUM — may overlap with what the model already captures via rolling averages.

---

### 1C. Poor Game → Minutes Redistribution → Teammate Boost

**Hypothesis:** When a player has a terrible shooting game (10+ below average), their coach reduces their minutes next game. Those minutes get redistributed to teammates, who then score more. This is different from injuries — it catches **coach decisions** that don't show up in injury reports.

**What we have:**
- `player_game_summary` has minutes and points per game
- `consecutive_games_below_avg` (feature 46) — cold streak counter
- `minutes_change` (feature 12) — but only for the player themselves

**What's missing:** The *cross-player* chain. Feature 46 tells the model "this player is cold" but not "this player's teammate is cold, so this player gets more minutes."

**Discovery query (step 1 — does poor game predict minutes drop?):**
```sql
WITH games AS (
  SELECT player_lookup, game_date, minutes_played, points,
         LAG(points) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_points,
         LAG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_minutes,
         AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                           ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as avg_points_10
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2025-11-02' AND minutes_played > 10
)
SELECT
  CASE
    WHEN prev_points < avg_points_10 - 10 THEN 'very_bad_prev_game'
    WHEN prev_points < avg_points_10 - 5 THEN 'bad_prev_game'
    ELSE 'normal_prev_game'
  END as prev_game_quality,
  COUNT(*) as n,
  ROUND(AVG(minutes_played - prev_minutes), 1) as avg_minutes_change
FROM games
WHERE prev_points IS NOT NULL AND avg_points_10 IS NOT NULL
GROUP BY 1
```

**If validated (step 2):** Check if *teammates* of the underperformer see a minutes/points bump. Would require a join through team rosters.

**Potential feature:** `teammate_bad_game_boost` — sum of minutes likely freed by teammates who had poor games recently.

**Estimated impact:** MEDIUM-HIGH — unique signal that no one else is modeling.

---

## Category 2: Team Defensive Tendencies

### 2A. Multi-Zone Mismatch (Improve Existing Feature)

**Hypothesis:** The current `shot_zone_mismatch_score` (feature 6) only evaluates the player's *primary* scoring zone. A player who scores 40% from paint + 35% from 3PT only gets evaluated on paint. The perimeter dimension is ignored.

**What we have:** `team_defense_zone_analysis` processor already computes paint/mid-range/perimeter defense vs league avg for every team (rolling 15 games).

**What to change:** Score ALL 3 zones weighted by the player's actual usage distribution, not just the primary one. For example:
```
multi_zone_score = (paint_mismatch * paint_usage) + (mid_mismatch * mid_usage) + (perim_mismatch * perim_usage)
```

**Discovery query:** Check whether the existing `shot_zone_mismatch_score` even correlates with outcomes:
```sql
SELECT
  CASE
    WHEN feature_6_value > 3 THEN 'strong_favorable'
    WHEN feature_6_value > 0 THEN 'mild_favorable'
    WHEN feature_6_value > -3 THEN 'mild_unfavorable'
    ELSE 'strong_unfavorable'
  END as mismatch_bucket,
  COUNT(*) as n,
  ROUND(AVG(CASE WHEN pa.prediction_correct THEN 1 ELSE 0 END) * 100, 1) as hr
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_predictions.prediction_accuracy pa
  ON fs.player_lookup = pa.player_lookup AND fs.game_date = pa.game_date
WHERE fs.game_date >= '2025-11-02'
  AND pa.system_id = 'catboost_v9'
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND fs.feature_6_value IS NOT NULL
GROUP BY 1
ORDER BY 1
```

**If the existing feature doesn't correlate:** Multi-zone scoring may fix it. If it does correlate, multi-zone would amplify it.

**Estimated impact:** MEDIUM — improves an existing feature rather than adding a new one. Lower risk.

---

### 2B. Position-Specific Defensive Tendencies

**Hypothesis:** "This team gives up X extra points to point guards vs league average" is more specific than overall defensive rating. A team might be elite at defending bigs but terrible against guards, and those are different prop bets.

**What we have:**
- Play-by-play data with shot zones and player IDs
- Player positions from roster data
- `opponent_def_rating` (feature 13) — but this is team-level, not position-specific

**What's missing:** A precomputed table like `team_defense_by_position` with columns:
```
team_abbr | position | points_allowed_per_game | vs_league_avg | rolling_15_games
```

**Discovery query:**
```sql
SELECT
  pgs.opponent_team_abbr,
  -- Approximate position from minutes/usage patterns or roster
  CASE
    WHEN pgs.minutes_played > 30 AND pgs.points > 15 THEN 'primary_scorer'
    WHEN pgs.minutes_played > 20 THEN 'rotation'
    ELSE 'bench'
  END as role_bucket,
  COUNT(*) as games,
  ROUND(AVG(pgs.points), 1) as avg_points_allowed
FROM nba_analytics.player_game_summary pgs
WHERE pgs.game_date >= '2025-12-01' AND pgs.minutes_played > 10
GROUP BY 1, 2
ORDER BY 1, 2
```

**Better version:** Use actual player positions from roster data. Could compute "points allowed to PG/SG/SF/PF/C" per team.

**Potential feature:** `opponent_position_defense_vs_avg` — how many extra/fewer points does the opponent give up to players at this position?

**Estimated impact:** MEDIUM — adds a dimension the model can't learn from the current feature set (no position info goes into the model at all today).

---

### 2C. Pace-Adjusted Defensive Tendencies

**Hypothesis:** A team can look bad at perimeter defense simply because they play fast (more possessions → more 3PA allowed → more 3PT points allowed). The current `team_defense_zone_analysis` uses raw points allowed, not pace-adjusted.

**What we have:** `team_pace` (feature 22), `opponent_pace` (feature 14). Zone analysis uses raw counts.

**What to change:** Normalize zone defense stats to "per 100 possessions" instead of "per game." This would separate "genuinely bad perimeter defense" from "fast team that gives up volume."

**Estimated impact:** LOW-MEDIUM — refinement of existing data, may not change outcomes much.

---

## Category 3: Market & Line Intelligence

### 3A. Line Staleness Detection

**Hypothesis:** Sometimes sportsbook prop lines don't move for days even after significant new information (injury report, back-to-back, blowout previous game). A "stale line" is easier to beat because it hasn't incorporated recent data.

**What we have:**
- `prop_line_delta` (feature 54) — current line vs previous game's line
- `multi_book_line_std` (feature 50) — cross-book line standard deviation
- `vegas_line_move` (feature 27) — opening vs current line movement

**What's missing:** A direct "line freshness" signal. If a player's line hasn't changed despite a teammate injury being announced today, that's stale.

**Discovery query:**
```sql
SELECT
  CASE
    WHEN ABS(f.feature_54_value) < 0.5 THEN 'line_unchanged'
    WHEN ABS(f.feature_54_value) < 2.0 THEN 'small_move'
    ELSE 'big_move'
  END as line_movement,
  COUNT(*) as n,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_predictions.prediction_accuracy pa
  ON f.player_lookup = pa.player_lookup AND f.game_date = pa.game_date
WHERE f.game_date >= '2025-11-02'
  AND pa.system_id = 'catboost_v9'
  AND ABS(pa.predicted_points - pa.line_value) >= 5
  AND f.feature_54_value IS NOT NULL
GROUP BY 1
```

**If validated:** "Unchanged line + high edge" could be a strong signal — the market is sleeping.

**Estimated impact:** MEDIUM-HIGH — exploits market inefficiency directly.

---

### 3B. Book Disagreement Deep Dive

**Hypothesis:** We already have `book_disagreement` signal (93% HR, small N). The `multi_book_line_std` (feature 50) captures cross-book stddev. But we might be able to go deeper — specifically, when one book has a line 2+ points off from the median, that's a pricing error.

**What we have:** `odds_api` data with per-book lines.

**What's missing:** A feature that captures "max book divergence from median" rather than just stddev.

**Estimated impact:** MEDIUM — extends an existing signal that shows promise.

---

## Category 4: Situational / Game-Context

### 4A. Blowout Prediction → Minutes Reduction

**Hypothesis:** When a game is projected to be a blowout (spread 10+), starters on the favored team play fewer minutes (garbage time). The model predicts points but doesn't account for minutes reduction in blowouts.

**What we have:**
- `spread_magnitude` (feature 41) — point spread
- `implied_team_total` (feature 42)

**Discovery query:**
```sql
SELECT
  CASE
    WHEN ABS(f.feature_41_value) >= 10 THEN 'projected_blowout'
    WHEN ABS(f.feature_41_value) >= 6 THEN 'moderate_spread'
    ELSE 'close_game'
  END as spread_bucket,
  pa.recommendation,
  COUNT(*) as n,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_predictions.prediction_accuracy pa
  ON f.player_lookup = pa.player_lookup AND f.game_date = pa.game_date
WHERE f.game_date >= '2025-11-02'
  AND pa.system_id = 'catboost_v9'
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND f.feature_41_value IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
```

**If validated:** Could add a blowout UNDER signal or use it as a negative filter for OVER picks on favored team starters.

**Estimated impact:** MEDIUM — the model has the spread feature but may not learn the minutes-reduction implication.

---

### 4B. Game Total Environment × Player Role

**Hypothesis:** High game totals (240+) benefit volume scorers differently than role players. The model has `game_total_line` (feature 38) but doesn't interact it with player role. A bench player in a high-total game doesn't benefit the same way a starter does.

**What we have:** `game_total_line` (feature 38), player averages.

**What's missing:** An interaction feature: `game_total_relative_to_player_avg`. If the game total implies 120 points for the player's team but the player averages 12, that's different from a 25 PPG player.

**Estimated impact:** LOW-MEDIUM — CatBoost can learn some interactions, but explicit interaction features help.

---

## Category 5: Temporal / Scheduling

### 5A. Schedule Spot Difficulty

**Hypothesis:** A player on a 4-games-in-5-nights stretch performs differently than one on 2-games-in-7-days, beyond what `back_to_back` (feature 16) and `days_rest` (feature 39) capture. The *sequence* matters — game 3 of a road trip is worse than the 2nd back-to-back at home.

**What we have:** `back_to_back`, `days_rest`, `fatigue_score` (feature 5), `minutes_load_last_7d` (feature 40).

**What's missing:** A "schedule difficulty" composite that looks at the upcoming/recent game density + travel. NBA teams have public schedule data we scrape.

**Estimated impact:** LOW-MEDIUM — fatigue features exist but may miss cumulative scheduling effects.

---

### 5B. Time-of-Season Effects

**Hypothesis:** Player behavior changes across the season. Early season (Oct-Nov) has higher variance. Post-All-Star has tanking teams resting players. Playoff push (Mar-Apr) has increased intensity. The model trains on a 42-day rolling window, which helps, but explicit season-phase features might add signal.

**What we have:** Training window handles some of this implicitly.

**Estimated impact:** LOW — the rolling window already adapts. Not a priority.

---

## Priority Ranking

| Rank | Idea | Category | Expected Impact | Effort | Data Ready? |
|------|------|----------|-----------------|--------|-------------|
| 1 | Player affinity score (1A) | Player | HIGH | Small (query only) | YES |
| 2 | Minutes redistribution (1C) | Player | MEDIUM-HIGH | Medium (new feature) | YES |
| 3 | Line staleness (3A) | Market | MEDIUM-HIGH | Small (query + signal) | YES |
| 4 | Multi-zone mismatch (2A) | Defense | MEDIUM | Medium (modify existing) | YES |
| 5 | Position-specific defense (2B) | Defense | MEDIUM | Large (new processor) | PARTIAL |
| 6 | Blowout minutes (4A) | Situational | MEDIUM | Small (query + filter) | YES |
| 7 | Player direction bias (1B) | Player | MEDIUM | Small (query only) | YES |
| 8 | Book disagreement deep dive (3B) | Market | MEDIUM | Medium | YES |
| 9 | Game total × role (4B) | Situational | LOW-MEDIUM | Medium | YES |
| 10 | Pace-adjusted defense (2C) | Defense | LOW-MEDIUM | Medium | YES |
| 11 | Schedule difficulty (5A) | Temporal | LOW-MEDIUM | Medium | PARTIAL |
| 12 | Season phase (5B) | Temporal | LOW | Small | YES |

---

## Research Protocol

For each idea:
1. **Discovery query** — Run the suggested query to check if the pattern exists
2. **Effect size** — If it exists, how big is the HR difference? (Need 5+ percentage points to matter)
3. **Sample size** — N >= 50 in each bucket for statistical reliability
4. **Overlap check** — Does the model already capture this via existing features?
5. **Implementation** — If validated: signal, feature, or negative filter?
6. **Backtest** — Run through season replay before production deployment
