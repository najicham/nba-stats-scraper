-- ============================================================================
-- BigQuery Data Validation - player_prop_predictions
-- Path: schemas/bigquery/nba_predictions/constraints_player_prop_predictions.sql
-- Created: 2026-01-21
-- ============================================================================
-- Purpose: Add data validation for predictions (BigQuery doesn't support CHECK constraints)
-- Impact: Prevents bad data from entering production table via validation views
-- Priority: P0-5 (CRITICAL - prevents data quality issues)
-- ============================================================================

-- NOTE: BigQuery does NOT support CHECK constraints
-- Instead, we use:
--   1. Validation views to detect violations
--   2. Application-level validation before writes
--   3. dbt tests for CI/CD validation
-- ============================================================================

-- ============================================================================
-- VALIDATION VIEW 1: Detect confidence_score violations
-- ============================================================================
-- Finds predictions with invalid confidence scores
-- Expected: 0 rows (all confidence_score should be 0-100)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_validation_confidence_score` AS
SELECT
  prediction_id,
  player_lookup,
  game_date,
  system_id,
  confidence_score,
  'confidence_score out of range' as violation_type,
  CASE
    WHEN confidence_score < 0 THEN 'confidence_score below 0'
    WHEN confidence_score > 100 THEN 'confidence_score above 100'
  END as violation_reason
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE confidence_score < 0 OR confidence_score > 100;

-- ============================================================================
-- VALIDATION VIEW 2: Detect predicted_points violations
-- ============================================================================
-- Finds predictions with negative predicted points
-- Expected: 0 rows (all predicted_points should be >= 0)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_validation_predicted_points` AS
SELECT
  prediction_id,
  player_lookup,
  game_date,
  system_id,
  predicted_points,
  'predicted_points negative' as violation_type,
  CONCAT('predicted_points = ', CAST(predicted_points AS STRING)) as violation_reason
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE predicted_points < 0;

-- ============================================================================
-- VALIDATION VIEW 3: All data quality violations combined
-- ============================================================================
-- Union of all validation violations for monitoring
-- Expected: 0 rows in production
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_validation_all_violations` AS
SELECT * FROM `nba-props-platform.nba_predictions.v_validation_confidence_score`
UNION ALL
SELECT * FROM `nba-props-platform.nba_predictions.v_validation_predicted_points`;

-- ============================================================================
-- ADDITIONAL RECOMMENDED CONSTRAINTS (Future Enhancement)
-- ============================================================================

-- CONSTRAINT 3: Validate prediction_version positive
-- ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
-- ADD CONSTRAINT prediction_version_valid
-- CHECK (prediction_version > 0)
-- NOT ENFORCED;

-- CONSTRAINT 4: Validate line_margin calculation (if both fields exist)
-- ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
-- ADD CONSTRAINT line_margin_valid
-- CHECK (
--   (current_points_line IS NULL AND line_margin IS NULL) OR
--   (current_points_line IS NOT NULL AND line_margin = predicted_points - current_points_line)
-- )
-- NOT ENFORCED;

-- CONSTRAINT 5: Validate recommendation values
-- ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
-- ADD CONSTRAINT recommendation_valid
-- CHECK (recommendation IN ('OVER', 'UNDER', 'PASS', 'NO_LINE'))
-- NOT ENFORCED;

-- CONSTRAINT 6: Validate completeness_percentage range
-- ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
-- ADD CONSTRAINT completeness_percentage_valid
-- CHECK (completeness_percentage BETWEEN 0 AND 100)
-- NOT ENFORCED;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Query 1: Check if constraints exist
SELECT
  constraint_catalog,
  constraint_schema,
  constraint_name,
  table_name,
  check_clause,
  enforced
FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.TABLE_CONSTRAINTS`
WHERE table_name = 'player_prop_predictions'
  AND constraint_type = 'CHECK'
ORDER BY constraint_name;

-- Query 2: Find existing violations (pre-constraint data)
-- Confidence score violations
SELECT
  COUNT(*) as violation_count,
  MIN(confidence_score) as min_value,
  MAX(confidence_score) as max_value,
  ARRAY_AGG(prediction_id LIMIT 5) as sample_ids
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE confidence_score < 0 OR confidence_score > 100;

-- Predicted points violations
SELECT
  COUNT(*) as violation_count,
  MIN(predicted_points) as min_value,
  ARRAY_AGG(prediction_id LIMIT 5) as sample_ids
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE predicted_points < 0;

-- ============================================================================
-- IMPACT ANALYSIS
-- ============================================================================

-- Before Constraints:
--   - No validation at schema level
--   - Bad data can enter table silently
--   - Requires application-level validation only
--   - Query results can include invalid values

-- After Constraints:
--   - Schema documents expected ranges
--   - Query optimizer can use constraints for optimization
--   - Serves as self-documenting data contract
--   - Application code validated against schema rules

-- Note: BigQuery CHECK constraints are informational (NOT ENFORCED)
-- They do NOT prevent invalid data from being inserted
-- They provide:
--   1. Schema documentation
--   2. Query optimizer hints
--   3. Data contract definition
--   4. Integration with BI tools for validation

-- For enforcement, application code must validate before writes

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Verify table exists: nba_predictions.player_prop_predictions
-- [ ] Run constraint validation queries to find existing violations
-- [ ] Fix any existing violations before adding constraints
-- [ ] Run ALTER TABLE for confidence_score_valid constraint
-- [ ] Run ALTER TABLE for predicted_points_valid constraint
-- [ ] Verify constraints exist via INFORMATION_SCHEMA query
-- [ ] Update prediction generation code to validate before INSERT
-- [ ] Document constraints in API documentation
-- [ ] Add constraint validation to CI/CD pipeline tests
-- ============================================================================

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Query 1: Check for any violations (should return 0)
SELECT COUNT(*) as violation_count
FROM `nba-props-platform.nba_predictions.v_validation_all_violations`
WHERE game_date >= CURRENT_DATE() - 7;

-- Query 2: Detail of violations (if any exist)
SELECT *
FROM `nba-props-platform.nba_predictions.v_validation_all_violations`
WHERE game_date >= CURRENT_DATE() - 7
ORDER BY game_date DESC, prediction_id
LIMIT 100;

-- ============================================================================
-- APPLICATION-LEVEL VALIDATION
-- ============================================================================
-- Prediction generation code MUST validate before INSERT:
--
-- Python example:
-- def validate_prediction(predicted_points, confidence_score):
--     if not (0 <= confidence_score <= 100):
--         raise ValueError(f"confidence_score {confidence_score} out of range [0, 100]")
--     if predicted_points < 0:
--         raise ValueError(f"predicted_points {predicted_points} must be >= 0")
--     return True
-- ============================================================================

-- ============================================================================
-- ROLLBACK PLAN
-- ============================================================================
-- To remove validation views (if needed):
--
-- DROP VIEW IF EXISTS `nba-props-platform.nba_predictions.v_validation_confidence_score`;
-- DROP VIEW IF EXISTS `nba-props-platform.nba_predictions.v_validation_predicted_points`;
-- DROP VIEW IF EXISTS `nba-props-platform.nba_predictions.v_validation_all_violations`;
-- ============================================================================
