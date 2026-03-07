-- Runtime filter overrides for auto-demotion.
-- When a filter's counterfactual HR >= 55% for 7 consecutive days at N >= 20,
-- it gets auto-demoted to observation-only via this table.
-- The aggregator reads active overrides at export time and skips blocked filters.
--
-- Created: Session 432

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.filter_overrides` (
  filter_name STRING NOT NULL,
  override_type STRING NOT NULL,
  reason STRING,
  cf_hr_7d FLOAT64,
  n_7d INT64,
  triggered_at TIMESTAMP,
  triggered_by STRING,
  active BOOLEAN
)
CLUSTER BY filter_name;
