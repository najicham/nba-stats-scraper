-- Daily counterfactual hit rate per negative filter.
-- Tracks what would have happened if each filter hadn't blocked picks.
-- Populated daily by filter-counterfactual-evaluator CF after grading completes.
--
-- Created: Session 432

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.filter_counterfactual_daily` (
  game_date DATE NOT NULL,
  filter_name STRING NOT NULL,
  blocked_count INT64,
  wins INT64,
  losses INT64,
  pushes INT64,
  counterfactual_hr FLOAT64,
  computed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY filter_name;
