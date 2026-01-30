-- =============================================================================
-- PATCH: Fix Feature Store L5/L10 Values from Player Daily Cache
-- Date: 2026-01-29
-- Author: Claude Code
-- =============================================================================
--
-- BACKGROUND:
-- The ml_feature_store_v2 table has incorrect L5 (features[0]) and L10
-- (features[1]) values for the 2024-25 season. These values incorrectly
-- include the current game's stats instead of being computed BEFORE the game.
--
-- The player_daily_cache table has the correct values computed properly.
-- This patch updates only the mismatched records (~11,000 of ~25,000).
--
-- APPROACH:
-- 1. Create audit infrastructure
-- 2. Backup affected records
-- 3. Record before/after values for audit trail
-- 4. Apply MERGE to update only mismatched records
-- 5. Verify fix
--
-- =============================================================================

-- =============================================================================
-- STEP 1: CREATE AUDIT TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba_predictions.feature_store_patch_audit` (
  patch_id STRING NOT NULL,
  patch_date TIMESTAMP NOT NULL,
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  old_l5 FLOAT64,
  new_l5 FLOAT64,
  old_l10 FLOAT64,
  new_l10 FLOAT64,
  l5_diff FLOAT64,
  l10_diff FLOAT64
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS(
  description='Audit trail for feature store patches'
);

-- =============================================================================
-- STEP 2: CREATE BACKUP TABLE
-- =============================================================================

CREATE TABLE `nba_predictions.ml_feature_store_v2_backup_20260129` AS
SELECT fs.*
FROM `nba_predictions.ml_feature_store_v2` fs
JOIN `nba_precompute.player_daily_cache` c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date BETWEEN '2024-10-01' AND '2025-06-30'
  AND (ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) >= 0.1
       OR ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) >= 0.1);

-- =============================================================================
-- STEP 3: INSERT AUDIT RECORDS
-- =============================================================================

INSERT INTO `nba_predictions.feature_store_patch_audit`
SELECT
  'PATCH_2026-01-29_L5L10_FROM_CACHE' as patch_id,
  CURRENT_TIMESTAMP() as patch_date,
  fs.player_lookup,
  fs.game_date,
  fs.features[OFFSET(0)] as old_l5,
  c.points_avg_last_5 as new_l5,
  fs.features[OFFSET(1)] as old_l10,
  c.points_avg_last_10 as new_l10,
  c.points_avg_last_5 - fs.features[OFFSET(0)] as l5_diff,
  c.points_avg_last_10 - fs.features[OFFSET(1)] as l10_diff
FROM `nba_predictions.ml_feature_store_v2` fs
JOIN `nba_precompute.player_daily_cache` c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date BETWEEN '2024-10-01' AND '2025-06-30'
  AND (ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) >= 0.1
       OR ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) >= 0.1);

-- =============================================================================
-- STEP 4: APPLY PATCH VIA MERGE
-- =============================================================================

MERGE `nba_predictions.ml_feature_store_v2` AS target
USING (
  SELECT
    fs.player_lookup,
    fs.game_date,
    -- Rebuild features array with corrected L5/L10
    ARRAY_CONCAT(
      [CAST(c.points_avg_last_5 AS FLOAT64), CAST(c.points_avg_last_10 AS FLOAT64)],
      ARRAY(SELECT elem FROM UNNEST(fs.features) elem WITH OFFSET pos WHERE pos >= 2 ORDER BY pos)
    ) as corrected_features
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
  WHERE fs.game_date BETWEEN '2024-10-01' AND '2025-06-30'
    AND (ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) >= 0.1
         OR ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) >= 0.1)
) AS source
ON target.player_lookup = source.player_lookup AND target.game_date = source.game_date
WHEN MATCHED THEN
  UPDATE SET
    features = source.corrected_features,
    updated_at = CURRENT_TIMESTAMP();

-- =============================================================================
-- STEP 5: VERIFICATION QUERIES
-- =============================================================================

-- 5a. Verify match rate is now ~100%
WITH comparison AS (
  SELECT
    fs.player_lookup,
    fs.game_date,
    ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1 as l5_match,
    ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) < 0.1 as l10_match
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
  WHERE fs.game_date BETWEEN '2024-10-01' AND '2025-06-30'
)
SELECT
  COUNT(*) as total,
  COUNTIF(l5_match) as l5_matches,
  ROUND(100.0 * COUNTIF(l5_match) / COUNT(*), 2) as l5_match_pct,
  COUNTIF(l10_match) as l10_matches,
  ROUND(100.0 * COUNTIF(l10_match) / COUNT(*), 2) as l10_match_pct
FROM comparison;

-- 5b. Spot check: Wembanyama Jan 15, 2025 should now be 22.2
SELECT
  fs.player_lookup,
  fs.game_date,
  fs.features[OFFSET(0)] as l5_value,
  c.points_avg_last_5 as cache_l5,
  fs.features[OFFSET(1)] as l10_value,
  c.points_avg_last_10 as cache_l10
FROM `nba_predictions.ml_feature_store_v2` fs
JOIN `nba_precompute.player_daily_cache` c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.player_lookup LIKE '%wembanyama%'
  AND fs.game_date = '2025-01-15';

-- 5c. Audit summary
SELECT
  patch_id,
  COUNT(*) as records_patched,
  ROUND(AVG(ABS(l5_diff)), 2) as avg_l5_diff,
  ROUND(MAX(ABS(l5_diff)), 2) as max_l5_diff,
  ROUND(AVG(ABS(l10_diff)), 2) as avg_l10_diff,
  ROUND(MAX(ABS(l10_diff)), 2) as max_l10_diff
FROM `nba_predictions.feature_store_patch_audit`
WHERE patch_id = 'PATCH_2026-01-29_L5L10_FROM_CACHE'
GROUP BY patch_id;

-- =============================================================================
-- ROLLBACK (IF NEEDED)
-- =============================================================================
-- If issues are found, restore from backup:
--
-- MERGE `nba_predictions.ml_feature_store_v2` AS target
-- USING `nba_predictions.ml_feature_store_v2_backup_20260129` AS source
-- ON target.player_lookup = source.player_lookup AND target.game_date = source.game_date
-- WHEN MATCHED THEN
--   UPDATE SET features = source.features, updated_at = source.updated_at;
