# Future Plan: NBA Stats Pipeline Strategic Roadmap

**Last Updated**: January 2, 2026 4:16 PM ET
**Status**: Active monitoring + strategic planning phase
**Priority**: Mix of immediate validation + medium-term improvements

---

## 🎯 EXECUTIVE SUMMARY

**Current State**: Pipeline is **HEALTHY** with all critical fixes deployed
- ✅ 7 major bugs fixed in past 4 days
- ✅ 4 monitoring layers active
- ✅ Data completeness: 57% → 100%
- ✅ Detection speed: 10 hours → <1 second

**Next Phase Focus**:
1. **Immediate** (Next 48h): Validate recent fixes (injury/referee discovery)
2. **Short-term** (Next 2 weeks): Address pre-existing scraper failures
3. **Medium-term** (Next 1-2 months): ML model development readiness
4. **Long-term** (Next 3-6 months): Platform maturity & automation

---

## 📅 IMMEDIATE PRIORITIES (Next 48 Hours)

### ⏰ Jan 3, 2026 - Critical Validation Day

**TONIGHT (7 PM-12 AM ET) - Game Collection Monitoring**

**What**: Verify boxscore collection works after games finish
- 10 games tonight (Jan 2) starting ~7 PM ET
- Expected: Scraper success rates improve post-game

**Monitoring**:
```sql
-- Tonight's game collection success (run at 11 PM ET)
SELECT
  scraper_name,
  COUNT(*) as runs,
  COUNTIF(status = 'success') as successes,
  ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 1) as success_rate
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) = '2026-01-02'
  AND EXTRACT(HOUR FROM triggered_at AT TIME ZONE 'America/New_York') >= 19
  AND scraper_name IN ('nbac_team_boxscore', 'bdl_live_box_scores_scraper', 'nbac_play_by_play')
GROUP BY scraper_name;
```

**Success Criteria**:
- ✅ nbac_team_boxscore: >80% success rate (post-game)
- ✅ bdl_live_box_scores: >70% success rate (during games)
- ✅ All 10 games collected by 4 AM ET (post_game_window_3)

---

**TOMORROW MORNING (6-10 AM ET) - Overnight Verification**

**What**: Verify overnight collection completed successfully
- All 10 games from Jan 2 should be in BigQuery
- Morning operations workflow should run

**Monitoring**:
```sql
-- Verify overnight game collection
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_collected
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date = '2026-01-02'
GROUP BY game_date;

-- Morning operations status
SELECT
  workflow_name,
  action,
  reason,
  decision_time
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE workflow_name = 'morning_operations'
  AND DATE(decision_time) = '2026-01-03'
ORDER BY decision_time DESC;
```

**Success Criteria**:
- ✅ games_collected = 10 (all tonight's games)
- ✅ morning_operations action = 'RUN' (not SKIP)

---

**TOMORROW MIDDAY (10 AM-2 PM ET) - 🚨 CRITICAL VALIDATION WINDOW 🚨**

**What**: FIRST FULL VALIDATION of both discovery workflow fixes

**1. Referee Discovery Validation** (12-attempt config):
```sql
-- Referee discovery timeline (should see up to 12 attempts)
SELECT
  game_date,
  status,
  FORMAT_TIMESTAMP('%H:%M ET', triggered_at, 'America/New_York') as time_et,
  error_message
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'nbac_referee_assignments'
  AND DATE(triggered_at) = '2026-01-03'
ORDER BY triggered_at;

-- Workflow decisions (check max_attempts)
SELECT
  FORMAT_TIMESTAMP('%H:%M ET', decision_time, 'America/New_York') as time_et,
  action,
  reason,
  context  -- Look for "max_attempts": 12
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE workflow_name = 'referee_discovery'
  AND DATE(decision_time) = '2026-01-03'
ORDER BY decision_time DESC;
```

**Success Criteria**:
- ✅ Attempts show "1/12", "2/12", ..., up to "12/12" (not stopping at 6)
- ✅ At least 1 success between 10 AM-2 PM ET
- ✅ context shows `"max_attempts": 12` (not 6)

---

**2. Injury Discovery Validation** (game_date tracking):
```sql
-- Injury discovery timeline (check game_date field)
SELECT
  game_date,  -- Should be '2026-01-03' when data found
  status,
  FORMAT_TIMESTAMP('%H:%M ET', triggered_at, 'America/New_York') as time_et,
  JSON_VALUE(data_summary, '$.record_count') as records
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'nbac_injury_report'
  AND DATE(triggered_at) = '2026-01-03'
ORDER BY triggered_at DESC;

-- Injury data completeness
SELECT
  report_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT player_full_name) as unique_players
FROM `nba-props-platform.nba_raw.nbac_injury_report`
WHERE report_date = '2026-01-03'
GROUP BY report_date;
```

**Success Criteria**:
- ✅ game_date = '2026-01-03' (matches DATA date, not execution date)
- ✅ unique_players ~110 (typical injury report size)
- ✅ Workflow shows "Already found data today" ONLY after game_date = '2026-01-03'
- ✅ No false positives (no premature "already found" messages)

---

**TOMORROW EVENING (6 PM-12 AM ET) - Tomorrow's Game Day**

**What**: Monitor Jan 3 games (8 games scheduled)
- Betting lines collection (6 PM ET)
- Live tracking during games (7 PM+ ET)
- Post-game collection (10 PM, 1 AM, 4 AM ET)

**Success Criteria**:
- ✅ Betting lines collected for 8 games
- ✅ Live boxscore tracking active (70%+ success rate)
- ✅ All 8 games collected by 4 AM ET (Jan 4)

---

## 🚨 SHORT-TERM PRIORITIES (Next 2 Weeks)

### 1. Investigate Pre-Existing Scraper Failures

**Priority**: HIGH (data completeness impact)

**Issues Identified** (from Jan 2 monitoring):
```
- nbac_schedule_api: 4.1% success rate (2/49) ← 🚨 URGENT
- betting_pros_events: 0% (0/18)
- betting_pros_player_props: 0% (0/9)
- oddsa_events: 14.3% (1/7)
```

**Investigation Plan**:

**A. nbac_schedule_api (URGENT - Critical Dependency)**
```sql
-- Get recent error messages
SELECT
  error_message,
  COUNT(*) as count,
  MAX(triggered_at) as latest_occurrence
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'nbac_schedule_api'
  AND DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND status = 'failed'
GROUP BY error_message
ORDER BY count DESC;
```

**Potential Causes**:
- API endpoint change
- Rate limiting
- Authentication issues
- Response format change

**Action**: Investigate within 2-3 days (critical for downstream workflows)

---

**B. Betting Site Scrapers (MEDIUM - Nice to Have)**
```sql
-- Error pattern analysis
SELECT
  scraper_name,
  error_message,
  COUNT(*) as count,
  MAX(triggered_at) as latest_occurrence
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name IN ('betting_pros_events', 'betting_pros_player_props', 'oddsa_events')
  AND DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND status = 'failed'
GROUP BY scraper_name, error_message
ORDER BY scraper_name, count DESC;
```

**Potential Causes**:
- API rate limiting (common with betting sites)
- Site redesign / scraper out of date
- Authentication token expiry
- IP blocking

**Action**: Investigate within 1-2 weeks (not critical for core pipeline)

---

### 2. Historical game_date Backfill (Optional)

**Priority**: LOW (not required - fallback logic handles NULL)

**What**: Backfill game_date for historical scraper runs

**Query**:
```sql
-- Preview how many rows would be updated
SELECT
  COUNT(*) as total_rows,
  COUNTIF(game_date IS NULL) as null_rows,
  COUNTIF(JSON_VALUE(opts, '$.gamedate') IS NOT NULL) as backfillable_rows
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`;

-- Backfill query (run after preview)
UPDATE `nba-props-platform.nba_orchestration.scraper_execution_log`
SET game_date = DATE(PARSE_TIMESTAMP('%Y%m%d', JSON_VALUE(opts, '$.gamedate')))
WHERE game_date IS NULL
  AND JSON_VALUE(opts, '$.gamedate') IS NOT NULL;
```

**Benefit**: Historical analytics, cleaner data
**Effort**: 30 minutes
**Risk**: Low (read-only for current system)

---

### 3. Add Phase 1 Integration Tests

**Priority**: MEDIUM (prevents future regressions)

**Issue**: Replay test doesn't cover Phase 1 scrapers
- Current: Only tests Phases 2-6
- Gap: Phase 1 scraper code never executed in tests
- Impact: AttributeError bug (Jan 3) went undetected

**Implementation Plan**:

**A. Simple Approach** (2-3 hours):
```python
# bin/testing/test_phase1_scrapers.py
def test_scraper_methods_exist():
    """Verify all scrapers have required methods."""
    from scrapers.scraper_base import ScraperBase

    required_methods = [
        '_validate_scraper_output',
        '_count_scraper_rows',
        '_diagnose_zero_scraper_rows',
        '_is_acceptable_zero_scraper_rows',
        '_log_scraper_validation',
        '_send_scraper_alert'
    ]

    # Import all scrapers
    scrapers = discover_all_scrapers()

    for scraper_class in scrapers:
        for method in required_methods:
            assert hasattr(scraper_class, method), \
                f"{scraper_class.__name__} missing {method}"
```

**B. Comprehensive Approach** (6-8 hours):
- Mock scraper HTTP endpoints
- Run scrapers with test data
- Verify outputs match expected format
- Check validation methods called
- Verify BigQuery logging

**Recommendation**: Start with Simple, add Comprehensive later

---

## 📊 MEDIUM-TERM PRIORITIES (Next 1-2 Months)

### 1. ML Model Development Readiness

**Priority**: HIGH (core business value)

**Current State**: Data foundation is ready
- ✅ Historical data: 4 seasons (2021-2025) complete
- ✅ Player stats: Complete through Jan 2, 2026
- ✅ Injury data: Complete and accurate
- ✅ Boxscore data: 100% recent completeness
- ✅ Advanced stats: Available in Phase 3-4

**See**: `docs/08-projects/current/ml-model-development/` for detailed plan

**Next Steps**:
1. **Feature Engineering** (2-3 weeks):
   - Player performance trends (rolling averages)
   - Team matchup analysis
   - Home/away splits
   - Rest days impact
   - Injury impact on minutes

2. **Model Training** (1-2 weeks):
   - Baseline models (simple averages)
   - ML models (random forest, gradient boosting)
   - Deep learning (if justified)
   - Cross-validation strategy

3. **Backtesting Framework** (1 week):
   - Historical prediction accuracy
   - Model comparison metrics
   - Production-ready evaluation

4. **Integration** (1 week):
   - Connect to Phase 6 pipeline
   - Replace or augment existing predictions
   - A/B testing framework

**Total Effort**: 5-7 weeks
**Business Impact**: Improved prediction accuracy → better user value

---

### 2. Enhanced Monitoring & Alerting

**Priority**: MEDIUM (operational excellence)

**Current State**: 4 monitoring layers active
- Layer 1: Scraper output validation ✅
- Layer 5: Processor output validation ✅
- Layer 6: Real-time completeness ✅
- Layer 7: Daily batch verification ✅

**Gaps Identified**:
1. **Email alerts not fully wired** (alert_manager.py has TODOs)
2. **No Slack integration** (common for dev teams)
3. **No cost monitoring** (BigQuery/Cloud Run costs)
4. **No performance trend tracking** (slowdown detection)

**Implementation Plan**:

**A. Complete Email Alerting** (2-3 hours):
- Wire up alert_manager.py TODOs
- Test with production alerts
- Set up email distribution list

**B. Add Slack Integration** (3-4 hours):
- Create Slack webhook
- Add Slack notifier to alert_manager.py
- Configure alert severity routing

**C. Cost Monitoring Dashboard** (4-6 hours):
- BigQuery cost tracking queries
- Cloud Run billing analysis
- Automated cost anomaly alerts
- Weekly cost reports

**D. Performance Trending** (4-6 hours):
- Track pipeline timing over time
- Detect slowdowns automatically
- Alert on >10% performance degradation

**Total Effort**: 13-19 hours (2-3 days)
**Benefit**: Proactive issue detection, cost control

---

### 3. Data Quality Improvements

**Priority**: MEDIUM (accuracy & completeness)

**Current Gaps**:
1. **BDL API reliability issues** (documented in Nov-Dec 2025)
2. **No automated data quality checks** (rely on manual validation)
3. **No cross-source validation** (e.g., compare BDL vs NBA.com)

**Implementation Plan**:

**A. Cross-Source Validation** (1-2 weeks):
```python
# Example: Verify BDL matches NBA.com
SELECT
  nba.game_id,
  nba.player_points,
  bdl.player_points,
  ABS(nba.player_points - bdl.player_points) as diff
FROM nba_analytics.player_game_stats nba
JOIN nba_raw.bdl_player_boxscores bdl
  ON nba.game_id = bdl.game_id
  AND nba.player_id = bdl.player_id
WHERE ABS(nba.player_points - bdl.player_points) > 0
ORDER BY diff DESC;
```

**B. Automated Data Quality Checks** (1-2 weeks):
- Daily completeness reports
- Statistical anomaly detection (e.g., player scores 200 points = data error)
- Missing data alerts (e.g., game finished but no boxscore)
- Historical consistency checks

**C. BDL Reliability Monitoring** (1 week):
- Track BDL API uptime
- Alert on missing games
- Automatic fallback to NBA.com if BDL fails
- Historical gap detection & auto-backfill

**Total Effort**: 3-5 weeks
**Benefit**: Higher data accuracy, fewer manual interventions

---

## 🚀 LONG-TERM PRIORITIES (Next 3-6 Months)

### 1. Platform Maturity & Automation

**Goal**: Reduce manual intervention to near-zero

**Current Manual Work**:
- Backfilling missing data (occasional)
- Investigating scraper failures (weekly)
- Monitoring pipeline health (daily)
- Deploying fixes (as needed)

**Automation Opportunities**:

**A. Self-Healing Backfill** (2-3 weeks):
- Automatic gap detection (already exists in Layer 6-7)
- Automatic backfill triggering (new)
- Success verification & retry logic
- Alert only on permanent failures

**B. Intelligent Retry Logic** (1-2 weeks):
- Scraper-specific retry strategies
- Exponential backoff (already exists)
- Circuit breaker pattern (prevent cascading failures)
- Automatic degradation (use cached data if fresh fails)

**C. Automated Health Reporting** (1 week):
- Daily health check emails (automated)
- Weekly trend reports (automated)
- Monthly platform metrics (automated)
- Quarterly planning insights (automated)

**Total Effort**: 4-6 weeks
**Benefit**: 80% reduction in manual operational work

---

### 2. Technical Debt Reduction

**Priority**: MEDIUM (code health)

**Current Technical Debt**:
- 143 TODO/FIXME comments (documented)
- Bare except handlers (partially fixed)
- Missing timeouts (partially fixed)
- Test coverage gaps (documented)

**Prioritized Cleanup Plan**:

**Phase 1: Critical TODOs** (1-2 weeks):
- P0-ORCH-1: Cleanup processor Pub/Sub TODO
- P0-ORCH-2: Phase 4→5 timeout
- P0-ORCH-3: Alert manager TODOs

**Phase 2: High-Priority TODOs** (2-3 weeks):
- Remaining bare except handlers
- Missing error handling
- Incomplete retry logic

**Phase 3: Medium-Priority Improvements** (2-4 weeks):
- Test coverage improvements
- Documentation updates
- Code style consistency

**Total Effort**: 5-9 weeks (can be done incrementally)
**Benefit**: Fewer future bugs, easier maintenance

---

### 3. Architecture Improvements

**Priority**: LOW (future-proofing)

**Opportunities**:

**A. Event-Driven Orchestration** (4-6 weeks):
- Replace cron-based scheduling with event triggers
- Use Pub/Sub for inter-phase communication
- Reduce latency (no waiting for scheduled runs)
- Better error isolation

**See**: `plans/EVENT-DRIVEN-ORCHESTRATION-DESIGN.md` for detailed design (200+ pages)

**B. Microservices Optimization** (2-3 weeks):
- Right-size Cloud Run instances
- Optimize cold start performance
- Implement connection pooling
- Add caching layers

**C. Database Optimization** (1-2 weeks):
- Review BigQuery partitioning strategy
- Add clustering to more tables (already done for predictions)
- Optimize frequently-run queries
- Implement materialized views

**Total Effort**: 7-11 weeks
**Benefit**: Faster pipeline, lower costs, more scalable

---

## 📈 SUCCESS METRICS

### Immediate (Next 48 Hours)
- [ ] Referee discovery: 12 attempts seen (not 6)
- [ ] Referee discovery: ≥1 success during 10 AM-2 PM ET
- [ ] Injury discovery: game_date = '2026-01-03' (not execution date)
- [ ] Injury discovery: ~110 records for Jan 3
- [ ] Tonight's games: All 10 collected by 4 AM ET

### Short-Term (Next 2 Weeks)
- [ ] nbac_schedule_api: Root cause identified
- [ ] nbac_schedule_api: Success rate >80%
- [ ] Betting scrapers: Error patterns documented
- [ ] Phase 1 tests: Integration tests implemented

### Medium-Term (Next 1-2 Months)
- [ ] ML model: Feature engineering complete
- [ ] ML model: Baseline models trained
- [ ] Monitoring: Email + Slack alerting live
- [ ] Monitoring: Cost tracking dashboard active
- [ ] Data quality: Cross-source validation implemented

### Long-Term (Next 3-6 Months)
- [ ] Automation: Self-healing backfill operational
- [ ] Automation: 80% reduction in manual work
- [ ] Technical debt: P0-P1 TODOs resolved
- [ ] Architecture: Event-driven design evaluated

---

## 🎯 RECOMMENDED NEXT SESSION PRIORITIES

**Session Priority Order**:

### Option A: Validation First (RECOMMENDED for next session)
**Goal**: Ensure recent fixes work as designed
**Duration**: 2-3 hours
**Tasks**:
1. Monitor tonight's game collection (11 PM ET check)
2. Verify overnight processing (tomorrow 8 AM ET)
3. Validate referee discovery (tomorrow 12 PM ET)
4. Validate injury discovery (tomorrow 12 PM ET)
5. Document results in handoff

**Why**: Critical to confirm fixes before moving on

---

### Option B: Investigation First
**Goal**: Address pre-existing failures
**Duration**: 3-4 hours
**Tasks**:
1. Investigate nbac_schedule_api failures (URGENT)
2. Document root cause + fix plan
3. Investigate betting scraper failures
4. Deploy fixes if straightforward

**Why**: Data completeness impact (schedule is critical dependency)

---

### Option C: ML Model Prep
**Goal**: Start feature engineering
**Duration**: 4-6 hours
**Tasks**:
1. Review historical data completeness
2. Design initial feature set
3. Implement feature extraction queries
4. Test with sample data

**Why**: High business value, foundation is ready

---

## 📚 REFERENCE DOCUMENTATION

**Immediate Monitoring**:
- `/tmp/2026-01-02-MONITORING-ULTRATHINK.md` - Complete monitoring guide (715 lines)
- `docs/09-handoff/2026-01-03-INJURY-DISCOVERY-FIX-COMPLETE.md` - Injury fix details

**Strategic Planning**:
- `docs/08-projects/current/ml-model-development/` - ML roadmap (when created)
- `plans/EVENT-DRIVEN-ORCHESTRATION-DESIGN.md` - Architecture redesign
- `COMPREHENSIVE-IMPROVEMENT-PLAN.md` - 200+ improvement opportunities

**Operational**:
- `QUICK-WINS-CHECKLIST.md` - Tactical optimizations
- `RECURRING-ISSUES.md` - Incident patterns
- `monitoring/FAILURE-TRACKING-DESIGN.md` - Monitoring architecture

---

## 💡 KEY PRINCIPLES

**1. Validate Before Building**
- Always verify fixes work before moving to next task
- Tomorrow's validation is critical for confidence

**2. Data Quality First**
- ML models are only as good as training data
- Fix scraper failures before building models

**3. Incremental Progress**
- Don't try to do everything at once
- Ship small, working increments
- Document as you go

**4. Measure Everything**
- Define success criteria upfront
- Track metrics consistently
- Use data to drive decisions

**5. Automate Repetitively**
- If you do it twice, automate it
- Invest in tooling that saves future time
- Reduce manual operational burden

---

**Last Updated**: January 2, 2026 4:16 PM ET
**Next Review**: After Jan 3 validation period (tomorrow evening)
**Status**: ✅ Ready for immediate validation + strategic planning
