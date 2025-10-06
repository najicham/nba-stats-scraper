-- File: schemas/bigquery/espn_team_rosters.sql
-- ESPN Team Rosters - Enhanced with source_file_date for gap detection
-- Compatible with both HTML scraper (espn_roster.py) and API scraper (espn_roster_api.py)

CREATE TABLE `nba-props-platform.nba_raw.espn_team_rosters` (
  -- Core identifiers
  roster_date          DATE         NOT NULL,   -- Date roster represents
  scrape_hour          INT64        NOT NULL,   -- Hour scraped (8, 14, 20 for future flexibility)
  season_year          INT64        NOT NULL,   -- Starting year (2024 for 2024-25 season)
  team_abbr            STRING       NOT NULL,   -- Three-letter code (LAL, BOS, etc.)
  team_display_name    STRING,                  -- "Los Angeles Lakers" (may be NULL for HTML scraper)
  
  -- Player identification
  espn_player_id       INT64        NOT NULL,   -- ESPN unique player ID
  player_full_name     STRING       NOT NULL,   -- "LeBron James"
  player_lookup        STRING       NOT NULL,   -- Normalized for matching: "lebronjames"
  
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
  source_file_path     STRING       NOT NULL,   -- GCS path: espn/team-rosters/{date}/{timestamp}.json
  source_file_date     DATE,                    -- Date extracted from file path (for gap detection)
  
  -- Processing metadata
  created_at           TIMESTAMP    NOT NULL,   -- When record first created (UTC)
  processed_at         TIMESTAMP    NOT NULL,   -- When record last processed/updated (UTC)
  
  -- Table constraints and optimizations
  PRIMARY KEY (roster_date, scrape_hour, team_abbr, espn_player_id) NOT ENFORCED
)
PARTITION BY roster_date
CLUSTER BY team_abbr, player_lookup
OPTIONS (
  description = "ESPN team rosters - backup data source for player reference validation. Supports both HTML and API scrapers.",
  require_partition_filter = true
  -- partition_expiration_days = 1095,  -- 3 years retention
);

-- INDEXES (implicit via clustering)
-- Primary lookup: team_abbr, player_lookup (clustered for roster registry queries)
-- Time-based queries: roster_date (partitioned)

-- NOTES:
-- 1. source_file_date is CRITICAL for processing gap detection monitoring
-- 2. HTML scraper populates: name, number, position, height, weight, playerId
-- 3. API scraper populates: all fields including age, college, birth info, injuries
-- 4. Processor must handle both data structures (see processor documentation)
-- 5. MERGE strategy deletes + inserts on (roster_date, scrape_hour, team_abbr)
-- 6. Registry processor validates against NBA.com canonical player set