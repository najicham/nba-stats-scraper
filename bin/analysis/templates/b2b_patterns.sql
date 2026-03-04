-- Back-to-Back Patterns
-- Analyzes hit rate by rest status (B2B vs rested).
-- Parameters: {start_date}, {end_date}

WITH graded AS (
    SELECT
        pa.game_date,
        pa.recommendation AS direction,
        ABS(pa.predicted_points - pa.line_value) AS edge,
        pa.prediction_correct AS hit,
        CASE
            WHEN pa.line_value >= 25 THEN 'Star'
            WHEN pa.line_value >= 15 THEN 'Starter'
            WHEN pa.line_value >= 5 THEN 'Role'
            ELSE 'Bench'
        END AS tier,
        fs.feature_9_value AS days_rest
    FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
    LEFT JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
        ON pa.player_lookup = fs.player_id
        AND pa.game_date = fs.game_date
        AND fs.prop_type = 'points'
    WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND ABS(pa.predicted_points - pa.line_value) >= 3.0
      AND pa.has_prop_line = TRUE
      AND pa.recommendation IN ('OVER', 'UNDER')
      AND pa.prediction_correct IS NOT NULL
)
SELECT
    CASE
        WHEN days_rest IS NULL THEN 'Unknown'
        WHEN days_rest <= 1 THEN 'B2B (0-1d)'
        WHEN days_rest <= 2 THEN 'Short Rest (2d)'
        ELSE 'Rested (3+d)'
    END AS rest_status,
    direction,
    tier,
    COUNT(*) AS n,
    ROUND(AVG(CAST(hit AS INT64)) * 100, 1) AS hr,
    ROUND(AVG(edge), 2) AS avg_edge
FROM graded
GROUP BY rest_status, direction, tier
HAVING COUNT(*) >= 10
ORDER BY rest_status, direction, tier
