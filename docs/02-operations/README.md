# Operations Documentation

**Created:** 2025-11-18 15:00 PST
**Last Updated:** 2025-12-02
**Purpose:** Step-by-step operational procedures for backfills, maintenance, and data management
**Audience:** Engineers running backfills, on-call engineers, operators
**Focus:** How to execute operational tasks (backfills, validation, recovery)

---

## Quick Start

| Task | Document |
|------|----------|
| **Daily Operations** | [daily-operations-runbook.md](./daily-operations-runbook.md) |
| **ML Monitoring Reminders** | [ML-MONITORING-REMINDERS.md](./ML-MONITORING-REMINDERS.md) - Automated Slack reminders for XGBoost V1 monitoring |
| **Incident Response** | [incident-response.md](./incident-response.md) |
| **Orchestrator Issues** | [orchestrator-monitoring.md](./orchestrator-monitoring.md) |
| **Pub/Sub Issues** | [pubsub-operations.md](./pubsub-operations.md) |

---

## 🎯 Overview

**This directory contains:**
- ✅ **Daily Operations Runbook** (NEW - daily health checks, common operations)
- ✅ **ML Monitoring Reminders** (Automated Slack reminders for XGBoost V1 performance tracking)
- ✅ **Incident Response Guide** (NEW - severity levels, troubleshooting)
- ✅ **v1.0 Orchestration monitoring** (orchestrators and Pub/Sub)
- ✅ Backfill procedures (historical data, gap filling, re-processing)
- ✅ Data validation procedures (completeness checks, row count reconciliation)
- ✅ Recovery operations (partial backfill recovery)

**Key Distinction:**
- **Operations** (this directory) = Procedures for running tasks
- **Monitoring** (`../monitoring/`) = Observing system health
- **Troubleshooting** (`../processors/`, `../orchestration/`) = Fixing issues

---

## 📖 Documents in This Directory

### **ML Monitoring Reminders** 🔔 AUTOMATED REMINDERS (5 min setup)
**Created:** 2026-01-17
**Purpose:** Automated Slack notifications for XGBoost V1 production performance milestones

**What's Inside:**
- ✅ Automated daily checks at 9:00 AM via cron
- ✅ Slack notifications to `#reminders` channel with rich formatting
- ✅ Desktop notifications (if available)
- ✅ Full task checklists and success criteria for each milestone
- ✅ Reminder dates: 2026-01-24 (7d), 2026-01-31 (14d), 2026-02-16 (30d), 2026-03-17 (60d), 2026-04-17 (Q1)

**Reminder Schedule:**
1. **Day 7** (2026-01-24): Initial XGBoost V1 performance check (verify MAE ≤ 4.5, no placeholders)
2. **Day 14** (2026-01-31): Head-to-head comparison vs CatBoost V8 (100+ overlapping picks)
3. **Day 30** (2026-02-16): Champion decision point (promote, keep, or retrain)
4. **Day 60** (2026-03-17): Ensemble optimization with 60 days of data
5. **Q1 End** (2026-04-17): Quarterly retrain with fresh 2026 data

**Key Files:**
- `ML-MONITORING-REMINDERS.md` - Full milestone documentation with queries
- `../09-handoff/SLACK-REMINDERS-SETUP.md` - Technical setup details
- `~/bin/nba-reminder.sh` - Daily cron script
- `~/bin/nba-slack-reminder.py` - Slack notification sender
- `~/bin/test-slack-reminder.py` - Test script

**Test the System:**
```bash
cd ~/code/nba-stats-scraper
export $(grep -v '^#' .env | xargs)
~/bin/test-slack-reminder.py
```

**Read This:**
- For XGBoost V1 monitoring milestone dates
- To understand what to check at each stage
- When setting up reminder system on new machine
- To verify Slack integration is working

---

### **orchestrator-monitoring.md** 🆕 v1.0 ORCHESTRATION (15 min read)
**Created:** 2025-11-29 16:54 PST
**Purpose:** Monitor and troubleshoot Phase 2→3 and Phase 3→4 orchestrators

**What's Inside:**
- ✅ Quick reference commands for orchestrator status
- ✅ Health check procedures
- ✅ Common issues and resolutions
- ✅ Log analysis and filtering
- ✅ Alerting setup
- ✅ Manual intervention procedures

**Read This:**
- When orchestrators are not triggering
- When checking Firestore state
- For daily health checks
- During incident response

---

### **pubsub-operations.md** 🆕 v1.0 PUB/SUB (15 min read)
**Created:** 2025-11-29 16:55 PST
**Purpose:** Monitor and manage Pub/Sub messaging infrastructure

**What's Inside:**
- ✅ Topic and subscription management
- ✅ Message backlog monitoring
- ✅ Manual message publishing for testing
- ✅ Troubleshooting delivery issues
- ✅ Emergency procedures (pause, purge)

**Read This:**
- When messages are not being delivered
- When checking message backlog
- For manual testing and debugging
- During incident response

---

### **backfill-guide.md** ⭐ PRIMARY GUIDE (60+ min comprehensive read)
**Created:** 2025-11-18 14:45 PST
**Purpose:** Complete step-by-step guide for running backfills safely

**What's Inside:**
- ✅ When to backfill (5 scenarios with decision criteria)
- ✅ Backfill order and sequencing (phase-by-phase, not date-by-date)
- ✅ Date range calculation (including lookback windows)
- ✅ Validation before/after each phase
- ✅ Partial backfill recovery (handle mid-run failures)
- ✅ Early season handling (degraded quality scores)
- ✅ Complete worked examples with commands

### **runbooks/backfill/phase4-precompute-backfill.md** 🆕 PHASE 4 SPECIFIC (20 min read)
**Created:** 2025-12-07
**Purpose:** Phase 4 precompute backfill with expected failure analysis

**What's Inside:**
- ✅ Phase 4 processor chain (TDZA+PSZA parallel → PCF → PDC → ML)
- ✅ Expected failure rates by season week (early season = high failures)
- ✅ Backfill mode optimizations (100x speedup from skipping checks)
- ✅ Failure triage (INSUFFICIENT_DATA = expected, PROCESSING_ERROR = investigate)
- ✅ Validation queries for each processor

**Read This:**
- Before running Phase 4 backfills
- When analyzing why failures occurred
- When validating backfill completion

---

**Scenarios Covered (in backfill-guide.md):**
1. **Historical Data** (full season backfill)
2. **Gap Filling** (missing days)
3. **Re-Processing** (data fix)
4. **Downstream Re-Processing** (manual corrections)
5. **Early Season Backfill** (limited historical data)

**Key Scripts:**
- `bin/backfill/calculate_range.sh` - Calculate date ranges
- `bin/backfill/check_existing.sh` - Check what data exists
- `bin/backfill/validate_phase.sh` - Validate phase completion
- `bin/backfill/monitor_progress.sh` - Real-time progress tracking

**Read This:**
- Before running any backfill
- When filling historical gaps
- When re-processing after data fixes
- When validating backfill completion

---

### **02-dlq-recovery-guide.md** 📮 DLQ RECOVERY (15-20 min read)
**Created:** 2025-11-18 15:15 PST
**Purpose:** Handle failed message processing and Dead Letter Queue recovery

**What's Inside:**
- ✅ DLQ concepts and workflow
- ✅ Recovery scripts (view, find gaps, clear)
- ✅ Common scenarios (outages, bugs, corrupted files)
- ✅ Monitoring DLQ depth
- ✅ Troubleshooting failed processing

**Key Scripts:**
- `bin/recovery/view_dlq.sh` - View failed messages
- `bin/recovery/find_data_gaps.sh` - Find missing data and trigger recovery
- `bin/recovery/clear_dlq.sh` - Clean up after recovery

**Read This:**
- When DLQ alerts fire
- When processing failures occur
- When backfills trigger Phase 2 failures
- During incident response

---

### **03-cloud-run-jobs-arguments.md** 🔧 CLOUD RUN ARGS (10 min read)
**Created:** 2025-11-21 18:35 PST
**Purpose:** Passing arguments to Cloud Run jobs without parsing errors

**What's Inside:**
- ✅ Custom delimiter syntax (`^|^`) for comma-separated values
- ✅ Working patterns for different argument types
- ✅ Real NBA platform examples (seasons, date ranges)
- ✅ Common failures and solutions
- ✅ Debugging tips and validation methods

**Key Pattern:**
```bash
# Comma-separated values (the critical pattern)
--args="^|^--seasons=2021,2022,2023|--limit=100"
```

**Read This:**
- Before running any Cloud Run job with arguments
- When getting "unrecognized arguments" errors
- When passing comma-separated seasons/dates
- When debugging job execution failures

---

## 🔗 Related Documentation

### Prerequisites (Read First)
**Before running backfills, understand:**
- `../01-architecture/cross-date-dependencies.md` - Why backfill order matters
  - Cross-date dependencies
  - Game-based vs calendar-based lookback
  - Early season handling
  - Dependency check queries

- `../monitoring/05-data-completeness-validation.md` - How to validate completeness
  - Daily completeness queries
  - Backfill range validation
  - Row count reconciliation
  - Missing entity detection

### Operational Guides
**Phase-specific operations:**
- `../orchestration/01-how-it-works.md` - Phase 1 scheduler operations
- `../processors/01-phase2-operations-guide.md` - Phase 2 processor operations
- `../processors/02-phase3-operations-guide.md` - Phase 3 analytics operations
- `../processors/05-phase4-operations-guide.md` - Phase 4 precompute operations
- `../predictions/operations/01-deployment-guide.md` - Phase 5 prediction operations

### Monitoring & Validation
**Health checks and monitoring:**
- `../monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring
- `../monitoring/02-grafana-daily-health-check.md` - Quick daily health check
- `./bin/orchestration/quick_health_check.sh` - Command-line health check

---

## 🎯 Quick Reference: Common Operations

### Run a Backfill

**Step 1: Calculate ranges**
```bash
./bin/backfill/calculate_range.sh 2024-11-08 2024-11-14 30
```

**Step 2: Check existing data**
```bash
./bin/backfill/check_existing.sh 2024-10-09 2024-11-14
```

**Step 3: Run phases sequentially**
```bash
# Phase 1-3 for extended range (includes lookback)
./bin/backfill/run_phases_1_3.sh --start=2024-10-09 --end=2024-11-14

# Validate Phase 3 complete
./bin/backfill/validate_phase.sh 3 2024-10-09 2024-11-14

# Phase 4-5 for target range only
./bin/backfill/run_phases_4_5.sh --start=2024-11-08 --end=2024-11-14

# Final validation
./bin/backfill/check_existing.sh 2024-11-08 2024-11-14
```

**See full examples:** `01-backfill-operations-guide.md` (Examples section)

---

### Validate Completeness

**Daily check (single date):**
```bash
# Use Query 1 from monitoring/05-data-completeness-validation.md
bq query --use_legacy_sql=false < docs/monitoring/queries/daily_completeness.sql
```

**Backfill range check:**
```bash
# Use Query 2 from monitoring/05-data-completeness-validation.md
./bin/backfill/validate_phase.sh <phase> <start_date> <end_date>
```

**Monitor progress:**
```bash
./bin/backfill/monitor_progress.sh 2024-10-09 2024-11-14 30
```

---

### Recover from Partial Failure

**Find failed dates:**
```bash
./bin/backfill/check_existing.sh <start> <end> | grep "❌"
```

**Re-run only failed dates:**
```bash
# Example: Phase 3 failed for Nov 11-14
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-11-11,END_DATE=2024-11-14"
```

**Validate recovery:**
```bash
./bin/backfill/validate_phase.sh 3 <start> <end>
```

**See full recovery procedures:** `01-backfill-operations-guide.md` (Partial Backfill Recovery section)

---

## 🔍 Finding Information

**"How do I backfill Nov 8-14?"**
→ See `01-backfill-operations-guide.md` Example 1

**"Why do I need to backfill Oct 9-31 when I only want Nov 8-14?"**
→ See `../01-architecture/cross-date-dependencies.md` (Lookback Windows)

**"How do I validate backfill completion?"**
→ See `../monitoring/05-data-completeness-validation.md` (Validation Queries)

**"Phase 3 failed midway, how do I recover?"**
→ See `01-backfill-operations-guide.md` (Partial Backfill Recovery)

**"What's the correct backfill order?"**
→ Phase-by-phase (2→3→4→5), NOT date-by-date
→ See `../01-architecture/cross-date-dependencies.md` (Backfill Orchestration Order)

---

## 📋 Pre-Flight Checklist

Before running any backfill:
- [ ] Read `01-backfill-operations-guide.md` (at least the relevant scenario)
- [ ] Understand cross-date dependencies (`../01-architecture/cross-date-dependencies.md`)
- [ ] Calculate date ranges (including lookback window)
- [ ] Check what data already exists
- [ ] Verify Cloud Run jobs are deployed
- [ ] Test with 1-2 dates first
- [ ] Have validation queries ready
- [ ] Know how to monitor progress
- [ ] Have recovery plan ready

---

## 🚨 Common Mistakes

**❌ Running date-by-date instead of phase-by-phase**
→ Result: Phase 4 fails (needs historical Phase 3 data)
→ Fix: Run all Phase 3 dates first, then Phase 4

**❌ Forgetting lookback window**
→ Result: Phase 4 has insufficient historical context
→ Fix: Include 30-day lookback in Phase 2-3 range

**❌ Not validating between phases**
→ Result: Phase 4 runs before Phase 3 complete
→ Fix: Validate after each phase before proceeding

**❌ Expecting normal quality scores in early season**
→ Result: Confusion about degraded data
→ Fix: Enable early_season_mode, expect low quality scores

---

## 📊 Backfill Progress Tracking

**Real-time monitoring:**
```bash
./bin/backfill/monitor_progress.sh <start> <end> <interval_seconds>

# Example output:
# Phase 2: [===============================================---] 94%
# Phase 3: [==========================================--------] 81%
# Phase 4: [=============-------------------------------------] 27%
```

**BigQuery validation:**
```sql
-- Count complete dates
SELECT
  COUNT(DISTINCT game_date) as complete_dates
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2024-10-09' AND '2024-11-14';
```

---

## 🎯 Success Criteria

**Backfill is complete when:**
- [ ] All target dates have data in all phases (Phase 2-5)
- [ ] Row counts match expectations (use reconciliation queries)
- [ ] No missing dates in range
- [ ] processed_at timestamps are recent
- [ ] Sample quality checks pass (pick 3 random dates, verify data)
- [ ] Final validation queries return ✅ for all dates

---

## 📞 Questions?

**"Where do I start?"**
→ Read `01-backfill-operations-guide.md` (When to Backfill section)

**"What's the correct order?"**
→ Phase-by-phase: 1→2→3→4→5, validate between each

**"Why is my backfill failing?"**
→ Check: Cross-date dependencies, lookback windows, validation
→ See `01-backfill-operations-guide.md` (Troubleshooting section)

**"How do I know it's working?"**
→ Use progress monitoring and validation queries
→ See `../monitoring/05-data-completeness-validation.md`

---

## 🔄 Future Documents (Planned)

**Maintenance Procedures:**
- `maintenance-weekly-checklist.md` - Weekly maintenance tasks
- `maintenance-monthly-checklist.md` - Monthly data quality checks
- `data-quality-validation.md` - Data quality checks and thresholds

**Advanced Operations:**
- `historical-data-migration.md` - Migrating data between environments
- `schema-evolution-procedures.md` - Handling schema changes
- `disaster-recovery-runbook.md` - Complete disaster recovery

---

**Document Status:** Current and maintained
**Last Review:** 2025-11-18
**Next Review:** After first major backfill operation

---

*This directory focuses on HOW to run operations. For WHY things work the way they do, see `../01-architecture/`. For monitoring system health, see `../07-monitoring/`.*
