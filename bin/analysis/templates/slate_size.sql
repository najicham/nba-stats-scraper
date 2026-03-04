-- Slate Size Effects
-- Analyzes hit rate by number of games on the slate.
-- Parameters: {start_date}, {end_date}

WITH games_per_date AS (
    SELECT
        game_date,
        COUNT(*) AS num_games
    FROM `nba-props-platform.nba_reference.nba_schedule`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND game_status = 3
    GROUP BY game_date
),
graded AS (
    SELECT
        pa.game_date,
        pa.recommendation AS direction,
        ABS(pa.predicted_points - pa.line_value) AS edge,
        pa.prediction_correct AS hit,
        CASE
            WHEN g.num_games <= 3 THEN 'Light (1-3)'
            WHEN g.num_games <= 6 THEN 'Medium (4-6)'
            WHEN g.num_games <= 9 THEN 'Heavy (7-9)'
            ELSE 'Mega (10+)'
        END AS slate_size
    FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
    JOIN games_per_date g ON pa.game_date = g.game_date
    WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND ABS(pa.predicted_points - pa.line_value) >= 3.0
      AND pa.has_prop_line = TRUE
      AND pa.recommendation IN ('OVER', 'UNDER')
      AND pa.prediction_correct IS NOT NULL
)
SELECT
    slate_size,
    direction,
    COUNT(*) AS n,
    ROUND(AVG(CAST(hit AS INT64)) * 100, 1) AS hr,
    ROUND(AVG(edge), 2) AS avg_edge
FROM graded
GROUP BY slate_size, direction
ORDER BY
    CASE slate_size
        WHEN 'Light (1-3)' THEN 1
        WHEN 'Medium (4-6)' THEN 2
        WHEN 'Heavy (7-9)' THEN 3
        WHEN 'Mega (10+)' THEN 4
    END,
    direction
