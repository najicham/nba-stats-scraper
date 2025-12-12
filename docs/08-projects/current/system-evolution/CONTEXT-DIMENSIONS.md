# Context Dimensions for Analysis

**Last Updated:** 2025-12-11

This document defines all the dimensions we'll analyze to discover which prediction systems work best in which situations.

---

## Dimension Categories

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONTEXT DIMENSIONS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  TEMPORAL                 PLAYER                    GAME                     │
│  ────────                 ──────                    ────                     │
│  • Season phase           • Scoring tier            • Home/Away              │
│  • Day of week            • Age group               • Back-to-back           │
│  • Month                  • Experience              • Rest days              │
│  • Games into season      • Role consistency        • Opponent strength      │
│                           • Minutes volatility      • Pace matchup           │
│                           • Team role               • Division game          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Temporal Dimensions

### 1.1 Season Phase

**Hypothesis:** Early season has less data, favoring similarity-based systems. Mid-season favors ML.

| Phase | Games | Rationale |
|-------|-------|-----------|
| EARLY | 1-20 | Limited current season data, rely on historical patterns |
| MID_EARLY | 21-40 | Building data, systems starting to have signal |
| MID_LATE | 41-60 | Peak data quality, ML should excel |
| LATE | 61-72 | Playoff positioning, rest patterns change |
| PLAYOFFS | 73+ | Different intensity, minutes patterns change |

```sql
-- Classification
CASE
  WHEN team_games_played <= 20 THEN 'EARLY'
  WHEN team_games_played <= 40 THEN 'MID_EARLY'
  WHEN team_games_played <= 60 THEN 'MID_LATE'
  WHEN team_games_played <= 72 THEN 'LATE'
  ELSE 'PLAYOFFS'
END as season_phase
```

### 1.2 Day of Week

**Hypothesis:** Sunday/Monday games (after weekend back-to-backs) may show fatigue patterns.

| Day | Notes |
|-----|-------|
| WEEKDAY | Mon-Thu: Normal schedule |
| FRIDAY | Start of weekend slate |
| SATURDAY | Heavy game day |
| SUNDAY | Often rest day or light slate |

### 1.3 Month of Season

**Hypothesis:** December (heavy schedule), March (playoff push) may have different patterns.

| Month | Notes |
|-------|-------|
| October | Season start, rust/ramp-up |
| November | Early patterns emerging |
| December | Heaviest schedule |
| January | All-Star break approaching |
| February | Trade deadline, roster flux |
| March | Playoff push |
| April | Load management peaks |

---

## 2. Player Dimensions

### 2.1 Scoring Tier (Already Implemented)

| Tier | Season Avg | Notes |
|------|------------|-------|
| BENCH | 0-9 | Limited, inconsistent minutes |
| ROTATION | 10-19 | Regular rotation players |
| STARTER | 20-29 | Core players |
| STAR | 30+ | High usage, complex patterns |

### 2.2 Age Group

**Hypothesis:** Veterans (32+) show more fatigue effects. Young players more volatile.

| Group | Age | Rationale |
|-------|-----|-----------|
| YOUNG | <25 | Still developing, volatile |
| PRIME | 25-31 | Peak performance, consistent |
| VETERAN | 32-35 | Experience but fatigue risk |
| ELDER | 36+ | Load management, selective effort |

```sql
-- Get age from player lookup or enrichment
CASE
  WHEN player_age < 25 THEN 'YOUNG'
  WHEN player_age < 32 THEN 'PRIME'
  WHEN player_age < 36 THEN 'VETERAN'
  ELSE 'ELDER'
END as age_group
```

### 2.3 Experience (Years in League)

**Hypothesis:** Rookies are unpredictable. Veterans are more pattern-consistent.

| Group | Years | Notes |
|-------|-------|-------|
| ROOKIE | 0-1 | First/second year |
| DEVELOPING | 2-4 | Finding role |
| ESTABLISHED | 5-9 | Known quantity |
| VETERAN | 10+ | Deep patterns |

### 2.4 Role Consistency

**Hypothesis:** Players with consistent minutes are easier to predict.

| Group | Minutes StdDev | Notes |
|-------|---------------|-------|
| CONSISTENT | <5 min std | Same role every game |
| MODERATE | 5-8 min std | Some variation |
| VOLATILE | >8 min std | Highly variable usage |

```sql
-- Compute from recent games
CASE
  WHEN STDDEV(minutes) < 5 THEN 'CONSISTENT'
  WHEN STDDEV(minutes) < 8 THEN 'MODERATE'
  ELSE 'VOLATILE'
END as role_consistency
```

### 2.5 Team Role

**Hypothesis:** Primary scorers vs complementary players have different patterns.

| Role | Criteria | Notes |
|------|----------|-------|
| PRIMARY | Top 2 in team usage | First options |
| SECONDARY | 3rd-4th in usage | Supporting scorers |
| COMPLEMENTARY | 5th+ in usage | Role players |

---

## 3. Game Context Dimensions

### 3.1 Location

**Hypothesis:** Home court provides small but consistent boost.

| Location | Notes |
|----------|-------|
| HOME | Home court advantage |
| AWAY | Travel, crowd factor |

### 3.2 Rest Status

**Hypothesis:** Back-to-backs matter more for veterans.

| Status | Days Rest | Notes |
|--------|-----------|-------|
| WELL_RESTED | 3+ days | Extra recovery |
| RESTED | 2 days | Normal rest |
| NORMAL | 1 day | Standard schedule |
| BACK_TO_BACK | 0 days | Second of B2B |

```sql
CASE
  WHEN days_rest >= 3 THEN 'WELL_RESTED'
  WHEN days_rest = 2 THEN 'RESTED'
  WHEN days_rest = 1 THEN 'NORMAL'
  ELSE 'BACK_TO_BACK'
END as rest_status
```

### 3.3 Opponent Defense Rating

**Hypothesis:** Elite defenses require different prediction approach.

| Rating | Rank | Notes |
|--------|------|-------|
| ELITE | 1-5 | Top defensive teams |
| GOOD | 6-15 | Above average |
| AVERAGE | 16-20 | Middle of pack |
| POOR | 21-30 | Below average |

### 3.4 Pace Matchup

**Hypothesis:** High-pace games have more variance.

| Matchup | Combined Pace | Notes |
|---------|--------------|-------|
| FAST | Top quartile | High possession games |
| NORMAL | Middle 50% | Standard pace |
| SLOW | Bottom quartile | Grind-it-out games |

### 3.5 Game Importance

**Hypothesis:** Playoff/elimination scenarios change behavior.

| Importance | Criteria | Notes |
|------------|----------|-------|
| REGULAR | Regular season | Normal patterns |
| PLAYOFF_PUSH | Last 10 games, close race | Elevated effort |
| PLAYOFFS | Postseason | Maximum effort |
| BLOWOUT_RISK | >10 pt spread | Garbage time risk |

---

## 4. Interaction Effects

Some dimensions interact - the combination matters more than individual dimensions.

### Key Interactions to Test

| Interaction | Hypothesis |
|-------------|-----------|
| **Age + Rest** | Veterans on B2B show bigger dropoff than young players |
| **Tier + Season Phase** | Stars are consistent all season; role players improve mid-season |
| **Role + Opponent** | Complementary players vary more against elite defense |
| **Age + Minutes** | Elder players with high minutes = fatigue risk |
| **Season Phase + Opponent** | Early season opponent rankings are noisy |

### Interaction Analysis Query

```sql
-- Example: Age + Rest interaction
SELECT
  age_group,
  rest_status,
  system_id,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias
FROM prediction_accuracy_enriched
GROUP BY 1, 2, 3
HAVING n >= 50
ORDER BY age_group, rest_status, mae
```

---

## 5. Data Requirements

### Enrichment Needed

Some dimensions require joining additional data:

| Dimension | Source | Join Key |
|-----------|--------|----------|
| player_age | Player roster/bio | player_id |
| team_games_played | Schedule/standings | team_id + date |
| opponent_def_rating | Team stats | opponent_id + date |
| days_rest | Schedule | player_id + date |

### Already Available

| Dimension | Source |
|-----------|--------|
| scoring_tier | ml_feature_store (season_avg) |
| home/away | prediction record |
| game_date | prediction record |

---

## 6. Priority Ranking

Based on expected impact and data availability:

| Priority | Dimension | Expected Impact | Data Ready? |
|----------|-----------|-----------------|-------------|
| 1 | Season Phase | High | Yes |
| 2 | Scoring Tier | High | Yes |
| 3 | Age Group | Medium-High | Needs enrichment |
| 4 | Rest Status | Medium | Partially |
| 5 | Opponent Defense | Medium | Needs enrichment |
| 6 | Role Consistency | Medium | Computable |
| 7 | Location | Low-Medium | Yes |
| 8 | Game Importance | Low | Complex logic |

---

## 7. Minimum Sample Sizes

To get reliable signal, require minimum samples per context:

| Analysis Type | Minimum N | Rationale |
|--------------|-----------|-----------|
| Single dimension | 100 | Basic reliability |
| Two dimensions | 50 | Manageable combinations |
| Three dimensions | 30 | Accept more noise |
| Interaction effects | 50 | Need enough for each cell |

---

## 8. Next Steps

1. **Run baseline analysis** with dimensions already available (season phase, tier, location)
2. **Add enrichment** for age group and rest status
3. **Analyze interactions** between top dimensions
4. **Identify actionable patterns** (where system performance differs by >0.3 MAE)
