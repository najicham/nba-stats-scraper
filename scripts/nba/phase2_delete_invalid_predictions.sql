-- PHASE 2: DELETE INVALID PREDICTIONS
-- Date: 2026-01-16
-- Purpose: Remove all placeholder line predictions from database
-- CRITICAL: Run this AFTER Phase 1 deployment (code fixes must be live first)
-- Estimated time: 5-10 minutes

-- ============================================================================
-- STEP 1: CREATE BACKUP ARCHIVE (SAFETY - CAN ROLLBACK)
-- ============================================================================

CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.deleted_placeholder_predictions_20260116` AS
SELECT
    *,
    CURRENT_TIMESTAMP() as deleted_at,
    'Session 76 - Placeholder elimination' as deletion_reason
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE
    -- XGBoost V1: All predictions (100% placeholders)
    system_id = 'xgboost_v1'
    AND game_date BETWEEN '2025-11-19' AND '2026-01-10'

    OR

    -- Jan 9-10, 2026: All systems (100% placeholders on Jan 9, 63% on Jan 10)
    game_date IN ('2026-01-09', '2026-01-10')

    OR

    -- Nov-Dec 2025: Predictions WITHOUT matching props (will not backfill)
    (
        game_date BETWEEN '2025-11-19' AND '2025-12-19'
        AND current_points_line = 20.0
        AND player_lookup NOT IN (
            -- Only keep predictions where we HAVE historical props
            SELECT DISTINCT player_lookup
            FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
            WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
        )
    );

-- Verify backup created
SELECT
    'BACKUP CREATED' as status,
    COUNT(*) as backed_up_predictions,
    COUNT(DISTINCT game_date) as dates,
    COUNT(DISTINCT system_id) as systems,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM `nba-props-platform.nba_predictions.deleted_placeholder_predictions_20260116`;

-- Expected: ~8,000-10,000 predictions (XGBoost V1 + Jan 9-10 + Nov-Dec unmatched)

-- ============================================================================
-- STEP 2: DELETE XGBOOST V1 PREDICTIONS (6,548 predictions)
-- ============================================================================

-- XGBoost V1 used mock model - entire dataset is invalid
DELETE FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'xgboost_v1'
    AND game_date BETWEEN '2025-11-19' AND '2026-01-10';

-- Verify deletion
SELECT
    'XGBOOST V1 DELETED' as status,
    COUNT(*) as remaining_xgboost_v1
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'xgboost_v1'
    AND game_date BETWEEN '2025-11-19' AND '2026-01-10';
-- Expected: 0

-- ============================================================================
-- STEP 3: DELETE JAN 9-10, 2026 PREDICTIONS (1,570 predictions)
-- ============================================================================

-- Jan 9-10 had 100% and 63% placeholders - delete all for clean regeneration
DELETE FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date IN ('2026-01-09', '2026-01-10');

-- Verify deletion
SELECT
    'JAN 9-10 DELETED' as status,
    COUNT(*) as remaining_jan_9_10
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date IN ('2026-01-09', '2026-01-10');
-- Expected: 0

-- ============================================================================
-- STEP 4: DELETE NOV-DEC PREDICTIONS WITHOUT MATCHING PROPS
-- ============================================================================

-- Keep predictions that CAN be backfilled (have historical props)
-- Delete predictions that CANNOT be backfilled (no historical props)
DELETE FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
    AND current_points_line = 20.0
    AND player_lookup NOT IN (
        -- Players with available props (will backfill these in Phase 3)
        SELECT DISTINCT player_lookup
        FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
        WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
    );

-- Verify what's left for backfill
SELECT
    'NOV-DEC READY FOR BACKFILL' as status,
    COUNT(*) as predictions_to_backfill,
    COUNT(DISTINCT game_date) as dates,
    COUNT(DISTINCT player_lookup) as players,
    COUNT(DISTINCT system_id) as systems
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
    AND current_points_line = 20.0;
-- Expected: ~15,000 predictions (most of Nov-Dec dataset)

-- ============================================================================
-- STEP 5: SUMMARY REPORT
-- ============================================================================

-- Before/After comparison
SELECT
    'SUMMARY' as report,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.deleted_placeholder_predictions_20260116`) as deleted_total,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.player_prop_predictions` WHERE current_points_line = 20.0) as remaining_placeholders,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.player_prop_predictions` WHERE game_date BETWEEN '2025-11-19' AND '2026-01-15') as remaining_predictions_nov_jan;

-- Breakdown by category
SELECT
    CASE
        WHEN system_id = 'xgboost_v1' THEN 'XGBoost V1 (deleted)'
        WHEN game_date IN ('2026-01-09', '2026-01-10') THEN 'Jan 9-10 (deleted)'
        WHEN game_date BETWEEN '2025-11-19' AND '2025-12-19' THEN 'Nov-Dec (deleted - no props)'
        ELSE 'Other'
    END as category,
    COUNT(*) as count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM `nba-props-platform.nba_predictions.deleted_placeholder_predictions_20260116`
GROUP BY category
ORDER BY count DESC;

-- ============================================================================
-- ROLLBACK PROCEDURE (IF NEEDED)
-- ============================================================================

/*
-- ONLY RUN IF YOU NEED TO RESTORE DELETED DATA:

INSERT INTO `nba-props-platform.nba_predictions.player_prop_predictions`
SELECT * EXCEPT(deleted_at, deletion_reason)
FROM `nba-props-platform.nba_predictions.deleted_placeholder_predictions_20260116`;

-- Verify restoration:
SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date BETWEEN '2025-11-19' AND '2026-01-10';
*/

-- ============================================================================
-- END OF PHASE 2
-- ============================================================================

-- Next step: Run Phase 3 backfill script to update Nov-Dec predictions with real lines
