-- Runtime filter overrides for auto-demotion.
-- When a filter's counterfactual HR >= 55% for 7 consecutive days at N >= 20,
-- it gets auto-demoted to observation-only via this table.
-- The aggregator reads active overrides at export time and skips blocked filters.
--
-- demote_start_date: When the auto-demotion was first applied
-- re_eval_date: When to re-evaluate (demote_start_date + 14 days). Filter reactivated
--               if re_eval_date passes AND last 3d CF HR < 50%.
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
  active BOOLEAN,
  demote_start_date DATE,
  re_eval_date DATE
)
CLUSTER BY filter_name;
