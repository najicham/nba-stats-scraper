-- ============================================================================
-- MLB Multi-Model Architecture Views
-- Views for ensemble predictions and system comparison
-- ============================================================================
--
-- These views support the multi-model architecture where multiple prediction
-- systems (V1 baseline, V1.6 rolling, ensemble) run concurrently.
--
-- IMPORTANT: Run after migration_add_system_id.sql has been applied
-- ============================================================================

-- ============================================================================
-- Today's Ensemble Picks
-- Returns only ensemble predictions for today's games
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.todays_picks` AS
SELECT
    pitcher_lookup,
    game_date,
    team_abbr,
    opponent_team_abbr,
    is_home,
    predicted_strikeouts,
    confidence,
    recommendation,
    edge,
    strikeouts_line,
    model_version,
    system_id,
    red_flags,
    created_at
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'ensemble_v1'
  AND recommendation IN ('OVER', 'UNDER')
ORDER BY ABS(edge) DESC;

-- ============================================================================
-- Today's System Comparison
-- Shows all systems side-by-side for today's games
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.system_comparison` AS
WITH ensemble AS (
    SELECT
        pitcher_lookup,
        game_date,
        predicted_strikeouts as ensemble_prediction,
        confidence as ensemble_confidence,
        recommendation as ensemble_recommendation,
        edge as ensemble_edge
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = CURRENT_DATE()
      AND system_id = 'ensemble_v1'
),
v1_baseline AS (
    SELECT
        pitcher_lookup,
        game_date,
        predicted_strikeouts as v1_prediction,
        confidence as v1_confidence,
        recommendation as v1_recommendation,
        edge as v1_edge
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = CURRENT_DATE()
      AND system_id = 'v1_baseline'
),
v1_6_rolling AS (
    SELECT
        pitcher_lookup,
        game_date,
        predicted_strikeouts as v1_6_prediction,
        confidence as v1_6_confidence,
        recommendation as v1_6_recommendation,
        edge as v1_6_edge
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = CURRENT_DATE()
      AND system_id = 'v1_6_rolling'
),
metadata AS (
    SELECT DISTINCT
        pitcher_lookup,
        game_date,
        team_abbr,
        opponent_team_abbr,
        is_home,
        strikeouts_line
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = CURRENT_DATE()
)
SELECT
    m.pitcher_lookup,
    m.game_date,
    m.team_abbr,
    m.opponent_team_abbr,
    m.is_home,
    m.strikeouts_line,

    -- Ensemble
    e.ensemble_prediction,
    e.ensemble_confidence,
    e.ensemble_recommendation,
    e.ensemble_edge,

    -- V1 Baseline
    v1.v1_prediction,
    v1.v1_confidence,
    v1.v1_recommendation,
    v1.v1_edge,

    -- V1.6 Rolling
    v1_6.v1_6_prediction,
    v1_6.v1_6_confidence,
    v1_6.v1_6_recommendation,
    v1_6.v1_6_edge,

    -- Agreement metrics
    ABS(COALESCE(v1.v1_prediction, 0) - COALESCE(v1_6.v1_6_prediction, 0)) as v1_v1_6_diff,
    CASE
        WHEN ABS(COALESCE(v1.v1_prediction, 0) - COALESCE(v1_6.v1_6_prediction, 0)) < 1.0 THEN 'STRONG'
        WHEN ABS(COALESCE(v1.v1_prediction, 0) - COALESCE(v1_6.v1_6_prediction, 0)) < 2.0 THEN 'MODERATE'
        ELSE 'WEAK'
    END as agreement_level

FROM metadata m
LEFT JOIN ensemble e USING (pitcher_lookup, game_date)
LEFT JOIN v1_baseline v1 USING (pitcher_lookup, game_date)
LEFT JOIN v1_6_rolling v1_6 USING (pitcher_lookup, game_date)
ORDER BY m.pitcher_lookup;

-- ============================================================================
-- System Performance Summary
-- Historical accuracy by system over last 30 days
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.system_performance` AS
SELECT
    system_id,
    COUNT(*) as total_predictions,
    COUNT(CASE WHEN recommendation IN ('OVER', 'UNDER') THEN 1 END) as actionable_predictions,
    COUNT(CASE WHEN recommendation = 'SKIP' THEN 1 END) as skipped,

    -- Accuracy metrics (when actual results available)
    COUNT(CASE WHEN actual_strikeouts IS NOT NULL THEN 1 END) as graded_predictions,
    AVG(CASE WHEN actual_strikeouts IS NOT NULL
             THEN ABS(predicted_strikeouts - actual_strikeouts)
             END) as mae,

    -- Recommendation accuracy
    ROUND(
        COUNT(CASE
            WHEN actual_strikeouts IS NOT NULL
                AND ((recommendation = 'OVER' AND actual_strikeouts > strikeouts_line)
                  OR (recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line))
            THEN 1
        END) * 100.0 / NULLIF(COUNT(CASE
            WHEN actual_strikeouts IS NOT NULL AND recommendation IN ('OVER', 'UNDER')
            THEN 1
        END), 0),
    1) as recommendation_accuracy_pct,

    -- Confidence distribution
    AVG(confidence) as avg_confidence,
    MIN(confidence) as min_confidence,
    MAX(confidence) as max_confidence

FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND system_id IS NOT NULL
GROUP BY system_id
ORDER BY recommendation_accuracy_pct DESC;

-- ============================================================================
-- Daily System Coverage
-- Ensures all systems ran for each game date
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.daily_coverage` AS
SELECT
    game_date,
    COUNT(DISTINCT pitcher_lookup) as unique_pitchers,
    COUNT(DISTINCT system_id) as systems_per_date,
    STRING_AGG(DISTINCT system_id ORDER BY system_id) as systems_used,

    -- Per-system counts
    COUNT(CASE WHEN system_id = 'v1_baseline' THEN 1 END) as v1_count,
    COUNT(CASE WHEN system_id = 'v1_6_rolling' THEN 1 END) as v1_6_count,
    COUNT(CASE WHEN system_id = 'ensemble_v1' THEN 1 END) as ensemble_count,

    -- Validation: All pitchers should have all active systems
    MIN(pitcher_system_count) as min_systems_per_pitcher,
    MAX(pitcher_system_count) as max_systems_per_pitcher

FROM (
    SELECT
        game_date,
        pitcher_lookup,
        system_id,
        COUNT(DISTINCT system_id) OVER (PARTITION BY game_date, pitcher_lookup) as pitcher_system_count
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
GROUP BY game_date
ORDER BY game_date DESC;

-- ============================================================================
-- System Agreement Analysis
-- Tracks how often systems agree/disagree
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.system_agreement` AS
WITH paired_predictions AS (
    SELECT
        p1.game_date,
        p1.pitcher_lookup,
        p1.strikeouts_line,
        p1.predicted_strikeouts as v1_prediction,
        p1.recommendation as v1_recommendation,
        p2.predicted_strikeouts as v1_6_prediction,
        p2.recommendation as v1_6_recommendation,
        ABS(p1.predicted_strikeouts - p2.predicted_strikeouts) as prediction_diff,
        p1.actual_strikeouts
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` p1
    INNER JOIN `nba-props-platform.mlb_predictions.pitcher_strikeouts` p2
        ON p1.game_date = p2.game_date
        AND p1.pitcher_lookup = p2.pitcher_lookup
        AND p1.system_id = 'v1_baseline'
        AND p2.system_id = 'v1_6_rolling'
    WHERE p1.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
    game_date,
    COUNT(*) as total_comparisons,

    -- Agreement levels
    COUNT(CASE WHEN prediction_diff < 1.0 THEN 1 END) as strong_agreement,
    COUNT(CASE WHEN prediction_diff >= 1.0 AND prediction_diff < 2.0 THEN 1 END) as moderate_agreement,
    COUNT(CASE WHEN prediction_diff >= 2.0 THEN 1 END) as disagreement,

    -- Recommendation agreement
    COUNT(CASE WHEN v1_recommendation = v1_6_recommendation THEN 1 END) as same_recommendation,
    COUNT(CASE WHEN v1_recommendation != v1_6_recommendation THEN 1 END) as different_recommendation,

    -- Accuracy when agreeing vs disagreeing
    ROUND(AVG(CASE
        WHEN prediction_diff < 1.0 AND actual_strikeouts IS NOT NULL
        THEN LEAST(
            ABS(v1_prediction - actual_strikeouts),
            ABS(v1_6_prediction - actual_strikeouts)
        )
    END), 2) as mae_when_agreeing,

    ROUND(AVG(CASE
        WHEN prediction_diff >= 2.0 AND actual_strikeouts IS NOT NULL
        THEN LEAST(
            ABS(v1_prediction - actual_strikeouts),
            ABS(v1_6_prediction - actual_strikeouts)
        )
    END), 2) as mae_when_disagreeing

FROM paired_predictions
GROUP BY game_date
ORDER BY game_date DESC;
