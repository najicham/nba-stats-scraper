-- File: schemas/bigquery/espn_team_rosters.sql
-- ESPN Team Rosters - Enhanced with Player Registry integration
-- Compatible with both HTML scraper (espn_roster.py) and API scraper (espn_roster_api.py)
-- Updated: 2025-10-18 - Added universal_player_id for cross-source player matching

CREATE TABLE `nba-props-platform.nba_raw.espn_team_rosters` (
  -- Core identifiers
  roster_date          DATE         NOT NULL,   -- Date roster represents
  scrape_hour          INT64        NOT NULL,   -- Hour scraped (8, 14, 20 for future flexibility)
  season_year          INT64        NOT NULL,   -- Starting year (2024 for 2024-25 season)
  team_abbr            STRING       NOT NULL,   -- Three-letter code (LAL, BOS, etc.)
  team_display_name    STRING,                  -- "Los Angeles Lakers" (may be NULL for HTML scraper)
  
  -- Player identification (with registry integration)
  espn_player_id       INT64        NOT NULL,   -- ESPN unique player ID
  player_full_name     STRING       NOT NULL,   -- "LeBron James"
  player_lookup        STRING       NOT NULL,   -- Normalized for matching: "lebronjames"
  universal_player_id  STRING,                  -- NEW: Cross-source player ID from registry (e.g., "lebronjames_001")
                                                 -- NULL if player not yet in registry (added to unresolved queue)
                                                 -- Links to nba_reference.nba_players_registry.universal_player_id
  
  -- Player details (availability varies by scraper type)
  jersey_number        STRING,                  -- "6" (string for "00", "0", multi-digit)
  position             STRING,                  -- "SF" or "Small Forward" (varies by source)
  position_abbr        STRING,                  -- "SF" (abbreviated form)
  height               STRING,                  -- "6' 9\"" (ESPN formatted string)
  weight               STRING,                  -- "250 lbs" (ESPN formatted string)
  age                  INT64,                   -- Current age (API only)
  
  -- Experience and background (API scraper only - NULL for HTML scraper)
  experience_years     INT64,                   -- Years in NBA
  college              STRING,                  -- College name or "None" for international
  birth_place          STRING,                  -- "Akron, OH"
  birth_date           DATE,                    -- Birth date
  
  -- Status and contract (limited availability)
  status               STRING,                  -- "Active", "Inactive", "Injured" (API only)
  roster_status        STRING,                  -- "Active Roster", "Two-Way", etc.
  salary               STRING,                  -- Contract info (rarely available)
  
  -- Source and lineage tracking
  espn_roster_url      STRING,                  -- Source URL for verification
  source_file_path     STRING       NOT NULL,   -- GCS path: espn/rosters/{date}/team_{TEAM}/{timestamp}.json
  source_file_date     DATE,                    -- Date extracted from file path (for gap detection)
  
  -- Processing metadata
  created_at           TIMESTAMP    NOT NULL,   -- When record first created (UTC)

  -- Smart Idempotency (Pattern #14)
  data_hash            STRING,                  -- SHA256 hash of meaningful fields: roster_date, team_abbr, player_lookup, position, jersey_number

  processed_at         TIMESTAMP    NOT NULL,   -- When record last processed/updated (UTC)

  -- Table constraints and optimizations
  PRIMARY KEY (roster_date, scrape_hour, team_abbr, espn_player_id) NOT ENFORCED
)
PARTITION BY roster_date
CLUSTER BY team_abbr, player_lookup
OPTIONS (
  description = "ESPN team rosters with Player Registry integration - backup data source for player reference validation. Supports both HTML and API scrapers.",
  require_partition_filter = true
  -- partition_expiration_days = 1095,  -- 3 years retention
);

-- INDEXES (implicit via clustering)
-- Primary lookup: team_abbr, player_lookup (clustered for roster registry queries)
-- Time-based queries: roster_date (partitioned)
-- Cross-source joins: universal_player_id (links to nba_players_registry)

-- PLAYER REGISTRY INTEGRATION:
-- =============================================================================
-- The processor uses RegistryReader (lenient consumer pattern) to resolve players:
-- 
-- 1. For each player, attempts to resolve universal_player_id from registry
-- 2. If found: universal_player_id is populated
-- 3. If NOT found: universal_player_id is NULL, player added to unresolved queue
-- 4. Unresolved players logged to: nba_reference.unresolved_player_names
-- 5. Manual review creates aliases or new registry entries to resolve
-- 6. Re-running processor backfills universal_player_id after aliases created
--
-- Resolution Rate Target: >95% (typical: 85-90% first run, 95%+ after aliases)
-- =============================================================================

-- DATA QUALITY NOTES:
-- 1. source_file_date is CRITICAL for processing gap detection monitoring
-- 2. HTML scraper populates: name, number, position, height, weight, playerId
-- 3. API scraper populates: all fields including age, college, birth info, injuries
-- 4. Processor must handle both data structures (see processor documentation)
-- 5. MERGE strategy deletes + inserts on (roster_date, scrape_hour, team_abbr)
-- 6. Registry processor validates against NBA.com canonical player set
-- 7. Most unresolved players are suffix variations (Jr., Sr., II, III)

-- USAGE EXAMPLES:
-- =============================================================================
-- Check resolution rate:
SELECT 
  roster_date,
  COUNT(*) as total_players,
  COUNT(universal_player_id) as resolved,
  ROUND(COUNT(universal_player_id) / COUNT(*) * 100, 1) as resolution_pct
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE roster_date >= CURRENT_DATE() - 7
GROUP BY roster_date
ORDER BY roster_date DESC;

-- Find unresolved players:
SELECT 
  roster_date,
  team_abbr,
  player_full_name,
  player_lookup,
  jersey_number,
  position
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE universal_player_id IS NULL
  AND roster_date = CURRENT_DATE()
ORDER BY team_abbr, player_full_name;

-- Join with registry for enriched data:
SELECT 
  r.roster_date,
  r.team_abbr,
  r.player_full_name,
  r.espn_player_id,
  reg.universal_player_id,
  reg.nba_player_id,
  reg.nba_canonical_name,
  reg.jersey_number as registry_jersey
FROM `nba-props-platform.nba_raw.espn_team_rosters` r
LEFT JOIN `nba-props-platform.nba_reference.nba_players_registry` reg
  ON r.universal_player_id = reg.universal_player_id
WHERE r.roster_date = CURRENT_DATE()
  AND r.team_abbr = 'LAL'
ORDER BY r.jersey_number;
-- =============================================================================