# NBA Data Pipeline Validation - Comprehensive Todo List
**Created**: 2026-01-16
**Status**: Living Document
**Priority**: HIGH - Critical for data quality and business operations

---

## Executive Summary

This document outlines a comprehensive validation strategy for the NBA data pipeline, based on:
- Existing MLB validation patterns (proven in production)
- NBA-specific requirements and data characteristics
- R-009 roster-only data bug learnings
- Agent research into validation best practices

**Key Principles:**
1. **Config-driven validation** - YAML configs define all validation rules
2. **Multi-layer approach** - GCS → BigQuery → Schedule → Cross-phase checks
3. **Automated alerting** - Slack/email/PagerDuty for failures
4. **Actionable remediation** - Every failure includes fix commands

---

## Phase 1: Immediate Validation Tasks (Week 1)

### 1.1 Daily Manual Validation Routine
**Priority**: CRITICAL
**Effort**: 15 minutes/day
**Owner**: On-call engineer

- [ ] **Yesterday's Game Completeness**
  ```sql
  -- Check analytics coverage for yesterday
  SELECT COUNT(*) as total_records, COUNT(DISTINCT game_id) as games
  FROM nba_analytics.player_game_summary
  WHERE game_date = CURRENT_DATE() - 1
  ```

- [ ] **Prediction Grading Status**
  ```sql
  -- Verify 100% grading for yesterday
  SELECT
    COUNT(*) as total,
    COUNTIF(grade IS NOT NULL) as graded,
    ROUND(COUNTIF(grade IS NOT NULL) * 100.0 / COUNT(*), 1) as pct
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE() - 1
  ```

- [ ] **R-009 Zero-Active Check**
  ```sql
  -- Alert if any games have 0 active players
  SELECT game_id, COUNT(*) as total, COUNTIF(is_active=TRUE) as active
  FROM nba_analytics.player_game_summary
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_id
  HAVING COUNTIF(is_active=TRUE) = 0
  ```

- [ ] **System Health Check**
  ```bash
  python scripts/system_health_check.py --date yesterday --output json
  ```

### 1.2 Validate Tonight's Predictions (Pre-Game)
**Priority**: HIGH
**Effort**: 10 minutes
**When**: 2-3 hours before first game

- [ ] **Predictions Generated**
  ```sql
  -- Should have ~1675 predictions (335 * 5 systems)
  SELECT COUNT(*) as total, COUNT(DISTINCT player_lookup) as players
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
  ```

- [ ] **All Systems Present**
  ```sql
  -- Should have 5 systems
  SELECT system_id, COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
  GROUP BY system_id
  ORDER BY system_id
  ```

- [ ] **Betting Lines Available**
  ```sql
  -- Should have 7000+ lines from 16 bookmakers
  SELECT COUNT(*) as lines, COUNT(DISTINCT bookmaker) as bookmakers
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = CURRENT_DATE()
  ```

### 1.3 Post-Game Validation (Next Morning)
**Priority**: HIGH
**Effort**: 15 minutes
**When**: 9 AM ET

- [ ] **All Games Processed**
  - Check scraper_execution_log for failures
  - Verify processor_run_history for successes
  - Compare against schedule (source of truth)

- [ ] **Analytics Data Quality**
  - Player counts per game (18-36 expected)
  - Points totals per team (70-180 expected)
  - Both teams present for each game

- [ ] **Check Morning Recovery Workflow**
  ```sql
  -- Did morning_recovery run? What did it decide?
  SELECT decision_time, decision, reason, games_targeted
  FROM nba_orchestration.master_controller_execution_log
  WHERE workflow_name = 'morning_recovery'
    AND DATE(decision_time) = CURRENT_DATE()
  ```

---

## Phase 2: Validation Infrastructure Setup (Week 1-2)

### 2.1 Implement Config-Driven Validators
**Priority**: HIGH
**Effort**: 2-3 days
**Dependencies**: Base validator framework already exists

- [ ] **Create validator classes for new configs**
  - [ ] `BettingPropsValidator` (validation/validators/raw/bettingpros_props_validator.py)
  - [ ] `PlayerGameSummaryValidator` (validation/validators/analytics/player_game_summary_validator.py)
  - [ ] `NbaPredictionCoverageValidator` (validation/validators/predictions/nba_prediction_coverage_validator.py)

- [ ] **Implement custom validation methods**
  - [ ] R-009 zero-active detection
  - [ ] Bookmaker diversity checks
  - [ ] System completeness validation
  - [ ] Cross-phase reconciliation

- [ ] **Test validators with historical data**
  ```bash
  python -m validation.validators.raw.bettingpros_props_validator \
    --config validation/configs/raw/bettingpros_props.yaml \
    --date 2026-01-15 \
    --dry-run
  ```

### 2.2 Set Up Monitoring Services
**Priority**: HIGH
**Effort**: 2-3 days

- [ ] **NBA Freshness Checker** (following MLB pattern)
  - [ ] Create `monitoring/nba/nba_freshness_checker.py`
  - [ ] Define freshness thresholds for each data source
  - [ ] Integrate with AlertManager
  - [ ] Test with recent dates

- [ ] **NBA Stall Detector**
  - [ ] Create `monitoring/nba/nba_stall_detector.py`
  - [ ] Define pipeline stages and expected lags
  - [ ] Implement upstream dependency diagnosis
  - [ ] Test with stalled scenarios

- [ ] **NBA Gap Detector**
  - [ ] Configure GCS → BigQuery gap detection
  - [ ] Set up per-processor gap monitoring
  - [ ] Generate remediation commands
  - [ ] Test with known gaps

### 2.3 Configure Alerting
**Priority**: HIGH
**Effort**: 1 day

- [ ] **Slack Integration**
  - [ ] Create dedicated channels (#nba-validation-alerts, #nba-critical-alerts)
  - [ ] Configure webhook URLs in services
  - [ ] Test alert formatting and routing
  - [ ] Document alert response procedures

- [ ] **Email Alerts** (optional)
  - [ ] Set up Brevo/SendGrid templates
  - [ ] Configure recipient lists by severity
  - [ ] Test email delivery

- [ ] **PagerDuty** (for critical issues)
  - [ ] Set up PagerDuty service
  - [ ] Define escalation policies
  - [ ] Configure critical alert conditions:
    - Pipeline stalled > 4 hours
    - 0-active games detected (R-009)
    - System-wide failure rate > 50%
  - [ ] Test on-call paging

---

## Phase 3: Automation & Scheduled Validation (Week 2-3)

### 3.1 Daily Automated Validation
**Priority**: MEDIUM
**Effort**: 2 days

- [ ] **Create daily validation runner**
  ```python
  # scripts/validation/run_daily_validation.py
  # Runs all validators for yesterday's date
  # Sends summary email/Slack message
  # Exits with error code if critical failures
  ```

- [ ] **Schedule via Cloud Scheduler**
  ```bash
  gcloud scheduler jobs create http nba-daily-validation \
    --schedule="0 9 * * *" \  # 9 AM ET daily
    --uri="https://validation-service.../run-daily" \
    --time-zone="America/New_York"
  ```

- [ ] **Configure summary report**
  - [ ] Email template with key metrics
  - [ ] Slack summary card
  - [ ] Link to detailed report in GCS/BigQuery

### 3.2 Real-Time Monitoring
**Priority**: MEDIUM
**Effort**: 3 days

- [ ] **Deploy monitoring services to Cloud Run**
  - [ ] Freshness checker (every 15 min)
  - [ ] Stall detector (every 30 min)
  - [ ] Gap detector (every 1 hour)

- [ ] **Set up Pub/Sub triggers**
  - [ ] Trigger validation on processor completion
  - [ ] Trigger reconciliation after phase completion
  - [ ] Trigger grading check after games finish

- [ ] **Create monitoring dashboard** (Cloud Monitoring/Grafana)
  - [ ] Data freshness by source
  - [ ] Pipeline flow metrics
  - [ ] Validation pass/fail rates
  - [ ] Alert history and response times

### 3.3 Automated Remediation (Where Safe)
**Priority**: LOW
**Effort**: 2 days

- [ ] **Identify safe auto-remediation scenarios**
  - Retry scrapers for transient failures (404, timeout)
  - Reprocess data when source GCS file exists
  - Trigger morning recovery for missing games

- [ ] **Implement auto-remediation with safeguards**
  - Max retry limits (3 attempts)
  - Rate limiting (1 backfill per minute)
  - Human approval for large-scale remediation
  - Dry-run mode for testing

- [ ] **Log all auto-remediation actions**
  - Track what was fixed and when
  - Measure effectiveness
  - Identify chronic issues requiring manual intervention

---

## Phase 4: Documentation & Runbooks (Week 3-4)

### 4.1 Validation Documentation
**Priority**: MEDIUM
**Effort**: 2 days

- [ ] **Create validation guide** (`docs/validation/NBA_VALIDATION_GUIDE.md`)
  - Overview of validation architecture
  - How to run validators manually
  - How to interpret results
  - Common failure modes and fixes

- [ ] **Document validation queries** (`docs/validation/VALIDATION_QUERIES.md`)
  - 7 standard queries per data source
  - Annotated with expected results
  - Include parameter substitution guide

- [ ] **Create alert response playbook** (`docs/runbooks/ALERT_RESPONSE.md`)
  - Alert types and severities
  - Investigation steps for each alert
  - Remediation commands
  - Escalation procedures

### 4.2 Operational Runbooks
**Priority**: HIGH
**Effort**: 2 days

- [ ] **Scraper Failure Runbook**
  - Diagnosis steps (check logs, GCS, API status)
  - Common fixes (re-run, update credentials, etc.)
  - When to escalate

- [ ] **Processor Failure Runbook**
  - Check dependencies (is source data available?)
  - Verify partition filters
  - Backfill commands
  - Data quality investigation

- [ ] **Analytics Gap Runbook**
  - How to identify root cause (scraper? processor? staleness?)
  - Backfill procedures
  - Data validation after backfill

- [ ] **Prediction Issues Runbook**
  - Missing predictions (check analytics dependency)
  - Incorrect predictions (model debugging)
  - Grading failures (check final scores available)

### 4.3 Training Materials
**Priority**: LOW
**Effort**: 1 day

- [ ] **Create validation training deck**
  - Why validation matters
  - Overview of validation layers
  - How to respond to alerts
  - Hands-on exercises

- [ ] **Record walkthrough video**
  - Running daily validation
  - Investigating a failure
  - Performing remediation
  - Escalation scenarios

---

## Phase 5: Advanced Validation (Week 4+)

### 5.1 Cross-Source Validation
**Priority**: MEDIUM
**Effort**: 3 days

- [ ] **BDL vs NBA.com Gamebook Comparison**
  - Compare points, assists, rebounds
  - Flag discrepancies > threshold
  - Investigate systematic differences
  - Document known discrepancies

- [ ] **Props Lines Market Comparison**
  - Compare consensus lines across bookmakers
  - Identify outlier bookmakers
  - Flag suspicious market movements
  - Track line movement over time

- [ ] **Prediction vs Actual Analysis**
  - Track prediction accuracy by system
  - Identify systematic biases
  - Flag degrading model performance
  - Trigger model retraining alerts

### 5.2 Historical Data Validation
**Priority**: LOW
**Effort**: 5 days

- [ ] **Run completeness checks for all seasons**
  ```bash
  for season in 2021-22 2022-23 2023-24 2024-25; do
    python scripts/validate_season.py --season $season
  done
  ```

- [ ] **Identify and document gaps**
  - Missing games
  - Missing players
  - Data quality issues
  - Known API outages

- [ ] **Backfill high-priority gaps**
  - Playoff games
  - High-profile games
  - Recent games (current season)

### 5.3 Validation Performance Tuning
**Priority**: LOW
**Effort**: 2 days

- [ ] **Optimize validator query performance**
  - Add appropriate indexes
  - Use partition filters effectively
  - Cache expensive queries
  - Batch validation checks

- [ ] **Reduce false positive alerts**
  - Tune thresholds based on historical data
  - Add context-aware logic (off-season, All-Star break)
  - Implement alert suppression rules

- [ ] **Improve remediation efficiency**
  - Batch similar remediations
  - Prioritize by business impact
  - Track remediation success rates

---

## Phase 6: Integration with MLB Patterns (Ongoing)

### 6.1 Unify Validation Framework
**Priority**: MEDIUM
**Effort**: 3 days

- [ ] **Extract common validation logic**
  - Schedule-aware validation base class
  - Standard query templates
  - Alert formatting utilities

- [ ] **Create sport-agnostic validators**
  - Generic completeness validator
  - Generic freshness checker
  - Generic gap detector

- [ ] **Refactor NBA and MLB to use common base**
  - Reduces code duplication
  - Easier to maintain
  - Faster to add new sports

### 6.2 Shared Monitoring Infrastructure
**Priority**: LOW
**Effort**: 2 days

- [ ] **Unified dashboard**
  - Show NBA + MLB metrics side-by-side
  - Cross-sport comparison
  - Shared alert history

- [ ] **Consolidated alerting**
  - Single Slack bot for all sports
  - Unified on-call rotation
  - Shared escalation policies

---

## Success Metrics

### Validation Coverage
- [ ] 100% of critical data sources have validation configs
- [ ] 95%+ of scheduled games validated within 12 hours
- [ ] All 7 standard queries implemented per data source

### Alert Quality
- [ ] < 5% false positive alert rate
- [ ] 100% of critical alerts have runbook
- [ ] < 15 min average alert response time

### Data Quality
- [ ] > 99% analytics completeness for finished games
- [ ] > 99.5% prediction grading completeness
- [ ] Zero R-009 incidents (0-active games)
- [ ] < 2 hours data staleness for post-game processing

### Operational Efficiency
- [ ] 80% of alerts auto-remediated (for safe scenarios)
- [ ] < 1 hour manual remediation time for remaining 20%
- [ ] < 1 data quality incident per week requiring escalation

---

## Risk Mitigation

### High-Risk Scenarios
1. **Validation service itself fails** → Monitor validator health, dual alerting paths
2. **Alert fatigue** → Tune thresholds, suppress known issues, focus on actionable
3. **Auto-remediation causes data corruption** → Dry-run mode, manual approval gates, audit logging
4. **BigQuery quota exhaustion** → Query optimization, caching, rate limiting

### Dependencies
- Base validator framework (DONE - already exists)
- Slack webhooks (DONE - already configured)
- BigQuery tables (DONE - already exist)
- Cloud Scheduler (DONE - already in use)

---

## Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 1: Immediate Tasks | Week 1 | Daily validation routine, manual checks |
| Phase 2: Infrastructure | Week 1-2 | Validator classes, monitoring services, alerting |
| Phase 3: Automation | Week 2-3 | Scheduled validation, real-time monitoring, auto-remediation |
| Phase 4: Documentation | Week 3-4 | Runbooks, training materials, query library |
| Phase 5: Advanced | Week 4+ | Cross-source validation, historical validation |
| Phase 6: Integration | Ongoing | Unified framework, shared infrastructure |

**Total Estimated Effort**: 30-40 person-days over 4-6 weeks

---

## Appendix: Quick Reference

### Common Validation Commands

```bash
# Run validator for specific date
python -m validation.validators.raw.bettingpros_props_validator \
  --config validation/configs/raw/bettingpros_props.yaml \
  --date 2026-01-16

# Run all validators for yesterday
python scripts/validation/run_daily_validation.py --date yesterday

# Check system health
python scripts/system_health_check.py --date yesterday --output json

# Manual backfill analytics
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-16", "end_date": "2026-01-16", "processors": ["PlayerGameSummaryProcessor"], "backfill_mode": true}'
```

### Validation Config Locations

```
validation/configs/
├── raw/
│   ├── bettingpros_props.yaml ✅ NEW
│   ├── nbac_schedule.yaml ✅ EXISTS
│   ├── bdl_boxscores.yaml ✅ EXISTS
│   └── odds_api_props.yaml ✅ EXISTS
├── analytics/
│   ├── player_game_summary.yaml ✅ NEW
│   └── (other analytics configs)
└── predictions/
    └── nba_prediction_coverage.yaml ✅ NEW
```

### Alert Severity Levels

| Severity | Response Time | Notification | Examples |
|----------|---------------|--------------|----------|
| CRITICAL | 5 min | PagerDuty + Slack | R-009 0-active, pipeline stalled, duplicates |
| ERROR | 1 hour | Slack | Missing games, field validation failures |
| WARNING | Next business day | Slack (low priority) | Low coverage, stale data (within threshold) |
| INFO | No action | Log only | Performance metrics, daily summaries |

---

**Document Version**: 1.0
**Last Updated**: 2026-01-16
**Next Review**: 2026-02-01
