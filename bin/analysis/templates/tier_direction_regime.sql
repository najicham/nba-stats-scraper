-- Tier x Direction x Regime Breakdown
-- Analyzes hit rate by player tier, prediction direction, and calendar regime.
-- Parameters: {start_date}, {end_date}

WITH regime_labels AS (
    SELECT
        game_date,
        CASE
            -- 2025-26 season toxic window
            WHEN game_date BETWEEN '2026-01-30' AND '2026-02-05' THEN 'pre_deadline'
            WHEN game_date = '2026-02-06' THEN 'trade_deadline'
            WHEN game_date BETWEEN '2026-02-07' AND '2026-02-12' THEN 'post_deadline'
            WHEN game_date BETWEEN '2026-02-13' AND '2026-02-18' THEN 'asb'
            WHEN game_date BETWEEN '2026-02-19' AND '2026-02-25' THEN 'post_asb'
            -- 2024-25 season toxic window
            WHEN game_date BETWEEN '2025-01-30' AND '2025-02-06' THEN 'pre_deadline'
            WHEN game_date = '2025-02-06' THEN 'trade_deadline'
            WHEN game_date BETWEEN '2025-02-07' AND '2025-02-13' THEN 'post_deadline'
            WHEN game_date BETWEEN '2025-02-14' AND '2025-02-19' THEN 'asb'
            WHEN game_date BETWEEN '2025-02-20' AND '2025-02-26' THEN 'post_asb'
            ELSE 'normal'
        END AS regime,
    FROM UNNEST(GENERATE_DATE_ARRAY('{start_date}', '{end_date}')) AS game_date
),
graded AS (
    SELECT
        pa.game_date,
        pa.recommendation AS direction,
        CASE
            WHEN pa.line_value >= 25 THEN 'Star'
            WHEN pa.line_value >= 15 THEN 'Starter'
            WHEN pa.line_value >= 5 THEN 'Role'
            ELSE 'Bench'
        END AS tier,
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
    r.regime,
    g.tier,
    g.direction,
    COUNT(*) AS n,
    ROUND(AVG(CAST(g.hit AS INT64)) * 100, 1) AS hr,
    ROUND(AVG(g.edge), 2) AS avg_edge
FROM graded g
JOIN regime_labels r ON g.game_date = r.game_date
WHERE r.regime != 'asb'
GROUP BY r.regime, g.tier, g.direction
HAVING COUNT(*) >= 10
ORDER BY
    CASE r.regime
        WHEN 'normal' THEN 1
        WHEN 'pre_deadline' THEN 2
        WHEN 'trade_deadline' THEN 3
        WHEN 'post_deadline' THEN 4
        WHEN 'post_asb' THEN 5
    END,
    g.tier, g.direction
