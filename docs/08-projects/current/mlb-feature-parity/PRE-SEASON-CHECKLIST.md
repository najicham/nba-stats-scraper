# MLB Pre-Season Checklist

**Purpose**: Ensure all systems are ready before Opening Day (Late March 2026)
**Owner**: MLB Infrastructure Team
**Created**: 2026-01-16

---

## Timeline

- **4 weeks before Opening Day**: Complete infrastructure deployment
- **2 weeks before**: Run end-to-end tests with Spring Training data
- **1 week before**: Final validation and monitoring checks
- **Opening Day**: Monitor closely, be on-call

---

## Infrastructure Deployment

### Service Accounts & Permissions
- [ ] MLB monitoring service account created
- [ ] BigQuery permissions granted (dataViewer, jobUser)
- [ ] GCS permissions granted (objectViewer, objectCreator)
- [ ] Secret Manager access configured
- [ ] Service account tested with manual job execution

### Cloud Run Jobs Deployed
- [ ] mlb-gap-detection deployed and tested
- [ ] mlb-freshness-checker deployed and tested
- [ ] mlb-prediction-coverage deployed and tested
- [ ] mlb-stall-detector deployed and tested
- [ ] mlb-schedule-validator deployed and tested
- [ ] mlb-pitcher-props-validator deployed and tested
- [ ] mlb-prediction-coverage-validator deployed and tested

### Cloud Scheduler Configured
- [ ] Gap detection schedule (daily 8 AM ET)
- [ ] Freshness checker schedule (every 2 hours, season only)
- [ ] Prediction coverage schedule (pre/post games)
- [ ] Stall detector schedule (hourly, season only)
- [ ] Schedule validator schedule (daily 6 AM ET)
- [ ] Props validator schedule (every 4 hours, game days)
- [ ] Prediction coverage validator schedule (pre/post games)
- [ ] All schedulers tested with manual triggers

---

## Data Pipeline Verification

### BigQuery Tables
- [ ] mlb_raw.mlb_schedule has current season data
- [ ] mlb_raw.bp_pitcher_props has recent props data
- [ ] mlb_raw.oddsa_pitcher_props has recent props data
- [ ] mlb_analytics.pitcher_game_summary exists and has schema
- [ ] mlb_precompute.pitcher_ml_features exists and has schema
- [ ] mlb_predictions.pitcher_strikeouts exists and has schema
- [ ] mlb_predictions.pitcher_strikeout_grading exists and has schema
- [ ] All tables have correct partitioning (by game_date)

### Data Quality
- [ ] Run schedule validator on recent Spring Training data
- [ ] Run props validator on recent Spring Training data
- [ ] Verify probable pitchers populated for upcoming games
- [ ] Check props coverage (> 80% of scheduled pitchers)
- [ ] Verify predictions generated for recent games
- [ ] Check prediction accuracy on graded Spring Training games

---

## Monitoring & Alerting

### AlertManager Integration
- [ ] mlb_analytics_service sends alerts on failures
- [ ] mlb_precompute_service sends alerts on failures
- [ ] mlb_grading_service sends alerts on failures
- [ ] mlb_prediction_worker sends alerts on failures
- [ ] Test alerts arrive in #mlb-alerts Slack channel
- [ ] Verify alert rate limiting works (no spam during backfill)
- [ ] Confirm backfill mode suppresses non-critical alerts

### Monitoring Jobs
- [ ] Gap detection runs successfully and reports correctly
- [ ] Freshness checker identifies stale data accurately
- [ ] Prediction coverage calculates percentages correctly
- [ ] Stall detector identifies pipeline issues
- [ ] All monitors send alerts when thresholds exceeded
- [ ] Alert messages include actionable remediation commands

### Validation Jobs
- [ ] Schedule validator catches data quality issues
- [ ] Props validator detects unusual lines
- [ ] Prediction coverage validator identifies gaps
- [ ] Validation reports sent to appropriate channels
- [ ] Failed validations trigger alerts

---

## Prediction System

### Models
- [ ] V1.6 model deployed and accessible
- [ ] V1.4 shadow model available for comparison
- [ ] Model inference tested with sample pitchers
- [ ] Confidence scores calibrated (70%+ is "high confidence")
- [ ] Edge calculations verified against historical accuracy

### Prediction Worker
- [ ] Batch prediction endpoint tested
- [ ] Individual prediction endpoint tested
- [ ] Shadow mode execution working
- [ ] Predictions writing to BigQuery correctly
- [ ] Prediction format matches API requirements

### Grading System
- [ ] Grading service processes completed games
- [ ] Accuracy calculations correct
- [ ] V1.4 vs V1.6 comparison working
- [ ] Grading results available for reporting

---

## Publishing & Export

### Exporters
- [ ] Predictions exporter generates valid JSON
- [ ] Best bets exporter filters high-confidence picks correctly
- [ ] System performance exporter calculates accuracy metrics
- [ ] Results exporter includes grading data
- [ ] All exporters write to correct GCS paths
- [ ] Exported JSON matches API schema expectations

### GCS Buckets
- [ ] MLB predictions bucket exists (gs://mlb-props-platform-api/)
- [ ] Correct permissions set (public read for API)
- [ ] Lifecycle policies configured (retain 90 days)
- [ ] Test file upload/download
- [ ] Verify CDN caching if applicable

### API Integration
- [ ] API can read exported prediction files
- [ ] Predictions endpoint returns MLB data correctly
- [ ] Best bets endpoint working
- [ ] System performance endpoint functional
- [ ] Results endpoint shows graded predictions

---

## Documentation

### Runbooks
- [ ] Deployment runbook complete and tested
- [ ] Alerting runbook covers all alert types
- [ ] Response procedures clearly documented
- [ ] Escalation contacts up to date
- [ ] Common troubleshooting scenarios included

### Architecture Docs
- [ ] MLB pipeline diagram created
- [ ] Data flow documented
- [ ] Schema documentation updated
- [ ] API integration guide written
- [ ] Monitoring strategy documented

### Handoff Materials
- [ ] Session handoffs organized and accessible
- [ ] Feature parity analysis documented
- [ ] Known issues documented with workarounds
- [ ] Pre-season checklist (this document) completed

---

## Testing & Validation

### End-to-End Test (Spring Training Data)
- [ ] **Day 1**: Scrape schedule for upcoming games
- [ ] **Day 1**: Scrape pitcher props for scheduled pitchers
- [ ] **Day 1**: Run analytics processors
- [ ] **Day 1**: Run precompute (generate features)
- [ ] **Day 1**: Generate predictions (batch mode)
- [ ] **Day 1**: Verify 90%+ prediction coverage
- [ ] **Day 1**: Export predictions to GCS
- [ ] **Day 1**: Verify API can serve predictions
- [ ] **Day 2**: Scrape game results
- [ ] **Day 2**: Run grading service
- [ ] **Day 2**: Verify accuracy calculations
- [ ] **Day 2**: Export results to GCS
- [ ] **Validation**: Run all monitors and validators, verify no critical alerts

### Load Testing
- [ ] Test with typical game day load (15 games, 30 pitchers)
- [ ] Test with heavy game day load (15 games, all scraped concurrently)
- [ ] Verify BigQuery quotas sufficient
- [ ] Check Cloud Run scaling under load
- [ ] Monitor costs during load test

### Failure Scenarios
- [ ] Test recovery from scraper failure
- [ ] Test recovery from processor failure
- [ ] Test recovery from prediction worker failure
- [ ] Verify monitoring detects failures within 15 minutes
- [ ] Verify alerts sent for all critical failures
- [ ] Test manual remediation procedures

---

## Operational Readiness

### Team Preparedness
- [ ] On-call schedule established for Opening Day
- [ ] Team trained on runbooks
- [ ] Alert escalation procedures understood
- [ ] Access verified (GCP console, Slack, PagerDuty)
- [ ] Backup contacts identified

### Communication
- [ ] Stakeholders notified of system readiness
- [ ] Product team briefed on capabilities
- [ ] Known limitations communicated
- [ ] Support process established for user issues

### Monitoring Dashboards
- [ ] Create Grafana/Looker dashboard for MLB metrics
- [ ] Add prediction coverage tracking
- [ ] Add prediction accuracy trends
- [ ] Add pipeline health indicators
- [ ] Share dashboard with team

---

## Opening Day Preparation

### Week Before
- [ ] Run final end-to-end test
- [ ] Review and acknowledge any known issues
- [ ] Confirm all monitors running on schedule
- [ ] Test alert delivery one more time
- [ ] Backup all configurations

### Day Before
- [ ] Verify season schedules loaded
- [ ] Check first week's games have probable pitchers
- [ ] Run validators on Opening Day data
- [ ] Brief on-call team
- [ ] Set up war room / monitoring station

### Opening Day
- [ ] Monitor pipeline continuously (first 6 hours)
- [ ] Watch for alerts in real-time
- [ ] Track prediction coverage throughout day
- [ ] Verify predictions exported before game times
- [ ] Check API serving predictions correctly
- [ ] Document any issues for post-game review

### Day After
- [ ] Verify game results scraped
- [ ] Check grading completed
- [ ] Review prediction accuracy for Opening Day
- [ ] Identify any systematic issues
- [ ] Update runbooks with lessons learned

---

## Post-Opening Day Review

Within 3 days of Opening Day:
- [ ] Review all alerts and incidents
- [ ] Calculate Opening Day prediction accuracy
- [ ] Identify improvement opportunities
- [ ] Update documentation with findings
- [ ] Plan follow-up work for regular season

---

## Success Criteria

System is ready for Opening Day when:

✅ All infrastructure deployed and tested
✅ End-to-end test completed successfully
✅ Monitoring and alerts working
✅ Prediction accuracy validated on Spring Training data
✅ Team trained and on-call schedule confirmed
✅ Documentation complete and accessible
✅ No critical known issues

---

## Risk Mitigation

### High-Risk Areas
1. **Props Coverage**: BettingPros may not have all pitchers
   - **Mitigation**: Odds API as backup source, manual overrides if needed

2. **Model Performance**: V1.6 untested in regular season
   - **Mitigation**: V1.4 shadow mode running, can revert if issues

3. **Pipeline Stalls**: Orchestration failures could block predictions
   - **Mitigation**: Manual trigger endpoints available, runbooks documented

4. **Alert Fatigue**: Too many false positives could cause missed critical alerts
   - **Mitigation**: Tune thresholds based on Spring Training data

---

## Sign-off

Before Opening Day, obtain sign-off from:

- [ ] Engineering Lead: Infrastructure ready
- [ ] Data Science Lead: Models validated
- [ ] Product Lead: API integration verified
- [ ] Operations Lead: On-call team prepared

---

**Checklist Owner**: @engineering-lead
**Target Completion**: 1 week before Opening Day
**Last Updated**: 2026-01-16
