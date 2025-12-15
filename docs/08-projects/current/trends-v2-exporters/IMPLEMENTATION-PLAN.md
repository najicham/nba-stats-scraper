# Trends v2 Implementation Plan

**Created:** 2024-12-14
**Status:** Ready for Discussion

---

## Executive Summary

After analyzing the existing codebase, the Trends v2 exporters can be built much faster than originally estimated. Key insight: **StreaksExporter already solves 60% of Who's Hot/Cold**, and `player_game_summary` already has `over_under_result` (the "hit" indicator).

**Revised estimate:** 12-18 hours (down from 24-33 hours)

---

## What Already Exists

### Reusable Components

| Component | Location | Relevance |
|-----------|----------|-----------|
| `BaseExporter` | `data_processors/publishing/base_exporter.py` | Base class with `query_to_list()`, `upload_to_gcs()` |
| `StreaksExporter` | `data_processors/publishing/streaks_exporter.py` | Already tracks OVER/UNDER streaks - 80% of Who's Hot/Cold |
| `player_game_summary` | BigQuery | Has `over_under_result` (OVER/UNDER/PUSH), `points_line` |
| `prediction_accuracy` | BigQuery | Has hit rate data, `prediction_correct` flag |
| Prop lines | 2.2M records | `bettingpros_player_points_props` |

### Key Realization

The original TODO suggested creating:
- `trends_base_exporter.py` - **SKIP**: `BaseExporter` already has everything needed
- `hit_rate_queries.py` - **SKIP**: `player_game_summary.over_under_result` IS the hit indicator
- `archetype_queries.py` - **MAYBE**: Only needed for "What Matters Most"

---

## Recommended Implementation Order

### Phase 1: Who's Hot/Cold (2-3 hours)

**Why first:** Highest priority, most similar to existing code.

**Approach:** Extend/modify `StreaksExporter` concept with heat score algorithm:
- 50% recent hit rate (last 10 games OVER %)
- 25% current streak length
- 25% average margin (points above/below line)

**Key query pattern:**
```sql
WITH recent_games AS (
  SELECT
    player_lookup,
    game_date,
    over_under_result,
    points - points_line as margin,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as game_num
  FROM player_game_summary
  WHERE over_under_result IS NOT NULL
),
hit_rate AS (
  SELECT
    player_lookup,
    SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) / COUNT(*) as hit_rate,
    AVG(margin) as avg_margin
  FROM recent_games
  WHERE game_num <= 10
  GROUP BY player_lookup
)
-- + streak calculation + heat score
```

**Output:** `gs://nba-props-platform-api/v1/trends/whos-hot-v2.json`

---

### Phase 2: Bounce-Back Watch (2-3 hours)

**Why second:** Also daily, uses same data sources.

**Logic:**
1. Find players who scored 10+ below season average in last game
2. Look up their historical bounce-back rate (next game after similar drops)
3. Filter to players with games today

**Key query pattern:**
```sql
WITH player_averages AS (
  SELECT player_lookup, AVG(points) as season_avg
  FROM player_game_summary
  WHERE season_year = 2024
  GROUP BY player_lookup
),
last_game AS (
  SELECT player_lookup, points, game_date
  FROM player_game_summary
  QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) = 1
),
bad_games AS (
  SELECT l.player_lookup, l.points, a.season_avg,
         a.season_avg - l.points as shortfall
  FROM last_game l JOIN player_averages a USING (player_lookup)
  WHERE a.season_avg - l.points >= 10
)
-- + historical bounce-back rate calculation
```

**Output:** `gs://nba-props-platform-api/v1/trends/bounce-back.json`

---

### Phase 3: What Matters Most (3-4 hours)

**Why third:** Weekly, requires archetype classification.

**Archetype logic (simple):**
```sql
CASE
  WHEN years_in_league >= 10 AND usage_rate >= 0.25 AND ppg >= 20 THEN 'veteran_star'
  WHEN years_in_league BETWEEN 5 AND 9 AND usage_rate >= 0.28 AND ppg >= 22 THEN 'prime_star'
  WHEN years_in_league < 5 AND usage_rate >= 0.22 AND ppg >= 18 THEN 'young_star'
  ELSE 'role_player'
END
```

**Analysis dimensions:**
- Rest days impact (0, 1, 2+) by archetype
- Home vs away by archetype
- Back-to-back impact by archetype

**Output:** `gs://nba-props-platform-api/v1/trends/what-matters.json`

---

### Phase 4: Team Tendencies (2-3 hours)

**Why fourth:** Uses existing precompute data.

**Data sources already available:**
- `team_offense_game_summary.pace` - Pace kings/grinders
- `team_defense_zone_analysis` - Defense by shot profile
- Can derive home/away and B2B from game logs

**Output:** `gs://nba-props-platform-api/v1/trends/team-tendencies.json`

---

### Phase 5: Quick Hits (1-2 hours)

**Simple:** 8 rotating stats, each is a single query.

Examples:
- "Players on Sundays hit 54% of OVERs"
- "Back-to-backs see 12% more UNDERs"
- "Home favorites hit 58%"

**Output:** `gs://nba-props-platform-api/v1/trends/quick-hits.json`

---

### Phase 6: Deep Dive (30 min)

**Minimal:** Just a promo card pointing to detailed analysis.

```json
{
  "title": "December Deep Dive",
  "hero_stat": "Veteran stars hit 67% on 2+ rest days",
  "slug": "veteran-rest-december-2024"
}
```

**Output:** `gs://nba-props-platform-api/v1/trends/deep-dive-current.json`

---

## Simplified File Structure

Instead of 15+ new files, we need only:

```
data_processors/publishing/
├── whos_hot_cold_exporter.py    # NEW (2-3 hrs)
├── bounce_back_exporter.py      # NEW (2-3 hrs)
├── what_matters_exporter.py     # NEW (3-4 hrs)
├── team_tendencies_exporter.py  # NEW (2-3 hrs)
├── quick_hits_exporter.py       # NEW (1-2 hrs)
└── deep_dive_exporter.py        # NEW (30 min)
```

Total: 6 files, ~12-15 hours implementation

---

## What We Can Skip

| Originally Planned | Decision | Reason |
|-------------------|----------|--------|
| `trends_base_exporter.py` | SKIP | `BaseExporter` sufficient |
| `hit_rate_queries.py` | SKIP | `over_under_result` already exists |
| `archetype_queries.py` | INLINE | Only needed in one exporter |
| Unit tests per exporter | DEFER | Manual testing first, add tests if issues |
| Integration tests | DEFER | Manual GCS verification |
| Grafana monitoring | DEFER | Add after v1 working |

---

## Options for Tomorrow

### Option A: Build All 6 Exporters (Full Day)
- Implement all exporters in one session
- ~12-15 hours of focused work
- Result: Complete Trends v2 backend

### Option B: MVP First (Half Day)
- Build only Who's Hot/Cold + Bounce-Back (daily exporters)
- ~4-6 hours
- Result: Core daily insights working, iterate on weekly later

### Option C: Validate Queries First (2-3 hours)
- Write and test the SQL queries in BigQuery console
- Validate data quality and performance
- Then build exporters with confidence

---

## Recommended: Option B (MVP First)

**Rationale:**
1. Daily exporters are highest priority
2. Get something working fast to validate approach
3. Can iterate on weekly exporters based on learnings
4. Avoids over-engineering upfront

**Deliverables from MVP:**
- `whos-hot-v2.json` - Hot/cold players with heat scores
- `bounce-back.json` - Bounce-back candidates

**Timeline:** 4-6 hours → working daily trends

---

## Questions for Tomorrow

1. **Time window for hit rate:** Last 10 games? Last 14 days? Configurable?
2. **Minimum games threshold:** 5 games? 8 games? For statistical significance.
3. **Tonight filter:** Should hot/cold only show players with games today, or all players?
4. **Export trigger:** Manual CLI first, or jump straight to Cloud Scheduler?

---

## Ready to Start

All data is available. Pattern is clear. Just need to decide which option and start coding.
