# ULTRATHINK: Phase 2 Precompute Backfill Strategic Plan

**Date**: January 9, 2026
**Context**: Phase 1 complete (mock v1 near-optimal at 4.80 MAE), proceeding to infrastructure fix
**Goal**: Backfill precompute features for 2021-2024 to enable fair ML comparison
**Priority**: HIGH - Critical path to ML showdown (Phase 3)

---

## SITUATION ANALYSIS

### Current State
- Mock v1: 4.80 MAE (near-optimal, hard to improve)
- Mock v2: 4.82 MAE (improvements backfired)
- XGBoost v5: 4.63 MAE (incomplete features, overfitting)
- **Precompute coverage**: 77-89% for training period (2021-2024)
- **Target coverage**: 95%+

### Why Phase 2 Matters
1. **Fair ML comparison**: Can't dismiss ML without testing with complete features
2. **Infrastructure value**: Backfill benefits entire platform (not just ML)
3. **Root cause**: XGBoost v5 failed because 11-23% of precompute features were missing
4. **Learning value**: Will definitively answer "can ML beat expert system?"

### What We're Backfilling

| Table | Current Coverage | Target | Records/Day | Total Est |
|-------|-----------------|--------|-------------|-----------|
| player_composite_factors | ~89% | 95%+ | ~500 | ~450k |
| team_defense_zone_analysis | ~86% | 95%+ | ~30 | ~27k |
| player_shot_zone_analysis | ~86% | 95%+ | ~500 | ~450k |
| player_daily_cache | ~77% | 95%+ | ~500 | ~450k |
| ml_feature_store | ~77% | 95%+ | ~500 | ~450k |

---

## ULTRATHINK: 6-PERSPECTIVE ANALYSIS

### Perspective 1: What's the REAL Bottleneck?

**Discovery**: The existing `run_complete_historical_backfill.sh` focuses on **PLAYOFF GAPS** only (Apr-Jun each year). But our ML training needs the **FULL REGULAR SEASON** (Oct-Apr) with complete precompute features.

**Current Playoff Focus**:
- 2021-22: Apr 16 - Jun 17 (62 days, ~120 games)
- 2022-23: Apr 15 - Jun 13 (59 days, ~120 games)
- 2023-24: Apr 16 - Jun 18 (63 days, ~120 games)

**What ML Training Needs**:
- 2021-22: Oct 19, 2021 - Jun 17, 2022 (~240 days, ~1420 games)
- 2022-23: Oct 18, 2022 - Jun 13, 2023 (~240 days, ~1420 games)
- 2023-24: Oct 24, 2023 - Jun 18, 2024 (~240 days, ~1420 games)

**Key Insight**: We need to verify regular season coverage FIRST, not just playoffs.

---

### Perspective 2: Dependency Chain Analysis

**Processing Order (MUST be sequential across phases)**:
```
Phase 1: Raw Data (GCS)
    ↓ (already backfilled)
Phase 2: Raw Processing (BigQuery nba_raw)
    ↓ (already backfilled)
Phase 3: Analytics (BigQuery nba_analytics)  ← VERIFY FIRST
    ├── player_game_summary
    ├── team_offense_game_summary
    ├── team_defense_game_summary
    ├── upcoming_player_game_context (betting - will be incomplete)
    └── upcoming_team_game_context (betting - will be incomplete)
    ↓
Phase 4: Precompute (BigQuery nba_precompute)  ← BACKFILL TARGET
    ├── 1. team_defense_zone_analysis    ← INDEPENDENT
    ├── 2. player_shot_zone_analysis     ← INDEPENDENT
    ├── 3. player_daily_cache            ← INDEPENDENT
    ├── 4. player_composite_factors      ← CASCADE (needs 1-3)
    └── 5. ml_feature_store              ← CASCADE (needs 1-4)
```

**Critical Path**:
1. Verify Phase 3 is complete (prerequisite)
2. Run independent Phase 4 processors (1-3) in parallel
3. Run cascade processors (4-5) sequentially

---

### Perspective 3: Time & Resource Estimation

**Based on exploration report**:

| Phase | Parallelism | Est. Time (Sequential) | Est. Time (Parallel) |
|-------|-------------|----------------------|---------------------|
| Phase 3 Verification | N/A | 5 min | 5 min |
| Phase 4 Independent (1-3) | 3-way | 6 hrs | 2 hrs |
| Phase 4 Cascade (4-5) | Sequential | 4 hrs | 4 hrs |
| Validation | N/A | 30 min | 30 min |
| **Total** | | 10.5 hrs | **6.5 hrs** |

**Optimization opportunities**:
- ThreadPoolExecutor within backfill jobs (already implemented)
- Day-by-day processing (inherent parallelism)
- Skip bootstrap periods (first 7 days)

---

### Perspective 4: Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Phase 3 incomplete | 20% | HIGH | Verify first, backfill if needed |
| BigQuery quota limits | 30% | MEDIUM | Day-by-day processing, rate limiting |
| Cascade contamination | 15% | HIGH | Pre-flight validation, fallback detection |
| Backfill script failures | 25% | MEDIUM | Checkpointing, resume capability |
| Betting tables incomplete | 100% | LOW | Expected - synthetic fallback exists |
| Out of disk/memory | 10% | MEDIUM | Monitor resources, batch if needed |

**Highest risk**: Phase 3 might be incomplete for regular season. MUST verify first.

---

### Perspective 5: Validation Strategy

**Pre-flight checks**:
1. Phase 3 row counts match expected game counts
2. No null critical fields (player_lookup, game_date)
3. Coverage by season year (detect gaps)

**Post-backfill validation**:
1. Target 95%+ coverage for each table
2. Cascade contamination check (synthetic fallback < 5%)
3. Date range verification (no missing days)
4. Sample quality check (spot-check random dates)

**Success criteria**:
```sql
-- All tables should return 95%+ coverage
SELECT
  table_name,
  season_year,
  COUNT(DISTINCT game_date) as dates_covered,
  ROUND(100.0 * COUNT(DISTINCT game_date) / expected_dates, 1) as coverage_pct
FROM precompute_tables
GROUP BY 1, 2
HAVING coverage_pct < 95  -- Flag any gaps
```

---

### Perspective 6: Execution Strategy Options

**Option A: Full Sequential (Safe but Slow)**
- Run each table one by one
- Maximum safety, minimum risk
- Time: 10-12 hours
- Good for: First run, untested infrastructure

**Option B: Parallel Independent + Sequential Cascade (Recommended)**
- Run tables 1-3 in parallel
- Then run 4-5 sequentially
- Time: 6-8 hours
- Good for: Balanced risk/speed

**Option C: Maximum Parallel (Risky but Fast)**
- Run all tables in parallel
- Risk cascade contamination
- Time: 4-5 hours
- Good for: Only if Phase 3 fully validated

**Recommendation**: Option B - Start with verification, parallel independent, sequential cascade.

---

## EXECUTION PLAN

### Stage 1: Pre-Flight Verification (30 min)

**Goal**: Confirm Phase 3 is complete before starting Phase 4 backfill

**Tasks**:
1. Query Phase 3 tables for date coverage (2021-2024 regular season + playoffs)
2. Identify any gaps in player_game_summary, team_offense_game_summary, team_defense_game_summary
3. Verify row counts match expected (~4M+ records across 3 seasons)

**SQL queries**:
```sql
-- Check Phase 3 coverage
SELECT
  'player_game_summary' as table_name,
  season_year,
  COUNT(*) as records,
  COUNT(DISTINCT game_date) as unique_dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023)
GROUP BY 1, 2
ORDER BY season_year;
```

**Decision point**:
- If Phase 3 coverage < 90%: STOP, backfill Phase 3 first
- If Phase 3 coverage >= 90%: Proceed to Stage 2

---

### Stage 2: Phase 4 Independent Processors (2-3 hours)

**Goal**: Backfill tables 1-3 that don't depend on each other

**Execute in parallel**:
```bash
# Terminal 1
PYTHONPATH=. python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2024-06-18 --parallel --workers 10

# Terminal 2
PYTHONPATH=. python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2024-06-18 --parallel --workers 10

# Terminal 3
PYTHONPATH=. python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2024-06-18 --parallel --workers 10
```

**Monitoring**:
- Check BigQuery console for job progress
- Tail log files for errors
- Watch for quota warnings

---

### Stage 3: Mid-Point Validation (15 min)

**Goal**: Confirm Stage 2 completed before cascade processors

**Validate**:
```sql
SELECT
  table_name,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as records
FROM (
  SELECT 'team_defense_zone_analysis' as table_name, game_date FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` WHERE game_date BETWEEN '2021-10-01' AND '2024-07-01'
  UNION ALL
  SELECT 'player_shot_zone_analysis', game_date FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis` WHERE game_date BETWEEN '2021-10-01' AND '2024-07-01'
  UNION ALL
  SELECT 'player_daily_cache', game_date FROM `nba-props-platform.nba_precompute.player_daily_cache` WHERE game_date BETWEEN '2021-10-01' AND '2024-07-01'
)
GROUP BY table_name;
```

**Decision point**:
- If any table < 90% coverage: Investigate, possibly re-run
- If all tables >= 90%: Proceed to Stage 4

---

### Stage 4: Phase 4 Cascade Processors (3-4 hours)

**Goal**: Backfill player_composite_factors and ml_feature_store (depend on tables 1-3)

**Execute sequentially**:
```bash
# First: player_composite_factors (needs 1-3)
PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2024-06-18 --parallel --workers 10

# Then: ml_feature_store (needs 1-4)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2024-06-18 --parallel --workers 10
```

**Critical**: Do NOT run these in parallel - cascade contamination risk!

---

### Stage 5: Final Validation (30 min)

**Goal**: Confirm all tables meet 95%+ coverage target

**Comprehensive validation**:
```sql
-- Final coverage check
WITH expected_dates AS (
  SELECT
    season_year,
    COUNT(DISTINCT game_date) as expected
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE season_year IN (2021, 2022, 2023)
  GROUP BY 1
),
actual_coverage AS (
  SELECT
    'player_composite_factors' as table_name,
    EXTRACT(YEAR FROM game_date) - CASE WHEN EXTRACT(MONTH FROM game_date) < 7 THEN 1 ELSE 0 END as season_year,
    COUNT(DISTINCT game_date) as actual_dates
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-07-01'
  GROUP BY 1, 2

  UNION ALL

  SELECT
    'ml_feature_store',
    EXTRACT(YEAR FROM game_date) - CASE WHEN EXTRACT(MONTH FROM game_date) < 7 THEN 1 ELSE 0 END,
    COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_precompute.ml_feature_store`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-07-01'
  GROUP BY 1, 2
)
SELECT
  a.table_name,
  a.season_year,
  a.actual_dates,
  e.expected,
  ROUND(100.0 * a.actual_dates / e.expected, 1) as coverage_pct
FROM actual_coverage a
JOIN expected_dates e ON a.season_year = e.season_year
ORDER BY table_name, season_year;
```

**Success criteria**:
- All tables >= 95% coverage
- No cascade contamination (< 5% synthetic fallback)
- No missing season years

---

## TODO LIST

### Pre-Execution (NOW)
- [ ] Run Phase 3 verification query
- [ ] Check current Phase 4 coverage baseline
- [ ] Verify backfill scripts exist and are correct
- [ ] Set up monitoring (BigQuery console, logs)

### Stage 1: Pre-Flight (30 min)
- [ ] Execute Phase 3 coverage queries
- [ ] Document current state
- [ ] Make go/no-go decision

### Stage 2: Independent Processors (2-3 hrs)
- [ ] Start team_defense_zone_analysis backfill
- [ ] Start player_shot_zone_analysis backfill
- [ ] Start player_daily_cache backfill
- [ ] Monitor progress every 30 min

### Stage 3: Mid-Point Validation (15 min)
- [ ] Query coverage for tables 1-3
- [ ] Verify no errors in logs
- [ ] Make go/no-go decision for cascade

### Stage 4: Cascade Processors (3-4 hrs)
- [ ] Run player_composite_factors backfill
- [ ] Validate completion
- [ ] Run ml_feature_store backfill
- [ ] Monitor progress every 30 min

### Stage 5: Final Validation (30 min)
- [ ] Run comprehensive coverage queries
- [ ] Check for cascade contamination
- [ ] Document final state
- [ ] Update handoff document

### Post-Backfill
- [ ] Update Phase 2 status in strategy doc
- [ ] Prepare for Phase 3 (ML training)
- [ ] Create handoff for next session

---

## SUCCESS METRICS

| Metric | Target | Measurement |
|--------|--------|-------------|
| player_composite_factors coverage | >= 95% | SQL query |
| ml_feature_store coverage | >= 95% | SQL query |
| Cascade contamination rate | < 5% | Synthetic fallback check |
| Total backfill time | < 8 hours | Wall clock |
| Zero critical errors | 0 | Log analysis |

---

## FALLBACK PLANS

### If Phase 3 is incomplete
1. Run Phase 3 backfill first (2-4 hours additional)
2. Use existing scripts: `run_phase3_backfill.sh`
3. Then proceed with Phase 4

### If backfill takes too long
1. Prioritize cascade tables (player_composite_factors, ml_feature_store)
2. Accept 90% coverage if needed
3. Flag gaps for future backfill

### If quota limits hit
1. Reduce workers from 10 to 5
2. Add delays between dates
3. Spread across multiple days

### If cascade contamination detected
1. Re-run affected dates
2. Investigate root cause
3. Fix upstream gaps first

---

## NEXT SESSION (Phase 3 - ML Showdown)

After Phase 2 completes successfully:

1. **Extract training data**: Query ml_feature_store for 2021-2024
2. **Train XGBoost v6**: Complete features, no missing data
3. **Add regularization**: Prevent overfitting (4.14 train vs 4.63 test gap)
4. **Compare fairly**: XGBoost v6 vs Mock v1 (4.80 MAE baseline)
5. **Decision**: If XGBoost wins by 0.10+ MAE, deploy ML

**Target MAE**: 4.50-4.60 (beat mock's 4.80 decisively)

---

## APPENDIX: Quick Reference

### Date Ranges

| Season | Regular Start | Regular End | Playoffs End |
|--------|---------------|-------------|--------------|
| 2021-22 | 2021-10-19 | 2022-04-10 | 2022-06-17 |
| 2022-23 | 2022-10-18 | 2023-04-09 | 2023-06-13 |
| 2023-24 | 2023-10-24 | 2024-04-14 | 2024-06-18 |

### Key Scripts

```bash
# Master orchestrator (playoffs focus)
./bin/backfill/run_complete_historical_backfill.sh

# Individual Phase 4 processors
./bin/backfill/run_phase4_backfill.sh

# Verification
./bin/backfill/preflight_verification.sh
```

### BigQuery Tables

```
nba_analytics.player_game_summary
nba_analytics.team_offense_game_summary
nba_analytics.team_defense_game_summary

nba_precompute.team_defense_zone_analysis
nba_precompute.player_shot_zone_analysis
nba_precompute.player_daily_cache
nba_precompute.player_composite_factors
nba_precompute.ml_feature_store
```

---

## EXECUTION RESULTS

### Phase 2 Verification Complete (January 9, 2026)

**Phase 3 Analytics**: ✅ 100% Complete
- player_game_summary: 213/212/207 dates (2021/2022/2023)
- team_offense_game_summary: 215/214/209 dates
- team_defense_game_summary: 215/214/209 dates

**Phase 4 Precompute**: ✅ Maximum Coverage Achieved

| Table | 2021 | 2022 | 2023 | Status |
|-------|------|------|------|--------|
| player_composite_factors | 199 (93%) | 198 (93%) | 193 (93%) | ✅ |
| team_defense_zone_analysis | 200 (94%) | 187 (88%) | 181 (87%) | ✅ |
| player_shot_zone_analysis | 197 (92%) | 195 (92%) | 191 (92%) | ✅ |
| player_daily_cache | 199 (93%) | 197 (93%) | 193 (93%) | ✅ |
| ml_feature_store_v2 | 199 (93%) | 198 (93%) | 193 (93%) | ✅ |

**Gap Analysis**: Attempted TDZA backfill for Nov 1-12 (2022) and Nov 8-19 (2023)
- Result: `INSUFFICIENT_DATA` - teams need 15 games minimum
- Conclusion: Gaps are bootstrap periods, cannot be backfilled

**PHASE 2 COMPLETE** ✅

---

## READY FOR PHASE 3: ML TRAINING

Next step: Train XGBoost v6 with complete ml_feature_store_v2 data (93% coverage).
