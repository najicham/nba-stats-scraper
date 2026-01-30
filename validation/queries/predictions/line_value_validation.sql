-- Line Value Validation Query
-- Session 36: Added to detect grading bugs where line values don't match raw source data
--
-- This query compares the line_value stored in prediction_accuracy against the
-- actual points line from raw betting data. Any significant discrepancy indicates
-- a potential bug in the prediction or grading pipeline.
--
-- Run this after grading to catch issues like the 2026-01-12 bug where predictions
-- were graded against wrong line values (average of all prop types instead of points-only).

WITH graded_predictions AS (
    SELECT
        player_lookup,
        game_date,
        system_id,
        line_value as graded_line,
        predicted_points,
        actual_points,
        absolute_error
    FROM `nba_predictions.prediction_accuracy`
    WHERE game_date = @game_date
      AND line_value IS NOT NULL
),

raw_points_lines AS (
    SELECT
        player_lookup,
        AVG(points_line) as raw_points_line
    FROM `nba_raw.bettingpros_player_points_props`
    WHERE game_date = @game_date
      AND market_type = 'points'  -- Critical: filter to points only
      AND bet_side = 'over'
      AND is_active = TRUE
    GROUP BY player_lookup
)

SELECT
    gp.game_date,
    gp.system_id,
    gp.player_lookup,
    gp.graded_line,
    rpl.raw_points_line,
    ABS(gp.graded_line - rpl.raw_points_line) as line_diff,
    gp.predicted_points,
    gp.actual_points,
    CASE
        WHEN ABS(gp.graded_line - rpl.raw_points_line) > 5 THEN 'CRITICAL'
        WHEN ABS(gp.graded_line - rpl.raw_points_line) > 2 THEN 'WARNING'
        ELSE 'OK'
    END as status
FROM graded_predictions gp
JOIN raw_points_lines rpl ON gp.player_lookup = rpl.player_lookup
WHERE ABS(gp.graded_line - rpl.raw_points_line) > 0.5
ORDER BY line_diff DESC
LIMIT 100;


-- Summary query for quick health check
-- SELECT
--     COUNT(*) as total_mismatches,
--     COUNTIF(ABS(gp.graded_line - rpl.raw_points_line) > 5) as critical_count,
--     COUNTIF(ABS(gp.graded_line - rpl.raw_points_line) BETWEEN 2 AND 5) as warning_count,
--     AVG(ABS(gp.graded_line - rpl.raw_points_line)) as avg_line_diff
-- FROM graded_predictions gp
-- JOIN raw_points_lines rpl ON gp.player_lookup = rpl.player_lookup
-- WHERE ABS(gp.graded_line - rpl.raw_points_line) > 0.5;
