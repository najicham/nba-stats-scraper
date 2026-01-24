# NBA Data Pipeline - Quick Reference Card
**Last Updated**: 2026-01-20 | **Branch**: week-0-security-fixes

## 🚨 **Daily Health Check** (2 minutes)

```bash
# 1. Check yesterday's pipeline health
YESTERDAY=$(date -d 'yesterday' +%Y-%m-%d)
python scripts/smoke_test.py $YESTERDAY --verbose

# 2. Check for circuit breaker blocks (last 24h)
gcloud functions logs read phase3-to-phase4-orchestrator --region us-west2 --limit=100 | grep "BLOCK"
gcloud functions logs read phase4-to-phase5-orchestrator --region us-west2 --limit=100 | grep "Circuit Breaker"

# 3. Check Slack monitoring-error channel for alerts
```

**Good = All phases PASS, no circuit breaker blocks, no Slack alerts**

---

## 📊 **Quick Validation Commands**

### Smoke Test (Fast - 1s per date)
```bash
# Single date
python scripts/smoke_test.py 2026-01-20

# Date range (100 dates in <10 seconds)
python scripts/smoke_test.py 2026-01-10 2026-01-20

# Verbose output with details
python scripts/smoke_test.py 2026-01-20 --verbose
```

### Historical Season Validation
```bash
# Validate last 30 days
python scripts/validate_historical_season.py --start 2025-12-21 --end 2026-01-20

# Generate CSV report
python scripts/validate_historical_season.py --start 2025-12-01 --end 2026-01-20 --output /tmp/report.csv
```

---

## 🔧 **Common Troubleshooting**

### "Phase 4 BLOCKED" Alert
**Cause**: Phase 3 analytics incomplete for game date

**Fix**:
```bash
# 1. Check what's missing
python scripts/smoke_test.py <GAME_DATE> --verbose

# 2. Manually trigger Phase 3
# (See "Manual Triggers" section below)

# 3. Verify Phase 3 completion
gcloud firestore documents get --collection=phase3_completion --document=<GAME_DATE>
```

### "Circuit Breaker TRIPPED" Alert
**Cause**: <3/5 Phase 4 processors or missing critical tables (PDC, MLFS)

**Fix**:
```bash
# 1. Check Phase 4 status
python scripts/smoke_test.py <GAME_DATE> --verbose

# 2. Check which processors failed
gcloud run services logs read nba-phase4-precompute-processors --region=us-west1 --limit=100

# 3. Manually trigger Phase 4
# (See "Manual Triggers" section below)
```

### Self-Heal Didn't Run
**Cause**: Transient errors (should now auto-retry)

**Check logs**:
```bash
gcloud functions logs read self-heal-pipeline --region us-west2 --limit=50 | grep -i "retry\|error"
```

**Manual trigger**:
```bash
gcloud functions call self-heal-pipeline --region us-west2 --data '{}'
```

---

## 🎯 **Manual Triggers** (Emergency)

### Trigger Phase 3 Analytics
```bash
# Call Phase 3 service directly
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-20", "end_date": "2026-01-20", "backfill_mode": false}' \
  https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range
```

### Trigger Phase 4 Precompute
```bash
# Call Phase 4 service directly
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-01-20", "processors": [], "strict_mode": false}' \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date
```

### Trigger Predictions
```bash
# Call prediction coordinator directly
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-20"}' \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start
```

---

## 📈 **Monitoring Dashboards**

### Cloud Console
- **Pipeline Health**: [Link to nba_data_pipeline_health_dashboard]
- **Pub/Sub**: Monitor DLQ depth at [Pub/Sub Console](https://console.cloud.google.com/cloudpubsub)
- **Cloud Functions**: [Functions Console](https://console.cloud.google.com/functions)

### Firestore Collections
- **Phase 3 Completion**: `phase3_completion/{game_date}`
- **Phase 4 Completion**: `phase4_completion/{game_date}`
- **Run History**: `run_history` (processor execution logs)

### Key Metrics to Watch
- **Circuit breaker blocks/day**: Should be near zero
- **DLQ message count**: Should be < 50 (yellow), < 100 (red)
- **Self-heal success rate**: Should be > 95%
- **Phase 4 pass rate**: Should be 100% (after scheduler timeout fix)

---

## 🛡️ **What's Protected Now**

### ✅ BDL Scraper
- **File**: `scrapers/balldontlie/bdl_box_scores.py`
- **Protection**: 5 retries with 60s-1800s backoff
- **Impact**: Prevents 40% of weekly failures

### ✅ Phase 3→4 Validation Gate
- **File**: `orchestration/cloud_functions/phase3_to_phase4/main.py`
- **Protection**: Blocks Phase 4 if Phase 3 incomplete
- **Impact**: Prevents 20-30% of cascade failures

### ✅ Phase 4→5 Circuit Breaker
- **File**: `orchestration/cloud_functions/phase4_to_phase5/main.py`
- **Protection**: Requires ≥3/5 processors + both critical (PDC, MLFS)
- **Impact**: Prevents 10-15% of poor-quality predictions

### ✅ Self-Heal Retry Logic **NEW**
- **File**: `orchestration/cloud_functions/self_heal/main.py`
- **Protection**: 3 retries with 2-30s backoff on all HTTP triggers
- **Impact**: Prevents complete self-heal failure on transient errors

### ✅ Pub/Sub ACK Verification **NEW**
- **Files**: Both orchestrator main.py files
- **Protection**: Exceptions re-raised to NACK failed messages
- **Impact**: **ELIMINATES silent multi-day failures (ROOT CAUSE FIX)**

---

## 🚀 **Deployment Commands**

### Deploy Orchestrators
```bash
# Phase 3→4
./bin/orchestrators/deploy_phase3_to_phase4.sh

# Phase 4→5
./bin/orchestrators/deploy_phase4_to_phase5.sh

# Self-heal
./bin/deploy/deploy_self_heal_function.sh

# Verify all active
gcloud functions list --region us-west2 --filter="state:ACTIVE" --format="table(name,state,updateTime)"
```

### Deploy Scrapers
```bash
# BDL scraper (with retry logic)
gcloud run deploy nba-scrapers --source . --region us-west1
```

---

## 📞 **Emergency Contacts**

### If Pipeline Completely Down
1. Check Slack #monitoring-error for alerts
2. Run smoke test to identify failure point
3. Check Cloud Function logs for exceptions
4. Manually trigger failed phase (see Manual Triggers)
5. If still stuck, check DLQ for stuck messages

### If Predictions Missing
1. Check Phase 4→5 circuit breaker didn't trip
2. Verify Phase 4 completion: `python scripts/smoke_test.py <DATE> --verbose`
3. Check prediction coordinator logs
4. Manually trigger predictions if safe

### If Data Quality Issues
1. **Don't immediately backfill** - investigate first
2. Check which phase failed using smoke test
3. Review orchestrator logs for circuit breaker blocks
4. Fix root cause before backfilling
5. Validate backfill with smoke test

---

## 🔑 **Success Thresholds**

### Phase-by-Phase
| Phase | Threshold | Excellent | Poor |
|-------|-----------|-----------|------|
| Phase 2 | ≥70% game coverage | ≥90% | <50% |
| Phase 3 | All 5 tables present | All complete | Any missing |
| Phase 4 | ≥3/5 processors | 5/5 + both critical | <3/5 or missing PDC/MLFS |
| Phase 5 | Predictions exist | MAE <6 | MAE >8 |
| Phase 6 | ≥80% grading | ≥95% | <60% |

### Overall Health Score
- **🟢 ≥85%**: EXCELLENT - No action needed
- **🟡 70-84%**: ACCEPTABLE - Minor gaps okay
- **🟠 50-69%**: NEEDS REVIEW - Investigate failures
- **🔴 <50%**: FAILED - Immediate intervention required

---

## 💡 **Pro Tips**

### Daily Routine (Start of Day)
1. Run smoke test for yesterday
2. Check Slack monitoring-error for overnight alerts
3. Glance at dashboard for unusual patterns
4. If issues found, investigate before they cascade

### Weekly Maintenance
1. Review DLQ for stuck messages (should be empty)
2. Check circuit breaker block count (should be near zero)
3. Validate last 7 days with smoke test
4. Review self-heal success rate

### Before Major Changes
1. Take snapshot of last 30 days health (smoke test)
2. Document current pass rates
3. Deploy to dev/staging first
4. Validate with smoke test immediately after deploy
5. Monitor for 24 hours before considering stable

---

**For detailed documentation**:
- Implementation: `docs/08-projects/current/week-0-deployment/`
- Operations: `docs/02-operations/MONITORING-QUICK-REFERENCE.md`
- Root Cause Analysis: `docs/08-projects/current/week-0-deployment/PDC-INVESTIGATION-FINDINGS-JAN-20.md`

**Questions?** Check the comprehensive handoff docs or executive summary.
