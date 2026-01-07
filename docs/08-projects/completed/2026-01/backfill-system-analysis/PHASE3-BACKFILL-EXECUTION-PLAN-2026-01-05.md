# Phase 3 Backfill Execution Plan - January 5, 2026, 3:30 AM

**Status**: Phase 4 failed pre-flight check due to incomplete Phase 3
**Goal**: Complete Phase 3 properly, then start Phase 4
**Approach**: Validation-first, comprehensive completion

---

## 📊 SITUATION SUMMARY

### What Happened
- Started Phase 4 last night at 7:30 PM
- Phase 4's built-in validation detected incomplete Phase 3
- Stopped after 15 minutes (fail-fast design worked!)
- Missing: 3 of 5 Phase 3 tables incomplete

### Current Phase 3 Status (from pre-flight logs)

| Table | Coverage | Status |
|-------|----------|--------|
| player_game_summary | 848/848 (100%) | ✅ COMPLETE |
| team_offense_game_summary | 848/848 (100%) | ✅ COMPLETE |
| **team_defense_game_summary** | **776/848 (91.5%)** | ⚠️ **72 dates missing** |
| **upcoming_player_game_context** | **446/848 (52.6%)** | ⚠️ **402 dates missing** |
| **upcoming_team_game_context** | **496/848 (58.5%)** | ⚠️ **352 dates missing** |

---

## 🎯 VALIDATION-FIRST APPROACH

### Step 1: Comprehensive Validation (RUNNING NOW)

**Command**:
```bash
python3 bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --verbose
```

**What it checks**:
- All 5 Phase 3 tables
- Coverage percentage (target: ≥95%)
- Missing dates (with verbose output)
- Bootstrap exclusions (first 14 days of season)

**Expected output**:
- ✅ player_game_summary: 100%
- ✅ team_offense_game_summary: 100%
- ⚠️ team_defense_game_summary: 91.5%
- ⚠️ upcoming_player_game_context: 52.6%
- ⚠️ upcoming_team_game_context: 58.5%

---

## 📋 EXECUTION PLAN

### Decision Tree Based on Validation Results

#### Option A: Critical Tables Only (RECOMMENDED)

**If Phase 4 processors can work with synthetic context fallback:**

**Backfill**:
1. ✅ team_defense_game_summary (72 dates missing)

**Skip**:
2. ❌ upcoming_player_game_context (has synthetic fallback)
3. ❌ upcoming_team_game_context (has synthetic fallback)

**Timeline**: 1-2 hours
**Phase 4 Ready**: Yes (with degraded context quality)
**ML Ready**: Yes (doesn't use context tables)

#### Option B: Complete All Tables (THOROUGH)

**Backfill all 3 incomplete tables**:
1. team_defense_game_summary (72 dates)
2. upcoming_player_game_context (402 dates)
3. upcoming_team_game_context (352 dates)

**Timeline**: 4-6 hours (if parallel)
**Phase 4 Ready**: Yes (full quality)
**ML Ready**: Yes (complete features)

#### Option C: Phase 4 with Skip-Preflight (FAST BUT RISKY)

**Skip Phase 3 backfill entirely:**
- Use `--skip-preflight` flag
- Phase 4 runs with incomplete dependencies
- Expected: 8.5% hard failures + 45% degraded quality

**Timeline**: Start immediately
**Phase 4 Ready**: Partial (60-75% success)
**ML Ready**: Degraded (4.0-4.5 MAE vs 3.8-4.0)

---

## 🚀 RECOMMENDED EXECUTION (Option A)

### Phase 1: Validate (RUNNING)

```bash
# Already running - wait for completion
python3 bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --verbose
```

### Phase 2: Backfill team_defense_game_summary

**Check if script supports parallelization**:
```bash
python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py --help | grep parallel
```

**If parallel supported**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --parallel \
  --workers 15 \
  > /tmp/team_defense_backfill_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "Team defense backfill PID: $!"
```

**If NOT parallel supported**:
```bash
nohup python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/team_defense_backfill_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

**Expected time**:
- With parallelization: 15-30 minutes (72 dates)
- Without parallelization: 1-2 hours

### Phase 3: Re-Validate Phase 3

```bash
python3 bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03
```

**Success criteria**:
- team_defense_game_summary: ≥95% (was 91.5%)
- All other tables: remain at current levels

### Phase 4: Start Phase 4 (Updated Orchestrator)

**Create improved orchestrator with validation**:

```bash
cat > /tmp/run_phase4_with_validation.sh <<'EOF'
#!/bin/bash
# Phase 4 Orchestrator with Pre-Flight Validation
set -e

CD_DIR="/home/naji/code/nba-stats-scraper"
START_DATE="2021-10-19"
END_DATE="2026-01-03"

cd "$CD_DIR"
export PYTHONPATH=.

# ===== STEP 0: PRE-FLIGHT VALIDATION =====
echo "================================================================"
echo "PRE-FLIGHT: Validating Phase 3 is complete"
echo "================================================================"

python3 bin/backfill/verify_phase3_for_phase4.py \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ FATAL: Phase 3 incomplete (exit code: $EXIT_CODE)"
    echo ""
    echo "Review output above for missing tables."
    echo ""
    echo "Options:"
    echo "  1. Run Phase 3 backfills to fill gaps"
    echo "  2. Use --skip-preflight flag (NOT RECOMMENDED)"
    echo ""
    exit 1
fi

echo "✅ Phase 3 verified complete"
echo ""

# ===== PHASE 4 EXECUTION =====
echo "================================================================"
echo "PHASE 4 OVERNIGHT EXECUTION STARTING"
echo "================================================================"
echo "Start time: $(date)"
echo ""

# GROUP 1: Run in parallel (independent)
echo "=== GROUP 1: Starting team_defense_zone + player_shot_zone (parallel) ==="
echo "Expected: 3-4 hours"
echo ""

nohup python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date "$START_DATE" --end-date "$END_DATE" \
  > /tmp/phase4_team_defense_$(date +%Y%m%d_%H%M%S).log 2>&1 &
PID_TEAM_DEFENSE=$!

nohup python3 backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date "$START_DATE" --end-date "$END_DATE" \
  > /tmp/phase4_player_shot_$(date +%Y%m%d_%H%M%S).log 2>&1 &
PID_PLAYER_SHOT=$!

echo "Started team_defense_zone (PID: $PID_TEAM_DEFENSE)"
echo "Started player_shot_zone (PID: $PID_PLAYER_SHOT)"
echo ""
echo "Waiting for Group 1 to complete..."

wait $PID_TEAM_DEFENSE
wait $PID_PLAYER_SHOT

echo "✓ Group 1 complete at $(date)"
echo ""

# GROUP 2: player_composite_factors (WITH PARALLELIZATION!)
echo "=== GROUP 2: Starting player_composite_factors (PARALLEL MODE) ==="
echo "Expected: 30-45 minutes"
echo ""

nohup python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date "$START_DATE" --end-date "$END_DATE" \
  --parallel --workers 15 \
  > /tmp/phase4_player_composite_$(date +%Y%m%d_%H%M%S).log 2>&1 &
PID_PCF=$!

echo "Started player_composite_factors (PID: $PID_PCF)"
echo "Waiting for Group 2 to complete..."

wait $PID_PCF

echo "✓ Group 2 complete at $(date)"
echo ""

# GROUP 3: player_daily_cache
echo "=== GROUP 3: Starting player_daily_cache ==="
echo "Expected: 2-3 hours"
echo ""

nohup python3 backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date "$START_DATE" --end-date "$END_DATE" \
  > /tmp/phase4_player_daily_$(date +%Y%m%d_%H%M%S).log 2>&1 &
PID_PDC=$!

echo "Started player_daily_cache (PID: $PID_PDC)"
echo "Waiting for Group 3 to complete..."

wait $PID_PDC

echo "✓ Group 3 complete at $(date)"
echo ""

# GROUP 4: ml_feature_store
echo "=== GROUP 4: Starting ml_feature_store ==="
echo "Expected: 2-3 hours"
echo ""

nohup python3 backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date "$START_DATE" --end-date "$END_DATE" \
  > /tmp/phase4_ml_feature_$(date +%Y%m%d_%H%M%S).log 2>&1 &
PID_ML=$!

echo "Started ml_feature_store (PID: $PID_ML)"
echo "Waiting for Group 4 to complete..."

wait $PID_ML

echo "✓ Group 4 complete at $(date)"
echo ""

echo "================================================================"
echo "PHASE 4 COMPLETE!"
echo "================================================================"
echo "End time: $(date)"
EOF

chmod +x /tmp/run_phase4_with_validation.sh
```

**Start Phase 4**:
```bash
nohup /tmp/run_phase4_with_validation.sh > /tmp/phase4_orchestrator_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "Phase 4 orchestrator PID: $!"
```

---

## ⏰ TIMELINE ESTIMATES

### Option A (Recommended)
- **Now - +5 min**: Validation completes
- **+5 min - +35 min**: team_defense backfill (30 min if parallel)
- **+35 min - +40 min**: Re-validate Phase 3
- **+40 min**: Start Phase 4
- **+40 min - +10 hours**: Phase 4 completes
- **Total**: ~10.5 hours → Ready by 2 PM

### Option B (Complete All)
- **Now - +5 min**: Validation completes
- **+5 min - +2.5 hours**: All 3 backfills in parallel
- **+2.5 hours - +2.6 hours**: Re-validate
- **+2.6 hours**: Start Phase 4
- **+2.6 hours - +12.6 hours**: Phase 4 completes
- **Total**: ~13 hours → Ready by 5 PM

### Option C (Skip-Preflight)
- **Now**: Start Phase 4 immediately
- **Now - +9 hours**: Phase 4 completes (with 40-45% degraded quality)
- **Total**: ~9 hours → Ready by 12:30 PM (but degraded)

---

## 📊 SUCCESS CRITERIA

### Phase 3 Validation Pass
```
✅ player_game_summary: ≥95% coverage
✅ team_defense_game_summary: ≥95% coverage
✅ team_offense_game_summary: ≥95% coverage
⚠️ upcoming_player_game_context: ≥50% OR synthetic fallback confirmed
⚠️ upcoming_team_game_context: ≥50% OR synthetic fallback confirmed
```

### Phase 4 Expected Coverage
- **Target**: 840-850 dates (92-93% of 918 total)
- **Bootstrap exclusions**: ~70 dates (intentional)
- **Success**: All 5 processors complete with 90-95% coverage

### ML Training Readiness
- **usage_rate coverage**: ≥95% (currently 89.56%)
- **Feature completeness**: All 21 features available
- **Data quality**: No critical NULL rates or duplicates

---

## 🚨 CONTINGENCY PLANS

### If team_defense backfill fails
1. Check logs for error details
2. Try without --parallel flag (single-threaded)
3. If persistent errors, use --skip-preflight for Phase 4 (degraded mode)

### If validation never passes
1. Review specific table coverage %
2. Determine if synthetic fallback acceptable
3. Document approved exceptions
4. Proceed with --skip-preflight if business approves degraded quality

### If Phase 4 still fails after backfill
1. Re-run validation to confirm Phase 3 complete
2. Check Phase 4 logs for NEW errors (not pre-flight)
3. May need to backfill context tables after all

---

## 📁 FILES CREATED

### Documentation
- `/home/naji/code/nba-stats-scraper/ROOT-CAUSE-WHY-WE-MISSED-PHASE3-TABLES.md`
- `/home/naji/code/nba-stats-scraper/docs/validation-framework/` (5 files from design agent)
- `/home/naji/code/nba-stats-scraper/PHASE3-BACKFILL-EXECUTION-PLAN-2026-01-05.md` (this file)

### Scripts
- `/tmp/run_phase4_with_validation.sh` (improved orchestrator)

### Logs (will be created)
- `/tmp/team_defense_backfill_*.log`
- `/tmp/phase4_orchestrator_*.log`
- `/tmp/phase4_team_defense_*.log`
- `/tmp/phase4_player_shot_*.log`
- `/tmp/phase4_player_composite_*.log`
- `/tmp/phase4_player_daily_*.log`
- `/tmp/phase4_ml_feature_*.log`

---

## 🎯 NEXT IMMEDIATE ACTIONS

1. **Wait for validation to complete** (running now, ~5 min)
2. **Review validation results** (understand exact gaps)
3. **Make decision**: Option A, B, or C
4. **Execute chosen plan**
5. **Monitor progress** (check logs periodically)
6. **Re-validate before Phase 4** (ensure completion)
7. **Start Phase 4 with validation gate**

---

## 💡 KEY LEARNINGS APPLIED

1. ✅ **Comprehensive validation BEFORE execution** (not after)
2. ✅ **Use existing validation scripts** (verify_phase3_for_phase4.py)
3. ✅ **Integrated validation into orchestrator** (pre-flight gate)
4. ✅ **Document all options** (not just "recommended" path)
5. ✅ **Clear success criteria** (quantified coverage %)
6. ✅ **Contingency plans** (what if it fails)
7. ✅ **Timeline transparency** (realistic estimates)

---

**Created**: January 5, 2026, 3:40 AM
**Author**: Claude (comprehensive execution planning)
**Status**: Awaiting validation results to proceed
**Next Check**: 3:45 AM (validation should be complete)
