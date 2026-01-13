# Referee Tendencies Enhancement

## Current State

**What we have:**
- `nba_raw.nbac_referee_game_assignments` - who refs which game
- Pivot views for easy joins
- Official names, codes, jersey numbers

**What we're missing:**
- `referee_avg_points_per_game` - placeholder in schema, not calculated
- `referee_avg_pace` - placeholder in schema, not calculated
- O/U record by referee crew
- Foul tendencies

## Why This Matters

Research shows referee crews have measurable impact on game outcomes:
- High-pace crews = more possessions = more points
- Some crews call more fouls = more free throws
- Total points variance of 5-10 points between crews

For player props, a 5-point game total swing can mean 1-2 point swing per star player.

## Implementation Options

### Option A: Build From Our Own Data (Recommended)

**Approach:** Create processor that joins referee assignments with game results

```sql
-- Calculate referee tendencies from our data
SELECT
  official_code,
  official_name,
  COUNT(*) as games_worked,
  AVG(home_score + away_score) as avg_total_points,
  AVG(home_score + away_score) - league_avg as points_vs_avg,
  SUM(CASE WHEN home_score + away_score > total_line THEN 1 ELSE 0 END) / COUNT(*) as over_pct
FROM nba_raw.nbac_referee_game_assignments r
JOIN nba_raw.game_results g ON r.game_id = g.game_id
JOIN nba_raw.game_lines l ON r.game_id = l.game_id
GROUP BY official_code, official_name
```

**Pros:**
- No external dependency
- Consistent with our other data
- Free

**Cons:**
- Need to build and maintain processor
- Limited to games since we started tracking

### Option B: Scrape External Source

**Sources:**
- NBAstuffer.com - Excel downloads, $$ subscription
- Covers.com - Web scraping needed
- RefMetrics.com - Limited free data

**Pros:**
- Historical data going back years
- Already calculated

**Cons:**
- External dependency
- Scraping maintenance
- Possible costs

## Recommended Implementation

### Phase 1: Build Processor (Option A)

Create `data_processors/analytics/referee_tendencies/referee_tendencies_processor.py`

**Output table:** `nba_analytics.referee_tendencies`

```sql
CREATE TABLE nba_analytics.referee_tendencies (
  official_code INT64,
  official_name STRING,
  season STRING,

  -- Volume
  games_worked INT64,

  -- Scoring tendencies
  avg_total_points NUMERIC(5,1),
  points_vs_league_avg NUMERIC(4,1),

  -- O/U record
  over_percentage NUMERIC(4,2),
  under_percentage NUMERIC(4,2),
  push_percentage NUMERIC(4,2),

  -- Pace indicators
  avg_possessions NUMERIC(5,1),
  avg_pace NUMERIC(5,1),

  -- Foul tendencies
  avg_personal_fouls NUMERIC(4,1),
  avg_free_throw_attempts NUMERIC(4,1),

  -- Recency
  last_updated TIMESTAMP,
  rolling_window_days INT64  -- e.g., last 30, 60, 90 days
)
```

### Phase 2: Integrate Into Predictions

Update `upcoming_team_game_context` or `daily_game_context` to include:
- `chief_referee_over_pct`
- `crew_avg_total_points`
- `crew_points_vs_avg`

### Phase 3: Add to ML Features

Add referee tendency features to Phase 4 precompute for ML models.

## Effort Estimate

- Phase 1: 4-6 hours (processor + table)
- Phase 2: 2-3 hours (integration)
- Phase 3: 1-2 hours (ML features)

**Total: ~1 day of work**

## Success Metrics

- Referee features show correlation with prediction accuracy
- Model accuracy improves 0.5-1% on games with extreme referee crews
