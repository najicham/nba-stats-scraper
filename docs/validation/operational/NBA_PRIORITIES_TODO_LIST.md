# NBA System Priorities - Todo List
**Created**: 2026-01-16
**Status**: Active - NBA Season in Progress
**Last Updated**: 2026-01-16

---

## Executive Summary

This document outlines NBA-specific priorities separate from the comprehensive validation framework. Focus is on:
1. Monitoring R-009 fixes in production
2. Daily operational health checks
3. Incremental system improvements
4. Performance optimization

**Key Distinction**:
- **NBA Validation Todo List**: Long-term framework development (30-40 days)
- **This List**: Immediate operational priorities (daily/weekly tasks)

---

## Priority 1: R-009 Monitoring (CRITICAL)

### Today (Jan 16, 2026) - Post-Game Validation

**6 games scheduled tonight** - First real test of R-009 fixes in production

#### Tonight's Games to Monitor
- BKN vs CHI
- IND vs NOP
- PHI vs CLE
- TOR vs LAC
- HOU vs MIN
- SAC vs WAS

#### Post-Game Checks (Run Tomorrow Morning - Jan 17, 9 AM ET)

**Priority: CRITICAL - R-009 Detection**
```sql
-- CHECK #1: Zero Active Players (R-009 Issue)
SELECT
  game_id,
  COUNT(*) as total_players,
  COUNTIF(is_active = TRUE) as active_players,
  COUNTIF(is_active = FALSE) as inactive_players
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-16'
GROUP BY game_id
HAVING COUNTIF(is_active = TRUE) = 0;

-- Expected: 0 results (no 0-active games)
-- If any results: R-009 regression - CRITICAL ALERT
```

**Priority: HIGH - Data Completeness**
```sql
-- CHECK #2: All 6 Games Have Analytics
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_with_analytics,
  COUNT(*) as total_player_records
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-16'
GROUP BY game_date;

-- Expected: 6 games, 120-200 total player records
-- If < 6 games: Missing data - investigate scraper/processor logs
```

**Priority: HIGH - Player Counts Per Game**
```sql
-- CHECK #3: Reasonable Player Counts
SELECT
  game_id,
  COUNT(*) as total_players,
  COUNTIF(is_active = TRUE) as active_players,
  COUNTIF(minutes_played > 0) as players_with_minutes,
  COUNT(DISTINCT team_abbr) as teams_present
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-16'
GROUP BY game_id
ORDER BY game_id;

-- Expected per game:
-- - total_players: 19-34
-- - active_players: 19-34
-- - players_with_minutes: 18-30
-- - teams_present: 2
```

**Priority: MEDIUM - Prediction Grading**
```sql
-- CHECK #4: Prediction Grading Completeness
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(grade IS NOT NULL) as graded,
  COUNTIF(grade IS NULL) as ungraded,
  ROUND(COUNTIF(grade IS NOT NULL) * 100.0 / COUNT(*), 1) as graded_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-16'
GROUP BY game_date;

-- Expected: 100% graded (1675 predictions)
-- If < 100%: Grading service issue - check logs
```

**Priority: MEDIUM - Morning Recovery Workflow**
```sql
-- CHECK #5: Morning Recovery Decision
SELECT
  decision_time,
  workflow_name,
  decision,
  reason,
  games_targeted
FROM nba_orchestration.master_controller_execution_log
WHERE workflow_name = 'morning_recovery'
  AND DATE(decision_time) = '2026-01-17'
ORDER BY decision_time DESC
LIMIT 5;

-- Expected: SKIP (if all games processed successfully)
-- If RUN: Check which games needed recovery and why
```

#### Action Items
- [ ] **Tomorrow 9 AM ET**: Run all 5 post-game checks
- [ ] **Document results**: Create brief report of findings
- [ ] **If any R-009 issues**: IMMEDIATE escalation, Slack alert
- [ ] **If data gaps**: Review scraper logs, run manual backfill
- [ ] **Share results**: Brief team on R-009 fix effectiveness

---

## Priority 2: Daily Operations (ONGOING)

### Morning Health Check Routine (15 minutes daily)

**Run Every Morning at 9 AM ET** for yesterday's games:

#### Quick Validation Script
```bash
# Create daily health check script
cat > /home/naji/code/nba-stats-scraper/scripts/daily_health_check.sh << 'EOF'
#!/bin/bash
# NBA Daily Health Check
# Run at 9 AM ET to validate yesterday's games

YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

echo "=== NBA Daily Health Check: $YESTERDAY ==="
echo

echo "1. Analytics Coverage:"
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_id) as games, COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date = '$YESTERDAY'
"

echo "2. R-009 Check (should be 0):"
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as total, COUNTIF(is_active=TRUE) as active
FROM nba_analytics.player_game_summary
WHERE game_date = '$YESTERDAY'
GROUP BY game_id
HAVING COUNTIF(is_active=TRUE) = 0
"

echo "3. Prediction Grading:"
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(grade IS NOT NULL) as graded,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(grade IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = '$YESTERDAY'
"

echo "4. System Health:"
python scripts/system_health_check.py --date yesterday --output json

echo
echo "=== Health Check Complete ==="
EOF

chmod +x /home/naji/code/nba-stats-scraper/scripts/daily_health_check.sh
```

#### Daily Checklist
- [ ] **9:00 AM ET**: Run daily health check script
- [ ] **9:15 AM ET**: Review results, flag any issues
- [ ] **9:30 AM ET**: If issues found, investigate and remediate
- [ ] **9:45 AM ET**: Document any incidents in log
- [ ] **Track metrics**: Games processed, prediction accuracy, grading %

### Weekly Review (30 minutes every Monday)

**Review Last Week's Performance**:
```sql
-- Weekly Stats: Last 7 Days
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as player_records,
  ROUND(AVG(COUNTIF(is_active=TRUE)), 1) as avg_active_players
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

- [ ] **Check for patterns**: Any dates with low coverage?
- [ ] **Review scraper failures**: Any persistent issues?
- [ ] **Prediction accuracy trends**: Improving or degrading?
- [ ] **Alert volume**: Too many false positives?
- [ ] **Document learnings**: Update runbooks with new insights

---

## Priority 3: Validation Infrastructure (2-3 weeks)

### Phase 1: Immediate Validators (Week 1)

**Implement the 3 new configs created**:

#### 1.1 BettingPros Props Validator
- [ ] Create `validation/validators/raw/bettingpros_props_validator.py`
- [ ] Implement custom validations from config:
  - `bookmaker_diversity()` - 16 bookmakers check
  - `line_consistency()` - Cross-bookmaker validation
  - `coverage_vs_analytics()` - Props vs analytics overlap
- [ ] Test with historical data (Jan 15, Jan 16)
- [ ] Test with today's data
- [ ] Document usage in validator README

**Estimated effort**: 4 hours

#### 1.2 Player Game Summary Validator
- [ ] Create `validation/validators/analytics/player_game_summary_validator.py`
- [ ] Implement R-009 specific validations:
  - `zero_active_check()` - Critical R-009 detection
  - `both_teams_check()` - Team presence validation
  - `active_vs_roster()` - Active tracking verification
- [ ] Implement data quality checks:
  - `player_count_check()` - 18-36 players per game
  - `team_points_check()` - 70-180 points per team
- [ ] Test with Jan 15-16 data
- [ ] Integrate into daily health check

**Estimated effort**: 6 hours

#### 1.3 NBA Prediction Coverage Validator
- [ ] Create `validation/validators/predictions/nba_prediction_coverage_validator.py`
- [ ] Implement validations:
  - `system_completeness()` - All 5 systems present
  - `coverage_vs_analytics()` - 50%+ coverage
  - `system_consistency()` - Predictions not too divergent
- [ ] Test with current predictions
- [ ] Set up pre-game validation (verify predictions exist)

**Estimated effort**: 4 hours

### Phase 2: Monitoring Services (Week 2)

Following MLB pattern, create:

#### 2.1 NBA Freshness Checker
- [ ] Create `monitoring/nba/nba_freshness_checker.py`
- [ ] Define freshness thresholds per data source:
  - Schedule: 24h warning, 48h critical
  - BettingPros props: 4h warning, 8h critical
  - BDL boxscores: 6h warning, 12h critical
  - Analytics: 2h warning, 6h critical
  - Predictions: 4h warning, 8h critical
- [ ] Test with current data
- [ ] Deploy to Cloud Run (optional for now)

**Estimated effort**: 3 hours

#### 2.2 NBA Stall Detector
- [ ] Create `monitoring/nba/nba_stall_detector.py`
- [ ] Define pipeline stages:
  - Raw data (scrapers)
  - Phase 2 processors
  - Phase 3 analytics
  - Phase 4 ML features
  - Phase 5 predictions
- [ ] Set expected lags and stall thresholds
- [ ] Test with historical data
- [ ] Deploy to Cloud Run (optional)

**Estimated effort**: 3 hours

#### 2.3 NBA Gap Detector
- [ ] Create `monitoring/nba/nba_gap_detector.py`
- [ ] Configure data sources to monitor:
  - Schedule → nba_raw.nbac_schedule
  - BettingPros props → nba_raw.bettingpros_player_points_props
  - BDL boxscores → nba_raw.bdl_player_boxscores
  - Analytics → nba_analytics.player_game_summary
- [ ] Test gap detection
- [ ] Generate remediation commands

**Estimated effort**: 3 hours

---

## Priority 4: System Improvements (Ongoing)

### Performance Optimization

#### 4.1 Reduce BigQuery Costs
- [ ] **Audit expensive queries**: Identify top cost queries
- [ ] **Add partition filters**: Ensure all queries use partition filters
- [ ] **Implement query caching**: Cache frequently run queries
- [ ] **Optimize table schemas**: Review clustering and partitioning
- [ ] **Set up budget alerts**: Get warned before overspending

**Target**: Reduce BigQuery costs by 20-30%

#### 4.2 Improve Scraper Reliability
Current failures on Jan 16:
- `nbac_team_boxscore`: 93 failures (0% success)
- `bdb_pbp_scraper`: 54 failures (0% success)
- `nbac_play_by_play`: 9 failures

**Note**: Most failures are expected (pre-game), but investigate chronic issues

- [ ] **Review failure patterns**: Are some always failing?
- [ ] **Improve retry logic**: Better backoff strategies
- [ ] **Add circuit breakers**: Prevent retry storms
- [ ] **Document expected failures**: Reduce alert noise

#### 4.3 Optimize Processor Performance
- [ ] **Profile slow processors**: Identify bottlenecks
- [ ] **Parallelize where possible**: Reduce processing time
- [ ] **Optimize BigQuery writes**: Batch operations
- [ ] **Reduce memory usage**: Handle large datasets efficiently
- [ ] **Monitor cold starts**: Optimize Cloud Run configs

### Data Quality Improvements

#### 4.4 Enhanced Reconciliation
Current R-007 has 7 checks. Consider adding:
- [ ] **Check #8**: Prediction vs props coverage overlap
- [ ] **Check #9**: Grading completeness within 12 hours
- [ ] **Check #10**: Team points totals reasonable (70-180)
- [ ] **Check #11**: No duplicate player-game records

#### 4.5 Data Lineage Tracking
- [ ] **Track data provenance**: Where did each record come from?
- [ ] **Version tracking**: Which scraper/processor version?
- [ ] **Quality scores**: Confidence in data accuracy
- [ ] **Audit trail**: Full history of data transformations

---

## Priority 5: Documentation & Knowledge Sharing

### Internal Documentation

#### 5.1 Architecture Documentation
- [ ] Create NBA pipeline architecture diagram
- [ ] Document data flow: Scrapers → Processors → Analytics → Predictions
- [ ] Explain R-009 fixes and detection mechanisms
- [ ] Document all config files and their purposes

#### 5.2 Operational Playbooks
- [ ] **Scraper Failure Playbook**: How to diagnose and fix
- [ ] **Processor Failure Playbook**: Dependencies and remediation
- [ ] **R-009 Incident Response**: What to do if detected
- [ ] **Missing Data Recovery**: Backfill procedures
- [ ] **Alert Fatigue Management**: Tuning thresholds

#### 5.3 Onboarding Materials
- [ ] **System Overview**: 30-minute intro presentation
- [ ] **Hands-on Tutorial**: Run validation, interpret results
- [ ] **Common Tasks**: Daily checks, weekly reviews, incident response
- [ ] **Tools Reference**: BigQuery queries, gcloud commands, scripts

### External Documentation

#### 5.4 API Documentation
- [ ] Document prediction API endpoints
- [ ] Explain data freshness guarantees
- [ ] Coverage expectations (% of players with predictions)
- [ ] Known limitations and edge cases

---

## Priority 6: Team & Process

### Team Readiness

#### 6.1 On-Call Rotation
- [ ] Define on-call schedule (24/7? Business hours only?)
- [ ] Set up PagerDuty or equivalent
- [ ] Create escalation policies
- [ ] Train team on alert response
- [ ] Test paging during off-hours

#### 6.2 Incident Management
- [ ] Define incident severity levels
- [ ] Create incident response templates
- [ ] Set up post-mortem process
- [ ] Document escalation paths
- [ ] Track MTTR (Mean Time To Resolution)

### Process Improvements

#### 6.3 Automated Workflows
- [ ] **Auto-remediation**: Safe retries for transient failures
- [ ] **Auto-scaling**: Handle game day load spikes
- [ ] **Auto-alerting**: Context-aware smart alerts
- [ ] **Auto-reporting**: Daily/weekly summary emails

#### 6.4 Metrics & KPIs
Track these metrics weekly:
- **Availability**: % of games with analytics data
- **Latency**: Time from game end to analytics available
- **Accuracy**: Prediction accuracy by system
- **Coverage**: % of players with predictions
- **Reliability**: % of scheduled jobs succeeding
- **Cost**: BigQuery and Cloud Run costs

---

## Weekly Sprints

### Week 1 (Jan 16-22)
**Focus**: R-009 monitoring and immediate validators

- [ ] Monitor Jan 16 games (R-009 validation)
- [ ] Implement BettingPros props validator
- [ ] Implement player_game_summary validator
- [ ] Implement prediction coverage validator
- [ ] Set up daily health check script
- [ ] Run daily checks all week, document learnings

**Success Criteria**: All 3 validators working, R-009 detection confirmed

### Week 2 (Jan 23-29)
**Focus**: Monitoring services and automation

- [ ] Create NBA freshness checker
- [ ] Create NBA stall detector
- [ ] Create NBA gap detector
- [ ] Automate daily health check (Cloud Scheduler)
- [ ] Test validators on full week of data
- [ ] Tune alert thresholds based on data

**Success Criteria**: All monitoring services working, daily automation live

### Week 3 (Jan 30 - Feb 5)
**Focus**: Documentation and optimization

- [ ] Write architecture documentation
- [ ] Create operational playbooks
- [ ] Optimize expensive BigQuery queries
- [ ] Improve scraper retry logic
- [ ] Create metrics dashboard (Grafana/Looker)
- [ ] Conduct team training session

**Success Criteria**: Team trained, costs reduced, documentation complete

### Week 4 (Feb 6-12)
**Focus**: Advanced features and polish

- [ ] Enhanced reconciliation checks
- [ ] Data lineage tracking
- [ ] Auto-remediation for safe scenarios
- [ ] Performance profiling and optimization
- [ ] Create onboarding materials
- [ ] Polish and refine based on 4 weeks of learnings

**Success Criteria**: Production-hardened system, new team members can onboard easily

---

## Success Metrics (30 Days)

By end of Week 4, measure success:

### Data Quality
- ✅ Zero R-009 incidents (0-active games)
- ✅ >99% analytics completeness for finished games
- ✅ >99.5% prediction grading completeness
- ✅ <2 hours data staleness post-game

### Operational Excellence
- ✅ All validators running daily
- ✅ <5% false positive alert rate
- ✅ <15 min average alert response time
- ✅ All critical alerts have runbook

### Team Readiness
- ✅ On-call rotation established
- ✅ All team members trained
- ✅ Documentation complete and accessible
- ✅ Incident response tested

### Cost & Performance
- ✅ BigQuery costs reduced by 20%
- ✅ Pipeline latency <2 hours post-game
- ✅ 99.9% uptime for critical services

---

## Risk Management

### High-Risk Scenarios

**1. R-009 Regression**
- **Risk**: R-009 bug returns despite fixes
- **Detection**: Daily zero-active checks
- **Mitigation**: Morning recovery workflow, manual backfill
- **Escalation**: CRITICAL alert, immediate investigation

**2. Data Pipeline Stall**
- **Risk**: Orchestration failure blocks predictions
- **Detection**: Stall detector, freshness checker
- **Mitigation**: Manual trigger endpoints, documented procedures
- **Escalation**: ERROR alert within 1 hour

**3. BigQuery Quota Exhaustion**
- **Risk**: Retry storm exhausts quotas (happened Jan 16)
- **Detection**: Circuit breaker timeouts, quota monitoring
- **Mitigation**: Rate limiting, backfill mode alert suppression
- **Prevention**: Circuit breaker 30m → 4h (already fixed)

**4. Alert Fatigue**
- **Risk**: Too many false positives, miss critical alerts
- **Detection**: Alert volume tracking
- **Mitigation**: Threshold tuning, alert suppression rules
- **Prevention**: Focus on actionable alerts only

---

## Questions & Unknowns

### Technical Questions
1. What's the actual impact of staleness threshold change (12h → 36h)?
2. Should we create separate dev/staging/prod environments?
3. Is circuit breaker timeout (4h) optimal or should we tune further?
4. Should reconciliation run more frequently than daily?

### Process Questions
1. Who owns NBA system health long-term?
2. What's the SLA for data availability?
3. How do we handle planned maintenance?
4. What's the budget for BigQuery/Cloud Run costs?

### Feature Questions
1. Should we build a public status page?
2. Do we need real-time prediction updates?
3. Should we expose data quality metrics via API?
4. Is there demand for more prediction systems beyond the 5 current?

---

## Appendix: Quick Reference Commands

### Daily Health Check
```bash
./scripts/daily_health_check.sh
```

### Manual R-009 Check
```bash
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as total, COUNTIF(is_active=TRUE) as active
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-16'
GROUP BY game_id
HAVING active = 0
"
```

### Manual Backfill Analytics
```bash
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-16", "end_date": "2026-01-16", "processors": ["PlayerGameSummaryProcessor"], "backfill_mode": true}'
```

### Run Validator Manually
```bash
PYTHONPATH=. python validation/validators/analytics/player_game_summary_validator.py \
  --config validation/configs/analytics/player_game_summary.yaml \
  --date 2026-01-16
```

### Check System Health
```bash
python scripts/system_health_check.py --date yesterday --output json
```

---

**Document Version**: 1.0
**Created**: 2026-01-16
**Next Review**: 2026-01-23 (weekly)
**Owner**: NBA Infrastructure Team
