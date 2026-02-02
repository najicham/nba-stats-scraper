-- Add Kalshi-related fields to player_prop_predictions table
-- These fields track Kalshi market availability and pricing for predictions

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_available BOOLEAN,
ADD COLUMN IF NOT EXISTS kalshi_line FLOAT64,
ADD COLUMN IF NOT EXISTS kalshi_yes_price INT64,
ADD COLUMN IF NOT EXISTS kalshi_no_price INT64,
ADD COLUMN IF NOT EXISTS kalshi_liquidity STRING,
ADD COLUMN IF NOT EXISTS kalshi_market_ticker STRING,
ADD COLUMN IF NOT EXISTS line_discrepancy FLOAT64;
