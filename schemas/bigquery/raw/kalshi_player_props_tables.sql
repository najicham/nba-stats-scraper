-- Kalshi Player Props Table
-- Stores NBA player prop betting data from Kalshi exchange
-- Created: 2026-02-01

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.kalshi_player_props` (
  -- Game and event identifiers
  game_date DATE NOT NULL,
  series_ticker STRING NOT NULL,
  event_ticker STRING NOT NULL,
  market_ticker STRING NOT NULL,
  
  -- Prop details
  prop_type STRING NOT NULL,  -- points, rebounds, assists, threes
  kalshi_player_name STRING NOT NULL,
  player_lookup STRING NOT NULL,
  player_team STRING,
  home_team STRING,
  away_team STRING,
  game_id STRING,
  
  -- Line and pricing
  line_value FLOAT64 NOT NULL,
  yes_bid INT64,
  yes_ask INT64,
  no_bid INT64,
  no_ask INT64,
  implied_over_prob FLOAT64,
  implied_under_prob FLOAT64,
  equivalent_over_odds INT64,
  equivalent_under_odds INT64,
  
  -- Liquidity metrics
  yes_bid_size INT64,
  yes_ask_size INT64,
  no_bid_size INT64,
  no_ask_size INT64,
  total_volume INT64,
  open_interest INT64,
  liquidity_score STRING,
  
  -- Market status
  market_status STRING NOT NULL,
  can_close_early BOOLEAN,
  close_time TIMESTAMP,
  
  -- Team validation fields (has_team_issues defaults to TRUE in application code)
  has_team_issues BOOLEAN NOT NULL,
  validated_team STRING,
  validation_confidence FLOAT64,
  validation_method STRING,
  
  -- Processing metadata
  data_hash STRING,
  scraped_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, prop_type, market_status
OPTIONS (
  description = 'Kalshi NBA player prop betting data with pricing and liquidity metrics',
  require_partition_filter = true
);
