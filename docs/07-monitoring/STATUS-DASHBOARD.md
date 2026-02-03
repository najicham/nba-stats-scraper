# NBA Stats Scraper - System Status Dashboard

**Last Updated:** Auto-generated on access
**Project:** nba-props-platform
**Environment:** Production

---

## 🎯 Quick Status Check

Run this to get current status:
```bash
./monitoring/check-system-health.sh
```

**Or manually check:**
```bash
# 1. Recent grading
bq query --use_legacy_sql=false '
SELECT MAX(graded_at) as last_graded,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(graded_at), HOUR) as hours_ago
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)'

# 2. Phase 3 health
curl -s https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health | jq

# 3. Check for 503 errors
gcloud functions logs read phase5b-grading --region=us-west2 --limit=100 | grep -c "503"
```

---

## 📊 System Components

### Core Infrastructure

| Component | Service | Region | Status Check |
|-----------|---------|--------|--------------|
| **Grading Function** | Cloud Function | us-west2 | `gcloud functions describe phase5b-grading --region=us-west2` |
| **Phase 3 Analytics** | Cloud Run | us-west2 | `curl https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health` |
| **Prediction Worker** | Cloud Run | us-west2 | `curl https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health` |
| **Firestore Locks** | Firestore | global | `gcloud firestore collections list \| grep lock` |

### Data Storage

| Dataset | Tables | Purpose |
|---------|--------|---------|
| **nba_predictions** | player_prop_predictions, prediction_accuracy | Predictions & grading results |
| **nba_analytics** | player_game_summary, team_*_summary | Processed analytics (Phase 3) |
| **nba_raw** | bdl_*, nbac_*, odds_* | Raw scraped data (Phase 2) |
| **nba_box_scores** | player_game_summary (legacy) | Historical boxscores |

### Scheduled Jobs

| Job | Schedule | Purpose | Check Status |
|-----|----------|---------|--------------|
| **nba-daily-grading** | Daily 6 AM ET | Grade predictions vs actuals | `gcloud scheduler jobs describe nba-daily-grading --location=us-west2` |
| **nba-daily-predictions** | Daily 10 AM ET | Generate predictions | `gcloud scheduler jobs list --location=us-west2` |

---

## 🔧 Recent Changes (Session 97-112)

### Session 112 (2026-01-19) 🎉
✅ **Prediction Worker Firestore Fix - CRITICAL**
- Fixed 37+ hour prediction pipeline outage
- Root cause: Missing `google-cloud-firestore==2.14.0` dependency
- All 7 prediction systems restored (including Ensemble V1.1)
- Verified: 614 predictions generated for Jan 19 games
- Reference: `docs/09-handoff/SESSION-112-PREDICTION-WORKER-FIRESTORE-FIX.md`

### Session 111 (2026-01-19)
✅ **Session 107 Metrics Deployed**
- Deployed 7 missing Session 107 metrics (variance + star tracking)
- Fixed analytics processor schema evolution
- Jan 19: 100% populated, Jan 17-18 need backfill
- Reference: `docs/09-handoff/SESSION-111-SESSION-107-METRICS-AND-PREDICTION-DEBUGGING.md`

⚠️ **Prediction Pipeline Investigation**
- Identified prediction worker crashes (fixed in Session 112)
- Fixed prediction coordinator deployment script
- Discovered issue started 12 hours BEFORE Session 110

### Session 110 (2026-01-18)
✅ **Ensemble V1.1 Deployed**
- Performance-based weighted ensemble (vs confidence-based)
- Expected MAE: 4.9-5.1 (6-9% improvement)
- Integration tested and operational
- Reference: `docs/09-handoff/SESSION-110-ENSEMBLE-V1.1-AND-COMPREHENSIVE-TODOS.md`

### Session 99 (2026-01-18)
✅ **Phase 3 Analytics 503 Fix**
- Set minScale=1 on Phase 3 service (prevents cold starts)
- Response time: 3.8s (vs 300s timeout)
- Cost: ~$12-15/month
- Reference: `docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md`

### Session 97-98 (2026-01-17-18)
✅ **Distributed Locking Deployed**
- Prevents duplicate grading records
- 3-layer defense: Lock → Validation → Alerting
- Zero duplicates since deployment
- Reference: `docs/09-handoff/SESSION-97-MONITORING-COMPLETE.md`

---

## 📈 Key Metrics

### Health Indicators

**Grading Coverage** (Target: 70-90%)
```sql
SELECT
  game_date,
  COUNT(*) as graded,
  (SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.player_prop_predictions`
   WHERE game_date = acc.game_date) as total,
  ROUND(COUNT(*) * 100.0 / (
    SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = acc.game_date
  ), 1) as coverage_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy` acc
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

**Phase 3 Response Time** (Target: <10s)
```bash
time curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-15", "end_date": "2026-01-15", "processors": ["PlayerGameSummaryProcessor"], "backfill_mode": true}'
```

**Duplicate Count** (Target: 0)
```sql
SELECT COUNT(*) as duplicates
FROM (
  SELECT player_lookup, game_id, system_id, line_value, COUNT(*) as cnt
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1,2,3,4
  HAVING COUNT(*) > 1
)
```

### Cost Monitoring

**Expected Monthly Costs:**
- Grading Function: ~$5-10/month
- Phase 3 Cloud Run: ~$12-15/month (minScale=1)
- Prediction Worker: ~$20-30/month
- BigQuery: ~$50-100/month
- **Total:** ~$87-155/month

**Cost Alert Thresholds:**
- 🟢 <$200/month: Normal
- 🟡 $200-300/month: Higher than expected
- 🔴 >$300/month: Investigate immediately

**Check costs:**
```
Cloud Console > Billing > Reports
Filter by: Service, Time Range (This Month)
Group by: SKU
```

---

## 🚨 Alert Conditions

### Critical (Immediate Action)

| Alert | Threshold | Action |
|-------|-----------|--------|
| **No grading for 48+ hours** | Last graded >48h ago | Check scheduler, function, Pub/Sub |
| **Phase 3 503 errors** | Any 503 in logs | Verify minScale=1, check service |
| **Coverage <40%** | Coverage <40% for 2+ days | Check boxscores, Phase 3 health |
| **Duplicates detected** | Any duplicates in last 7 days | Verify locks, check Firestore |

### Warning (Monitor)

| Alert | Threshold | Action |
|-------|-----------|--------|
| **Coverage 40-70%** | Coverage below target | Monitor trends, check specific dates |
| **Phase 3 cost spike** | >$30/month | Check scaling, review request volume |
| **High grading latency** | Grading takes >10 min | Check data volume, timeout settings |

---

## 🔍 Troubleshooting

### Common Issues

**Problem: Low Grading Coverage**
→ See: `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md#issue-1`

**Problem: Phase 3 503 Errors**
→ See: `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md#issue-2`

**Problem: Duplicate Records**
→ See: `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md#issue-3`

**Problem: Grading Stopped**
→ See: `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md#issue-5`

### Quick Fixes

**Trigger Manual Grading:**
```bash
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-01-XX","trigger_source":"manual"}'
```

**Check Phase 3 minScale:**
```bash
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])"
# Should return: 1
```

**Force Phase 3 Processing:**
```bash
TOKEN=$(gcloud auth print-identity-token --audiences="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date":"2026-01-XX","end_date":"2026-01-XX","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}'
```

---

## 📚 Documentation Index

### Quick Guides
- **Start Here:** `docs/09-handoff/SESSION-100-START-HERE.md`
- **Monitoring Guide:** `docs/02-operations/GRADING-MONITORING-GUIDE.md`
- **Troubleshooting:** `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md`

### Recent Sessions
- **Session 99:** Phase 3 Fix (`docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md`)
- **Session 98:** Data Validation (`docs/09-handoff/SESSION-98-VALIDATION-COMPLETE.md`)
- **Session 97:** Distributed Locking (`docs/09-handoff/SESSION-97-MONITORING-COMPLETE.md`)

### Operational
- **ML Monitoring:** `docs/02-operations/ML-MONITORING-REMINDERS.md`
- **Alert Runbooks:** `docs/04-deployment/ALERT-RUNBOOKS.md`

---

## 🎯 Current Priorities

### This Week (Jan 18-24)
1. ✅ Monitor Phase 3 fix effectiveness (daily health checks)
2. ✅ Verify grading coverage improves to 70-90%
3. ✅ Ensure zero 503 errors
4. ⏳ XGBoost V1 Milestone 1 (Jan 24) - automated reminder set

### Next 30 Days
- Continue passive monitoring
- XGBoost V1 milestones (Jan 24, 31, Feb 16)
- Optional: Run staging table cleanup
- Optional: Set up Cloud Monitoring dashboard

### No Action Needed
- Distributed locking working (Session 97)
- Data quality verified clean (Session 98)
- Phase 3 fix deployed (Session 99)
- Comprehensive monitoring docs created

---

## 🔗 Quick Links

### Cloud Console
- [Cloud Functions](https://console.cloud.google.com/functions?project=nba-props-platform)
- [Cloud Run](https://console.cloud.google.com/run?project=nba-props-platform)
- [Cloud Scheduler](https://console.cloud.google.com/cloudscheduler?project=nba-props-platform)
- [BigQuery](https://console.cloud.google.com/bigquery?project=nba-props-platform)
- [Monitoring](https://console.cloud.google.com/monitoring?project=nba-props-platform)
- [Billing](https://console.cloud.google.com/billing?project=nba-props-platform)

### Services
- [Phase 3 Analytics](https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app)
- [Prediction Worker](https://prediction-worker-f7p3g7f6ya-wl.a.run.app)
- [Prediction Coordinator](https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app)

---

**Last Review:** 2026-01-18 (Session 99)
**Next Review:** 2026-01-24 (XGBoost V1 Milestone 1)
**Status:** ✅ All Systems Operational
