# Historical Data Validation - January 22, 2026
**Chat Purpose:** Comprehensive validation of past months data and identify backfill needs
**Expected Duration:** 2-3 hours
**Scope:** Past 30-90 days (primary focus on Jan 1-21, 2026)

---

## Your Mission

Perform a comprehensive historical data validation to:
1. Identify missing games/dates across all phases (raw, analytics, precompute)
2. Detect data quality issues (incomplete records, outliers, anomalies)
3. Categorize gaps by priority (critical, high, medium)
4. Generate a backfill priority list with specific actions

---

## Context: Known Issues

**From Recent Audit (Jan 21, 2026):**
- **33 BDL missing games** (Jan 1-21, 2026) - BallDontLie API gaps
- **76% at West Coast venues:** GSW (6), SAC (6), LAC (5), LAL (4), POR (4)
- **4 games need Phase 2/3 analytics backfill**
- **2 games need Phase 4 precompute backfill**
- **29 of 33 games:** Pipeline successfully fell back to NBAC gamebook ✅
- **Jan 15 infrastructure failure:** 8 games affected

**Known Root Causes:**
- BDL API inconsistency (especially for West Coast evening games)
- R-009 regression (zero-active-player bug) - now fixed
- Phase boundaries not validating (now fixed with phase_boundary_validator)

---

## Primary Guide

**Follow this document step-by-step:**
`/docs/08-projects/current/historical-backfill-audit/data-completeness-validation-guide.md`

This guide has 5 comprehensive steps. I'll provide the details below.

---

## Step 1: 30-Day Overview (15 minutes)

**Purpose:** Get high-level snapshot of data completeness across all phases

**Query Location:** data-completeness-validation-guide.md (Step 1)

**What to check:**
```sql
-- Check date range and record counts across key tables
SELECT
  'bdl_player_boxscores' as table_name,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(*) as total_records
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

UNION ALL

SELECT
  'nbac_gamebook_player_stats',
  MIN(game_date),
  MAX(game_date),
  COUNT(DISTINCT game_date),
  COUNT(DISTINCT game_id),
  COUNT(*)
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

UNION ALL

SELECT
  'player_game_summary',
  MIN(game_date),
  MAX(game_date),
  COUNT(DISTINCT game_date),
  COUNT(DISTINCT game_id),
  COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

UNION ALL

SELECT
  'player_composite_factors',
  MIN(game_date),
  MAX(game_date),
  COUNT(DISTINCT game_date),
  COUNT(DISTINCT game_id),
  COUNT(*)
FROM nba_precompute.player_composite_factors
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

**Expected Results:**
- BDL: ~30 dates, ~200-300 games, ~5000-7000 player records
- NBAC Gamebook: ~30 dates, ~200-300 games, ~5000-7000 player records
- Player Game Summary: ~30 dates, ~200-300 games, ~5000-7000 records
- Composite Factors: ~30 dates, ~200-300 games, ~5000-7000 records

**Red Flags:**
- ⚠️ If any table has <25 unique dates (missing days)
- ⚠️ If player_game_summary < bdl_player_boxscores (analytics gaps)
- ⚠️ If composite_factors < player_game_summary (precompute gaps)

---

## Step 2: Day-by-Day Phase Comparison (30 minutes)

**Purpose:** Identify which dates have gaps in which phases

**Query Location:** data-completeness-validation-guide.md (Step 2)

**This is the MOST IMPORTANT query - it shows everything:**
```sql
WITH schedule AS (
  -- Get expected games from schedule
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as scheduled_games
  FROM nba_raw.nbac_schedule
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
    AND game_status = 3  -- Final
  GROUP BY game_date
),
bdl AS (
  -- BDL coverage
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as bdl_games
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
  GROUP BY game_date
),
nbac AS (
  -- NBAC gamebook coverage
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as nbac_games
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
  GROUP BY game_date
),
analytics AS (
  -- Analytics coverage
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as analytics_games
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
  GROUP BY game_date
),
precompute AS (
  -- Precompute coverage
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as precompute_games
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.scheduled_games,
  COALESCE(b.bdl_games, 0) as bdl_games,
  COALESCE(n.nbac_games, 0) as nbac_games,
  COALESCE(a.analytics_games, 0) as analytics_games,
  COALESCE(p.precompute_games, 0) as precompute_games,
  -- Flags
  CASE
    WHEN COALESCE(b.bdl_games, 0) < s.scheduled_games THEN 'BDL_GAP'
    ELSE 'OK'
  END as bdl_status,
  CASE
    WHEN COALESCE(a.analytics_games, 0) < s.scheduled_games THEN 'ANALYTICS_GAP'
    ELSE 'OK'
  END as analytics_status,
  CASE
    WHEN COALESCE(p.precompute_games, 0) < s.scheduled_games THEN 'PRECOMPUTE_GAP'
    ELSE 'OK'
  END as precompute_status
FROM schedule s
LEFT JOIN bdl b ON s.game_date = b.game_date
LEFT JOIN nbac n ON s.game_date = n.game_date
LEFT JOIN analytics a ON s.game_date = a.game_date
LEFT JOIN precompute p ON s.game_date = p.game_date
ORDER BY s.game_date DESC;
```

**Analysis:**
- Identify all dates where `bdl_status = 'BDL_GAP'` (BDL missing games)
- Identify all dates where `analytics_status = 'ANALYTICS_GAP'` (need Phase 2/3 backfill)
- Identify all dates where `precompute_status = 'PRECOMPUTE_GAP'` (need Phase 4 backfill)

**Expected Issues from Jan 21 audit:**
- ~33 BDL gaps (known)
- ~4 analytics gaps (need backfill)
- ~2 precompute gaps (need backfill)

---

## Step 3: Missing Game Detection (15 minutes)

**Purpose:** Find specific games that BDL is missing

**Query Location:** `/validation/queries/raw/nbac_gamebook/find_missing_regular_season_games.sql`

```sql
-- Find games in NBAC but NOT in BDL
SELECT
  n.game_date,
  n.game_id,
  CONCAT(away.team_abbrev, ' @ ', home.team_abbrev) as matchup,
  COUNT(DISTINCT n.player_id) as nbac_players,
  'BDL_MISSING' as status
FROM nba_raw.nbac_gamebook_player_stats n
LEFT JOIN nba_raw.bdl_player_boxscores b
  ON n.game_id = b.game_id
LEFT JOIN nba_raw.nbac_schedule s
  ON n.game_id = s.game_id
LEFT JOIN nba_reference.teams away ON s.away_team_id = away.team_id
LEFT JOIN nba_reference.teams home ON s.home_team_id = home.team_id
WHERE n.game_date >= '2026-01-01'
  AND n.game_date <= '2026-01-21'
  AND b.game_id IS NULL  -- Not in BDL
GROUP BY n.game_date, n.game_id, matchup
ORDER BY n.game_date DESC, matchup;
```

**Expected:** ~33 games for Jan 1-21, 2026

**For each missing game:**
- Note the game_id and matchup
- Check if nbac_players > 0 (confirms fallback worked)
- Prioritize by date (recent = higher priority)

---

## Step 4: Analytics Gap Detection (15 minutes)

**Purpose:** Find games that have raw data but NOT analytics

```sql
-- Find games in raw data but missing from player_game_summary
WITH raw_games AS (
  SELECT DISTINCT game_date, game_id
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
),
analytics_games AS (
  SELECT DISTINCT game_date, game_id
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
)
SELECT
  r.game_date,
  r.game_id,
  'ANALYTICS_MISSING' as status,
  COUNT(n.player_id) as raw_player_count
FROM raw_games r
LEFT JOIN analytics_games a
  ON r.game_id = a.game_id
LEFT JOIN nba_raw.nbac_gamebook_player_stats n
  ON r.game_id = n.game_id
WHERE a.game_id IS NULL  -- Not in analytics
GROUP BY r.game_date, r.game_id
ORDER BY r.game_date DESC;
```

**Expected from Jan 21 audit:** ~4 games

**These games NEED Phase 2/3 backfill:**
- 2026-01-18: POR @ SAC (23 NBAC rows)
- 2026-01-17: WAS @ DEN (17 NBAC rows)
- 2026-01-01: UTA @ LAC (35 NBAC rows)
- 2026-01-01: BOS @ SAC (35 NBAC rows)

---

## Step 5: Precompute Gap Detection (15 minutes)

**Purpose:** Find games that have analytics but NOT precompute

```sql
-- Find games in analytics but missing from player_composite_factors
WITH analytics_games AS (
  SELECT DISTINCT game_date, game_id
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
),
precompute_games AS (
  SELECT DISTINCT game_date, game_id
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
)
SELECT
  a.game_date,
  a.game_id,
  'PRECOMPUTE_MISSING' as status
FROM analytics_games a
LEFT JOIN precompute_games p
  ON a.game_id = p.game_id
WHERE p.game_id IS NULL  -- Not in precompute
ORDER BY a.game_date DESC;
```

**Expected from Jan 21 audit:** ~2 games

**These games NEED Phase 4 backfill.**

---

## Step 6: Data Quality Checks (30 minutes)

### A. Check for R-009 Regression (Zero-Active Players)

```sql
-- Find games with all players marked inactive (R-009 bug)
SELECT
  game_date,
  game_id,
  COUNT(*) as total_players,
  COUNTIF(is_active = TRUE) as active_players,
  COUNTIF(is_active = FALSE) as inactive_players
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
GROUP BY game_date, game_id
HAVING active_players = 0  -- R-009 regression
ORDER BY game_date DESC;
```

**Expected:** 0 rows (R-009 was fixed)
**If any rows:** These games need analytics reprocessing

### B. Check Player Count Anomalies

```sql
-- Find games with unusually low player counts
SELECT
  game_date,
  game_id,
  COUNT(DISTINCT player_id) as player_count
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
GROUP BY game_date, game_id
HAVING player_count < 18  -- Normal is 18-36 players per game
ORDER BY player_count ASC, game_date DESC;
```

**Expected:** Few or no games with <18 players
**If found:** May indicate incomplete data

### C. Check for Duplicate Games

```sql
-- Find duplicate game records
SELECT
  game_date,
  game_id,
  COUNT(*) as record_count
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-21'
GROUP BY game_date, game_id, player_id
HAVING record_count > 1
ORDER BY game_date DESC;
```

**Expected:** 0 duplicates
**If found:** Data quality issue, may need cleanup

---

## Step 7: Cross-Source Validation (20 minutes)

### A. BDL vs NBAC Consistency

```sql
-- Compare player stats between BDL and NBAC for same games
SELECT
  b.game_date,
  b.game_id,
  COUNT(DISTINCT b.player_id) as bdl_players,
  COUNT(DISTINCT n.player_id) as nbac_players,
  ABS(COUNT(DISTINCT b.player_id) - COUNT(DISTINCT n.player_id)) as player_diff
FROM nba_raw.bdl_player_boxscores b
INNER JOIN nba_raw.nbac_gamebook_player_stats n
  ON b.game_id = n.game_id
WHERE b.game_date >= '2026-01-01' AND b.game_date <= '2026-01-21'
GROUP BY b.game_date, b.game_id
HAVING player_diff > 3  -- More than 3 player difference
ORDER BY player_diff DESC;
```

**Expected:** Few or no games with >3 player difference
**If found:** May indicate data quality issues in one source

### B. Prediction Coverage by Data Source

```sql
-- Check which data sources are actually feeding predictions
SELECT
  pgs.game_date,
  COUNT(DISTINCT pgs.game_id) as games_with_analytics,
  COUNT(DISTINCT pcf.game_id) as games_with_precompute,
  COUNT(DISTINCT ppp.game_id) as games_with_predictions,
  ROUND(COUNT(DISTINCT ppp.game_id) * 100.0 / COUNT(DISTINCT pgs.game_id), 1) as coverage_pct
FROM nba_analytics.player_game_summary pgs
LEFT JOIN nba_precompute.player_composite_factors pcf
  ON pgs.game_id = pcf.game_id
LEFT JOIN nba_predictions.player_prop_predictions ppp
  ON pgs.game_id = ppp.game_id
WHERE pgs.game_date >= '2026-01-01' AND pgs.game_date <= '2026-01-21'
GROUP BY pgs.game_date
ORDER BY pgs.game_date DESC;
```

**Expected:** 90%+ coverage (most analytics games have predictions)
**If <80%:** Investigate why some analytics games aren't generating predictions

---

## Step 8: Backfill Priority Categorization (15 minutes)

Based on your findings, categorize gaps into priorities:

### 🔴 CRITICAL (Backfill within 24 hours)
- Games from last 7 days with analytics gaps
- Games with R-009 regressions
- Games with 0 predictions where data exists

### 🟡 HIGH (Backfill within 1 week)
- Games from last 30 days with analytics gaps
- Games with precompute gaps affecting current models
- Games with <50% player coverage

### 🟢 MEDIUM (Backfill within 1 month)
- Games 30-90 days old with gaps
- Historical completeness improvements
- BDL gaps where NBAC fallback worked

### ⚪ LOW (Backfill as time permits)
- Games 90+ days old
- Data quality improvements
- Non-blocking gaps

---

## Step 9: Generate Backfill Plan (30 minutes)

For each gap category, create specific backfill commands:

### Phase 2/3 Analytics Backfill

**Example for 4 known games:**
```bash
# 2026-01-18: POR @ SAC
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-18 --end-date 2026-01-18 --backfill-mode

# 2026-01-17: WAS @ DEN
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-17 --end-date 2026-01-17 --backfill-mode

# 2026-01-01: Both games
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-01 --end-date 2026-01-01 --backfill-mode
```

### Phase 4 Precompute Backfill

```bash
# Run for dates with precompute gaps
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --start-date <date> --end-date <date> --backfill-mode
```

### BDL Raw Data Backfill

**For BDL gaps (if NBAC didn't work):**
```bash
# Trigger BDL box scores scraper for specific date
python -m scrapers.balldontlie.bdl_box_scores \
  --date <date> --force
```

**Note:** Most BDL gaps have NBAC fallback, so this is only needed if NBAC also missing.

---

## Expected Findings Summary

Based on Jan 21 audit, you should find approximately:

| Category | Expected Count | Priority |
|----------|---------------|----------|
| BDL missing games | ~33 | 🟢 MEDIUM (NBAC fallback worked) |
| Analytics gaps | ~4 | 🟡 HIGH (need backfill) |
| Precompute gaps | ~2 | 🟡 HIGH (need backfill) |
| R-009 regressions | 0 | (Fixed) |
| Duplicate records | 0 | (None expected) |
| Player count anomalies | <5 | 🟡 HIGH (investigate) |

---

## Deliverable

Create a comprehensive backfill report with:

### 1. Executive Summary
- Total games validated
- Overall completeness percentage
- Critical issues found
- High priority backfill needs

### 2. Detailed Findings
- Day-by-day breakdown (from Step 2)
- Specific games missing analytics (from Step 4)
- Specific games missing precompute (from Step 5)
- Data quality issues (from Step 6)

### 3. Backfill Priority List
- 🔴 Critical (list specific games + commands)
- 🟡 High (list specific games + commands)
- 🟢 Medium (summary + batch commands)
- ⚪ Low (note for future)

### 4. Root Cause Analysis
- BDL API patterns (West Coast bias?)
- Infrastructure failures (Jan 15)
- Processing gaps (Phase 2/3 failures)

### 5. Recommendations
- Immediate backfill actions
- Process improvements
- Monitoring enhancements

---

## Reference Documentation

**Primary Guide:**
- `/docs/08-projects/current/historical-backfill-audit/data-completeness-validation-guide.md`

**Backfill Procedures:**
- `/docs/02-operations/backfill/backfill-validation-checklist.md`

**Validation Queries:**
- `/validation/queries/raw/nbac_gamebook/`
- `/validation/queries/raw/bdl_boxscores/`

**Recent Audit Findings:**
- `/docs/08-projects/current/historical-backfill-audit/` (multiple reports)

---

## Tips for Success

1. **Start with Step 2** - the day-by-day comparison shows everything at once
2. **Export results to CSV** for easier analysis
3. **Focus on Jan 1-21 first** (most recent, highest priority)
4. **Verify NBAC fallback worked** for BDL gaps (low priority if yes)
5. **Prioritize analytics gaps** - these directly impact predictions
6. **Document patterns** - West Coast games, specific teams, time patterns

---

**This validation will take 2-3 hours but will give you a complete picture of data health.** 🔍
