# 🚨 START HERE FOR ERROR INVESTIGATION

**New to this codebase? Investigating an issue? Read this first.**

---

## 📍 You Are Here

This is the NBA Stats Scraper project. If you're investigating errors, data gaps, or system issues, this guide will point you in the right direction.

---

## 🎯 Quick Navigation

### I'm investigating...

**Data Quality Issues (missing games, incomplete data)**
- → Read: [`/COMPLETENESS-CHECK-SUMMARY.txt`](/COMPLETENESS-CHECK-SUMMARY.txt) - Quick overview
- → Read: [`/DATA-COMPLETENESS-REPORT-JAN-21-2026.md`](/DATA-COMPLETENESS-REPORT-JAN-21-2026.md) - Detailed 7-day analysis
- → Read: [`/docs/08-projects/current/week-1-improvements/ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md`](/docs/08-projects/current/week-1-improvements/ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md) - Full investigation report

**System Errors (scrapers failing, services crashing)**
- → Read: [`/ERROR-QUICK-REF.md`](/ERROR-QUICK-REF.md) - Quick commands
- → Read: [`/docs/ERROR-LOGGING-GUIDE.md`](/docs/ERROR-LOGGING-GUIDE.md) - Comprehensive guide
- → Read: [`/docs/08-projects/current/week-1-improvements/ERROR-SCAN-JAN-15-21-2026.md`](/docs/08-projects/current/week-1-improvements/ERROR-SCAN-JAN-15-21-2026.md) - Recent error analysis

**API Provider Issues (need to report to BallDontLie, NBA.com, etc.)**
- → Read: [`/docs/08-projects/current/week-1-improvements/API-ERROR-LOGGING-PROPOSAL.md`](/docs/08-projects/current/week-1-improvements/API-ERROR-LOGGING-PROPOSAL.md) - Proposed logging system
- → Use: `python bin/operations/query_api_errors.py` (once implemented)

**Pipeline/Orchestration Issues (data not flowing through stages)**
- → Check: Firestore `phase*_completion` collections
- → Check: `nba_orchestration.scraper_execution_log` BigQuery table
- → Read: Section 2-4 of [`/docs/ERROR-LOGGING-GUIDE.md`](/docs/ERROR-LOGGING-GUIDE.md)

**"I don't know what's wrong, just know something is broken"**
- → Run: `./bin/validation/daily_data_quality_check.sh`
- → Run: `python scripts/check_30day_completeness.py --days 7`
- → Read: `/ERROR-QUICK-REF.md` for quick diagnostic commands

---

## 📊 Error Logging Systems Overview

### Current (Production)
1. **BigQuery Tables**
   - `nba_orchestration.scraper_execution_log` - All scraper runs
   - `nba_orchestration.scraper_output_validation` - Data quality checks
   - `nba_orchestration.processor_output_validation` - Processor validation

2. **Google Cloud Logging**
   - All service logs (Cloud Run, Cloud Functions)
   - Query: `gcloud logging read 'severity>=ERROR' --limit=50 --freshness=24h`

3. **Sentry.io**
   - Exception tracking with stack traces
   - Environment: Production/Staging/Development

4. **Notifications**
   - Email (AWS SES / Brevo)
   - Slack webhooks
   - Discord (optional)

### Proposed (To Be Implemented)
5. **API Error Table**
   - `nba_orchestration.api_errors` - Detailed HTTP request/response logging
   - See: `/docs/08-projects/current/week-1-improvements/API-ERROR-LOGGING-PROPOSAL.md`

---

## 🔍 Common Investigation Workflows

### Workflow 1: "Data Missing for Date X"

```bash
# Step 1: Check scraper execution
bq query --use_legacy_sql=false "
  SELECT scraper_name, status, COUNT(*) as count
  FROM nba_orchestration.scraper_execution_log
  WHERE DATE(created_at) = 'YYYY-MM-DD'
  GROUP BY scraper_name, status
"

# Step 2: Check for errors
gcloud logging read 'severity>=ERROR timestamp>="YYYY-MM-DDT00:00:00Z"' --limit=100

# Step 3: Check data completeness
python scripts/check_30day_completeness.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD

# Step 4: If needed, backfill
./bin/run_backfill.sh raw/bdl_boxscores --dates=YYYY-MM-DD
```

### Workflow 2: "Service Keeps Crashing"

```bash
# Step 1: Check recent errors for service
gcloud logging read 'resource.labels.service_name="SERVICE_NAME" severity>=ERROR' \
  --limit=50 --freshness=24h

# Step 2: Check current revision
gcloud run services describe SERVICE_NAME --region us-west2 \
  --format="value(status.latestReadyRevisionName,status.traffic)"

# Step 3: Check for HealthChecker or dependency issues
gcloud logging read 'resource.labels.service_name="SERVICE_NAME" "HealthChecker"' \
  --limit=10

# Step 4: Review recent deployments
gcloud run revisions list --service=SERVICE_NAME --region=us-west2 --limit=5
```

### Workflow 3: "Predictions Not Generating"

```bash
# Step 1: Check if Phase 4/5 completed
bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= CURRENT_DATE() - 7 AND is_active = TRUE
  GROUP BY game_date ORDER BY game_date DESC
"

# Step 2: Check prediction pipeline errors
gcloud logging read 'resource.labels.service_name=~"prediction" severity>=ERROR' \
  --limit=50 --freshness=24h

# Step 3: Check upstream dependencies (Phase 3/4 data)
bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(*) as player_records
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date ORDER BY game_date DESC
"
```

---

## 📚 Documentation Structure

```
/
├── ERROR-QUICK-REF.md              ← Start here for quick commands
├── COMPLETENESS-CHECK-SUMMARY.txt  ← Quick data status overview
├── DATA-COMPLETENESS-REPORT-*.md   ← Detailed data analysis
├── docs/
│   ├── 00-START-HERE-FOR-ERRORS.md ← This file
│   ├── ERROR-LOGGING-GUIDE.md      ← Comprehensive error logging guide
│   └── 08-projects/current/week-1-improvements/
│       ├── ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md  ← Full investigation
│       ├── ERROR-SCAN-JAN-15-21-2026.md           ← Error analysis
│       ├── API-ERROR-LOGGING-PROPOSAL.md          ← Structured logging proposal
│       ├── SYSTEM-VALIDATION-JAN-21-2026.md       ← System health report
│       └── DEPLOYMENT-SESSION-JAN-21-2026.md      ← Deployment notes
├── validation/
│   ├── VALIDATOR_QUICK_REFERENCE.md
│   └── IMPLEMENTATION_GUIDE.md
└── bin/
    ├── validation/
    │   └── daily_data_quality_check.sh  ← Daily health check script
    └── operations/
        ├── monitoring_queries.sql       ← Useful BigQuery queries
        └── query_api_errors.py          ← Query API errors (proposed)
```

---

## 🎓 For New Chats/Sessions

When starting a new chat session to investigate issues:

1. **Read this file first** to understand the system
2. **Check `/ERROR-QUICK-REF.md`** for immediate diagnostic commands
3. **Review recent investigation reports** in `/docs/08-projects/current/week-1-improvements/`
4. **Run health checks** to get current status
5. **Consult `/docs/ERROR-LOGGING-GUIDE.md`** for detailed guidance
6. **Document your findings** in a new report in `/docs/08-projects/current/`

---

## 🔧 Key Operational Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `daily_data_quality_check.sh` | Check data quality | `./bin/validation/daily_data_quality_check.sh` |
| `check_30day_completeness.py` | Data completeness analysis | `python scripts/check_30day_completeness.py --days 7` |
| `query_api_errors.py` | Query API errors | `python bin/operations/query_api_errors.py --days 7` (proposed) |
| `monitoring_queries.sql` | BigQuery monitoring | `bq query < bin/operations/monitoring_queries.sql` |
| `run_backfill.sh` | Backfill missing data | `./bin/run_backfill.sh raw/bdl_boxscores --dates=YYYY-MM-DD` |

---

## 🚨 Known Issues & Patterns

**Recent Issues Documented:**

1. **BigDataBall Google Drive Files Missing** (Jan 15-21)
   - 100% failure rate for play-by-play data
   - See: ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md, Issue #1

2. **Phase 2 Processor Incompleteness** (Jan 20)
   - Only 2 of 6 processors completed
   - Phase 3 not triggered
   - See: ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md, Issue #2

3. **HealthChecker Bug** (Jan 20-21) - RESOLVED
   - Services crashed due to API signature change
   - Fixed on Jan 21
   - See: ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md, Issue #3

4. **Missing upstream_team_game_context** (Jan 16-21)
   - Composite factors incomplete or missing
   - 93.8% of predictions have quality warnings
   - See: ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md, Issue #4

5. **Silent Scraper Failures** (Ongoing)
   - Pagination failures discard data
   - No game count validation
   - See: ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md, Issue #5

---

## 📞 Getting Help

**Resources:**
- `/docs/ERROR-LOGGING-GUIDE.md` - Comprehensive error guide
- `/docs/08-projects/current/` - Recent investigations
- `/validation/` - Data validation system docs
- `gcloud logging read --help` - Cloud Logging help

**Common Commands:**
```bash
# Quick health check
./bin/validation/daily_data_quality_check.sh

# Check recent errors
gcloud logging read 'severity>=ERROR' --limit=50 --freshness=24h

# Data completeness
python scripts/check_30day_completeness.py --days 7

# Service status
gcloud run services list --region us-west2 --filter="metadata.name:nba"
```

---

## ✅ Checklist for New Investigation

- [ ] Read this document
- [ ] Review `/ERROR-QUICK-REF.md`
- [ ] Check recent investigation reports in `/docs/08-projects/current/`
- [ ] Run `daily_data_quality_check.sh`
- [ ] Run `check_30day_completeness.py`
- [ ] Check Cloud Logging for errors
- [ ] Check BigQuery execution log
- [ ] Document findings in new report
- [ ] Update this document if new patterns discovered

---

**Last Updated:** January 21, 2026
**Maintained By:** Engineering Team
**For Questions:** Review documentation first, then investigate using error logging guide
