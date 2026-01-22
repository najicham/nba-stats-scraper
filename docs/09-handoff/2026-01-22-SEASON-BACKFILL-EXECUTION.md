# Season Backfill Execution Plan

**Date:** January 22, 2026
**Status:** Ready to Execute
**Priority:** P1 - Critical for data quality

---

## Executive Summary

The 2025-26 NBA season has significant data gaps causing cascade contamination through the entire pipeline. This document provides step-by-step instructions to backfill all missing data.

**Root Cause:** Team boxscore scraper wasn't running properly Oct-Dec 2025, plus V2 API deprecation Dec 27+.

**Impact:**
- 100% of `player_composite_factors.opponent_strength_score` = 0 (broken)
- 29% of `team_defense_game_summary` missing paint/zone data
- ML features and predictions using incorrect values

---

## What Was Already Done (Jan 22, 2026)

1. ✅ Fixed `nbac_team_boxscore` scraper - migrated V2→V3 API
2. ✅ Backfilled 199 games (Dec 27 - Jan 21)
3. ✅ Deployed fix to Cloud Run
4. ✅ Created audit documents

**Commits:**
- `e57aa33f` - fix: Migrate nbac_team_boxscore from V2 to V3 API endpoint
- `74e53753` - docs: Add NBA API V2 to V3 migration tracker
- `4ff44e2a` - docs: Add comprehensive data pipeline impact assessment
- `3a0155c7` - docs: Add Phase 2 raw data audit for 2025-26 season

---

## What Still Needs to Be Done

### Step 1: Backfill Raw Team Boxscore (454 games)

**Missing dates:** Oct 22 - Dec 26, 2025 (65 dates, 454 games)

**CSV file is already prepared:** `backfill_jobs/scrapers/nbac_team_boxscore/game_ids_to_scrape.csv`

**Command:**
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
  --workers=15
```

**Estimated time:** 30-45 minutes

**Verification:**
```bash
bq query --use_legacy_sql=false "
  SELECT COUNT(DISTINCT game_date) as dates, COUNT(DISTINCT nba_game_id) as games
  FROM nba_raw.nbac_team_boxscore
  WHERE game_date >= '2025-10-22'"
# Expected: ~91 dates, ~650+ games
```

---

### Step 2: Reprocess Phase 3 (Analytics)

After raw data is complete, reprocess all analytics tables for the full season.

**Date range:** Oct 22, 2025 - Jan 22, 2026

**Run in order:**

```bash
# 1. Team Offense Game Summary
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 2. Team Defense Game Summary
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 3. Player Game Summary
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 4. Upcoming Team Game Context
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 5. Upcoming Player Game Context
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22
```

**Verification:**
```bash
PYTHONPATH=. python scripts/validate_cascade_contamination.py \
  --start-date 2025-10-22 --end-date 2026-01-22 --stage phase3
```

---

### Step 3: Reprocess Phase 4 (Precompute)

**Run in order:**

```bash
# 1. Team Defense Zone Analysis
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 2. Player Shot Zone Analysis
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 3. Player Daily Cache
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# 4. Player Composite Factors (CRITICAL - fixes opponent_strength_score)
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22
```

**Verification:**
```bash
# Check opponent_strength_score is no longer 0
bq query --use_legacy_sql=false "
  SELECT
    COUNT(*) as total,
    COUNTIF(opponent_strength_score = 0) as zeros,
    ROUND(100.0 * COUNTIF(opponent_strength_score > 0) / COUNT(*), 1) as pct_valid
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= '2025-10-22'"
# Expected: pct_valid should be 99%+
```

---

### Step 4: Reprocess Phase 5 (ML Features)

```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22
```

**Verification:**
```bash
PYTHONPATH=. python bin/spot_check_features.py --date 2026-01-21 --count 20
```

---

### Step 5: Final Validation

```bash
# Full cascade contamination check
PYTHONPATH=. python scripts/validate_cascade_contamination.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# Should show all tables as CLEAN
```

---

## Current Data State (Before Backfill)

| Layer | Table | Dates | Expected | Coverage |
|-------|-------|-------|----------|----------|
| RAW | nbac_team_boxscore | 27 | 92 | 29% ❌ |
| RAW | nbac_gamebook_player_stats | 42 | 92 | 46% ⚠️ |
| RAW | bdl_player_boxscores | 90 | 92 | 98% ✅ |
| PHASE 3 | team_defense_game_summary | 90 | 92 | 98% (29% bad data) |
| PHASE 4 | player_composite_factors | 78 | 92 | 85% (100% bad data!) |
| PHASE 5 | ml_feature_store_v2 | 77 | 92 | 84% |

---

## Cascade Contamination (Current)

| Table | Field | % Affected |
|-------|-------|------------|
| team_defense_game_summary | opp_paint_attempts = 0 | 29.2% |
| player_composite_factors | opponent_strength_score = 0 | **100%** |

---

## Reference Documents

- `docs/09-handoff/2026-01-22-NBA-API-V2-TO-V3-MIGRATION.md` - API migration details
- `docs/09-handoff/2026-01-22-DATA-PIPELINE-IMPACT-ASSESSMENT.md` - Full dependency chain
- `docs/09-handoff/2026-01-22-PHASE2-RAW-DATA-AUDIT.md` - Raw data coverage audit
- `docs/09-handoff/2026-01-22-PROXY-INFRASTRUCTURE-AND-VALIDATION.md` - Proxy fixes

---

## Troubleshooting

### If backfill script fails to import
```bash
# Make sure PYTHONPATH is set
export PYTHONPATH=/home/naji/code/nba-stats-scraper
```

### If scraper returns errors
```bash
# Check scraper service health
curl -s https://nba-phase1-scrapers-756957797294.us-west2.run.app/health | jq .
```

### If games fail to scrape
- Check `backfill_jobs/scrapers/nbac_team_boxscore/failed_games_*.json` for failures
- Re-run with `--start-date` to resume from specific date

---

## Success Criteria

After all steps complete:

1. ✅ `nbac_team_boxscore` has 91+ dates
2. ✅ `team_defense_game_summary.opp_paint_attempts` < 5% zeros
3. ✅ `player_composite_factors.opponent_strength_score` < 5% zeros
4. ✅ `validate_cascade_contamination.py` shows all CLEAN
5. ✅ `spot_check_features.py` shows valid rolling averages

---

**Next Session:** Start with Step 1 (raw team boxscore backfill), then proceed through steps 2-5 in order.
