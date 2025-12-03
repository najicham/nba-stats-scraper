# October-November 2021 Test Backfill - Gameplan

**Created:** 2025-12-02
**Test Window:** Oct 19 - Nov 15, 2021 (28 game days)
**Purpose:** Validate backfill process works before full run
**Bootstrap Period:** First 14 days (Oct 19 - Nov 1) - Phase 4 may skip

---

## Pre-Test State (Baseline - Dec 2, 2025)

| Phase | Table | Dates | Out of 28 | Status |
|-------|-------|-------|-----------|--------|
| Phase 1-2 | nbac_gamebook_player_stats | 28 | 100% | ✅ Ready |
| Phase 3 | player_game_summary | 14 | 50% | Partial |
| Phase 3 | team_defense_game_summary | 0 | 0% | Empty |
| Phase 3 | team_offense_game_summary | 0 | 0% | Empty |
| Phase 3 | upcoming_player_game_context | ? | TBD | Unknown |
| Phase 3 | upcoming_team_game_context | 0 | 0% | Empty |
| Phase 4 | all 5 tables | 0 | 0% | Empty |

---

## STEP 0: Validate Phase 1-2 Source Data (3 min) ⚠️ CRITICAL FIRST STEP

Before running ANY backfill, verify the source data exists:

```bash
# Run validation for the test window - this checks ALL 7 data source chains
python3 bin/validate_pipeline.py 2021-10-19 2021-11-15
```

**What to look for:**
- "PHASE 1-2: DATA SOURCES BY CHAIN" section
- All 7 chains should show "✓ Complete" or at least have primary source available
- Look for any "○ Missing" on critical chains (player_boxscores, team_boxscores, game_schedule)

**The 7 chains checked:**
1. `game_schedule` (critical) - nbac_schedule
2. `player_boxscores` (critical) - nbac_gamebook_player_stats
3. `team_boxscores` (critical) - nbac_team_boxscore
4. `player_props` (warning) - odds_api or bettingpros fallback
5. `game_lines` (info) - odds_api_game_lines
6. `injury_reports` (info) - nbac_injury_report
7. `shot_zones` (info) - bigdataball_play_by_play

**STOP if critical chains are missing!** You'll need to run Phase 1 scrapers first.

---

## STEP 1: Pre-Flight Check (2 min)

```bash
# Verify backfill infrastructure is ready
./bin/backfill/preflight_verification.sh --quick
```

**Expected:** All checks pass

---

## STEP 2: Run Phase 3 Backfill (5-15 min)

Run all 5 Phase 3 processors. They can run in PARALLEL (no dependencies between them).

### Option A: Run in parallel (faster)

Open 5 terminal tabs and run each:

**Terminal 1 - player_game_summary:**
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

**Terminal 2 - team_defense_game_summary:**
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

**Terminal 3 - team_offense_game_summary:**
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

**Terminal 4 - upcoming_player_game_context:**
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

**Terminal 5 - upcoming_team_game_context:**
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

### Option B: Run sequentially (simpler to monitor)

```bash
cd /home/naji/code/nba-stats-scraper

# Run each one after the previous completes
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

---

## STEP 3: Validate Phase 3 Results (2 min)

After ALL Phase 3 processors complete, run validation:

```bash
# Validate the test window
python3 bin/validate_pipeline.py 2021-10-19 2021-10-31

# Quick data check
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name, COUNT(DISTINCT game_date) as dates
FROM nba_analytics.player_game_summary WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'team_defense_game_summary', COUNT(DISTINCT game_date)
FROM nba_analytics.team_defense_game_summary WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'team_offense_game_summary', COUNT(DISTINCT game_date)
FROM nba_analytics.team_offense_game_summary WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'upcoming_player_game_context', COUNT(DISTINCT game_date)
FROM nba_analytics.upcoming_player_game_context WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'upcoming_team_game_context', COUNT(DISTINCT game_date)
FROM nba_analytics.upcoming_team_game_context WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
"
```

**Expected Results:**
- player_game_summary: 28 dates
- team_defense_game_summary: 28 dates
- team_offense_game_summary: 28 dates
- upcoming tables: depends on odds data availability

**STOP if Phase 3 is not 100% complete for core tables before proceeding to Phase 4!**

---

## STEP 4: Run Phase 4 Backfill (10-20 min)

**CRITICAL: Phase 4 processors MUST run SEQUENTIALLY in this exact order!**

```bash
cd /home/naji/code/nba-stats-scraper

# 1. Team Defense Zone Analysis (reads Phase 3 only)
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

# 2. Player Shot Zone Analysis (reads Phase 3 only)
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

# 3. Player Composite Factors (reads #1, #2, Phase 3)
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

# 4. Player Daily Cache (reads #1-3, Phase 3)
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15

# 5. ML Feature Store (reads #1-4) - LAST!
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

---

## STEP 5: Validate Phase 4 Results (2 min)

```bash
# Full validation
python3 bin/validate_pipeline.py 2021-10-19 2021-10-31

# Check Phase 4 tables
bq query --use_legacy_sql=false "
SELECT
  'team_defense_zone_analysis' as table_name, COUNT(DISTINCT analysis_date) as dates
FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'player_shot_zone_analysis', COUNT(DISTINCT analysis_date)
FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'player_composite_factors', COUNT(DISTINCT analysis_date)
FROM nba_precompute.player_composite_factors WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'player_daily_cache', COUNT(DISTINCT analysis_date)
FROM nba_precompute.player_daily_cache WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'ml_feature_store_v2', COUNT(DISTINCT analysis_date)
FROM nba_precompute.ml_feature_store_v2 WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
"
```

**Expected Results:**
- First 14 days (Oct 19 - Nov 1): May have 0 or limited records (bootstrap period - expected!)
- Bootstrap constant: `BOOTSTRAP_DAYS = 14` in `shared/validation/config.py`
- Quality scores may be low early in season (expected - limited lookback data)

**Note:** For our Oct 19-31 test window, most days fall in bootstrap period, so Phase 4 may produce very few records. This is expected behavior.

---

## Expected Outcomes

### What Success Looks Like:
1. All Phase 3 core tables have 13 dates
2. Phase 4 tables have 6+ dates (after bootstrap period)
3. No errors in processor output
4. Validation script shows "complete" or "partial" (not "missing")

### What Failure Looks Like:
1. Errors during processing (check logs)
2. 0 records written after processor runs
3. Validation shows "missing" for Phase 3 tables

### Expected Gotchas:
1. **Bootstrap period (Oct 19-25):** Phase 4 may skip these dates - this is expected!
2. **Low quality scores:** Normal for early season data
3. **Missing odds data:** upcoming_player_game_context may have fewer dates

---

## Troubleshooting

### If a processor fails:
```bash
# Check recent processor runs
bq query --use_legacy_sql=false "
SELECT data_date, processor_name, status, errors
FROM nba_reference.processor_run_history
WHERE data_date BETWEEN '2021-10-19' AND '2021-11-15'
  AND status = 'failed'
ORDER BY started_at DESC
LIMIT 20
"
```

### If data is missing:
```bash
# Check what raw data exists
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
GROUP BY 1
ORDER BY 1
"
```

---

## Post-Test: Next Steps

If test succeeds:
1. ✅ Backfill process validated
2. Decide: Run full season (Oct 2021 - Apr 2022) or continue small batches
3. Estimate time: ~180 dates × ~2 min/date = ~6 hours for one season

If test fails:
1. Identify failing processor
2. Check logs for specific error
3. Fix issue before proceeding
4. Re-run failed processor only

---

**Document Version:** 1.0
**Created:** 2025-12-02
