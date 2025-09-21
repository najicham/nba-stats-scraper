-- File: schemas/bigquery/nba_reference/sample_data.sql
-- Description: Sample data for NBA reference tables to bootstrap the system
-- Created: 2025-01-20
-- Purpose: Insert initial sample aliases and test data for system validation

-- =============================================================================
-- Sample Data for Testing and Bootstrapping
-- =============================================================================

-- Insert sample aliases for common name variations
INSERT INTO `nba-props-platform.nba_reference.player_aliases` VALUES
('kenyonmartinjr', 'kjmartin', 'Kenyon Martin Jr.', 'KJ Martin', 'source_variation', 'bdl', TRUE, 'BDL uses full formal name', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('nicolasclaxton', 'nicclaxton', 'Nicolas Claxton', 'Nic Claxton', 'nickname', 'bdl', TRUE, 'BDL uses formal first name', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('reggiebullockjr', 'reggiebullock', 'Reggie Bullock Jr.', 'Reggie Bullock', 'suffix_difference', 'bdl', TRUE, 'Suffix handling difference', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('charliebrownjr', 'charliebrown', 'Charlie Brown Jr.', 'Charlie Brown', 'suffix_difference', 'multiple', TRUE, 'Common suffix variation across sources', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('pjtucker', 'pjtucker', 'P.J. Tucker', 'P.J. Tucker', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('tjmcconnell', 'tjmcconnell', 'T.J. McConnell', 'T.J. McConnell', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('michaelporterjr', 'michaelporterjr', 'Michael Porter Jr.', 'Michael Porter Jr.', 'punctuation', 'multiple', TRUE, 'Period handling in suffix', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('ojanisby', 'ojanisby', 'O.J. Anisby', 'O.J. Anisby', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
('rjbarrett', 'rjbarrett', 'R.J. Barrett', 'R.J. Barrett', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP());

-- Insert sample unresolved names for testing the review workflow
INSERT INTO `nba-props-platform.nba_reference.unresolved_player_names` VALUES
('bdl', 'Test Player', 'testplayer', CURRENT_DATE(), CURRENT_DATE(), 'LAL', '2024-25', 1, ['20250120_LAL_GSW'], 'pending', NULL, NULL, 'Sample unresolved name for testing', NULL, NULL, CURRENT_DATE(), CURRENT_DATE()),
('espn', 'Unknown Rookie', 'unknownrookie', CURRENT_DATE(), CURRENT_DATE(), 'BOS', '2024-25', 3, ['20250120_BOS_MIA', '20250121_BOS_NYK'], 'pending', NULL, NULL, 'Testing multiple occurrences', NULL, NULL, CURRENT_DATE(), CURRENT_DATE());

-- =============================================================================
-- Validation Queries (for testing after data load)
-- =============================================================================

-- Test alias resolution
-- SELECT 
--     alias_display,
--     nba_canonical_display,
--     alias_type,
--     alias_source
-- FROM `nba-props-platform.nba_reference.player_aliases`
-- WHERE is_active = TRUE
-- ORDER BY alias_source, alias_display;

-- Test unresolved queue
-- SELECT 
--     source,
--     original_name,
--     team_abbr,
--     season,
--     occurrences,
--     status
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- ORDER BY occurrences DESC;

-- Test data quality summary
-- SELECT * FROM `nba-props-platform.nba_reference.data_quality_summary`;

-- =============================================================================
-- Common Name Variations to Add (for reference)
-- =============================================================================

-- Add these aliases manually after initial setup based on your actual data:
-- 
-- ESPN variations:
-- ('kristapsporzingis', 'kristapsporzingis', 'Kristaps Porzingis', 'Kristaps Porzingis', 'spelling_variation', 'espn', TRUE, 'ESPN alternate spelling', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
-- 
-- Historical name changes:
-- ('ronbaker', 'ronbaker', 'Ron Baker', 'Ron Baker', 'historical', 'multiple', FALSE, 'Player no longer active', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),
-- 
-- International players with accent marks:
-- ('niklavucevic', 'niklavucevic', 'Nikla Vučević', 'Nikola Vucevic', 'diacritics', 'multiple', TRUE, 'Accent mark handling', 'manual_setup', CURRENT_DATE(), CURRENT_TIMESTAMP()),

-- =============================================================================
-- Maintenance and Cleanup Commands
-- =============================================================================

-- Remove test data (run these commands to clean up test entries):
-- DELETE FROM `nba-props-platform.nba_reference.unresolved_player_names` WHERE original_name IN ('Test Player', 'Unknown Rookie');

-- Deactivate old aliases instead of deleting them:
-- UPDATE `nba-props-platform.nba_reference.player_aliases` 
-- SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP()
-- WHERE alias_display = 'Old Player Name';