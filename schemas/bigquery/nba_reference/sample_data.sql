-- File: schemas/bigquery/nba_reference/sample_data.sql
-- Description: Sample data for NBA reference tables to bootstrap the system
-- Created: 2025-01-20
-- Updated: 2025-01-23 - Fixed timestamp fields and added historical name changes
-- Purpose: Insert initial sample aliases and test data for system validation

-- =============================================================================
-- Sample Data for Testing and Bootstrapping
-- =============================================================================

-- Insert sample aliases for common name variations and historical changes
INSERT INTO `nba-props-platform.nba_reference.player_aliases` VALUES
-- Historical name changes (Basketball Reference shows new name for all seasons)
('kjmartin', 'kenyonmartinjr', 'KJ Martin', 'Kenyon Martin Jr.', 'historical_name_change', 'name_change_between_seasons', TRUE, 'Player changed name from Kenyon Martin Jr. to KJ Martin between 2022-23 seasons. BR shows new name retroactively.', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- BDL/API source variations (formal vs informal names)
('nicolasclaxton', 'nicclaxton', 'Nicolas Claxton', 'Nic Claxton', 'source_variation', 'bdl', TRUE, 'BDL uses formal first name', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- Suffix handling differences between sources
('reggiebullockjr', 'reggiebullock', 'Reggie Bullock Jr.', 'Reggie Bullock', 'suffix_difference', 'bdl', TRUE, 'Suffix handling difference between sources', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('charliebrownjr', 'charliebrown', 'Charlie Brown Jr.', 'Charlie Brown', 'suffix_difference', 'multiple', TRUE, 'Common suffix variation across sources', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('michaelporterjr', 'michaelporterjr', 'Michael Porter Jr.', 'Michael Porter Jr.', 'suffix_difference', 'multiple', TRUE, 'Period handling in suffix', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- Period/punctuation handling in initials
('pjtucker', 'pjtucker', 'P.J. Tucker', 'P.J. Tucker', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('tjmcconnell', 'tjmcconnell', 'T.J. McConnell', 'T.J. McConnell', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('ojanisby', 'ojanisby', 'O.J. Anisby', 'O.J. Anisby', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('rjbarrett', 'rjbarrett', 'R.J. Barrett', 'R.J. Barrett', 'punctuation', 'multiple', TRUE, 'Period handling in initials', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- International/accent mark variations
('niklavucevic', 'nikolavucevic', 'Nikla Vučević', 'Nikola Vucevic', 'diacritics', 'multiple', TRUE, 'Accent mark handling differences', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- Common nickname variations
('williamsmckennie', 'westmckennie', 'William McKennie', 'Weston McKennie', 'nickname', 'multiple', TRUE, 'First name nickname variation', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());

-- Insert sample unresolved names for testing the review workflow
INSERT INTO `nba-props-platform.nba_reference.unresolved_player_names` VALUES
-- Test cases for manual review workflow
('bdl', 'Test Player', 'testplayer', CURRENT_DATE(), CURRENT_DATE(), 'LAL', '2024-25', 1, ['20250120_LAL_GSW'], 'pending', NULL, NULL, 'Sample unresolved name for testing', NULL, NULL, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('espn', 'Unknown Rookie', 'unknownrookie', CURRENT_DATE(), CURRENT_DATE(), 'BOS', '2024-25', 3, ['20250120_BOS_MIA', '20250121_BOS_NYK'], 'pending', NULL, NULL, 'Testing multiple occurrences', NULL, NULL, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- Basketball Reference player who appears on rosters but never played (legitimate unresolved)
('basketball_reference', 'Practice Squad Player', 'practicesquadplayer', CURRENT_DATE(), CURRENT_DATE(), 'MIA', '2024-25', 1, [], 'pending', NULL, NULL, 'Found in roster data but no game appearances', NULL, NULL, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());

-- =============================================================================
-- Validation Queries (for testing after data load)
-- =============================================================================

-- Test alias resolution (uncomment to run)
-- SELECT 
--     alias_display,
--     nba_canonical_display,
--     alias_type,
--     alias_source,
--     notes
-- FROM `nba-props-platform.nba_reference.player_aliases`
-- WHERE is_active = TRUE
-- ORDER BY alias_type, alias_source, alias_display;

-- Test historical name change alias specifically
-- SELECT 
--     alias_display as 'BR Name',
--     nba_canonical_display as 'NBA Gamebook Name',
--     notes
-- FROM `nba-props-platform.nba_reference.player_aliases`
-- WHERE alias_type = 'historical_name_change';

-- Test unresolved queue
-- SELECT 
--     source,
--     original_name,
--     team_abbr,
--     season,
--     occurrences,
--     status,
--     notes
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- ORDER BY occurrences DESC;

-- Test data quality summary
-- SELECT * FROM `nba-props-platform.nba_reference.data_quality_summary`;

-- =============================================================================
-- Additional Historical Name Changes to Add (for reference)
-- =============================================================================

-- Add these manually based on your actual data analysis:
-- 
-- Other players who may have changed names:
-- ('newname', 'oldname', 'New Name', 'Old Name', 'historical_name_change', 'name_change_between_seasons', TRUE, 'Player changed name between YYYY-YY seasons', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
--
-- International players with multiple name formats:
-- ('shortname', 'fullname', 'Short Name', 'Full International Name', 'cultural_variation', 'multiple', TRUE, 'Cultural name format differences', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

-- =============================================================================
-- Maintenance and Cleanup Commands
-- =============================================================================

-- Remove test data (run these commands to clean up test entries):
-- DELETE FROM `nba-props-platform.nba_reference.unresolved_player_names` WHERE original_name IN ('Test Player', 'Unknown Rookie', 'Practice Squad Player');

-- Deactivate old aliases instead of deleting them:
-- UPDATE `nba-props-platform.nba_reference.player_aliases` 
-- SET is_active = FALSE, processed_at = CURRENT_TIMESTAMP()
-- WHERE alias_display = 'Old Player Name';

-- Add new aliases without disrupting existing ones:
-- INSERT INTO `nba-props-platform.nba_reference.player_aliases` VALUES
-- ('newalias', 'canonicalname', 'New Alias', 'Canonical Name', 'alias_type', 'source', TRUE, 'Description', 'manual_setup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());

-- =============================================================================
-- Expected Outcomes After Processor Run
-- =============================================================================

-- With the KJ Martin alias in place, the processor should:
-- 1. Create registry entry for "kenyonmartinjr" from 2021-22 gamebook data
-- 2. Find "kjmartin" in Basketball Reference 2021-22 roster data
-- 3. Check aliases and find kjmartin -> kenyonmartinjr mapping
-- 4. NOT create an unresolved record for "kjmartin"
-- 5. Successfully enhance the registry record with BR roster data

-- Validation query to confirm this works:
-- SELECT 
--     r.player_name,
--     r.player_lookup,
--     r.team_abbr,
--     r.season,
--     r.jersey_number,
--     r.position,
--     'Found via alias resolution' as resolution_method
-- FROM `nba-props-platform.nba_reference.nba_players_registry` r
-- WHERE r.player_lookup = 'kenyonmartinjr'
--   AND r.jersey_number IS NOT NULL  -- Should be enhanced via alias resolution