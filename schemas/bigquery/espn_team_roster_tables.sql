-- File: schemas/bigquery/espn_team_roster_tables.sql
-- Description: BigQuery table schemas for ESPN team roster data
-- ESPN Team Roster Tables
-- Description: Backup data source for player information from ESPN API

CREATE TABLE `nba-props-platform.nba_raw.espn_team_rosters` (
  -- Core identifiers
  roster_date          DATE         NOT NULL,   -- Date roster was captured
  scrape_hour          INT64        NOT NULL,   -- Hour scraped (8, 14, 20 for future flexibility)
  season_year          INT64        NOT NULL,   -- Starting year (2024 for 2024-25)
  team_abbr            STRING       NOT NULL,   -- Three-letter code (LAL, BOS, etc.)
  team_display_name    STRING,                  -- "Los Angeles Lakers"
  
  -- Player identification
  espn_player_id       INT64        NOT NULL,   -- ESPN unique player ID
  player_full_name     STRING       NOT NULL,   -- "LeBron James"
  player_lookup        STRING       NOT NULL,   -- Normalized: "lebronjames"
  
  -- Player details
  jersey_number        STRING,                  -- "6" (as string for flexibility)
  position             STRING,                  -- "SF" or "Small Forward"
  position_abbr        STRING,                  -- "SF"
  height               STRING,                  -- "6' 9\"" (ESPN format)
  weight               STRING,                  -- "250 lbs" (ESPN format)
  age                  INT64,                   -- Current age
  
  -- Experience and background
  experience_years     INT64,                   -- Years in NBA
  college              STRING,                  -- "None" for international
  birth_place          STRING,                  -- "Akron, OH"
  birth_date           DATE,                    -- Birth date if available
  
  -- Status and contract
  status               STRING,                  -- "Active", "Inactive", "Injured"
  roster_status        STRING,                  -- "Active Roster", "Two-Way", etc.
  salary               STRING,                  -- Contract info if available
  
  -- Processing metadata
  espn_roster_url      STRING,                  -- Source URL if available
  source_file_path     STRING       NOT NULL,   -- GCS path
  created_at           TIMESTAMP    NOT NULL,   -- When record first created (UTC)
  processed_at         TIMESTAMP    NOT NULL,   -- When record last updated (UTC)
  
  -- Table constraints and optimizations
  PRIMARY KEY (roster_date, scrape_hour, team_abbr, espn_player_id) NOT ENFORCED
)
PARTITION BY roster_date
CLUSTER BY team_abbr, player_lookup
OPTIONS (
  description = "ESPN team rosters - backup data source for player information",
  partition_expiration_days = 1095,  -- 3 years retention
  require_partition_filter = true
);

-- Common query patterns this schema supports:
-- 1. Current roster: WHERE roster_date = CURRENT_DATE() AND scrape_hour = 8 AND team_abbr = 'LAL'
-- 2. Player search: WHERE player_lookup = 'lebronjames' AND roster_date = CURRENT_DATE()
-- 3. Multiple daily snapshots: WHERE roster_date = '2025-09-01' ORDER BY scrape_hour
-- 4. Backup player source: When NBA.com/BDL unavailable
-- 5. Cross-reference: JOIN with other player tables on player_lookup

-- Processing Strategy:
-- APPEND_ALWAYS with conditional MERGE_UPDATE:
-- - Same roster_date + scrape_hour = MERGE_UPDATE (replace existing)
-- - Different scrape_hour same day = APPEND (new snapshot)
-- - Future-proofs for multiple daily scrapes while keeping current single scrape simple