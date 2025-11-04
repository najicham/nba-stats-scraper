-- ============================================================================
-- Table: feature_versions
-- File: 05_feature_versions.sql
-- Purpose: Define feature versions and track evolution from v1 (25) → v2 (47)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.feature_versions` (
  feature_version STRING NOT NULL,                  -- e.g., "v1_baseline_25"
  feature_count INT64 NOT NULL,                     -- 25, 47, etc.
  feature_names ARRAY<STRING> NOT NULL,             -- Ordered array of feature names
  description STRING,                               -- What's in this version
  active BOOLEAN DEFAULT FALSE,                     -- Currently in use
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
);

-- ============================================================================
-- Insert v1_baseline_25 (Week 1-4 Feature Set)
-- ============================================================================

INSERT INTO `nba-props-platform.nba_predictions.feature_versions`
(feature_version, feature_count, feature_names, description, active)
VALUES (
  'v1_baseline_25',
  25,
  [
    -- Player Recent Performance (5 features: 0-4)
    'points_avg_last_5',          -- Feature 0
    'points_avg_last_10',          -- Feature 1
    'points_avg_season',           -- Feature 2
    'points_std_last_10',          -- Feature 3
    'games_played_last_7_days',    -- Feature 4
    
    -- Composite Factors (8 features: 5-12)
    'fatigue_score',               -- Feature 5: 0-100 (higher = more tired)
    'shot_zone_mismatch_score',    -- Feature 6: -10 to +10 (matchup quality)
    'pace_score',                  -- Feature 7: -3 to +3 (game tempo impact)
    'usage_spike_score',           -- Feature 8: -3 to +3 (increased role)
    'rest_advantage',              -- Feature 9: -2 to +2 (rest differential)
    'injury_risk',                 -- Feature 10: 0-3 (health status)
    'recent_trend',                -- Feature 11: -2 to +2 (hot/cold streak)
    'minutes_change',              -- Feature 12: -2 to +2 (playing time change)
    
    -- Matchup Context (5 features: 13-17)
    'opponent_def_rating',         -- Feature 13: Opponent defensive rating
    'opponent_pace',               -- Feature 14: Opponent pace factor
    'home_away',                   -- Feature 15: 1=home, 0=away
    'back_to_back',                -- Feature 16: 1=B2B, 0=normal rest
    'playoff_game',                -- Feature 17: 1=playoff, 0=regular
    
    -- Shot Zones (4 features: 18-21)
    'pct_paint',                   -- Feature 18: % shots in paint
    'pct_mid_range',               -- Feature 19: % shots mid-range
    'pct_three',                   -- Feature 20: % shots from 3
    'pct_free_throw',              -- Feature 21: % shots at FT line
    
    -- Team Context (3 features: 22-24)
    'team_pace',                   -- Feature 22: Team pace factor
    'team_off_rating',             -- Feature 23: Team offensive rating
    'team_win_pct'                 -- Feature 24: Team win percentage
  ],
  'Week 1-4 baseline feature set. Start with 25 core features before expanding to v2 (47 features).',
  TRUE  -- This is the active version
)
ON CONFLICT (feature_version) DO NOTHING;

-- ============================================================================
-- Future: v2_enhanced_47 (Week 5+ Feature Set)
-- ============================================================================
-- Placeholder for future expansion - will include:
-- - Additional composite factors (referee, look-ahead, matchup history, momentum)
-- - Opponent-specific features (shot zone defense by zone)
-- - Advanced metrics (usage spike details, fatigue breakdown)
-- - Team dynamics (offensive synergy, defensive adjustments)

-- INSERT INTO `nba-props-platform.nba_predictions.feature_versions`
-- (feature_version, feature_count, feature_names, description, active)
-- VALUES (
--   'v2_enhanced_47',
--   47,
--   [... 47 feature names ...],
--   'Enhanced feature set with 22 additional features for improved accuracy.',
--   FALSE  -- Not yet active
-- );

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get active feature version
-- SELECT * FROM `nba-props-platform.nba_predictions.feature_versions`
-- WHERE active = TRUE;

-- List all feature versions
-- SELECT 
--   feature_version,
--   feature_count,
--   active,
--   description,
--   created_at
-- FROM `nba-props-platform.nba_predictions.feature_versions`
-- ORDER BY created_at DESC;

-- Get feature names for v1
-- SELECT 
--   feature_version,
--   feature_names,
--   ARRAY_LENGTH(feature_names) as total_features
-- FROM `nba-props-platform.nba_predictions.feature_versions`
-- WHERE feature_version = 'v1_baseline_25';

-- Validate feature count matches
-- SELECT 
--   fv.feature_version,
--   fv.feature_count as expected_count,
--   AVG(fs.feature_count) as actual_avg_count,
--   COUNT(*) as record_count
-- FROM `nba-props-platform.nba_predictions.feature_versions` fv
-- LEFT JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
--   ON fv.feature_version = fs.feature_version
-- WHERE fs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY fv.feature_version, fv.feature_count;
