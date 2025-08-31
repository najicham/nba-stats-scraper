-- Check new unresolved names from yesterday
SELECT 
    resolution_id,
    team_abbr,
    original_name,
    games_affected,
    possible_matches,
    context_notes
FROM `nba_raw.name_resolutions_pending`
WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY games_affected DESC;