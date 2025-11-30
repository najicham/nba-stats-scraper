-- ============================================================================
-- Player Name Mappings Table Schema
-- ============================================================================
-- Dataset: nba_reference
-- Table: player_name_mappings
-- Auto-generated from deployed BigQuery table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.player_name_mappings` (
  nba_name STRING NOT NULL,
  bdl_name STRING NOT NULL,
  mapping_type STRING NOT NULL,
  confidence FLOAT NOT NULL,
  created_date DATE NOT NULL,
  last_verified DATE NOT NULL,
  games_count INTEGER NOT NULL,
  is_active BOOLEAN NOT NULL,
  created_by STRING,
  notes STRING,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY DAY(created_date)
CLUSTER BY mapping_type, is_active;
