# Database Schema Changes

**Last Updated:** 2026-01-22

This document details the database schema changes required for the auto-resolution pipeline.

## New Tables

### 1. `nba_processing.registry_affected_games`

**Purpose:** Track ALL games affected by unresolved players (not just 10 examples).

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.registry_affected_games` (
  -- Primary identification
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,

  -- Game context
  game_date DATE NOT NULL,
  season STRING,  -- "2025-26"
  team_abbr STRING,
  source_table STRING,  -- e.g., "bdl_player_boxscores"

  -- Tracking timestamps
  first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  reprocessed_at TIMESTAMP,
  reprocess_result STRING,  -- "success", "failed", "skipped"

  -- Metadata
  had_prop_lines BOOL DEFAULT FALSE,
  prop_line_sources ARRAY<STRING>,  -- ["odds_api", "bettingpros"]

  PRIMARY KEY (player_lookup, game_id) NOT ENFORCED
)
PARTITION BY DATE(game_date)
CLUSTER BY player_lookup, team_abbr
OPTIONS(
  description = "Tracks all games affected by unresolved player names for comprehensive reprocessing"
);
```

**Indexes (via clustering):**
- `player_lookup` - Fast lookup of all games for a player
- `team_abbr` - Filter by team for validation

---

### 2. `nba_reference.resolution_audit_log`

**Purpose:** Audit trail of all resolution decisions for debugging and analysis.

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.resolution_audit_log` (
  -- Identification
  log_id STRING DEFAULT GENERATE_UUID(),
  player_lookup STRING NOT NULL,

  -- Resolution details
  resolution_method STRING NOT NULL,  -- "fuzzy_auto", "ai_resolution", "manual"
  resolution_decision STRING NOT NULL,  -- "MATCH", "NEW_PLAYER", "DATA_ERROR", "NEEDS_REVIEW"
  confidence_score FLOAT64,

  -- Mapping details (for MATCH)
  canonical_lookup STRING,
  universal_player_id STRING,

  -- Context
  team_abbr STRING,
  season STRING,
  similar_names ARRAY<STRUCT<name STRING, score FLOAT64>>,

  -- AI details (if AI resolution)
  ai_model STRING,  -- "claude-3-haiku"
  ai_prompt_hash STRING,
  ai_response_hash STRING,
  ai_cost_usd FLOAT64,

  -- Timestamps
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  created_by STRING,  -- "auto_pipeline", "manual_review", "batch_job"

  PRIMARY KEY (log_id) NOT ENFORCED
)
PARTITION BY DATE(created_at)
OPTIONS(
  description = "Audit log of all player name resolution decisions"
);
```

---

### 3. `nba_reference.player_name_history`

**Purpose:** Track player name changes over time (legal changes, preferred names).

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.player_name_history` (
  -- Identification
  universal_player_id STRING NOT NULL,
  lookup_name STRING NOT NULL,

  -- Validity period
  valid_from DATE NOT NULL,
  valid_to DATE,  -- NULL for current name

  -- Change details
  change_type STRING NOT NULL,  -- "legal_change", "preferred_name", "nickname", "correction"
  change_source STRING,  -- "nba_official", "player_request", "data_correction"
  previous_lookup STRING,  -- Name being replaced

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  created_by STRING,
  notes STRING,

  PRIMARY KEY (universal_player_id, lookup_name, valid_from) NOT ENFORCED
)
OPTIONS(
  description = "Historical record of player name changes over time"
);
```

---

## Schema Modifications

### 1. `nba_reference.unresolved_player_names`

**Add columns:**

```sql
ALTER TABLE `nba-props-platform.nba_reference.unresolved_player_names`
ADD COLUMN IF NOT EXISTS resolution_method STRING,
ADD COLUMN IF NOT EXISTS resolution_confidence FLOAT64,
ADD COLUMN IF NOT EXISTS resolved_to_id STRING,
ADD COLUMN IF NOT EXISTS ai_resolution_id STRING,
ADD COLUMN IF NOT EXISTS reprocessing_status STRING DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS reprocessed_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS games_reprocessed INT64 DEFAULT 0;
```

**New status values:**
- `pending` - Awaiting resolution
- `resolved` - Successfully resolved (alias or new entry created)
- `needs_review` - AI confidence too low, needs human review
- `invalid` - Determined to be data error/typo
- `ignored` - Deliberately ignored (G-League, etc.)

**New resolution_method values:**
- `fuzzy_auto` - High confidence fuzzy match (≥95%)
- `ai_resolution` - AI resolution (≥80% confidence)
- `manual` - Human review
- `batch_import` - Bulk import/backfill

---

### 2. `nba_reference.player_aliases`

**Add columns for context-aware aliasing:**

```sql
ALTER TABLE `nba-props-platform.nba_reference.player_aliases`
ADD COLUMN IF NOT EXISTS valid_team_abbr STRING,
ADD COLUMN IF NOT EXISTS valid_season STRING,
ADD COLUMN IF NOT EXISTS valid_from DATE,
ADD COLUMN IF NOT EXISTS valid_to DATE,
ADD COLUMN IF NOT EXISTS alias_type STRING DEFAULT 'permanent',
ADD COLUMN IF NOT EXISTS confidence_score FLOAT64,
ADD COLUMN IF NOT EXISTS created_by STRING;
```

**New alias_type values:**
- `permanent` - Always applies (default)
- `team_specific` - Only when player is on specific team
- `season_specific` - Only for specific season
- `historical` - Only for games before a certain date

**Updated lookup logic:**

```sql
-- New alias resolution query
SELECT canonical_lookup, universal_player_id
FROM nba_reference.player_aliases a
JOIN nba_players_registry r ON a.canonical_lookup = r.player_lookup
WHERE a.alias_lookup = @lookup
  AND a.is_active = TRUE
  AND (a.valid_team_abbr IS NULL OR a.valid_team_abbr = @team_abbr)
  AND (a.valid_season IS NULL OR a.valid_season = @season)
  AND (a.valid_from IS NULL OR @game_date >= a.valid_from)
  AND (a.valid_to IS NULL OR @game_date <= a.valid_to)
ORDER BY
  -- Prefer most specific matches
  CASE WHEN a.valid_team_abbr IS NOT NULL THEN 0 ELSE 1 END,
  CASE WHEN a.valid_season IS NOT NULL THEN 0 ELSE 1 END,
  a.created_at DESC
LIMIT 1;
```

---

### 3. `nba_reference.ai_resolution_cache`

**Add columns for better tracking:**

```sql
ALTER TABLE `nba-props-platform.nba_reference.ai_resolution_cache`
ADD COLUMN IF NOT EXISTS usage_count INT64 DEFAULT 1,
ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS invalidation_reason STRING;
```

**Cache invalidation rules:**
- DATA_ERROR decisions: Never expire (permanent skip)
- MATCH decisions: Expire after 90 days or if player changes teams
- NEW_PLAYER decisions: Expire after 30 days (verify player exists)

---

## Migration Scripts

### Migration 1: Create New Tables

```sql
-- Run once to create new tables
-- File: migrations/2026_01_22_01_create_registry_tables.sql

-- 1. registry_affected_games
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.registry_affected_games` (
  ...
);

-- 2. resolution_audit_log
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.resolution_audit_log` (
  ...
);

-- 3. player_name_history
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.player_name_history` (
  ...
);
```

### Migration 2: Alter Existing Tables

```sql
-- Run once to add columns to existing tables
-- File: migrations/2026_01_22_02_alter_registry_tables.sql

-- 1. unresolved_player_names
ALTER TABLE `nba-props-platform.nba_reference.unresolved_player_names`
ADD COLUMN IF NOT EXISTS resolution_method STRING,
...;

-- 2. player_aliases
ALTER TABLE `nba-props-platform.nba_reference.player_aliases`
ADD COLUMN IF NOT EXISTS valid_team_abbr STRING,
...;

-- 3. ai_resolution_cache
ALTER TABLE `nba-props-platform.nba_reference.ai_resolution_cache`
ADD COLUMN IF NOT EXISTS usage_count INT64 DEFAULT 1,
...;
```

### Migration 3: Backfill Affected Games

```sql
-- Backfill registry_affected_games from existing data
-- File: migrations/2026_01_22_03_backfill_affected_games.sql

INSERT INTO `nba-props-platform.nba_processing.registry_affected_games`
(player_lookup, game_id, game_date, season, team_abbr, source_table, first_seen_at)

SELECT
  rf.player_lookup,
  rf.game_id,
  rf.game_date,
  rf.season,
  rf.team_abbr,
  rf.source_table,
  rf.created_at as first_seen_at
FROM `nba-props-platform.nba_processing.registry_failures` rf
WHERE rf.player_lookup IN (
  SELECT normalized_lookup
  FROM `nba-props-platform.nba_reference.unresolved_player_names`
  WHERE status = 'pending'
)
AND NOT EXISTS (
  SELECT 1 FROM `nba-props-platform.nba_processing.registry_affected_games` ag
  WHERE ag.player_lookup = rf.player_lookup AND ag.game_id = rf.game_id
);
```

---

## Data Flow Diagram

```
                                    ┌─────────────────────┐
                                    │   Raw Data Sources  │
                                    │  (scrapers)         │
                                    └──────────┬──────────┘
                                               │
                                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           RESOLUTION FLOW                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────┐     ┌─────────────────────┐                         │
│  │ nba_players_registry│     │   player_aliases    │                         │
│  │  (master list)      │◄────│ (name mappings)     │                         │
│  └─────────────────────┘     └─────────────────────┘                         │
│           │                           │                                       │
│           │  LOOKUP                   │  LOOKUP                              │
│           ▼                           ▼                                       │
│  ┌────────────────────────────────────────────────────┐                      │
│  │              PlayerResolver.resolve()               │                      │
│  │  1. Direct registry lookup                          │                      │
│  │  2. Alias resolution                                │                      │
│  │  3. AI cache lookup                                 │                      │
│  └────────────────────────────────────────────────────┘                      │
│                          │                                                    │
│            ┌─────────────┴─────────────┐                                     │
│            │                           │                                      │
│         FOUND                      NOT FOUND                                  │
│            │                           │                                      │
│            ▼                           ▼                                      │
│  ┌─────────────────┐       ┌─────────────────────────┐                       │
│  │ Return player_id│       │ Log to:                 │                       │
│  │ Continue process│       │ • unresolved_player_names│                       │
│  └─────────────────┘       │ • registry_affected_games│                       │
│                            │ • registry_failures      │                       │
│                            └───────────┬─────────────┘                       │
│                                        │                                      │
└────────────────────────────────────────│──────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         NIGHTLY AUTO-RESOLUTION                               │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────┐                                                     │
│  │ unresolved_player_  │                                                     │
│  │ names (pending)     │                                                     │
│  └─────────┬───────────┘                                                     │
│            │                                                                  │
│            ▼                                                                  │
│  ┌─────────────────────────────────────────────────────┐                     │
│  │          AutoResolutionPipeline                      │                     │
│  │  Stage 1: Fuzzy (≥95%) → player_aliases              │                     │
│  │  Stage 2: AI (≥80%) → ai_resolution_cache            │                     │
│  │  Stage 3: Low conf → mark needs_review               │                     │
│  └─────────────────────────────────────────────────────┘                     │
│            │                                                                  │
│            ▼                                                                  │
│  ┌─────────────────────┐                                                     │
│  │ resolution_audit_log│                                                     │
│  │ (all decisions)     │                                                     │
│  └─────────────────────┘                                                     │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AUTO-REPROCESSING                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────┐     ┌─────────────────────┐                         │
│  │ registry_affected_  │────►│ ReprocessingOrch.   │                         │
│  │ games (unprocessed) │     │ process_single_game │                         │
│  └─────────────────────┘     └─────────┬───────────┘                         │
│                                        │                                      │
│                                        ▼                                      │
│                              ┌─────────────────────┐                         │
│                              │ player_game_summary │                         │
│                              │ (updated records)   │                         │
│                              └─────────┬───────────┘                         │
│                                        │                                      │
│                                        ▼                                      │
│                              ┌─────────────────────┐                         │
│                              │ Phase 4/5 Cascade   │                         │
│                              │ (predictions)       │                         │
│                              └─────────────────────┘                         │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```
