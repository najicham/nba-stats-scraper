# Historical Data Validation & Backfill Guide

**Purpose:** Validate historical data completeness and identify dates needing backfill
**Created:** January 21, 2026
**Updated:** January 21, 2026 (corrected table names)
**Use Case:** Give this to another Claude Code session to check data gaps

---

## Important: Actual Table Names

The BigQuery schema uses these datasets and tables:

| Dataset | Tables | Purpose |
|---------|--------|---------|
| `nba_raw` | `bdl_player_boxscores`, `nbac_gamebook_player_stats`, `espn_scoreboard` | Phase 1 raw data |
| `nba_analytics` | `player_game_summary`, `team_defense_game_summary`, `team_offense_game_summary` | Phase 2/3 processed |
| `nba_precompute` | `player_composite_factors`, `player_daily_cache`, `player_shot_zone_analysis` | Phase 4 precomputed |

**Note:** `espn_scoreboard` only has data through June 2025. For current season, use `nbac_gamebook_player_stats` as source of truth for games.

---

## Quick Start for AI Assistant

If you're an AI assistant helping with data validation, follow these steps:

### Step 1: Check Date Range & Recent Data
```sql
-- Check what recent data exists across key tables
SELECT
  'bdl_player_boxscores' as table_name,
  COUNT(DISTINCT game_id) as distinct_games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

UNION ALL

SELECT
  'nbac_gamebook_player_stats' as table_name,
  COUNT(DISTINCT game_id) as distinct_games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

UNION ALL

SELECT
  'player_game_summary' as table_name,
  COUNT(DISTINCT game_id) as distinct_games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

UNION ALL

SELECT
  'player_composite_factors' as table_name,
  COUNT(DISTINCT game_date) as distinct_games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

### Step 2: Compare Data Across All Phases (Day by Day)
```sql
-- Main comparison query: BDL vs NBAC vs Analytics vs Precompute
WITH bdl AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
nbac AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
pgs AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
pcf AS (
  SELECT game_date, 1 as has_pcf
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
all_dates AS (
  SELECT DISTINCT game_date FROM bdl
  UNION DISTINCT SELECT DISTINCT game_date FROM nbac
  UNION DISTINCT SELECT DISTINCT game_date FROM pgs
)
SELECT
  d.game_date,
  COALESCE(bdl.games, 0) as bdl_games,
  COALESCE(nbac.games, 0) as nbac_games,
  COALESCE(pgs.games, 0) as pgs_games,
  CASE WHEN pcf.has_pcf = 1 THEN 'Y' ELSE 'N' END as has_composite_factors,
  CASE
    WHEN ABS(COALESCE(bdl.games,0) - COALESCE(nbac.games,0)) > 0 THEN 'BDL/NBAC mismatch'
    WHEN ABS(COALESCE(pgs.games,0) - COALESCE(nbac.games,0)) > 0 THEN 'Analytics gap'
    WHEN pcf.has_pcf IS NULL THEN 'Missing composite factors'
    ELSE 'OK'
  END as status
FROM all_dates d
LEFT JOIN bdl ON d.game_date = bdl.game_date
LEFT JOIN nbac ON d.game_date = nbac.game_date
LEFT JOIN pgs ON d.game_date = pgs.game_date
LEFT JOIN pcf ON d.game_date = pcf.game_date
ORDER BY d.game_date DESC;
```

### Step 3: Find Specific Missing Games
```sql
-- Find games in NBAC that are NOT in BDL (BDL API gaps)
WITH nbac_games AS (
  SELECT DISTINCT
    game_id,
    game_date,
    CASE WHEN game_id LIKE '202%' THEN SPLIT(game_id, '_')[SAFE_OFFSET(1)] ELSE 'Unknown' END as away_team,
    CASE WHEN game_id LIKE '202%' THEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] ELSE 'Unknown' END as home_team
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
bdl_games AS (
  SELECT DISTINCT game_id
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
  n.game_date,
  n.game_id,
  n.away_team,
  n.home_team,
  CONCAT(n.away_team, ' @ ', n.home_team) as matchup
FROM nbac_games n
LEFT JOIN bdl_games b ON n.game_id = b.game_id
WHERE b.game_id IS NULL
ORDER BY n.game_date DESC;
```

### Step 4: Find Games Missing from Analytics
```sql
-- Find games in raw (NBAC) that are NOT in analytics (player_game_summary)
WITH nbac_games AS (
  SELECT DISTINCT game_id, game_date
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
analytics_games AS (
  SELECT DISTINCT game_id
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
  n.game_date,
  n.game_id,
  'Missing from player_game_summary' as issue
FROM nbac_games n
LEFT JOIN analytics_games a ON n.game_id = a.game_id
WHERE a.game_id IS NULL
ORDER BY n.game_date DESC;
```

### Step 5: Check Precompute Coverage
```sql
-- Check player_daily_cache and player_composite_factors coverage
SELECT
  cache_date as game_date,
  COUNT(DISTINCT player_lookup) as players_in_cache
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC;
```

---

## Step 6: Execute Backfill

### For Phase 1 (Raw Data Scraping)

If BDL is missing games but NBAC has them, this is a BallDontLie API issue. Contact their support.

If both are missing, trigger scrapers:
```bash
# Trigger Phase 1 scrapers for specific date
gcloud functions call phase1-scrapers-prod \
  --data '{"date":"2026-01-15","force":true}'
```

### For Phase 2/3 (Analytics Processing)

If raw data exists but analytics is missing:
```bash
# Trigger Phase 2/3 processors
gcloud functions call phase2-to-phase3-prod \
  --data '{"date":"2026-01-15","force":true}'
```

### For Phase 4 (Precompute)

```bash
# Trigger self-heal check (will detect and heal Phase 4)
gcloud functions call self-heal-check-prod

# Or trigger Phase 4 processors directly for specific date
gcloud functions call phase3-to-phase4-prod \
  --data '{"date":"2026-01-15","force":true}'
```

---

## Common Patterns

### Pattern 1: BDL Missing West Coast Games
**Symptom:** BDL has fewer games than NBAC, mostly GSW/LAL/LAC/SAC/POR home games
**Cause:** BallDontLie API data availability issue
**Solution:** Report to BDL support; NBAC data will cover analytics needs

### Pattern 2: Raw Data Exists but Analytics Missing
**Symptom:** NBAC has games, but player_game_summary doesn't
**Cause:** Phase 2/3 processor didn't run
**Solution:** Trigger phase2-to-phase3 processor for that date

### Pattern 3: Missing Composite Factors
**Symptom:** Analytics exists, but player_composite_factors missing for date
**Cause:** Phase 4 processor didn't run
**Solution:** Trigger phase3-to-phase4 processor for that date

---

## Quick Commands for AI Assistants

When given this document, an AI assistant should:

1. **Run Step 1 & 2** to get overview of data coverage
2. **Run Step 3 & 4** to identify specific gaps
3. **Categorize gaps** by pattern (BDL issue, analytics gap, precompute gap)
4. **Recommend actions:**
   - BDL gaps: Prepare email for BDL support
   - Analytics gaps: Trigger Phase 2/3 backfill
   - Precompute gaps: Trigger Phase 4 backfill

---

## References

- **Self-Heal Function:** `orchestration/cloud_functions/self_heal/main.py`
- **Phase 2→3 Trigger:** `orchestration/cloud_functions/phase2_to_phase3/main.py`
- **Phase 3→4 Trigger:** `orchestration/cloud_functions/phase3_to_phase4/main.py`
- **BDL Scraper:** `scrapers/balldontlie/bdl_box_scores.py`
- **Validation Report (Jan 21):** `2026-01-21-DATA-VALIDATION-REPORT.md`

---

**Last Updated:** January 21, 2026
**Maintained By:** Data Engineering Team
