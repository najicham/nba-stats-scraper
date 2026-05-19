-- Runtime filter overrides for MLB auto-demotion.
-- When a filter's counterfactual HR >= 55% for 7 consecutive days at N >= 20,
-- it gets auto-demoted to observation-only via this table.
-- The MLB best_bets_exporter reads active overrides at export time and
-- skips blocked filters.
--
-- Initial deployment 2026-05-18: ELIGIBLE_FOR_AUTO_DEMOTE = {} in the
-- evaluator (Phase 1 data collection only). Filters can be added later
-- once MLB pick volume + book regime stabilize.
--
-- demote_start_date: When the auto-demotion was first applied
-- re_eval_date: When to re-evaluate (demote_start_date + 14 days). Filter
--               reactivated if re_eval_date passes AND last 3d CF HR < 50%.
--
-- Created: 2026-05-18

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.filter_overrides` (
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
