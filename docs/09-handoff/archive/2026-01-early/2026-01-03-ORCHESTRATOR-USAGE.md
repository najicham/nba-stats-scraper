# 🤖 Backfill Orchestrator Usage Guide

**Created**: January 3, 2026
**Status**: Production Ready
**Purpose**: Automate multi-phase backfills with validation

---

## ⚡ Quick Start

### Currently Running (Tonight)

Phase 1 (team_offense) is already running. Start the orchestrator to monitor it and auto-start Phase 2:

```bash
cd /home/naji/code/nba-stats-scraper

./scripts/backfill_orchestrator.sh \
  --phase1-pid 3022978 \
  --phase1-log logs/team_offense_backfill_phase1.log \
  --phase1-dates "2021-10-19 2026-01-02" \
  --phase2-dates "2024-05-01 2026-01-02"
```

This will:
1. Monitor Phase 1 until completion (~5-8 hours)
2. Validate team_offense data quality
3. Auto-start Phase 2 (player_game_summary) if validation passes
4. Monitor Phase 2 until completion (~3-4 hours)
5. Validate player_game_summary data quality
6. Provide final report

**Total time**: ~8-12 hours (runs unattended!)

---

## 🏗️ What It Does

### Orchestration Flow

```
Monitor Phase 1 → Parse Logs → Validate BigQuery →
✅ PASS → Auto-start Phase 2 → Monitor Phase 2 →
Validate BigQuery → ✅ PASS → Final Report
```

### Validation Checks

**Phase 1 (team_offense)**:
- Game count >= 5,600
- Success rate >= 95%
- Avg quality score >= 75
- Production ready >= 80%
- No blocking issues

**Phase 2 (player_game_summary)**:
- Record count >= 35,000
- Success rate >= 95%
- minutes_played >= 99% (CRITICAL)
- usage_rate >= 95% (CRITICAL)
- shot_zones >= 40%
- Avg quality score >= 75
- Production ready >= 95%
- No blocking issues

---

## 📋 Command Reference

### Full Syntax

```bash
./scripts/backfill_orchestrator.sh \
  --phase1-pid <PID> \
  --phase1-log <log_file> \
  --phase1-dates "<start> <end>" \
  --phase2-dates "<start> <end>" \
  [--config <config_file>] \
  [--dry-run]
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--phase1-pid` | Yes | Process ID of running Phase 1 backfill |
| `--phase1-log` | Yes | Log file path for Phase 1 |
| `--phase1-dates` | Yes | Start and end dates (space-separated) |
| `--phase2-dates` | No | Dates for auto-starting Phase 2 |
| `--config` | No | Custom config file (default: scripts/config/backfill_thresholds.yaml) |
| `--dry-run` | No | Test mode - won't actually start Phase 2 |

### Examples

**Monitor Phase 1 only** (no Phase 2 auto-start):
```bash
./scripts/backfill_orchestrator.sh \
  --phase1-pid 3022978 \
  --phase1-log logs/team_offense_backfill_phase1.log \
  --phase1-dates "2021-10-19 2026-01-02"
```

**Full orchestration** (auto-start Phase 2):
```bash
./scripts/backfill_orchestrator.sh \
  --phase1-pid 3022978 \
  --phase1-log logs/team_offense_backfill_phase1.log \
  --phase1-dates "2021-10-19 2026-01-02" \
  --phase2-dates "2024-05-01 2026-01-02"
```

**Dry run** (test without starting Phase 2):
```bash
./scripts/backfill_orchestrator.sh \
  --phase1-pid 3022978 \
  --phase1-log logs/team_offense_backfill_phase1.log \
  --phase1-dates "2021-10-19 2026-01-02" \
  --phase2-dates "2024-05-01 2026-01-02" \
  --dry-run
```

---

## 📊 Output & Monitoring

### Real-Time Progress

The orchestrator shows progress every 10 polling cycles (default: every 10 minutes):

```
[13:45:12] 📊 Progress: 150/1537 days (9.8%), 1387 remaining
[13:45:12]   Success rate: 98.0%, Records: 2,240
[13:45:12]   Elapsed: 33m 5s
```

### Validation Output

```
════════════════════════════════════════════════════════
  VALIDATING TEAM_OFFENSE_GAME_SUMMARY
════════════════════════════════════════════════════════

[14:20:05] Check 1/4: Game count...
[14:20:06] ✅ Game count: 5,798 (threshold: 5,600+) ✓

[14:20:06] Check 2/4: Record count...
[14:20:07] ✅ Record count: 11,596 (~2 per game) ✓

[14:20:07] Check 3/4: Quality metrics...
[14:20:09] ✅ Avg quality score: 81.2 (threshold: 75+) ✓
[14:20:09] ✅ Production ready: 84.3% (threshold: 80%+) ✓
[14:20:09]   Gold/Silver tier: 87.1%

[14:20:09] Check 4/4: Critical issues...
[14:20:10] ✅ No critical blocking issues ✓

════════════════════════════════════════════════════════
  VALIDATION SUMMARY
════════════════════════════════════════════════════════

[14:20:10] ✅ team_offense_game_summary: ALL CHECKS PASSED ✓
[14:20:10]   Games: 5,798, Records: 11,596
[14:20:10]   Quality: 81.2, Production Ready: 84.3%
```

### Final Report

```
════════════════════════════════════════════════════════
  ORCHESTRATOR FINAL REPORT
════════════════════════════════════════════════════════

[22:15:30] ✅ ALL PHASES COMPLETE & VALIDATED ✓

[22:15:30] Phase 1: team_offense_game_summary
[22:15:30]   Duration: 7h 32m 18s
[22:15:30]   Success rate: 99.2%
[22:15:30]   Records: 11,596
[22:15:30]   Validation: ✅ PASSED

[22:15:30] Phase 2: player_game_summary
[22:15:30]   Duration: 2h 43m 12s
[22:15:30]   Success rate: 98.8%
[22:15:30]   Records: 38,547
[22:15:30]   Validation: ✅ PASSED

[22:15:30] Total Duration: 10h 15m 30s
[22:15:30] ✅ Data is ready for ML training! 🎉

[22:15:30] Next steps:
[22:15:30]   1. ⏭️  Run Phase 4 backfill (precompute)
[22:15:30]   2. ⏭️  Train XGBoost v5 model
[22:15:30]   3. ⏭️  Compare to 4.27 MAE baseline
```

---

## ⚙️ Configuration

### Threshold Configuration

Edit `scripts/config/backfill_thresholds.yaml`:

```yaml
team_offense:
  min_games: 5600
  min_success_rate: 95.0
  min_quality_score: 75.0
  min_production_ready_pct: 80.0

player_game_summary:
  min_records: 35000
  min_success_rate: 95.0
  minutes_played_pct: 99.0      # CRITICAL
  usage_rate_pct: 95.0          # CRITICAL
  shot_zones_pct: 40.0
  min_quality_score: 75.0
  min_production_ready_pct: 95.0

polling:
  interval_seconds: 60
  progress_update_interval: 10
```

---

## 🚨 Troubleshooting

### Orchestrator Won't Start

**Symptom**: Error about missing PID or log file

**Solution**:
```bash
# Check if Phase 1 is running:
ps aux | grep team_offense | grep -v grep

# If not running, Phase 1 may have completed. Check log:
tail -50 logs/team_offense_backfill_phase1.log
```

### Validation Fails

**Symptom**: Validation check fails, Phase 2 doesn't start

**Solutions**:

1. **Game count too low**:
   ```sql
   -- Check actual game count
   SELECT COUNT(DISTINCT game_id)
   FROM nba_analytics.team_offense_game_summary
   WHERE game_date >= '2021-10-19'
   ```

2. **Feature coverage too low**:
   ```sql
   -- Check minutes_played coverage
   SELECT
     COUNTIF(minutes_played IS NOT NULL) * 100.0 / COUNT(*) as pct
   FROM nba_analytics.player_game_summary
   WHERE game_date >= '2024-05-01' AND points IS NOT NULL
   ```

3. **Lower thresholds** (if justified):
   - Edit `scripts/config/backfill_thresholds.yaml`
   - Adjust thresholds as needed
   - Re-run orchestrator

### Phase 2 Fails to Start

**Symptom**: Phase 1 passes validation but Phase 2 doesn't start

**Solution**:
```bash
# Check if Phase 2 command is valid:
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --help

# Check Phase 2 log for errors:
tail -50 logs/player_game_summary_backfill_phase2.log
```

### Orchestrator Hangs

**Symptom**: No progress updates for >1 hour

**Solution**:
```bash
# Check if Phase 1 process is still running:
ps aux | grep 3022978

# Check if log file is being updated:
ls -lh logs/team_offense_backfill_phase1.log
tail -20 logs/team_offense_backfill_phase1.log

# If hung, kill and restart:
kill 3022978
# Then restart Phase 1 manually (it will resume from checkpoint)
```

---

## 🔧 Advanced Usage

### Manual Validation Only

Run validation without orchestration:

```bash
# Validate team_offense
bash scripts/validation/validate_team_offense.sh \
  "2021-10-19" "2026-01-02"

# Validate player_game_summary
bash scripts/validation/validate_player_summary.sh \
  "2024-05-01" "2026-01-02"
```

### Custom Validation Thresholds

Create custom config:

```bash
cp scripts/config/backfill_thresholds.yaml /tmp/custom_thresholds.yaml
vim /tmp/custom_thresholds.yaml  # Edit as needed

# Run with custom config
./scripts/backfill_orchestrator.sh \
  --phase1-pid 3022978 \
  --phase1-log logs/team_offense_backfill_phase1.log \
  --phase1-dates "2021-10-19 2026-01-02" \
  --config /tmp/custom_thresholds.yaml
```

### Run in Background

Use `nohup` or `screen` to run unattended:

```bash
# Using nohup
nohup ./scripts/backfill_orchestrator.sh \
  --phase1-pid 3022978 \
  --phase1-log logs/team_offense_backfill_phase1.log \
  --phase1-dates "2021-10-19 2026-01-02" \
  --phase2-dates "2024-05-01 2026-01-02" \
  > logs/orchestrator_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "Orchestrator PID: $!"

# Monitor progress
tail -f logs/orchestrator_*.log
```

---

## 📁 Files Created

### Scripts
- `scripts/backfill_orchestrator.sh` - Main orchestrator
- `scripts/monitoring/monitor_process.sh` - Process monitoring
- `scripts/monitoring/parse_backfill_log.sh` - Log parsing
- `scripts/validation/validate_team_offense.sh` - Phase 1 validation
- `scripts/validation/validate_player_summary.sh` - Phase 2 validation
- `scripts/validation/common_validation.sh` - Shared utilities

### Configuration
- `scripts/config/backfill_thresholds.yaml` - Validation thresholds

### Documentation
- `docs/09-handoff/2026-01-03-ORCHESTRATOR-USAGE.md` - This file
- `docs/08-projects/current/backfill-system-analysis/ULTRATHINK-ORCHESTRATOR-AND-VALIDATION-MASTER-PLAN.md` - Design doc

---

## 🎯 Success Criteria

**Orchestrator succeeds when**:
- ✅ Phase 1 completes with >95% success rate
- ✅ Phase 1 validation passes all checks
- ✅ Phase 2 auto-starts (if configured)
- ✅ Phase 2 completes with >95% success rate
- ✅ Phase 2 validation passes all checks
- ✅ Final report shows data ready for ML training

**What this prevents**:
- ❌ Forgetting to start Phase 2 manually
- ❌ Starting Phase 2 when Phase 1 failed
- ❌ Proceeding with bad data (0% usage_rate)
- ❌ "Claimed complete but wasn't" disasters

---

**Created**: January 3, 2026, 13:45 UTC
**Status**: Production Ready
**Next**: Run orchestrator to monitor Phase 1 and auto-start Phase 2
