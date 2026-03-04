-- Day of Week Patterns
-- Analyzes hit rate by day of week and direction.
-- Parameters: {start_date}, {end_date}

WITH graded AS (
    SELECT
        pa.game_date,
        FORMAT_DATE('%A', pa.game_date) AS day_name,
        EXTRACT(DAYOFWEEK FROM pa.game_date) AS day_num,
        pa.recommendation AS direction,
        ABS(pa.predicted_points - pa.line_value) AS edge,
        pa.prediction_correct AS hit
    FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
    WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND ABS(pa.predicted_points - pa.line_value) >= 3.0
      AND pa.has_prop_line = TRUE
      AND pa.recommendation IN ('OVER', 'UNDER')
      AND pa.prediction_correct IS NOT NULL
)
SELECT
    day_name,
    direction,
    COUNT(*) AS n,
    ROUND(AVG(CAST(hit AS INT64)) * 100, 1) AS hr,
    ROUND(AVG(edge), 2) AS avg_edge,
    ROUND(STDDEV(edge), 2) AS std_edge
FROM graded
GROUP BY day_name, day_num, direction
ORDER BY day_num, direction
