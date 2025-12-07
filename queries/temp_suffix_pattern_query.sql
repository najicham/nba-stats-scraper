-- Query 2: Suffix pattern matching - Find unresolved names where adding suffixes would match registry
-- This identifies cases where the difference is just a missing suffix (jr, sr, ii, iii, iv)

WITH suffixes AS (
  SELECT suffix FROM UNNEST([' jr', ' sr', ' ii', ' iii', ' iv', ' jr.', ' sr.']) AS suffix
),
unresolved AS (
  SELECT DISTINCT normalized_lookup, team_abbr, season
  FROM `nba-props-platform.nba_reference.unresolved_player_names`
  WHERE status = 'pending'
)
SELECT
  u.normalized_lookup as unresolved_name,
  CONCAT(u.normalized_lookup, s.suffix) as potential_match,
  r.player_lookup as registry_match,
  r.player_name as registry_display_name,
  u.team_abbr,
  u.season
FROM unresolved u
CROSS JOIN suffixes s
JOIN `nba-props-platform.nba_reference.nba_players_registry` r
  ON CONCAT(u.normalized_lookup, s.suffix) = r.player_lookup
LIMIT 50
