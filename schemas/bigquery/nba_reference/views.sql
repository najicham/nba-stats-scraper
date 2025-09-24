-- File: schemas/bigquery/nba_reference/views.sql
-- Description: Views for common NBA reference data operations
-- Created: 2025-01-20
-- Updated: 2025-01-23 - Fixed UNION ALL type compatibility
-- Purpose: Provide convenient views for common name resolution and player registry queries

-- =============================================================================
-- Views for Common Operations
-- =============================================================================

-- Active aliases view for production lookups
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.active_aliases` AS
SELECT 
    alias_lookup,
    alias_display,
    nba_canonical_lookup,
    nba_canonical_display,
    alias_type,
    alias_source,
    notes,
    created_at,
    processed_at
FROM `nba-props-platform.nba_reference.player_aliases`
WHERE is_active = TRUE;

-- Current season players view
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.current_season_players` AS
SELECT 
    player_name,
    player_lookup,
    team_abbr,
    jersey_number,
    position,
    games_played,
    total_appearances,
    last_game_date,
    confidence_score
FROM `nba-props-platform.nba_reference.nba_players_registry`
WHERE season = (
    SELECT MAX(season) 
    FROM `nba-props-platform.nba_reference.nba_players_registry`
);

-- Pending review queue (prioritized)
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.review_queue` AS
SELECT 
    source,
    original_name,
    normalized_lookup,
    team_abbr,
    season,
    occurrences,
    first_seen_date,
    last_seen_date,
    example_games[SAFE_OFFSET(0)] as sample_game_id,
    -- Priority scoring for manual review
    CASE 
        WHEN occurrences >= 10 THEN 'high'
        WHEN occurrences >= 5 THEN 'medium'
        ELSE 'low'
    END as priority
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending'
ORDER BY occurrences DESC, first_seen_date ASC;

-- Data quality monitoring view (FIXED: Consistent TIMESTAMP types)
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.data_quality_summary` AS
SELECT 
    'aliases' as table_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN is_active THEN 1 END) as active_records,
    COUNT(DISTINCT alias_source) as unique_sources,
    MAX(processed_at) as last_updated  -- FIXED: Use TIMESTAMP consistently
FROM `nba-props-platform.nba_reference.player_aliases`

UNION ALL

SELECT 
    'registry' as table_name,
    COUNT(*) as total_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT season) as seasons_covered,
    MAX(processed_at) as last_updated
FROM `nba-props-platform.nba_reference.nba_players_registry`

UNION ALL

SELECT 
    'unresolved' as table_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_review,
    COUNT(DISTINCT source) as unique_sources,
    MAX(processed_at) as last_updated
FROM `nba-props-platform.nba_reference.unresolved_player_names`;

-- Player name resolution lookup view (for debugging)
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.name_resolution_debug` AS
SELECT 
    'alias' as source_type,
    alias_display as input_name,
    nba_canonical_display as resolved_name,
    alias_lookup as normalized_input,
    nba_canonical_lookup as normalized_output,
    alias_source as data_source,
    is_active,
    created_at
FROM `nba-props-platform.nba_reference.player_aliases`

UNION ALL

SELECT 
    'registry' as source_type,
    player_name as input_name,
    player_name as resolved_name,
    player_lookup as normalized_input,
    player_lookup as normalized_output,
    source_priority as data_source,
    TRUE as is_active,
    created_at
FROM `nba-props-platform.nba_reference.nba_players_registry`
WHERE season = (SELECT MAX(season) FROM `nba-props-platform.nba_reference.nba_players_registry`);

-- Team roster summary view
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.team_rosters_current` AS
SELECT 
    team_abbr,
    season,
    COUNT(*) as total_players,
    COUNT(CASE WHEN games_played > 0 THEN 1 END) as active_players,
    COUNT(CASE WHEN jersey_number IS NOT NULL THEN 1 END) as players_with_jersey,
    COUNT(CASE WHEN position IS NOT NULL THEN 1 END) as players_with_position,
    AVG(games_played) as avg_games_played,
    MAX(last_game_date) as most_recent_game
FROM `nba-props-platform.nba_reference.nba_players_registry`
WHERE season = (SELECT MAX(season) FROM `nba-props-platform.nba_reference.nba_players_registry`)
GROUP BY team_abbr, season
ORDER BY team_abbr;

-- Resolution success rate by source
CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.resolution_success_rates` AS
SELECT 
    source,
    COUNT(*) as total_attempts,
    COUNT(CASE WHEN status = 'resolved' THEN 1 END) as successful_resolutions,
    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_review,
    COUNT(CASE WHEN status = 'invalid' THEN 1 END) as marked_invalid,
    ROUND(
        SAFE_DIVIDE(
            COUNT(CASE WHEN status = 'resolved' THEN 1 END),
            COUNT(*)
        ) * 100, 1
    ) as success_rate_pct,
    MIN(first_seen_date) as earliest_attempt,
    MAX(last_seen_date) as latest_attempt
FROM `nba-props-platform.nba_reference.unresolved_player_names`
GROUP BY source
ORDER BY success_rate_pct DESC;