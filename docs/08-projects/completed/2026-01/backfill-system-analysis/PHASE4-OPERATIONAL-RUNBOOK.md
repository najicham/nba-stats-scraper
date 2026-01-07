# Phase 4 (Precompute) Operational Runbook

**Purpose**: Practical guide for executing and troubleshooting Phase 4 backfills
**Audience**: Anyone running Phase 4 precompute layer backfills
**Last Updated**: January 3, 2026

---

## 🎯 QUICK START

### Prerequisites Check

```bash
# 1. Verify Phase 3 data exists
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as dates
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '[START_DATE]' AND '[END_DATE]'
"
# Should return > 80% of expected dates

# 2. Verify Phase 4 dependencies exist
bq query --use_legacy_sql=false "
SELECT
  (SELECT COUNT(DISTINCT analysis_date) FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date BETWEEN '[START_DATE]' AND '[END_DATE]') as tdza_dates,
  (SELECT COUNT(DISTINCT analysis_date) FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date BETWEEN '[START_DATE]' AND '[END_DATE]') as psza_dates
"
# Both should be > 75%

# 3. Check for running processes
ps aux | grep "player_composite_factors\|precompute" | grep -v grep
# Should return nothing (no conflicts)
```

### Execute Backfill

```bash
# Standard execution (with pre-flight check)
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-01-01 \
    --end-date 2024-06-01 \
    > logs/phase4_pcf_backfill_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Save PID
echo $! > /tmp/phase4_backfill.pid

# Skip pre-flight (for historical dates with incomplete context)
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-01-01 \
    --end-date 2024-06-01 \
    --skip-preflight \
    > logs/phase4_pcf_backfill_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Monitor Progress

```bash
# Check process
cat /tmp/phase4_backfill.pid | xargs ps -p

# Check log
tail -f logs/phase4_pcf_backfill_*.log

# Count processed dates
grep -c "Success:" logs/phase4_pcf_backfill_*.log
```

---

## 📋 PHASE 4 PROCESSORS OVERVIEW

### Processing Order (CASCADE Dependencies)

```
1. team_defense_zone_analysis (TDZA)
   ├─ Depends on: Phase 3 (team_defense_game_summary)
   └─ Produces: Team defensive zone weaknesses

2. player_shot_zone_analysis (PSZA)
   ├─ Depends on: Phase 3 (player_game_summary)
   └─ Produces: Player shot zone preferences

3. player_daily_cache (PDC)
   ├─ Depends on: Phase 3 (team_offense_game_summary)
   └─ Produces: Player daily stats cache

4. player_composite_factors (PCF) ← MAIN PROCESSOR
   ├─ Depends on: TDZA, PSZA, Phase 3
   └─ Produces: 4-factor composite adjustments

5. ml_feature_store (MLFS)
   ├─ Depends on: PCF, PDC, Phase 3
   └─ Produces: ML features for predictions
```

**CRITICAL**: Must run in order (1 → 2 → 3 → 4 → 5)

### Backfill Scripts Location

```
/backfill_jobs/precompute/
├── team_defense_zone_analysis/
│   └── team_defense_zone_analysis_precompute_backfill.py
├── player_shot_zone_analysis/
│   └── player_shot_zone_analysis_precompute_backfill.py
├── player_daily_cache/
│   └── player_daily_cache_precompute_backfill.py
├── player_composite_factors/
│   └── player_composite_factors_precompute_backfill.py
└── ml_feature_store/
    └── ml_feature_store_precompute_backfill.py
```

---

## ⚙️ PLAYER COMPOSITE FACTORS (PCF) DETAILS

### What It Does

Calculates 4 contextual adjustment factors for each player-game:

1. **Fatigue** (0-100 score → -5 to 0 adjustment)
   - Back-to-back games
   - High minutes recently
   - Age factor
   - Recent workload

2. **Shot Zone Mismatch** (-10 to +10 adjustment)
   - Player's primary scoring zones
   - Opponent's defensive weaknesses
   - Usage-weighted impact

3. **Pace Differential** (-3 to +3 adjustment)
   - Game pace vs league average
   - Player's pace preferences

4. **Usage Spike** (-3 to +3 adjustment)
   - Projected vs baseline usage
   - Boosted if star teammates out

**Total Adjustment Range**: -21 to +15 points per player

### Bootstrap Period (CRITICAL)

**First 14 days of EACH season are SKIPPED**:

| Season | Bootstrap Period | Reason |
|--------|-----------------|--------|
| 2021-22 | Oct 19 - Nov 1 | Need L7d/L10 history |
| 2022-23 | Oct 24 - Nov 6 | Need L7d/L10 history |
| 2023-24 | Oct 18 - Oct 31 | Need L7d/L10 history |
| 2024-25 | Oct 22 - Nov 4 | Need L7d/L10 history |

**Why**: Rolling window features (L5, L7d, L10) require game history

**Impact**: Expected coverage is **88%, NOT 100%** (by design)

### Synthetic Context Generation

When `upcoming_player_game_context` or `upcoming_team_game_context` are incomplete:

```python
# Automatic fallback for historical dates
if context_missing:
    # Generate from player_game_summary instead
    # Uses actual stats vs betting projections
    # Slightly less accurate but valid
```

**Use Cases**:
- Historical backfills (no betting lines exist)
- Data gaps in upstream
- Resilient execution

---

## 🚀 EXECUTION SCENARIOS

### Scenario 1: Full Historical Backfill (2021-2026)

**Use Case**: Initial data population or complete refresh

**Commands**:
```bash
# Step 1: TDZA (run first)
PYTHONPATH=. python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    > logs/phase4_tdza_$(date +%Y%m%d).log 2>&1 &

# Wait for completion, then...

# Step 2: PSZA (run second)
PYTHONPATH=. python3 backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    > logs/phase4_psza_$(date +%Y%m%d).log 2>&1 &

# Wait for completion, then...

# Step 3: PCF (run third - main processor)
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    --skip-preflight \
    > logs/phase4_pcf_$(date +%Y%m%d).log 2>&1 &

# Step 4: MLFS (run fourth - ML features)
PYTHONPATH=. python3 backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    > logs/phase4_mlfs_$(date +%Y%m%d).log 2>&1 &
```

**Timing**:
- TDZA: ~2-3 hours
- PSZA: ~3-4 hours
- PCF: ~7-8 hours
- MLFS: ~2-3 hours
- **Total**: ~15-18 hours (can optimize with parallelization)

### Scenario 2: Single Season Backfill

**Use Case**: Fill gap for one season (e.g., 2024-25)

```bash
# Just PCF (if dependencies already exist)
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-10-22 \
    --end-date 2025-06-01 \
    --skip-preflight \
    > logs/phase4_pcf_2024_25_$(date +%Y%m%d).log 2>&1 &
```

**Timing**: ~2-3 hours for one season

### Scenario 3: Targeted Date Range

**Use Case**: Fill specific gap (e.g., playoff dates)

```bash
# Specific date range
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-04-15 \
    --end-date 2024-06-18 \
    --skip-preflight \
    > logs/phase4_pcf_playoffs_$(date +%Y%m%d).log 2>&1 &
```

**Timing**: ~1-2 hours for playoff range

### Scenario 4: Retry Failed Dates

**Use Case**: Re-process specific dates that failed

```bash
# Using --dates flag (comma-separated)
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --dates 2024-01-05,2024-01-12,2024-02-03 \
    > logs/phase4_pcf_retry_$(date +%Y%m%d).log 2>&1 &
```

**Timing**: ~1 minute per date

### Scenario 5: Dry Run (Test Only)

**Use Case**: Check what would happen without executing

```bash
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-01-01 \
    --end-date 2024-01-07 \
    --dry-run
```

**Output**: Dependency check results, no data written

---

## 📊 MONITORING & VALIDATION

### Real-Time Monitoring

```bash
# 1. Check process status
ps -p $(cat /tmp/phase4_backfill.pid) -o pid,etime,%cpu,%mem,stat

# 2. Watch log in real-time
tail -f logs/phase4_pcf_backfill_*.log | grep -E "Processing|Success|Failed|Progress"

# 3. Count progress
watch -n 30 "grep -c 'Success:' logs/phase4_pcf_backfill_*.log"

# 4. Check coverage in BigQuery
watch -n 300 'bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(DISTINCT analysis_date) as dates
FROM nba_precompute.player_composite_factors
WHERE analysis_date >= CURRENT_DATE() - 30
"'
```

### Performance Metrics

```bash
# Extract metrics from log
grep "PRECOMPUTE_STATS" logs/phase4_pcf_backfill_*.log | tail -20

# Calculate processing rate
START_TIME=$(head -1 logs/phase4_pcf_backfill_*.log | grep -oP '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
CURRENT_DATES=$(grep -c "Success:" logs/phase4_pcf_backfill_*.log)
echo "Dates processed: $CURRENT_DATES"
```

### Validation After Completion

```bash
# 1. Coverage check
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(DISTINCT analysis_date) as pcf_dates,
  COUNT(*) as total_records,
  MIN(analysis_date) as earliest,
  MAX(analysis_date) as latest,
  ROUND(COUNT(DISTINCT analysis_date) * 100.0 / 888, 1) as coverage_pct
FROM nba_precompute.player_composite_factors
WHERE analysis_date BETWEEN '2021-10-19' AND '2026-01-02'
"

# 2. Pipeline completeness
python3 scripts/validation/validate_pipeline_completeness.py \
    --start-date 2021-10-01 \
    --end-date 2026-01-02

# 3. Feature validation
python3 scripts/validation/validate_backfill_features.py \
    --start-date 2021-10-01 \
    --end-date 2026-01-02 \
    --full --check-regression

# 4. ml_feature_store check
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates_with_features,
  COUNT(*) as total_records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2021-10-01' AND '2024-06-01'
"
```

**Success Criteria**:
- ✅ Coverage ≥85% (target 88%)
- ✅ Bootstrap exclusions = 28 dates (4 seasons × ~7 days)
- ✅ No critical failures
- ✅ Feature coverage ≥95%
- ✅ No regressions detected
- ✅ ml_feature_store_v2 populated

---

## 🔧 TROUBLESHOOTING

### Issue: Pre-flight Check Fails

**Symptoms**:
```
ERROR: PRE-FLIGHT CHECK FAILED: Phase 3 data is incomplete!
Cannot proceed with Phase 4 backfill until Phase 3 is complete.
```

**Diagnosis**:
```bash
# Check what's missing
python bin/backfill/verify_phase3_for_phase4.py \
    --start-date [START] \
    --end-date [END] \
    --verbose
```

**Solutions**:

**Option 1**: Run Phase 3 backfill first (recommended for production)
```bash
# Fill Phase 3 gaps
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
    --start-date [START] --end-date [END]
```

**Option 2**: Skip pre-flight (use for historical dates with synthetic context)
```bash
# Add --skip-preflight flag
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date [START] \
    --end-date [END] \
    --skip-preflight
```

**When to use Option 2**:
- Historical dates (no betting context available)
- Context tables < 60% (synthetic fallback available)
- player_game_summary > 95% (critical dependency met)

### Issue: Process Stalled/Hung

**Symptoms**:
- Log not growing
- CPU at 0%
- No progress for > 10 minutes

**Diagnosis**:
```bash
# Check process state
ps -p $(cat /tmp/phase4_backfill.pid) -o pid,stat,wchan:20

# Check for BigQuery errors
tail -100 logs/phase4_pcf_backfill_*.log | grep -i "error\|timeout\|quota"
```

**Solutions**:

**BigQuery quota exceeded**:
```bash
# Wait 1 hour, process auto-resumes from checkpoint
sleep 3600
# Check if resumed
tail -f logs/phase4_pcf_backfill_*.log
```

**Network timeout**:
```bash
# Kill and restart (checkpoint preserved)
kill $(cat /tmp/phase4_backfill.pid)
# Re-run same command (auto-resumes)
```

**Memory exhaustion**:
```bash
# Check memory
free -h
# Restart with lower parallelization if needed
```

### Issue: High Failure Rate

**Symptoms**:
```
Progress: 100/917 dates (90.0% success), 10 failed
```

**Diagnosis**:
```bash
# Find failed dates
grep "✗ Failed" logs/phase4_pcf_backfill_*.log

# Check error patterns
grep "ERROR" logs/phase4_pcf_backfill_*.log | sort | uniq -c | sort -rn
```

**Common Causes & Solutions**:

**Missing dependencies (TDZA/PSZA)**:
```bash
# Check dependency coverage
bq query --use_legacy_sql=false "
SELECT analysis_date
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '[START]' AND '[END]'
  AND analysis_date NOT IN (
    SELECT analysis_date FROM nba_precompute.player_shot_zone_analysis
  )
ORDER BY analysis_date
LIMIT 20
"
# Backfill dependencies first
```

**Data quality issues**:
```bash
# Check for NULL critical fields
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as null_players
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '[START]' AND '[END]'
  AND (player_lookup IS NULL OR universal_player_id IS NULL)
GROUP BY game_date
HAVING null_players > 0
"
```

**Retry failed dates**:
```bash
# Extract failed dates
grep "✗ Failed" logs/phase4_pcf_backfill_*.log | grep -oP '\d{4}-\d{2}-\d{2}' > failed_dates.txt

# Convert to comma-separated
FAILED_DATES=$(cat failed_dates.txt | paste -sd,)

# Retry
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --dates $FAILED_DATES \
    --skip-preflight
```

### Issue: Coverage Below Expected

**Symptoms**:
- Coverage shows 70% instead of expected 88%

**Diagnosis**:
```bash
# Check bootstrap exclusions
grep "Skipped: bootstrap" logs/phase4_pcf_backfill_*.log | wc -l
# Should be ~28 for full range (2021-2026)

# Check processable vs total dates
grep "Processing game date" logs/phase4_pcf_backfill_*.log | wc -l
```

**Solutions**:

**Verify expected coverage calculation**:
```python
total_game_dates = 917  # For 2021-2026
bootstrap_exclusions = 28  # 4 seasons × 7 days avg
processable = 889
expected_coverage = (processable / (total_game_dates + bootstrap_exclusions)) * 100
# = 889 / 917 = 96.9% of game dates
# = 889 / 888 = ~100% of processable dates
```

**Check for additional failures**:
```bash
# List all skipped dates with reasons
grep "Skipped:" logs/phase4_pcf_backfill_*.log | sort | uniq -c
```

---

## 📝 CHECKPOINT SYSTEM

### How Checkpoints Work

**Location**: `/tmp/backfill_checkpoints/player_composite_factors_[START]_[END].json`

**Content**:
```json
{
  "start_date": "2021-10-19",
  "end_date": "2026-01-02",
  "successful_dates": ["2021-11-02", "2021-11-03", ...],
  "failed_dates": ["2022-02-18", ...],
  "skipped_dates": [],
  "stats": {
    "total_dates": 917,
    "successful": 850,
    "failed": 6,
    "skipped": 61
  },
  "last_updated": "2026-01-03T20:15:30Z"
}
```

### Manual Checkpoint Operations

**View checkpoint status**:
```bash
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    --status
```

**Resume from checkpoint** (automatic):
```bash
# Just re-run same command - auto-resumes
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    --skip-preflight
```

**Ignore checkpoint (start fresh)**:
```bash
# Use --no-resume flag
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-10-19 \
    --end-date 2026-01-02 \
    --no-resume \
    --skip-preflight
```

**Delete checkpoint manually**:
```bash
rm /tmp/backfill_checkpoints/player_composite_factors_2021-10-19_2026-01-02.json
```

---

## ⚡ PERFORMANCE OPTIMIZATION

### Parallel Execution

**Current**: Sequential processing (~30 sec/date)

**Not recommended for PCF**: Processor has internal parallelization (ProcessPoolExecutor)

**For multiple processors**:
```bash
# Run TDZA and PDC in parallel (independent)
PYTHONPATH=. python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2024-01-01 --end-date 2024-06-01 &
PID1=$!

PYTHONPATH=. python3 backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2024-01-01 --end-date 2024-06-01 &
PID2=$!

# Wait for both
wait $PID1 $PID2
```

### Date Range Splitting

**For very large ranges**:
```bash
# Split by season
for SEASON in 2021 2022 2023 2024; do
  python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date ${SEASON}-10-01 \
    --end-date $((SEASON+1))-06-30 \
    --skip-preflight \
    > logs/phase4_pcf_${SEASON}.log 2>&1 &
done
```

**Risk**: Multiple checkpoint files, harder to track

### Resource Tuning

**Environment variables**:
```bash
# Adjust worker count (default: 32)
export PCF_WORKERS=16  # Lower for memory-constrained systems

# Adjust parallelization
export PARALLELIZATION_WORKERS=24

# Run with custom config
PYTHONPATH=. python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-01-01 --end-date 2024-06-01
```

---

## 📚 REFERENCE

### Command Line Flags

| Flag | Description | Example |
|------|-------------|---------|
| `--start-date` | Start date (inclusive) | `--start-date 2024-01-01` |
| `--end-date` | End date (inclusive) | `--end-date 2024-06-01` |
| `--dates` | Specific dates (comma-separated) | `--dates 2024-01-05,2024-01-12` |
| `--dry-run` | Test without writing | `--dry-run` |
| `--skip-preflight` | Skip Phase 3 pre-flight check | `--skip-preflight` |
| `--no-resume` | Ignore checkpoint (start fresh) | `--no-resume` |
| `--status` | Show checkpoint status | `--status` |

### Important Files

**Processors**:
- PCF processor: `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
- Precompute base: `data_processors/precompute/precompute_base.py`

**Backfill Scripts**:
- PCF backfill: `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py`
- All Phase 4: `backfill_jobs/precompute/*/`

**Configuration**:
- Bootstrap days: `shared/validation/config.py` (BOOTSTRAP_DAYS = 14)
- Season detection: `shared/config/nba_season_dates.py`
- Feature thresholds: `shared/validation/feature_thresholds.py`

**Validation**:
- Pipeline completeness: `scripts/validation/validate_pipeline_completeness.py`
- Feature validation: `scripts/validation/validate_backfill_features.py`
- Phase 4 validator: `shared/validation/validators/phase4_validator.py`

**Utilities**:
- Schedule utils: `shared/backfill/schedule_utils.py`
- Checkpoint: `shared/backfill/checkpoint.py`

### BigQuery Tables

**Inputs**:
- `nba_analytics.player_game_summary` (Phase 3)
- `nba_analytics.upcoming_player_game_context` (Phase 3, optional)
- `nba_analytics.upcoming_team_game_context` (Phase 3, optional)
- `nba_precompute.team_defense_zone_analysis` (Phase 4)
- `nba_precompute.player_shot_zone_analysis` (Phase 4)

**Outputs**:
- `nba_precompute.player_composite_factors`
- `nba_predictions.ml_feature_store_v2`

**Tracking**:
- `nba_reference.processor_run_history`
- `nba_orchestration.phase*_completion` (Firestore)

---

## 🎓 BEST PRACTICES

### Before Execution

1. ✅ Verify Phase 3 data exists (≥80% coverage)
2. ✅ Verify Phase 4 dependencies exist (TDZA, PSZA ≥75%)
3. ✅ Check for running processes (avoid conflicts)
4. ✅ Estimate runtime (30 sec/date × number of dates)
5. ✅ Plan for long execution (use nohup or screen)

### During Execution

1. ✅ Monitor logs periodically (every 15-30 min)
2. ✅ Check progress vs expected (dates/hour)
3. ✅ Watch for error patterns
4. ✅ Verify BigQuery coverage incrementally
5. ✅ Don't kill process unnecessarily (checkpoint handles resume)

### After Execution

1. ✅ Run comprehensive validation
2. ✅ Check coverage vs expected (88%)
3. ✅ Verify bootstrap exclusions correct (~28 dates)
4. ✅ Test downstream (ml_feature_store_v2)
5. ✅ Document any issues encountered

### Common Mistakes to Avoid

1. ❌ Running without checking dependencies first
2. ❌ Expecting 100% coverage (should be 88%)
3. ❌ Killing process on first error (let it retry)
4. ❌ Running multiple overlapping backfills (conflicts)
5. ❌ Ignoring bootstrap period design
6. ❌ Not using --skip-preflight for historical dates

---

**Last Updated**: January 3, 2026
**Version**: 1.0
**Maintainer**: See docs/09-handoff/ for session documentation
