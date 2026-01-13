# Backfill Verification Guide

**Purpose:** Verify data completeness after overnight processing or historical backfills.

---

## Quick Reference: Which Check Do You Need?

| Scenario | Section |
|----------|---------|
| Verify yesterday's games processed | [Recent Backfill Check](#recent-backfill-check-yesterday) |
| Verify last few days | [Recent Backfill Check](#recent-backfill-check-yesterday) with date range |
| Verify full season backfill | [Full Season Verification](#full-season-verification) |
| Debug missing/incomplete data | [Troubleshooting](#troubleshooting) |

---

## Recent Backfill Check (Yesterday)

Run after 4 AM ET when `post_game_window_3` completes.

### Step 1: Quick Completeness Check (1 minute)

```bash
PYTHONPATH=. python scripts/check_data_completeness.py --date $(date -d 'yesterday' +%Y-%m-%d)
```

**Expected output:**
```
Gamebooks: 6/6 (100%) ✅
Box Scores: 6/6 (100%) ✅
BettingPros Props: 10,432 (expected ≥900) ✅
✅ ALL DATA COMPLETE
```

### Step 2: Verify All Phases (3 minutes)

```bash
# Set target date
TARGET_DATE=$(date -d 'yesterday' +%Y-%m-%d)

# Phase 1: Raw data counts
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Gamebooks' as source, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` WHERE game_date = '$TARGET_DATE'
UNION ALL
SELECT 'BDL Box Scores', COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\` WHERE game_date = '$TARGET_DATE'
UNION ALL
SELECT 'ESPN Scoreboard', COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_raw.espn_scoreboard\` WHERE game_date = '$TARGET_DATE'"

# Phase 3: Analytics
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Player Game Summary' as table_name, COUNT(DISTINCT game_id) as games, COUNT(*) as rows
FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date = '$TARGET_DATE'
UNION ALL
SELECT 'Team Defense Summary', COUNT(DISTINCT game_id), COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\` WHERE game_date = '$TARGET_DATE'"

# Phase 4: Precompute
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Player Composite Factors' as table_name, COUNT(*) as rows
FROM \`nba-props-platform.nba_precompute.player_composite_factors\` WHERE game_date = '$TARGET_DATE'
UNION ALL
SELECT 'ML Feature Store', COUNT(*)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` WHERE game_date = '$TARGET_DATE'"
```

### Step 3: Decision Matrix

| Phase | Check | Expected | If Missing |
|-------|-------|----------|------------|
| Phase 1 | Gamebooks | = scheduled games | Backfill gamebooks |
| Phase 1 | BDL Box Scores | = scheduled games | Backfill BDL |
| Phase 3 | Player Game Summary | = scheduled games | Re-run Phase 3 |
| Phase 3 | Team Defense Summary | = scheduled games | Re-run TDGS |
| Phase 4 | Composite Factors | > 0 rows | Re-run PCF |
| Phase 4 | ML Feature Store | > 0 rows | Re-run MLFS |

---

## Full Season Verification

Use for historical backfill validation or periodic audits.

### Step 1: Run Coverage Validation Script

```bash
# Current season (2024-25 started Oct 22, 2024)
PYTHONPATH=. python scripts/validate_backfill_coverage.py \
  --start-date 2024-10-22 \
  --end-date $(date +%Y-%m-%d) \
  --details

# Specific season
PYTHONPATH=. python scripts/validate_backfill_coverage.py \
  --start-date 2023-10-24 \
  --end-date 2024-04-14 \
  --details
```

### Step 2: Check Cascade Contamination

Ensures upstream data properly flows to downstream tables:

```bash
PYTHONPATH=. python scripts/validate_cascade_contamination.py \
  --start-date 2024-10-22 \
  --end-date $(date +%Y-%m-%d) \
  --strict
```

**What it checks:**
- `opponent_strength_score > 0` (should be populated)
- `opp_paint_attempts > 0` (should be populated)
- No NULLs in required fields

### Step 3: Coverage Queries

```sql
-- Overall coverage by season
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as game_days,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_analytics.player_game_summary`
GROUP BY 1 ORDER BY 1;

-- Find gaps (dates with missing data)
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY 1
HAVING COUNT(DISTINCT game_id) = 0
ORDER BY 1;

-- Phase 4 coverage
SELECT
  game_date,
  COUNT(*) as pcf_rows
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2024-10-22'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 10;
```

### Step 4: Expected Coverage Baselines

| Season | Game Days | Total Games | Notes |
|--------|-----------|-------------|-------|
| 2024-25 | ~82 | ~1230 | Current season |
| 2023-24 | 177 | 1312 | Full season |
| 2022-23 | 177 | 1312 | Full season |
| 2021-22 | 173 | 1312 | COVID shortened |

---

## Troubleshooting

### Missing Gamebooks

```bash
# Find which games are missing
bq query --use_legacy_sql=false "
SELECT s.game_date, s.game_id, s.away_team_tricode, s.home_team_tricode
FROM \`nba-props-platform.nba_raw.nbac_schedule\` s
LEFT JOIN \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` g
  ON s.game_id = g.game_id
WHERE s.game_date = 'YYYY-MM-DD'
  AND s.game_status = 3
  AND g.game_id IS NULL"

# Backfill specific date
PYTHONPATH=. python scripts/backfill_gamebooks.py --date YYYY-MM-DD
```

### Missing BDL Box Scores

```bash
# Check what's missing
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date >= 'YYYY-MM-DD'
GROUP BY 1 ORDER BY 1"

# Backfill
PYTHONPATH=. python backfill_jobs/scrapers/bdl_boxscores/bdl_boxscores_scraper_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

### Missing Phase 3 Data

```bash
# Re-run player game summary
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD

# Re-run team defense game summary
PYTHONPATH=. python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

### Missing Phase 4 Data

```bash
# Re-run player composite factors
PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD

# Re-run ML feature store
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

### Check Circuit Breakers

Circuit breakers can block processing for specific entities:

```bash
# Check active breakers
bq query --use_legacy_sql=false "
SELECT processor_name, entity_id, state, updated_at
FROM \`nba-props-platform.nba_orchestration.circuit_breaker_state\`
WHERE state = 'open'
ORDER BY updated_at DESC"
```

---

## Deep Dive Documentation

| Topic | Location |
|-------|----------|
| Full validation queries | `docs/08-projects/current/historical-backfill-audit/VALIDATION-QUERIES.md` |
| Current backfill status | `docs/08-projects/current/historical-backfill-audit/STATUS.md` |
| Remediation procedures | `docs/08-projects/current/historical-backfill-audit/REMEDIATION-PLAN.md` |
| Known issues | `docs/08-projects/current/historical-backfill-audit/ISSUES-FOUND.md` |

---

## Backfill Session Prompt Template

```
Backfill Verification - [Date Range]

Start by reading: docs/00-start-here/BACKFILL-VERIFICATION-GUIDE.md

Target: Verify [yesterday's games / season YYYY-YY backfill]

Expected:
- Gamebooks: X games
- BDL Box Scores: X games
- Phase 3/4 tables: populated

If issues found, use troubleshooting section to identify and fix gaps.
```

---

## Maintaining This Documentation

**When you find something during backfill verification:**

| What Happened | Where to Document |
|---------------|-------------------|
| Found a data gap/issue | Add to `docs/08-projects/current/historical-backfill-audit/ISSUES-FOUND.md` |
| Discovered a useful query | Add to `docs/08-projects/current/daily-orchestration-tracking/VALIDATION-IMPROVEMENTS.md` |
| See a recurring pattern | Add to `docs/08-projects/current/daily-orchestration-tracking/PATTERNS.md` |

**When to update this guide:**
- Add new troubleshooting steps for common issues
- Update expected coverage baselines each season
- Add new backfill scripts as they're created

**Canonical sources:**
- Full validation queries: `docs/08-projects/current/historical-backfill-audit/VALIDATION-QUERIES.md`
- Current backfill status: `docs/08-projects/current/historical-backfill-audit/STATUS.md`
- Remediation procedures: `docs/08-projects/current/historical-backfill-audit/REMEDIATION-PLAN.md`

---

*Last Updated: January 13, 2026 (Session 27)*
