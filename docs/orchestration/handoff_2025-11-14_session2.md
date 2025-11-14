# Handoff Document: NBA Orchestration System - All Fixes Complete

**Date:** 2025-11-14 (Session 2)
**Status:** ✅ Production Ready - 100% Success Rate Achieved
**Previous Session:** docs/orchestration/handoff_2025-11-14.md
**Current Revision:** nba-scrapers-00079-t9z

---

## Executive Summary

**All orchestration fixes completed and verified in production!**

### What Was Accomplished Today:

1. ✅ **Fixed 5 critical issues** (from previous handoff):
   - bdl_standings missing season parameter
   - Season year extraction (2025 not 2026)
   - Basketball Reference team code mappings (PHX→PHO, BKN→BRK, CHA→CHO)
   - BigQuery opts field JSON conversion
   - Charlotte Hornets team mapping (discovered during testing)

2. ✅ **Deployed and verified** (2 deployments):
   - Initial deployment with 4 fixes: 33/34 scrapers succeeded
   - Final deployment with CHA fix: **34/34 scrapers succeeded (100%)**

3. ✅ **Created Grafana monitoring guide**:
   - 14 dashboard panel queries
   - 4 alert queries
   - Complete schema documentation
   - Location: `docs/orchestration/grafana-monitoring-guide.md`

4. ✅ **Consolidated all Dockerfiles**:
   - Moved 4 localized Dockerfiles to `/docker` directory
   - Updated 3 deployment scripts
   - Removed old localized files
   - Centralized management for all services

### Current Production Status:

**Service:** nba-scrapers (includes orchestration)
**Revision:** nba-scrapers-00079-t9z
**Success Rate:** 100% (34/34 scrapers)
**Last Test:** 2025-11-14 04:32 UTC
**Execution ID:** 95dc1c01-666d-4736-a8cc-331ffb3302ba

---

## Quick Health Check for Tomorrow

Run these commands to verify everything is still working:

### 1. Check Latest Workflow Execution

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  execution_time,
  workflow_name,
  status,
  scrapers_triggered,
  scrapers_succeeded,
  scrapers_failed,
  ROUND(duration_seconds, 1) as duration_sec
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE DATE(execution_time) = CURRENT_DATE()
ORDER BY execution_time DESC
LIMIT 5
"
```

**Expected:** All recent workflows should have `scrapers_failed = 0`

---

### 2. Check for Any Scraper Failures (Last 24 Hours)

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  scraper_name,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT error_type LIMIT 3) as error_types
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE status = 'failed'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
ORDER BY failure_count DESC
"
```

**Expected:** No results (zero failures)

---

### 3. Verify Multi-Team Scraper (30 Teams)

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  JSON_VALUE(opts, '\$.teamAbbr') as team,
  status,
  COUNT(*) as executions
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE scraper_name = 'basketball_ref_season_roster'
  AND DATE(triggered_at) = CURRENT_DATE()
GROUP BY team, status
ORDER BY team
"
```

**Expected:** 30 teams, all with `status = 'success'`
**Teams to verify:** PHO (not PHX), BRK (not BKN), CHO (not CHA)

---

### 4. Check Service Health

```bash
curl -s https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/health | jq '.'
```

**Expected:** Status 200, service healthy

---

### 5. Quick Workflow Trigger Test (Optional)

```bash
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/trigger-workflow \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "morning_operations"}'
```

**Expected:** 34 scrapers triggered, 34 succeeded, 0 failed

---

## Files Modified Today

### 1. Orchestration Fixes

**config/scraper_parameters.yaml**
```yaml
# Line 42-43: Added season parameter for bdl_standings
bdl_standings:
  season: context.season_year  # Ball Don't Lie API uses 4-digit year
```

**orchestration/parameter_resolver.py**
```python
# Line 115-122: Fixed season_year extraction (starting year not ending year)
season_year = season.split('-')[0]  # "2025" not "2026"

# Line 308-314: Added team code mappings
NBA_TO_BR_TEAM_CODES = {
    'PHX': 'PHO',  # Phoenix Suns
    'BKN': 'BRK',  # Brooklyn Nets
    'CHA': 'CHO',  # Charlotte Hornets
}
```

**scrapers/scraper_base.py**
```python
# Line 629-630: Fixed BigQuery opts field JSON conversion
'opts': json.dumps({k: v for k, v in self.opts.items()
        if k not in ['password', 'api_key', 'token', 'proxyUrl']}),
```

### 2. Dockerfile Consolidation

**New files in docker/ directory:**
- docker/scrapers.Dockerfile
- docker/analytics-processor.Dockerfile
- docker/raw-processor.Dockerfile
- docker/reportgen.Dockerfile

**Updated deployment scripts:**
- bin/scrapers/deploy/deploy_scrapers_simple.sh
- bin/analytics/deploy/deploy_analytics_processors.sh
- bin/raw/deploy/deploy_processors_simple.sh

**Removed files:**
- scrapers/Dockerfile (moved to docker/)
- data_processors/analytics/Dockerfile (moved to docker/)
- data_processors/raw/Dockerfile (moved to docker/)
- reportgen/Dockerfile (moved to docker/)

### 3. Documentation

**New documents created:**
- docs/orchestration/grafana-monitoring-guide.md (comprehensive Grafana guide)
- docs/orchestration/handoff_2025-11-14_session2.md (this document)

---

## Outstanding Tasks

### Priority: LOW (Optional - System is working)

**1. Commit Changes to Git**

The following changes are uncommitted but deployed to production:

```bash
# View all changes
git status

# Modified files (from previous session):
# - bin/scrapers/deploy/deploy_scrapers_simple.sh
# - data_processors/raw/main_processor_service.py
# - orchestration/cleanup_processor.py
# - orchestration/schedule_locker.py
# - orchestration/workflow_executor.py
# - scrapers/main_scraper_service.py
# - scrapers/oddsapi/oddsa_events.py
# - scrapers/requirements.txt
# - scrapers/scraper_base.py

# New files from today's sessions:
# - config/scraper_parameters.yaml
# - orchestration/parameter_resolver.py
# - docker/scrapers.Dockerfile
# - docker/analytics-processor.Dockerfile
# - docker/raw-processor.Dockerfile
# - docker/reportgen.Dockerfile
# - docs/orchestration/grafana-monitoring-guide.md
# - docs/orchestration/handoff_2025-11-14.md
# - docs/orchestration/handoff_2025-11-14_session2.md
# + many more from previous sessions
```

**Suggested commit message:**
```
fix: orchestration parameter resolution and Dockerfile consolidation

- Fix season_year extraction (use starting year not ending year)
- Add Basketball Reference team code mappings (PHX→PHO, BKN→BRK, CHA→CHO)
- Fix bdl_standings missing season parameter
- Fix BigQuery opts field JSON conversion
- Consolidate all Dockerfiles to /docker directory
- Update deployment scripts to use centralized Dockerfiles
- Add comprehensive Grafana monitoring guide

Verified in production: 100% scraper success rate (34/34)
Service: nba-scrapers-00079-t9z

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**2. Deploy Processors Service (Optional)**

If you want enhanced error notifications:

```bash
./bin/raw/deploy/deploy_processors_simple.sh
```

**Note:** This is optional. The enhanced error notification system is implemented in the code but not deployed yet. Current processors still use the old error format.

---

## Test Results Summary

### Before Fixes (2025-11-14 03:57 UTC):
- Execution ID: 09c00038-a029-4757-904b-404c8a18d5c4
- Scrapers triggered: 34
- Scrapers succeeded: 29
- **Scrapers failed: 5** ❌

**Failures:**
1. bdl_standings - Missing season parameter
2. br_season_roster (PHX) - Team code mismatch
3. br_season_roster (BKN) - Team code mismatch
4. nbac_schedule_api - Wrong season year (2026-27)
5. Multiple scrapers - BigQuery opts field error

### After Initial Fixes (2025-11-14 04:20 UTC):
- Execution ID: 7106d0a9-9ea6-4bd0-901d-4f3e439d3e2b
- Scrapers triggered: 34
- Scrapers succeeded: 33
- **Scrapers failed: 1** ⚠️

**Remaining failure:**
1. br_season_roster (CHA) - Charlotte team code mismatch

### After Final Fix (2025-11-14 04:32 UTC):
- Execution ID: 95dc1c01-666d-4736-a8cc-331ffb3302ba
- Scrapers triggered: 34
- **Scrapers succeeded: 34** ✅
- **Scrapers failed: 0** ✅

**Perfect score!**

---

## System Architecture (Current State)

### Phase 1 Orchestration (Active)

**Components:**
1. **nba-scrapers** (Cloud Run service)
   - Runs scrapers
   - Executes workflows
   - HTTP-based orchestration
   - Logs to BigQuery

2. **Workflow Executor** (bundled in nba-scrapers)
   - Resolves parameters
   - Triggers scraper executions
   - Handles multi-entity scrapers (30 teams)
   - Records execution metrics

3. **BigQuery Logging**
   - `nba_orchestration.workflow_executions`
   - `nba_orchestration.scraper_execution_log`

4. **Pub/Sub Integration**
   - Scrapers publish completion events
   - Processors subscribe and process data
   - Phase 1→Phase 2 handoff

### Services Not Updated Yet:

1. **nba-processors** - Still using old code
   - Enhanced error notifications not deployed
   - Works fine with current setup

2. **Other services** - Unchanged
   - Analytics processors
   - Predictions coordinator/workers
   - Monitoring services

---

## Key Learnings from Today

### 1. Team Code Mappings Are Critical

NBA uses different abbreviations than Basketball Reference for some teams:
- Phoenix Suns: NBA=PHX, BR=PHO
- Brooklyn Nets: NBA=BKN, BR=BRK
- Charlotte Hornets: NBA=CHA, BR=CHO

**Solution:** Added mapping dict in parameter_resolver.py:308-314

### 2. Season Year Confusion

NBA season format: "2025-26" (crosses calendar years)
- Some APIs want starting year: 2025
- Some APIs want ending year: 2026
- We were using ending year for everything → wrong!

**Solution:** Changed to starting year as default (parameter_resolver.py:115-116)

### 3. BigQuery JSON Fields Need Strings

BigQuery JSON fields must receive JSON strings, not Python dicts.

**Solution:** Added `json.dumps()` wrapper in scraper_base.py:629-630

### 4. Multi-Team Scrapers Work Great

The multi-team scraper support (br_season_roster) successfully triggers 30 separate executions from a single workflow request. This pattern can be used for other per-team scrapers in the future.

### 5. Dockerfile Consolidation Improves Maintainability

Having all Dockerfiles in `/docker` directory makes it easier to:
- Compare configurations across services
- Update base images consistently
- Spot duplicate dependencies
- Understand deployment structure

---

## Monitoring Resources

### Grafana Dashboard Queries

See: `docs/orchestration/grafana-monitoring-guide.md`

**Quick access panels to set up:**
1. Workflow Success Rate (last 24h)
2. Scraper Success Rate by Name
3. Failed Scraper Executions (recent)
4. Execution Duration (P95)

### GCP Monitoring

**Cloud Console → Monitoring → Dashboards**
- View Cloud Run metrics
- Check Pub/Sub queue depths
- Monitor BigQuery usage

### Email Alerts

Email alerting is configured for:
- Critical scraper failures
- High failure rates
- Processing errors

**Recipients:** nchammas@gmail.com
**SMTP:** Brevo (configured via environment variables)

---

## Troubleshooting Guide

### If Scrapers Start Failing:

**1. Check the error type:**

```bash
bq query --use_legacy_sql=false "
SELECT error_type, error_message, scraper_name
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE status = 'failed'
  AND DATE(triggered_at) = CURRENT_DATE()
LIMIT 10
"
```

**2. Common issues and solutions:**

| Error | Cause | Solution |
|-------|-------|----------|
| `Missing required option [season]` | Parameter config missing | Check config/scraper_parameters.yaml |
| `Invalid team abbreviation` | Team code mismatch | Check parameter_resolver.py mappings |
| `This field: opts is not a record` | BigQuery JSON error | Ensure json.dumps() is used |
| `Season=2026-27` (wrong year) | Season year logic | Verify parameter_resolver.py:115-116 |

**3. Check recent deployments:**

```bash
gcloud run services describe nba-scrapers --region=us-west2 --format="value(status.latestCreatedRevisionName)"
```

**4. View service logs:**

```bash
gcloud run services logs read nba-scrapers --region=us-west2 --limit=50
```

---

## Contact & Reference

**Previous Handoffs:**
- docs/orchestration/handoff_2025-11-14.md (Session 1 - identified 4 fixes)
- docs/orchestration/handoff_2025-11-14_session2.md (this document)

**Related Documentation:**
- docs/orchestration/grafana-monitoring-guide.md (monitoring queries)
- docs/orchestration/phase1_monitoring_operations_guide.md (operations guide)
- docs/orchestration/2025-11-13-parameter-fixes-summary.md (earlier fixes)
- docs/orchestration/enhanced-error-notifications-summary.md (enhanced notifications)
- DEPLOYMENT_PLAN.md (deployment procedures)

**GCP Resources:**
- Project: nba-props-platform
- Region: us-west2
- Service: nba-scrapers (https://nba-scrapers-f7p3g7f6ya-wl.a.run.app)
- BigQuery Dataset: nba_orchestration

---

## Success Metrics

### Production Readiness Checklist

- ✅ All scrapers execute successfully (34/34)
- ✅ Multi-team support working (30 teams)
- ✅ Correct season year (2025 not 2026)
- ✅ Team code mappings (PHX→PHO, BKN→BRK, CHA→CHO)
- ✅ BigQuery logging working (JSON fields)
- ✅ Pub/Sub integration active
- ✅ Email alerts configured
- ✅ Monitoring queries documented
- ✅ Deployment scripts updated
- ✅ Dockerfiles centralized

### System Health Indicators

**Healthy:**
- Workflow success rate: >95%
- Scraper success rate: >95%
- Duration: Within 10% of baseline
- No data rate: <10% (expected for some scrapers)

**Warning:**
- Workflow success rate: 90-95%
- Scraper success rate: 90-95%
- Duration: 10-25% above baseline
- Repeated timeouts

**Critical:**
- Workflow success rate: <90%
- Scraper success rate: <90%
- Duration: >25% above baseline
- All executions failing
- No executions in expected window

---

## Next Session Recommendations

### If Everything Looks Good:

1. ✅ Review health checks (all green)
2. ✅ Optional: Commit changes to git
3. ✅ Optional: Set up Grafana dashboards
4. ✅ Continue with normal operations

### If Issues Arise:

1. Run health check queries above
2. Check error types in BigQuery
3. Review recent deployments
4. Check service logs
5. Consult troubleshooting guide

### Future Enhancements (Low Priority):

1. Deploy enhanced error notifications (processors service)
2. Set up Grafana dashboards for monitoring
3. Add more alert queries
4. Create automated health check script
5. Consider migrating to docker build pattern (vs gcloud run deploy --source)

---

**Last Updated:** 2025-11-14 21:00 UTC
**System Status:** ✅ Production Ready
**Next Deployment:** Not needed unless issues arise
**Confidence Level:** HIGH - All fixes tested and verified

---

**End of Handoff Document**
