-- Basketball Reference roster tables
-- Implements MERGE_UPDATE strategy with first_seen_date tracking

-- Current rosters with tracking
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.br_rosters_current` (
  -- Season and team identity
  season_year INT64 NOT NULL,          -- 2023 (for 2023-24 season)
  season_display STRING NOT NULL,      -- "2023-24"
  team_abbrev STRING NOT NULL,         -- "LAL"
  
  -- Player identity (matching scraper output)
  player_full_name STRING NOT NULL,    -- "LeBron James"
  player_last_name STRING NOT NULL,    -- "James"
  player_normalized STRING NOT NULL,   -- "lebron james" (from source)
  player_lookup STRING NOT NULL,       -- "lebronjames" (no spaces/punctuation)
  
  -- Player details (kept as strings matching scraper)
  position STRING,                     -- "F"
  jersey_number STRING,                -- "23"
  height STRING,                       -- "6-9"
  weight STRING,                       -- "250"
  birth_date STRING,                   -- "December 30, 1984"
  college STRING,                      -- "None"
  
  -- Parsed fields
  experience_years INT64,              -- 20 (parsed from "20 years")
  
  -- Tracking fields
  first_seen_date DATE NOT NULL,       -- When player first appeared on roster
  last_scraped_date DATE,              -- When we last confirmed
  
  -- Metadata
  source_file_path STRING,             -- GCS path of source file

  -- Smart Idempotency (Pattern #14)
  data_hash STRING,                    -- SHA256 hash of meaningful fields: season_year, team_abbrev, player_lookup, jersey_number, position

  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY RANGE_BUCKET(season_year, GENERATE_ARRAY(2020, 2030, 1))
CLUSTER BY team_abbrev, player_lookup;


-- Historical roster changes (for tracking)
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.br_roster_changes` (
  change_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  team_abbrev STRING NOT NULL,
  player_full_name STRING NOT NULL,
  change_type STRING NOT NULL,         -- 'added', 'removed', 'modified'
  change_details JSON,                 -- Flexible field for change details
  
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY change_date
CLUSTER BY team_abbrev, season_year;