-- Create source_blocked_resources table for tracking data unavailable from source
--
-- Purpose: Track specific resources (games, players, etc.) that are unavailable
--          from their source systems (not infrastructure failures)
--
-- Usage: Allows validation to distinguish between:
--   1. Infrastructure failures (scrapers broken)
--   2. Source blocks (specific resource blocked by source)
--   3. Source unavailable (data doesn't exist anywhere)

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.source_blocked_resources` (
  -- Resource Identification
  resource_id STRING NOT NULL OPTIONS(description="ID of the blocked resource (e.g., game_id, player_id)"),
  resource_type STRING NOT NULL OPTIONS(description="Type of resource: play_by_play, boxscore, player_stats, etc."),
  game_date DATE OPTIONS(description="Associated game date for partitioning (nullable for non-game resources)"),

  -- Source Information
  source_system STRING NOT NULL OPTIONS(description="Source system that blocked it: nba_com_cdn, bdb, bdl, etc."),
  source_url STRING OPTIONS(description="Full URL that returned error"),

  -- Block Status
  http_status_code INT64 OPTIONS(description="HTTP status code: 403 (forbidden), 404 (not found), 410 (gone)"),
  block_type STRING NOT NULL OPTIONS(description="Block classification: access_denied, not_found, removed, server_error"),

  -- Verification Tracking
  first_detected_at TIMESTAMP NOT NULL OPTIONS(description="When block was first detected"),
  last_verified_at TIMESTAMP NOT NULL OPTIONS(description="Last time we checked (for periodic re-checks)"),
  verification_count INT64 DEFAULT 1 OPTIONS(description="How many times we've verified it's blocked"),

  -- Alternative Source Tracking
  available_from_alt_source BOOL OPTIONS(description="Is this available from another source?"),
  alt_source_system STRING OPTIONS(description="Which alternative source has it (if any)"),
  alt_source_verified_at TIMESTAMP OPTIONS(description="When we verified alt source has it"),

  -- Metadata
  notes STRING OPTIONS(description="Human-readable explanation or context"),
  created_by STRING OPTIONS(description="Source of record: scraper, manual, backfill"),

  -- Resolution Tracking
  is_resolved BOOL DEFAULT FALSE OPTIONS(description="Set to TRUE if source block lifted"),
  resolved_at TIMESTAMP OPTIONS(description="When block was lifted"),
  resolution_notes STRING OPTIONS(description="How it was resolved")
)
PARTITION BY game_date
CLUSTER BY resource_type, source_system, block_type
OPTIONS(
  description="Tracks resources unavailable from source (not infrastructure failures)",
  labels=[("purpose", "data_quality"), ("category", "observability")]
);
