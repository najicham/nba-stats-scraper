-- File: schemas/bigquery/nba_orchestration/performance_diagnostics_daily.sql
-- ============================================================================
-- NBA Props Platform - Unified Performance Diagnostics
-- ============================================================================
-- Purpose: Consolidated daily diagnostics combining vegas sharpness, model
--          drift, data quality, and root cause attribution for ML health
-- Update: Daily (after predictions graded)
-- Entities: One row per game_date
-- Retention: 365 days (for historical trend analysis)
--
-- Version: 1.0
-- Date: January 31, 2026
-- Status: Production-Ready
--
-- Key Use Cases:
--   1. Single-pane-of-glass for ML system health
--   2. Automated alerting on performance degradation
--   3. Root cause attribution for prediction issues
--   4. Vegas sharpness tracking (are we betting against sharp lines?)
--   5. Model drift detection (is performance degrading over time?)
--
-- Alert Levels:
--   - 'healthy': All metrics within expected ranges
--   - 'warning': One or more metrics showing early degradation
--   - 'critical': Significant performance issues requiring attention
--   - 'emergency': System failure or severe degradation
--
-- Dependencies:
--   - nba_predictions.prediction_accuracy (grading data)
--   - nba_analytics.player_game_summary (shot zone data)
--   - nba_predictions.ml_feature_store_v2 (feature quality)
--   - nba_orchestration.vegas_sharpness_history (vegas tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.performance_diagnostics_daily` (
  -- ==========================================================================
  -- IDENTIFIERS (2 fields)
  -- ==========================================================================

  game_date DATE NOT NULL,
    -- The date for which diagnostics are computed
    -- Format: YYYY-MM-DD
    -- Example: "2026-01-30"
    -- Partition key
    -- Used for: Time-series analysis, trend detection

  computed_at TIMESTAMP NOT NULL,
    -- When these diagnostics were computed (UTC)
    -- Format: ISO 8601 timestamp
    -- Example: "2026-01-31T08:30:15.123Z"
    -- Used for: Data freshness, debugging late computations

  -- ==========================================================================
  -- VEGAS SHARPNESS METRICS (6 fields)
  -- ==========================================================================
  -- Measures how sharp (accurate) Vegas lines are for this date.
  -- Sharper lines = harder to beat. Tracking sharpness helps understand
  -- why hit rates may vary independently of model quality.

  vegas_mae_tier1 FLOAT64,
    -- Mean Absolute Error of Vegas lines for high-confidence tier
    -- Lower = sharper lines (harder to beat)
    -- Range: 0.0 to 10.0+ (typical: 3.0-5.0 for points props)
    -- Example: 3.8 means Vegas was off by 3.8 points on average
    -- NULL if: No tier 1 predictions graded

  vegas_mae_tier2 FLOAT64,
    -- Mean Absolute Error of Vegas lines for medium-confidence tier
    -- NULL if: No tier 2 predictions graded

  vegas_mae_tier3 FLOAT64,
    -- Mean Absolute Error of Vegas lines for lower-confidence tier
    -- NULL if: No tier 3 predictions graded

  model_beats_vegas_pct FLOAT64,
    -- Percentage of predictions where model was closer than Vegas
    -- Range: 0.0 to 100.0
    -- Target: >52% (edge over Vegas)
    -- Example: 55.2 means model beat Vegas on 55.2% of props
    -- NULL if: No predictions graded

  sharpness_score FLOAT64,
    -- Composite sharpness score (0-100)
    -- Higher = sharper Vegas lines on this date
    -- Calculated from: vegas_mae weighted by volume, variance, etc.
    -- Range: 0 (very dull lines) to 100 (extremely sharp)
    -- Example: 72.5 indicates moderately sharp lines
    -- Used for: Context when interpreting hit rate

  sharpness_status STRING,
    -- Categorized sharpness level
    -- Values:
    --   'dull': Low sharpness, easier to beat (score <40)
    --   'normal': Typical sharpness (score 40-65)
    --   'sharp': Above average sharpness (score 65-80)
    --   'razor_sharp': Extremely sharp, hard to beat (score >80)
    -- Used for: Alert contextualization

  -- ==========================================================================
  -- MODEL DRIFT METRICS (7 fields)
  -- ==========================================================================
  -- Tracks whether model performance is degrading over time.
  -- Drift indicates need for retraining or investigation.

  hit_rate_7d FLOAT64,
    -- Rolling 7-day hit rate (percentage)
    -- Range: 0.0 to 100.0
    -- Target: >52% for profitability
    -- Example: 53.8 means 53.8% of predictions hit over past 7 days
    -- NULL if: Insufficient data

  hit_rate_14d FLOAT64,
    -- Rolling 14-day hit rate (percentage)
    -- More stable than 7-day, good for trend detection
    -- NULL if: Insufficient data

  hit_rate_30d FLOAT64,
    -- Rolling 30-day hit rate (percentage)
    -- Best for detecting sustained drift
    -- NULL if: Insufficient data

  model_mae FLOAT64,
    -- Model's Mean Absolute Error for this date
    -- Lower is better
    -- Range: 0.0 to 20.0+ (typical: 4.0-7.0 for points props)
    -- Example: 5.2 means model predictions off by 5.2 points on average
    -- NULL if: No predictions graded

  model_mean_error FLOAT64,
    -- Model's Mean Error (signed, shows bias direction)
    -- Negative = model underestimates, Positive = overestimates
    -- Range: -10.0 to +10.0 (typical: -2.0 to +2.0)
    -- Example: -1.5 means model underpredicts by 1.5 points on average
    -- Used for: Detecting systematic bias
    -- NULL if: No predictions graded

  bias_direction STRING,
    -- Direction of model bias
    -- Values:
    --   'under': Model consistently underpredicts (mean_error < -0.5)
    --   'neutral': No significant bias (-0.5 <= mean_error <= 0.5)
    --   'over': Model consistently overpredicts (mean_error > 0.5)
    -- Used for: Quick bias identification

  drift_score FLOAT64,
    -- Composite drift score (0-100)
    -- Higher = more drift detected, potential model degradation
    -- Calculated from: hit rate trends, MAE trends, bias changes
    -- Range: 0 (no drift) to 100 (severe drift)
    -- Threshold: >40 triggers warning, >70 triggers critical
    -- Example: 35 indicates mild drift, monitor closely

  drift_severity STRING,
    -- Categorized drift severity
    -- Values:
    --   'none': No significant drift (score <20)
    --   'mild': Early drift signals (score 20-40)
    --   'moderate': Significant drift, investigate (score 40-70)
    --   'severe': Major drift, action required (score >70)
    -- Used for: Alert triggering

  -- ==========================================================================
  -- DATA QUALITY CONTEXT (4 fields)
  -- ==========================================================================
  -- Data quality issues can cause apparent performance drops.
  -- Track these to distinguish data problems from model problems.

  shot_zone_completeness FLOAT64,
    -- Percentage of players with complete shot zone data
    -- Range: 0.0 to 100.0
    -- Target: >80% for reliable predictions
    -- Example: 85.3 means 85.3% of players have full zone data
    -- Impact: Low completeness can hurt shooting-based props
    -- NULL if: No data for this date

  predictions_made INT64,
    -- Total number of predictions generated for this date
    -- Range: 0 to 1000+ (typical game day: 200-500)
    -- Low count may indicate data pipeline issues
    -- Example: 312 predictions for 8-game slate

  predictions_graded INT64,
    -- Number of predictions that have been graded
    -- Should equal predictions_made after game completion
    -- Difference indicates grading pipeline delay
    -- Example: 308 graded (4 games still in progress)

  feature_quality_avg FLOAT64,
    -- Average feature quality score across all predictions
    -- Range: 0.0 to 100.0
    -- Target: >90 for high-quality features
    -- Lower scores indicate missing/stale features
    -- Example: 94.5 indicates good feature quality
    -- NULL if: No predictions made

  -- ==========================================================================
  -- BASELINE COMPARISONS (3 fields)
  -- ==========================================================================
  -- Compare current performance against historical baselines.

  vegas_mae_baseline FLOAT64,
    -- Historical baseline Vegas MAE (30-day average)
    -- Used for: Detecting unusual Vegas sharpness
    -- Example: 4.2 (our rolling baseline)

  hit_rate_baseline FLOAT64,
    -- Historical baseline hit rate (60-day average)
    -- Used for: Detecting sustained underperformance
    -- Example: 53.1 (our expected hit rate)

  sharpness_vs_baseline FLOAT64,
    -- How today's sharpness compares to baseline
    -- Calculated as: (sharpness_score - baseline_sharpness) / baseline_sharpness * 100
    -- Positive = sharper than usual, Negative = duller than usual
    -- Range: -50.0 to +50.0 (typical: -15 to +15)
    -- Example: +12.5 means lines 12.5% sharper than baseline

  -- ==========================================================================
  -- ROOT CAUSE ATTRIBUTION (3 fields)
  -- ==========================================================================
  -- Automated root cause analysis when issues detected.

  primary_cause STRING,
    -- Primary suspected cause of performance issues
    -- Values:
    --   'none': No significant issues detected
    --   'vegas_sharpness': Sharp lines causing lower hit rate
    --   'model_drift': Model performance degradation
    --   'data_quality': Missing or poor quality input data
    --   'feature_staleness': Stale features in prediction
    --   'sample_size': Too few predictions for reliable metrics
    --   'outlier_games': Unusual game outcomes affecting metrics
    --   'mixed': Multiple contributing factors
    -- Used for: Directing investigation efforts

  cause_confidence FLOAT64,
    -- Confidence in the primary cause attribution
    -- Range: 0.0 to 1.0
    -- >0.8: High confidence, act on this cause
    -- 0.5-0.8: Moderate confidence, investigate further
    -- <0.5: Low confidence, multiple factors likely
    -- Example: 0.85 means 85% confident in attribution

  contributing_factors JSON,
    -- Additional factors contributing to issues
    -- Structure: [
    --   {"factor": "vegas_sharpness", "contribution": 0.35, "details": "..."},
    --   {"factor": "sample_size", "contribution": 0.20, "details": "..."}
    -- ]
    -- Each factor has:
    --   - factor: Factor name
    --   - contribution: 0.0-1.0 contribution weight
    --   - details: Human-readable explanation
    -- NULL if: primary_cause = 'none'

  -- ==========================================================================
  -- ALERT STATUS (3 fields)
  -- ==========================================================================
  -- Alert state for this diagnostic row.

  alert_triggered BOOLEAN NOT NULL,
    -- Whether any alert was triggered
    -- True if: Any metric exceeds threshold
    -- Used for: Quick filtering of problem days

  alert_level STRING NOT NULL,
    -- Highest alert level triggered
    -- Values:
    --   'healthy': All metrics in normal range
    --   'warning': Early warning, monitor closely
    --   'critical': Significant issue, investigate
    --   'emergency': Severe issue, immediate action needed
    -- Default: 'healthy'
    -- Used for: Alert prioritization, clustering

  alert_message STRING,
    -- Human-readable summary of alert
    -- Format: "[LEVEL] Brief description of issue"
    -- Example: "[CRITICAL] Hit rate dropped to 48.2% (14-day),
    --           primary cause: model_drift (confidence: 0.82)"
    -- NULL if: alert_level = 'healthy'
    -- Used for: Slack/email notifications

  -- ==========================================================================
  -- METADATA (1 field)
  -- ==========================================================================

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- When this record was inserted into BigQuery
    -- Auto-populated by BigQuery
    -- Used for: Audit trail, debugging

)
PARTITION BY game_date
CLUSTER BY alert_level, primary_cause
OPTIONS(
  description = "Unified daily performance diagnostics combining vegas sharpness, model drift, data quality, and root cause attribution. Partition key: game_date (daily). Cluster by: alert_level, primary_cause. CRITICAL TABLE for ML health monitoring and alerting.",
  labels = [("team", "ml-engineering"), ("purpose", "performance-monitoring")],
  partition_expiration_days = 365
);

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 29
--   - Identifiers: 2 (game_date, computed_at)
--   - Vegas sharpness: 6 (vegas_mae_tier1/2/3, model_beats_vegas_pct,
--                         sharpness_score, sharpness_status)
--   - Model drift: 7 (hit_rate_7d/14d/30d, model_mae, model_mean_error,
--                     bias_direction, drift_score, drift_severity)
--   - Data quality: 4 (shot_zone_completeness, predictions_made/graded,
--                      feature_quality_avg)
--   - Baselines: 3 (vegas_mae_baseline, hit_rate_baseline,
--                   sharpness_vs_baseline)
--   - Root cause: 3 (primary_cause, cause_confidence, contributing_factors)
--   - Alert status: 3 (alert_triggered, alert_level, alert_message)
--   - Metadata: 1 (created_at)
-- ============================================================================

-- ============================================================================
-- SAMPLE ROW (Healthy Day)
-- ============================================================================
/*
{
  "game_date": "2026-01-30",
  "computed_at": "2026-01-31T08:30:15.123Z",
  "vegas_mae_tier1": 4.2,
  "vegas_mae_tier2": 4.8,
  "vegas_mae_tier3": 5.5,
  "model_beats_vegas_pct": 54.3,
  "sharpness_score": 58.5,
  "sharpness_status": "normal",
  "hit_rate_7d": 53.2,
  "hit_rate_14d": 52.8,
  "hit_rate_30d": 53.1,
  "model_mae": 5.1,
  "model_mean_error": -0.3,
  "bias_direction": "neutral",
  "drift_score": 12.5,
  "drift_severity": "none",
  "shot_zone_completeness": 87.2,
  "predictions_made": 312,
  "predictions_graded": 312,
  "feature_quality_avg": 94.5,
  "vegas_mae_baseline": 4.3,
  "hit_rate_baseline": 53.0,
  "sharpness_vs_baseline": -1.8,
  "primary_cause": "none",
  "cause_confidence": null,
  "contributing_factors": null,
  "alert_triggered": false,
  "alert_level": "healthy",
  "alert_message": null,
  "created_at": "2026-01-31T08:30:16.000Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Critical Alert - Model Drift)
-- ============================================================================
/*
{
  "game_date": "2026-01-28",
  "computed_at": "2026-01-29T08:45:22.456Z",
  "vegas_mae_tier1": 4.0,
  "vegas_mae_tier2": 4.5,
  "vegas_mae_tier3": 5.2,
  "model_beats_vegas_pct": 47.8,
  "sharpness_score": 55.2,
  "sharpness_status": "normal",
  "hit_rate_7d": 48.2,
  "hit_rate_14d": 49.5,
  "hit_rate_30d": 51.8,
  "model_mae": 6.8,
  "model_mean_error": -2.1,
  "bias_direction": "under",
  "drift_score": 72.5,
  "drift_severity": "severe",
  "shot_zone_completeness": 82.1,
  "predictions_made": 285,
  "predictions_graded": 285,
  "feature_quality_avg": 91.2,
  "vegas_mae_baseline": 4.3,
  "hit_rate_baseline": 53.0,
  "sharpness_vs_baseline": -5.2,
  "primary_cause": "model_drift",
  "cause_confidence": 0.82,
  "contributing_factors": [
    {"factor": "model_drift", "contribution": 0.65, "details": "7-day hit rate 4.8 points below baseline"},
    {"factor": "feature_staleness", "contribution": 0.20, "details": "Some rest day features not updating"},
    {"factor": "vegas_sharpness", "contribution": 0.15, "details": "Lines slightly duller than normal"}
  ],
  "alert_triggered": true,
  "alert_level": "critical",
  "alert_message": "[CRITICAL] Hit rate dropped to 48.2% (7-day), primary cause: model_drift (confidence: 0.82). Model showing consistent under-prediction bias (-2.1 points).",
  "created_at": "2026-01-29T08:45:23.000Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Warning - Sharp Vegas Lines)
-- ============================================================================
/*
{
  "game_date": "2026-01-25",
  "computed_at": "2026-01-26T09:00:05.789Z",
  "vegas_mae_tier1": 3.2,
  "vegas_mae_tier2": 3.8,
  "vegas_mae_tier3": 4.5,
  "model_beats_vegas_pct": 51.2,
  "sharpness_score": 78.5,
  "sharpness_status": "sharp",
  "hit_rate_7d": 50.5,
  "hit_rate_14d": 52.1,
  "hit_rate_30d": 52.8,
  "model_mae": 5.8,
  "model_mean_error": 0.2,
  "bias_direction": "neutral",
  "drift_score": 28.5,
  "drift_severity": "mild",
  "shot_zone_completeness": 89.5,
  "predictions_made": 342,
  "predictions_graded": 342,
  "feature_quality_avg": 95.2,
  "vegas_mae_baseline": 4.3,
  "hit_rate_baseline": 53.0,
  "sharpness_vs_baseline": 22.8,
  "primary_cause": "vegas_sharpness",
  "cause_confidence": 0.71,
  "contributing_factors": [
    {"factor": "vegas_sharpness", "contribution": 0.60, "details": "Vegas MAE 25% lower than baseline"},
    {"factor": "sample_size", "contribution": 0.25, "details": "High volume day with 342 predictions"},
    {"factor": "model_drift", "contribution": 0.15, "details": "Slight downward trend in 7-day"}
  ],
  "alert_triggered": true,
  "alert_level": "warning",
  "alert_message": "[WARNING] Vegas lines unusually sharp (score: 78.5, +22.8% vs baseline). Hit rate impact expected but model still beating Vegas 51.2% of time.",
  "created_at": "2026-01-26T09:00:06.000Z"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Recent diagnostics overview
-- Purpose: Quick health check of recent days
-- Expected: Most days 'healthy', occasional 'warning'
-- SELECT
--   game_date,
--   alert_level,
--   hit_rate_7d,
--   sharpness_status,
--   drift_severity,
--   primary_cause
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ORDER BY game_date DESC;

-- Query 2: Trend analysis - 30-day rolling metrics
-- Purpose: Detect gradual degradation
-- SELECT
--   game_date,
--   hit_rate_30d,
--   drift_score,
--   sharpness_score,
--   model_mae
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- ORDER BY game_date;

-- Query 3: Alert frequency by level
-- Purpose: Track system stability over time
-- SELECT
--   alert_level,
--   COUNT(*) as day_count,
--   ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct_of_days
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY alert_level
-- ORDER BY
--   CASE alert_level
--     WHEN 'healthy' THEN 1
--     WHEN 'warning' THEN 2
--     WHEN 'critical' THEN 3
--     WHEN 'emergency' THEN 4
--   END;

-- Query 4: Root cause breakdown
-- Purpose: Understand most common issues
-- SELECT
--   primary_cause,
--   COUNT(*) as occurrences,
--   ROUND(AVG(cause_confidence), 2) as avg_confidence,
--   AVG(hit_rate_7d) as avg_hit_rate_when_this_cause
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   AND alert_triggered = TRUE
-- GROUP BY primary_cause
-- ORDER BY occurrences DESC;

-- Query 5: Vegas sharpness vs hit rate correlation
-- Purpose: Validate sharpness affects outcomes
-- SELECT
--   sharpness_status,
--   COUNT(*) as days,
--   ROUND(AVG(hit_rate_7d), 2) as avg_hit_rate,
--   ROUND(AVG(model_beats_vegas_pct), 2) as avg_beats_vegas_pct
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
-- GROUP BY sharpness_status
-- ORDER BY
--   CASE sharpness_status
--     WHEN 'dull' THEN 1
--     WHEN 'normal' THEN 2
--     WHEN 'sharp' THEN 3
--     WHEN 'razor_sharp' THEN 4
--   END;

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Alert: Critical or Emergency status
-- Trigger: Immediate investigation required
-- SELECT
--   game_date,
--   alert_level,
--   alert_message,
--   primary_cause,
--   cause_confidence
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
--   AND alert_level IN ('critical', 'emergency')
-- ORDER BY game_date DESC;

-- Alert: Sustained drift (3+ days of moderate+ drift)
-- Trigger: Model retraining may be needed
-- WITH drift_days AS (
--   SELECT
--     game_date,
--     drift_severity,
--     drift_score,
--     LAG(drift_severity, 1) OVER (ORDER BY game_date) as prev_day,
--     LAG(drift_severity, 2) OVER (ORDER BY game_date) as prev_day_2
--   FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
--   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- )
-- SELECT *
-- FROM drift_days
-- WHERE drift_severity IN ('moderate', 'severe')
--   AND prev_day IN ('moderate', 'severe')
--   AND prev_day_2 IN ('moderate', 'severe');

-- Alert: Low data quality
-- Trigger: Data pipeline investigation needed
-- SELECT
--   game_date,
--   shot_zone_completeness,
--   feature_quality_avg,
--   predictions_made,
--   primary_cause
-- FROM `nba-props-platform.nba_orchestration.performance_diagnostics_daily`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND (shot_zone_completeness < 70 OR feature_quality_avg < 85)
-- ORDER BY game_date DESC;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_orchestration dataset
-- [ ] Verify partitioning (daily on game_date)
-- [ ] Verify clustering (alert_level, primary_cause)
-- [ ] Test with sample insert
-- [ ] Validate JSON field (contributing_factors)
-- [ ] Set up daily computation job
-- [ ] Configure alerting based on alert_level
-- [ ] Add to admin dashboard
-- [ ] Document alert thresholds
-- [ ] Add to daily validation checks
-- ============================================================================

-- ============================================================================
-- DEPLOYMENT COMMAND
-- ============================================================================
-- bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/performance_diagnostics_daily.sql
-- ============================================================================

-- ============================================================================
-- CHANGELOG
-- ============================================================================
-- Version 1.0 (2026-01-31)
--   - Initial schema
--   - Vegas sharpness metrics with tiered MAE
--   - Model drift detection with 7/14/30-day hit rates
--   - Data quality tracking (shot zones, feature quality)
--   - Baseline comparisons for trend detection
--   - Root cause attribution with confidence scoring
--   - Alert status with four severity levels
--   - Partitioned by game_date, clustered by alert_level and primary_cause
-- ============================================================================
