# Validation Framework Project

**Status:** Active
**Started:** 2026-01-25
**Priority:** P0
**Last Validated:** 2026-01-25 07:30 AM PST

---

## Overview

This project consolidates all validation angles for the NBA pipeline into a comprehensive framework. The goal is to catch issues before they become problems, validate recovery after outages, and maintain confidence in data quality.

---

## Current Status (Updated Jan 25)

| Metric | Status | Notes |
|--------|--------|-------|
| Jan 24 Boxscores | WARNING | 6/7 games (GSW@MIN missing) |
| Jan 24 Analytics | WARNING | 183 players (missing 1 game) |
| Jan 24 Features | WARNING | 100% bronze tier (quality regression) |
| Jan 24 Grading | WARNING | 25.5% complete |
| Auto-Retry | ACTIVE | nbac_player_boxscore pending retry |

See [CURRENT-FINDINGS.md](./CURRENT-FINDINGS.md) for detailed analysis.

---

## Key Documents

| Document | Purpose |
|----------|---------|
| [CURRENT-FINDINGS.md](./CURRENT-FINDINGS.md) | Latest investigation results |
| [VALIDATION-ANGLES.md](./VALIDATION-ANGLES.md) | All 15 validation angles with queries |
| [ROOT-CAUSE-ANALYSIS.md](./ROOT-CAUSE-ANALYSIS.md) | Root cause investigation templates |
| [ISSUES-TO-FIX.md](./ISSUES-TO-FIX.md) | Known issues and fix commands |
| [BACKFILL-PLAN.md](./BACKFILL-PLAN.md) | Backfill prioritization |

---

## Quick Start

### Daily Morning Check (Recommended)

```bash
# 1. Quick completeness check
python bin/validation/daily_data_completeness.py --days 3

# 2. If issues found, diagnose
python bin/validation/daily_pipeline_doctor.py --days 3 --show-fixes

# 3. Check orchestration health
python bin/validation/workflow_health.py --hours 24
```

### After an Outage

```bash
# 1. Check workflow decision gaps (did orchestration stop?)
python bin/validation/workflow_health.py --hours 72 --threshold-minutes 120

# 2. Check end-to-end flow for affected dates
python bin/validation/phase_transition_health.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD

# 3. Comprehensive multi-angle check
python bin/validation/comprehensive_health_check.py --date YYYY-MM-DD

# 4. Root cause analysis
python bin/validation/root_cause_analyzer.py --date YYYY-MM-DD
```

### Deep Investigation

```bash
# Multi-angle validation (7 angles)
python bin/validation/multi_angle_validator.py --date 2026-01-24

# Advanced validation (15 angles)
python bin/validation/advanced_validation_angles.py --days 7

# Weekly coverage report
python bin/validation/check_prediction_coverage.py --weeks 4
```

---

## Validation Tools Inventory

### Primary Tools

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `daily_data_completeness.py` | Phase coverage by date | Daily AM |
| `daily_pipeline_doctor.py` | Issue detection + fix commands | When issues found |
| `workflow_health.py` | Orchestration health | Daily / On-demand |
| `phase_transition_health.py` | Phase flow validation | Daily / On-demand |
| `comprehensive_health_check.py` | 9-angle quality check | Daily / On-demand |

### Investigation Tools

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `root_cause_analyzer.py` | Diagnose WHY issues occur | After issues found |
| `multi_angle_validator.py` | Cross-validate data | After outages |
| `advanced_validation_angles.py` | 15 deep checks | Weekly / Deep dive |

### Operational Tools

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `check_prediction_coverage.py` | Weekly coverage report | Weekly review |
| `validate_orchestration_config.py` | Config drift detection | Pre-deployment |
| `detect_config_drift.py` | Cloud resource drift | Weekly |

---

## Validation Philosophy

### Multiple Angles
Data quality issues can hide from single-dimension checks. By validating from multiple angles simultaneously, discrepancies surface:
- If boxscores exist but analytics don't → Phase 3 failed
- If predictions exist but grading doesn't → Grading processor stalled
- If props exist but predictions don't → Prediction coverage issue

### Layered Timing
Different validations run at different frequencies:
- **Hourly:** Schedule staleness, error rates (planned)
- **Daily:** Completeness, coverage, timing
- **Weekly:** Trends, comprehensive audit
- **On-demand:** Deep investigation, recovery validation

### Trust but Verify
Even when everything looks good, periodically trace a single entity (game, player) through all phases to ensure the happy path actually works.

---

## BigQuery Views

| View | Purpose |
|------|---------|
| `nba_orchestration.v_recovery_dashboard` | Failed processors needing attention |
| `nba_orchestration.pipeline_event_log` | Processor execution audit trail |
| `nba_orchestration.failed_processor_queue` | Processors pending retry |
| `nba_raw.v_nbac_schedule_latest` | Deduplicated schedule view |
| `nba_raw.v_game_id_mappings` | Cross-table game ID mapping |

---

## Known Issue Patterns

### Pattern 1: Missing Boxscore

**Symptoms:**
- Schedule shows game as Final
- Boxscore count < schedule count

**Diagnosis:**
```bash
python bin/validation/root_cause_analyzer.py --issue missing_boxscores --date YYYY-MM-DD
```

**Fix:**
```bash
python bin/backfill/bdl_boxscores.py --date YYYY-MM-DD
```

### Pattern 2: Low Feature Quality

**Symptoms:**
- All features are "bronze" tier
- Prediction coverage is low

**Diagnosis:**
```bash
python bin/validation/comprehensive_health_check.py --date YYYY-MM-DD
# Check: feature_quality, rolling_window_completeness
```

**Fix:**
```bash
python bin/backfill/phase4.py --date YYYY-MM-DD
```

### Pattern 3: Grading Lag

**Symptoms:**
- Predictions exist but grading is incomplete
- Grading rate < 80%

**Diagnosis:**
```bash
python bin/validation/root_cause_analyzer.py --issue grading_lag --date YYYY-MM-DD
```

**Fix:**
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

### Pattern 4: Workflow Decision Gap

**Symptoms:**
- No new data even though games finished
- `workflow_health.py` shows gap

**Diagnosis:**
```bash
python bin/validation/workflow_health.py --hours 72
# Check: workflow_decision_gaps
```

**Fix:**
- Check master controller logs
- Verify Firestore permissions
- Check Cloud Scheduler jobs

---

## Improvement Roadmap

### Near-Term (This Week)

- [ ] Add hourly validation during game hours
- [ ] Integrate Slack alerts for critical issues
- [ ] Fix game ID format inconsistencies in validation scripts

### Medium-Term (This Sprint)

- [ ] Add historical trend analysis
- [ ] Create validation dashboard
- [ ] Add predictive alerting (detect degradation before failure)

### Long-Term (This Quarter)

- [ ] Full automation with self-healing
- [ ] ML-based anomaly detection
- [ ] Cost-benefit backfill prioritization

---

## Related Documentation

- [Pipeline Resilience Improvements](../pipeline-resilience-improvements/README.md)
- [Session Handoff](../../09-handoff/HANDOFF-JAN25-2026-DAILY-VALIDATION-SESSION.md)
- [Orchestration Troubleshooting](../../00-orchestration/troubleshooting.md)

---

*Last Updated: 2026-01-25*
