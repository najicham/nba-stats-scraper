# Session 76: Data Gap Analysis and Prevention Framework

> **Date:** 2025-12-08
> **Focus:** Analyzed cascade data gap issue, created prevention/recovery guide, prepared backfill plan
> **Status:** Ready for backfill execution

---

## Executive Summary

This session continued from Session 75 (shot zone fix) and focused on:
1. **Impact analysis** - Discovered the shot zone gap affected 10,000+ PCF records
2. **Infrastructure investigation** - Analyzed existing data lineage/validation systems
3. **Prevention guide** - Created comprehensive documentation for future gap handling
4. **Backfill planning** - Prepared the full recovery sequence

---

## The Problem (Full Context)

### Root Cause Chain
```
Session 74-75: Fixed _extract_shot_zone_stats() method in TeamDefenseGameSummaryProcessor
    │
    ▼ BUT upstream data was never populated
    │
team_defense_game_summary.opp_paint_attempts = NULL (all dates except Dec 1 test)
    │
    ▼ TDZA reads from team_defense_game_summary
    │
team_defense_zone_analysis.paint_defense_vs_league_avg = NULL (1,770 records, 100%)
    │
    ▼ PCF reads from TDZA for opponent strength
    │
player_composite_factors.opponent_strength_score = 0 (10,068 of 10,069 records, 99.99%)
    │
    ▼ MLFS extracts opponent_strength_score from PCF
    │
ml_feature_store_v2 would have bad features (0 predictions made for Nov-Dec 2021)
```

### Scope of Impact

| Table | Dataset | Issue | Records Affected | Date Range |
|-------|---------|-------|------------------|------------|
| team_defense_game_summary | nba_analytics | opp_paint_attempts = NULL | ~2,000+ | Nov 2 - Dec 31, 2021 |
| team_defense_zone_analysis | nba_precompute | paint_defense_vs_league_avg = NULL | 1,770 (100%) | Nov 2 - Dec 31, 2021 |
| player_composite_factors | nba_precompute | opponent_strength_score = 0 | 10,068 (99.99%) | Nov 5, 2021 - Dec 3, 2025 |

### Why This Wasn't Caught
1. No field-level validation for NULL/zero values in critical fields
2. Backfill mode (`--skip-preflight`) bypasses most checks
3. No cascade impact detection when upstream data is incomplete
4. Source hash tracking exists but wasn't properly populated

---

## What Was Done This Session

### 1. Impact Analysis
- Discovered `opponent_strength_score = 0` for virtually all PCF records
- Traced root cause back to missing shot zone data in Phase 3
- Confirmed TDZA has NULL `paint_defense_vs_league_avg` for all 59 dates (1,770 records)
- Verified no predictions were made for Nov-Dec 2021 (no downstream ML impact)

### 2. Infrastructure Investigation
Explored existing data quality infrastructure:

| Component | Maturity | Notes |
|-----------|----------|-------|
| Source hash tracking | 60% | Exists in some processors, not consistently used |
| Data validation | 70% | Good completeness checking, missing field-level validation |
| Dependency management | 80% | Comprehensive definition & checking |
| Failure tracking | 65% | Good logging, weak recovery mechanisms |
| Alerting | 75% | Multi-channel, good dedup, weak escalation |

### 3. Documentation Created
- **`docs/02-operations/guides/data-gap-prevention-and-recovery.md`** - Comprehensive guide covering:
  - 5 types of data gaps
  - Prevention strategies
  - Detection methods
  - Recovery procedures
  - Diagnostic queries
  - Future improvements roadmap

---

## Backfill Execution Plan

### Pre-Requisites
1. Kill any stale background processes from previous sessions
2. Verify the shot zone fix (commit 43f41a7) is deployed

### Execution Order (CRITICAL - Must Follow This Order!)

```bash
# Step 1: Fix Dec 7 Phase 3 gap (missing upcoming_player_game_context)
.venv/bin/python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
    --start-date 2021-12-07 --end-date 2021-12-07

# Step 2: Backfill team_defense_game_summary with shot zone data
.venv/bin/python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# Step 3: Backfill TDZA (can run in parallel with PSZA)
.venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --skip-preflight

# Step 4: Backfill PSZA (can run in parallel with TDZA)
.venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --skip-preflight

# Step 5: Backfill PDC (depends on PSZA)
.venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --skip-preflight

# Step 6: Backfill PCF (depends on TDZA, PSZA)
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-05 --end-date 2021-12-31 --skip-preflight

# Step 7: Backfill MLFS (depends on PCF)
.venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-11-05 --end-date 2021-12-31 --skip-preflight
```

### Expected Runtimes (Estimates)
- Step 1: ~30 seconds (single date)
- Step 2: ~5-10 minutes (61 dates)
- Step 3-4: ~10-15 minutes each
- Step 5: ~15-20 minutes
- Step 6: ~20-30 minutes
- Step 7: ~15-20 minutes

Total: ~1-2 hours

---

## Validation Queries

### Before Backfill (Current State)

```sql
-- Current state of shot zone data (should show mostly NULL)
SELECT
  game_date,
  COUNT(*) as records,
  SUM(CASE WHEN opp_paint_attempts IS NOT NULL THEN 1 ELSE 0 END) as with_paint
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY game_date ORDER BY game_date;

-- Current state of TDZA (should show all NULL)
SELECT
  analysis_date,
  AVG(paint_defense_vs_league_avg) as avg_paint_defense,
  SUM(CASE WHEN paint_defense_vs_league_avg IS NULL THEN 1 ELSE 0 END) as null_count
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY analysis_date ORDER BY analysis_date;

-- Current state of PCF (should show all 0)
SELECT
  game_date,
  AVG(opponent_strength_score) as avg_opp_score,
  SUM(CASE WHEN opponent_strength_score = 0 THEN 1 ELSE 0 END) as zero_count,
  COUNT(*) as total
FROM `nba_precompute.player_composite_factors`
WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY game_date ORDER BY game_date;
```

### After Backfill (Success Criteria)

```sql
-- Shot zone data should be populated (avg ~30-40 paint attempts per team)
SELECT
  game_date,
  COUNT(*) as records,
  SUM(CASE WHEN opp_paint_attempts > 0 THEN 1 ELSE 0 END) as with_paint,
  AVG(opp_paint_attempts) as avg_paint_attempts
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY game_date ORDER BY game_date;
-- SUCCESS: with_paint should equal records, avg_paint_attempts ~30-40

-- TDZA paint defense should be populated (values typically -10 to +10)
SELECT
  analysis_date,
  AVG(paint_defense_vs_league_avg) as avg_paint_defense,
  MIN(paint_defense_vs_league_avg) as min_paint,
  MAX(paint_defense_vs_league_avg) as max_paint,
  SUM(CASE WHEN paint_defense_vs_league_avg IS NULL THEN 1 ELSE 0 END) as null_count
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY analysis_date ORDER BY analysis_date;
-- SUCCESS: null_count = 0, values in reasonable range

-- PCF opponent_strength_score should be > 0 (typically 0.3-0.7 range)
SELECT
  game_date,
  AVG(opponent_strength_score) as avg_opp_score,
  MIN(opponent_strength_score) as min_opp,
  MAX(opponent_strength_score) as max_opp,
  SUM(CASE WHEN opponent_strength_score = 0 THEN 1 ELSE 0 END) as zero_count,
  COUNT(*) as total
FROM `nba_precompute.player_composite_factors`
WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY game_date ORDER BY game_date;
-- SUCCESS: zero_count = 0, avg_opp_score in 0.3-0.7 range
```

---

## Speed Measurement

### During Backfill Runs
Each processor logs timing info. Look for:
```
INFO:precompute_base:PRECOMPUTE_STATS {"run_id": "xxx", "processor": "...", "total_runtime": 26.44, ...}
```

### Key Metrics to Track
1. **Per-date processing time**: Should be <60s per date for most processors
2. **Players per second**: PCF should process 300-500 players/sec
3. **Dependency check time**: Should be <1s in backfill mode (we added skip optimization)

### If Backfill is Slow
- Check for BigQuery quota limits
- Verify `--skip-preflight` flag is used
- Consider breaking into smaller date ranges
- Check for API rate limiting on schedule service

---

## Database Fields to Monitor

### team_defense_game_summary (Phase 3)
| Field | Expected | Issue Indicator |
|-------|----------|-----------------|
| opp_paint_attempts | 25-50 per team | NULL or 0 |
| opp_paint_makes | 10-25 per team | NULL or 0 |
| opp_mid_range_attempts | 10-30 per team | NULL or 0 |
| opp_three_pt_attempts_pbp | 20-45 per team | NULL or 0 |

### team_defense_zone_analysis (Phase 4)
| Field | Expected | Issue Indicator |
|-------|----------|-----------------|
| paint_defense_vs_league_avg | -15 to +15 | NULL |
| mid_range_defense_vs_league_avg | -15 to +15 | NULL |
| three_pt_defense_vs_league_avg | -15 to +15 | NULL |

### player_composite_factors (Phase 4)
| Field | Expected | Issue Indicator |
|-------|----------|-----------------|
| opponent_strength_score | 0.2 to 0.8 | 0 (exactly) |
| shot_zone_mismatch_score | 0 to 1 | Should vary |
| pace_score | 0.3 to 0.7 | Should vary |

---

## Known Issues

### 1. Dec 7, 2021 Missing Context
- `upcoming_player_game_context` is missing for Dec 7
- **Fix:** Run Step 1 of backfill first
- **Root cause:** Unknown - may have been a gap in original processing

### 2. Nov 1-4 Missing PCF
- PCF records don't exist for Nov 1-4 (only starts Nov 5)
- **Expected:** Early season bootstrap - PCF requires 5 games of history
- **No action needed**

### 3. Stale Background Processes
- Multiple background bash processes from previous sessions
- **Fix:** Can be ignored - they've completed
- Process IDs: d41664, 8f8eb9, 5e653f, dd3b1e, 0ed18c, dc5e1c, def882, 4e8b49, 8909bb, 31a8d5

---

## Improvement Opportunities

### High Priority (Should Implement Soon)

1. **Critical Field Validator**
   - Add validation that fails when critical fields are NULL/zero
   - Location: `shared/processors/mixins/`
   - Fields to validate:
     - team_defense_game_summary: opp_paint_attempts
     - team_defense_zone_analysis: paint_defense_vs_league_avg
     - player_composite_factors: opponent_strength_score

2. **Cascade Impact Analyzer Script**
   - Script that takes table+date and shows all downstream impact
   - Would help diagnose future gaps quickly
   - Could auto-generate backfill commands

3. **Source Hash Consistency**
   - PCF has `source_team_defense_hash` columns but they're NULL
   - Need to actually populate these during processing
   - Would enable detecting stale downstream data

### Medium Priority

4. **Backfill Mode Tightening**
   - Current `--skip-preflight` skips too much
   - Should still validate critical fields
   - Add `--force-despite-nulls` for explicit acknowledgment

5. **Data Lineage Dashboard**
   - Visual DAG of pipeline dependencies
   - Click-to-see impact of gaps

### Reference Document
- See `docs/02-operations/guides/data-gap-prevention-and-recovery.md` for full details

---

## Files Changed/Created This Session

| File | Action | Description |
|------|--------|-------------|
| `docs/02-operations/guides/data-gap-prevention-and-recovery.md` | Created | Comprehensive gap prevention guide |
| `docs/09-handoff/2025-12-08-SESSION76-DATA-GAP-ANALYSIS-AND-PREVENTION.md` | Created | This handoff doc |

---

## Temp Files to Clean Up

The repo root has many temp files from previous sessions:
```bash
# Preview what would be deleted
git clean -fd --dry-run

# Files include:
# - *.md analysis docs
# - *.py test/query scripts
# - *.patch, *.diff files

# Actually delete
git clean -fd
```

---

## Todo List for Next Session

1. [ ] **Fix Dec 7 Phase 3 gap** - Run upcoming_player_game_context backfill for Dec 7
2. [ ] **Run Phase 3 backfill** - team_defense_game_summary (Nov-Dec 2021)
3. [ ] **Run Phase 4 backfill** - TDZA (Nov-Dec 2021)
4. [ ] **Run Phase 4 backfill** - PSZA (Nov-Dec 2021) - can run parallel with TDZA
5. [ ] **Run Phase 4 backfill** - PDC (Nov-Dec 2021) - after PSZA
6. [ ] **Run Phase 4 backfill** - PCF (Nov 5 - Dec 31, 2021) - after TDZA, PSZA
7. [ ] **Run Phase 5 backfill** - MLFS (Nov 5 - Dec 31, 2021) - after PCF
8. [ ] **Verify fix** - Run validation queries to confirm opponent_strength_score > 0
9. [ ] **Clean up temp files** - git clean -fd
10. [ ] **Optional: Implement Critical Field Validator** - Prevent future cascade gaps

---

## Quick Reference Commands

```bash
# Check current PCF opponent_strength (should be 0 before fix)
bq query --use_legacy_sql=false 'SELECT AVG(opponent_strength_score), COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"'

# Check TDZA paint defense (should be NULL before fix)
bq query --use_legacy_sql=false 'SELECT AVG(paint_defense_vs_league_avg), COUNT(*) FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date BETWEEN "2021-11-01" AND "2021-12-31"'

# Check team_defense_game_summary paint data (should be NULL before fix)
bq query --use_legacy_sql=false 'SELECT AVG(opp_paint_attempts), COUNT(*) FROM nba_analytics.team_defense_game_summary WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"'

# Validate backfill coverage
.venv/bin/python scripts/validate_backfill_coverage.py --start-date 2021-11-05 --end-date 2021-12-31 --details
```

---

## Related Commits

```
43f41a7 feat: Extract shot zone data from play-by-play for team defense
5fa7d22 docs: Update data integrity guide with implementation status
21132a7 feat: Add lightweight upstream existence check in backfill mode
98f459e docs: Add Phase 4 data integrity guide with prevention strategies
6cc8474 perf: Skip upstream completeness queries in backfill mode for PCF
```

---

## Contact/Context

- **Previous Session:** SESSION75-SHOT-ZONE-FIX-COMPLETE.md
- **Key Fix Commit:** 43f41a7
- **Prevention Guide:** docs/02-operations/guides/data-gap-prevention-and-recovery.md

---

*End of Session 76 Handoff*
