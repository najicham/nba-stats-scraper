# Data Completeness Strategy Design Prompt

**Created:** 2025-11-26
**Purpose:** Get architectural guidance on handling missing/incomplete data across the NBA analytics pipeline

---

## Context: The System

We have an NBA stats platform that:
1. **Scrapes** data from multiple sources (NBA.com, ESPN, BallDontLie API)
2. **Stores raw data** in GCS (Google Cloud Storage) as JSON files
3. **Processes to BigQuery** in phases:
   - Phase 2: Raw tables (one per scraper)
   - Phase 3: Analytics tables (aggregated game/team/player stats)
   - Phase 4: Precompute/Features for ML
   - Phase 5: Player predictions

### Data Sources & Overlap

| Data Type | NBA.com | ESPN | BDL | Gamebook PDF |
|-----------|---------|------|-----|--------------|
| Team boxscore | ✅ Primary | ✅ Backup | ✅ Backup | ✅ (in PDF) |
| Player boxscore | ✅ Primary | ✅ Backup | ✅ Backup | ✅ (in PDF) |
| Play-by-play | ✅ Primary | ✅ Backup | ❌ | ❌ |
| Betting lines | ❌ | ❌ | ❌ | ❌ (separate source) |
| Injury reports | ✅ | ✅ | ❌ | ❌ |

### Current Data Flow

```
Scrapers → GCS (JSON) → Phase 2 Processor → BigQuery Raw Tables
                                                    ↓
                                          Phase 3 Analytics
                                                    ↓
                                          Phase 4 Features
                                                    ↓
                                          Phase 5 Predictions
```

---

## The Problem We Encountered

### Specific Case: Missing Play-In Tournament Games

During a team boxscore backfill (5,299 games), 6 games failed:
- All are 2024-25 Play-In Tournament games (April 2025)
- NBA.com's `boxscoretraditionalv2` API returns empty data for these game IDs
- No alternative sources (ESPN, BDL) have data for these dates either
- The games exist on the NBA.com website, but not via the stats API

### The Bigger Question

This revealed we have no systematic approach for:
1. Detecting when data is missing
2. Trying alternative sources
3. Reconstructing data from other available data
4. Flagging gaps for attention
5. Continuing with degraded quality when appropriate
6. Reporting data quality in final predictions

---

## Types of Missing Data

### Game-Level Gaps

| Scenario | Example | Possible Solutions |
|----------|---------|-------------------|
| Primary source missing | NBA.com team boxscore empty | Try ESPN, BDL |
| All sources missing | No one has Play-In data | Alert, skip game |
| Reconstructible | Team totals missing | Sum from player boxscores |
| Temporary failure | API timeout | Retry with backoff |

### Player-Level Gaps

| Scenario | Example | Possible Solutions |
|----------|---------|-------------------|
| Missing player in game | 9/10 players have boxscores | Flag partial, continue |
| Player history gap | Missing games in Feb 2024 | Backfill or interpolate |
| New player | Just traded, no history | Use league averages |
| DNP player | Didn't play but on roster | Handle as expected |

### Field-Level Gaps

| Scenario | Example | Possible Solutions |
|----------|---------|-------------------|
| Optional field missing | Advanced stats not available | Compute or omit |
| Required field missing | Points not available | Cannot proceed |
| Inconsistent fields | ESPN has different fields than NBA.com | Normalize or flag |

---

## Requirements for a Solution

### 1. Detection
- Know when data is missing (not just failed to process)
- Distinguish between "not available" vs "not yet scraped" vs "scraper failed"
- Track at game, player, and field levels

### 2. Fallback Logic
- Automated attempts to get data from alternative sources
- Reconstruction from other data when possible (e.g., sum player stats for team totals)
- Priority order for sources (which to trust most)

### 3. Alerting
- Immediate alerts for critical missing data
- Daily digest of data gaps
- Clear visibility into what's missing and why

### 4. Graceful Degradation
- Continue processing with partial data when acceptable
- Quality scores that flow through the pipeline
- Final predictions report their data quality

### 5. Tracking & Reporting
- Historical record of what data was available when
- Audit trail of fallbacks used
- Quality metrics over time

---

## Design Questions to Answer

### Architecture Level

1. **Centralized vs Distributed?**
   - One "data completeness service" that all processors query?
   - Or each processor handles its own completeness checks?
   - Or metadata tables that processors read/write independently?

2. **Where should fallback logic live?**
   - In the scraper layer (try multiple sources during scrape)?
   - In Phase 2 processors (check other raw tables)?
   - In Phase 3 analytics (query multiple Phase 2 tables)?
   - In a dedicated "data completeness" processor?

3. **How to handle cross-entity relationships?**
   - A game has teams, teams have players, players have stats
   - If team data is missing, does that mean all player data is suspect?
   - How do we track completeness at each level?

### Data Model Level

4. **What schema for tracking completeness?**
   - Game-level table? Player-level table? Both?
   - What fields are needed?
   - How to handle the hierarchy (game → team → player → stat)?

5. **How to represent quality scores?**
   - Simple percentage (85% complete)?
   - Detailed field-by-field status?
   - Source confidence weighting?

### Operational Level

6. **When should the system stop vs continue?**
   - What's "critical" vs "nice to have"?
   - Should this be configurable per data type?
   - How does this affect predictions?

7. **How to handle backfills?**
   - Retroactively updating completeness status?
   - Re-running processors after gaps are filled?
   - Versioning predictions based on data available at time?

---

## Existing Patterns in Our Codebase

We already have some relevant patterns:

1. **SmartSkipMixin** - Skips processing when no games scheduled
2. **CircuitBreakerMixin** - Prevents repeated failures
3. **Multi-source queries** - Some processors already query ESPN as fallback
4. **Quality flags** - Some tables have `data_quality` columns

These could be extended/unified into a comprehensive solution.

---

## Possible Approaches

### Approach A: Centralized Completeness Table

```sql
-- Game-level completeness
CREATE TABLE nba_reference.game_data_completeness (
  game_id STRING,
  game_date DATE,

  -- Source status
  nbac_team_boxscore STRING,  -- 'available', 'missing', 'reconstructed', 'partial'
  nbac_player_boxscore STRING,
  espn_boxscore STRING,
  play_by_play STRING,

  -- Computed scores
  overall_quality FLOAT64,

  -- Flags
  requires_attention BOOL,

  last_updated TIMESTAMP
);

-- Player-level completeness
CREATE TABLE nba_reference.player_data_completeness (
  player_id STRING,
  game_id STRING,
  game_date DATE,

  -- What we have for this player in this game
  boxscore_status STRING,
  shot_chart_status STRING,

  -- Quality
  completeness_pct FLOAT64,
  missing_fields ARRAY<STRING>,

  last_updated TIMESTAMP
);
```

**Pros:** Single source of truth, easy to query
**Cons:** Another table to maintain, could get out of sync

### Approach B: Metadata on Existing Tables

Add completeness columns to existing tables:

```sql
-- In each analytics table
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN data_quality FLOAT64,
ADD COLUMN data_sources ARRAY<STRING>,
ADD COLUMN missing_fields ARRAY<STRING>,
ADD COLUMN reconstruction_notes STRING;
```

**Pros:** Data and quality metadata together
**Cons:** Duplicated pattern across tables

### Approach C: Event-Driven Completeness Service

A dedicated service that:
1. Listens to all scraper completion events
2. Maintains a real-time view of what data exists
3. Exposes an API: `GET /completeness/game/{game_id}`
4. Triggers alerts when gaps detected

**Pros:** Real-time, decoupled
**Cons:** More infrastructure

### Approach D: Hybrid

- Centralized completeness table for visibility/querying
- Metadata columns on analytics tables for downstream use
- Processors update both as they run

---

## What We Need From This Discussion

1. **Recommended architecture** - Which approach (or combination)?
2. **Data model design** - What tables/columns specifically?
3. **Decision framework** - When to stop vs continue vs alert?
4. **Implementation priority** - What to build first?
5. **Edge cases** - What scenarios are we missing?

---

## Constraints

- We use BigQuery (SQL, no stored procedures)
- Processors run on Cloud Run (stateless)
- Events flow via Pub/Sub
- We want minimal new infrastructure
- Solution should scale to 1000+ games/season

---

## Example Scenarios to Consider

### Scenario 1: New Season Starts
- First game of season, no historical data for new players
- Should predictions run? With what quality score?

### Scenario 2: Mid-Season Trade
- Player traded, has history with old team
- First game with new team, teammates have no shared history
- How to handle similarity calculations?

### Scenario 3: API Outage
- NBA.com down for 2 days
- Have ESPN data but not NBA.com
- Should we process with ESPN only? Flag it?

### Scenario 4: Partial Game Data
- Team boxscore available
- Only 8/10 players have individual boxscores
- Team totals don't match sum of players
- Which do we trust?

### Scenario 5: Historical Backfill
- Found a bug, need to reprocess 2023 data
- Some games now have better data than before
- How to track "data version" in predictions?
