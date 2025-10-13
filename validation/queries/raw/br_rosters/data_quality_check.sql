-- ============================================================================
-- File: validation/queries/raw/br_rosters/data_quality_check.sql
-- Purpose: Validate data completeness, name normalization, and field quality
-- Usage: Run after backfills or when investigating data quality issues
-- ============================================================================
-- Expected Results:
--   - NULL counts should be minimal (0 for critical fields)
--   - Name normalization should be 100% (player_lookup always present)
--   - Position, height, weight should be mostly populated
--   - Jersey numbers can have some NULLs (players who changed teams)
-- ============================================================================

WITH
roster_data AS (
  SELECT
    season_year,
    season_display,
    team_abbrev,
    player_full_name,
    player_last_name,
    player_normalized,
    player_lookup,
    position,
    jersey_number,
    height,
    weight,
    birth_date,
    college,
    experience_years,
    first_seen_date,
    last_scraped_date
  FROM `nba-props-platform.nba_raw.br_rosters_current`
  WHERE season_year BETWEEN 2021 AND 2024
),

-- Overall completeness metrics
completeness_summary AS (
  SELECT
    COUNT(*) as total_records,
    
    -- Critical fields (should be 100%)
    COUNT(CASE WHEN season_year IS NULL THEN 1 END) as null_season_year,
    COUNT(CASE WHEN team_abbrev IS NULL THEN 1 END) as null_team_abbrev,
    COUNT(CASE WHEN player_full_name IS NULL THEN 1 END) as null_full_name,
    COUNT(CASE WHEN player_lookup IS NULL THEN 1 END) as null_player_lookup,
    
    -- Important fields (should be >95%)
    COUNT(CASE WHEN player_last_name IS NULL THEN 1 END) as null_last_name,
    COUNT(CASE WHEN position IS NULL THEN 1 END) as null_position,
    
    -- Optional fields (can have some NULLs)
    COUNT(CASE WHEN jersey_number IS NULL THEN 1 END) as null_jersey,
    COUNT(CASE WHEN height IS NULL THEN 1 END) as null_height,
    COUNT(CASE WHEN weight IS NULL THEN 1 END) as null_weight,
    COUNT(CASE WHEN birth_date IS NULL THEN 1 END) as null_birth_date,
    COUNT(CASE WHEN college IS NULL THEN 1 END) as null_college,
    COUNT(CASE WHEN experience_years IS NULL THEN 1 END) as null_experience,
    
    -- Date tracking
    COUNT(CASE WHEN first_seen_date IS NULL THEN 1 END) as null_first_seen,
    COUNT(CASE WHEN last_scraped_date IS NULL THEN 1 END) as null_last_scraped
  FROM roster_data
),

-- Name normalization quality check
name_quality AS (
  SELECT
    COUNT(*) as total_records,
    COUNT(CASE WHEN player_normalized IS NULL OR player_normalized = '' THEN 1 END) as bad_normalized,
    COUNT(CASE WHEN player_lookup IS NULL OR player_lookup = '' THEN 1 END) as bad_lookup,
    COUNT(CASE WHEN LENGTH(player_lookup) < 5 THEN 1 END) as suspiciously_short_lookup,
    COUNT(CASE WHEN player_lookup LIKE '% %' THEN 1 END) as lookup_has_spaces,
    COUNT(CASE WHEN UPPER(player_lookup) != player_lookup AND LOWER(player_lookup) != player_lookup THEN 1 END) as lookup_mixed_case
  FROM roster_data
),

-- Position validation
position_quality AS (
  SELECT
    position,
    COUNT(*) as count,
    COUNT(DISTINCT player_lookup) as unique_players
  FROM roster_data
  WHERE position IS NOT NULL
  GROUP BY position
),

-- Experience year distribution
experience_distribution AS (
  SELECT
    season_display,
    COUNT(CASE WHEN experience_years = 0 THEN 1 END) as rookies,
    COUNT(CASE WHEN experience_years BETWEEN 1 AND 3 THEN 1 END) as young_players,
    COUNT(CASE WHEN experience_years BETWEEN 4 AND 7 THEN 1 END) as mid_career,
    COUNT(CASE WHEN experience_years BETWEEN 8 AND 12 THEN 1 END) as veterans,
    COUNT(CASE WHEN experience_years > 12 THEN 1 END) as old_veterans,
    COUNT(CASE WHEN experience_years IS NULL THEN 1 END) as unknown_experience
  FROM roster_data
  GROUP BY season_display
)

-- Output completeness summary
SELECT
  'COMPLETENESS' as check_type,
  CAST(total_records AS STRING) as metric,
  CAST(null_season_year AS STRING) as value,
  CAST(null_team_abbrev AS STRING) as value2,
  CAST(null_full_name AS STRING) as value3,
  CAST(null_player_lookup AS STRING) as value4,
  CAST(null_last_name AS STRING) as value5,
  CAST(null_position AS STRING) as value6,
  'Total | Season nulls | Team nulls | Name nulls | Lookup nulls | LastName nulls | Position nulls' as description
FROM completeness_summary

UNION ALL

SELECT
  'COMPLETENESS_2' as check_type,
  'optional_fields' as metric,
  CAST(null_jersey AS STRING) as value,
  CAST(null_height AS STRING) as value2,
  CAST(null_weight AS STRING) as value3,
  CAST(null_birth_date AS STRING) as value4,
  CAST(null_college AS STRING) as value5,
  CAST(null_experience AS STRING) as value6,
  'Jersey | Height | Weight | Birth date | College | Experience (some nulls OK)' as description
FROM completeness_summary

UNION ALL

SELECT
  'DATE_TRACKING' as check_type,
  'date_fields' as metric,
  CAST(null_first_seen AS STRING) as value,
  CAST(null_last_scraped AS STRING) as value2,
  '' as value3,
  '' as value4,
  '' as value5,
  '' as value6,
  'Null first_seen | Null last_scraped (should both be 0)' as description
FROM completeness_summary

UNION ALL

-- Name normalization quality
SELECT
  'NAME_QUALITY' as check_type,
  CAST(total_records AS STRING) as metric,
  CAST(bad_normalized AS STRING) as value,
  CAST(bad_lookup AS STRING) as value2,
  CAST(suspiciously_short_lookup AS STRING) as value3,
  CAST(lookup_has_spaces AS STRING) as value4,
  CAST(lookup_mixed_case AS STRING) as value5,
  '' as value6,
  'Total | Bad normalized | Bad lookup | Short lookup | Has spaces | Mixed case (all should be 0)' as description
FROM name_quality

UNION ALL

-- Position distribution
SELECT
  'POSITION' as check_type,
  p.position as metric,
  CAST(p.count AS STRING) as value,
  CAST(p.unique_players AS STRING) as value2,
  '' as value3,
  '' as value4,
  '' as value5,
  '' as value6,
  'Position | Total occurrences | Unique players' as description
FROM position_quality p

UNION ALL

-- Experience distribution
SELECT
  'EXPERIENCE' as check_type,
  e.season_display as metric,
  CAST(e.rookies AS STRING) as value,
  CAST(e.young_players AS STRING) as value2,
  CAST(e.mid_career AS STRING) as value3,
  CAST(e.veterans AS STRING) as value4,
  CAST(e.old_veterans AS STRING) as value5,
  CAST(e.unknown_experience AS STRING) as value6,
  'Season | Rookies (0yr) | Young (1-3yr) | Mid (4-7yr) | Vets (8-12yr) | Old vets (13+yr) | Unknown' as description
FROM experience_distribution e

ORDER BY
  check_type,
  metric;