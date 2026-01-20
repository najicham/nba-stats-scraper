# Quick Action Checklist: 2026-01-18 Incident

**Status:** Ready for Execution
**Total Time:** 2 hours (immediate) + 12 hours (this week)
**Priority:** P1 - High

---

## ⚡ Immediate Actions (Today - 2 hours)

### ☐ Action 1: Fix Firestore Dependency (5 minutes)

**What:** Add missing `google-cloud-firestore` dependency to prediction worker

**Why:** Worker crashes with ImportError when trying to write predictions

**Commands:**
```bash
cd /home/naji/code/nba-stats-scraper

# Add dependency
echo "google-cloud-firestore==2.14.0" >> predictions/worker/requirements.txt

# Commit
git add predictions/worker/requirements.txt
git commit -m "fix(predictions): Add missing google-cloud-firestore dependency

- Fixes ImportError at worker.py:556
- Distributed lock feature from Session 92 requires Firestore
- Already present in coordinator, now added to worker
- Prevents Pub/Sub retry storms during grading

Refs: incidents/2026-01-18/INCIDENT-REPORT.md"

git push

# Deploy
cd predictions/worker
gcloud run deploy prediction-worker \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform \
  --platform=managed \
  --timeout=3600
```

**Verify:**
```bash
# Check for successful deployment
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# Monitor logs (wait 2 minutes for cold start)
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND severity>=WARNING' \
  --limit=10 \
  --format="table(timestamp,severity,textPayload)"

# Should see NO ImportError messages
```

**Success Criteria:**
- ✅ Deployment completes successfully
- ✅ No ImportError in logs
- ✅ Worker starts without crashes

**Time:** 5 minutes

---

### ☐ Action 2: Investigate Grading Accuracy (15 minutes)

**What:** Determine if 18.75% accuracy is system regression or expected variance

**Why:** Need to know if there's a real problem or just statistical noise

**Commands:**
```bash
cd /home/naji/code/nba-stats-scraper

# Create investigation query file
cat > monitoring/queries/grading_accuracy_investigation.sql << 'EOF'
-- Grading accuracy investigation for 2026-01-18

WITH grading_stats AS (
  SELECT
    game_date,
    system_id,
    COUNT(*) as total_predictions,
    SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) as correct,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 2) as accuracy_pct,
    ROUND(AVG(absolute_error), 2) as mae,
    MIN(graded_at) as first_graded,
    MAX(graded_at) as last_graded
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date = '2026-01-18'
    AND recommendation IN ('OVER', 'UNDER')
    AND graded_at IS NOT NULL
  GROUP BY game_date, system_id
),
historical_avg AS (
  SELECT
    system_id,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 2) as historical_accuracy,
    ROUND(AVG(absolute_error), 2) as historical_mae
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date BETWEEN DATE_SUB('2026-01-18', INTERVAL 14 DAY)
    AND DATE_SUB('2026-01-18', INTERVAL 1 DAY)
    AND recommendation IN ('OVER', 'UNDER')
    AND graded_at IS NOT NULL
  GROUP BY system_id
)
SELECT
  g.system_id,
  g.total_predictions,
  g.correct,
  g.accuracy_pct as today_accuracy,
  h.historical_accuracy as avg_14d_accuracy,
  ROUND(g.accuracy_pct - h.historical_accuracy, 2) as accuracy_delta,
  g.mae as today_mae,
  h.historical_mae as avg_14d_mae,
  ROUND(g.mae - h.historical_mae, 2) as mae_delta,
  g.first_graded,
  g.last_graded,
  CASE
    WHEN g.accuracy_pct < h.historical_accuracy - 10 THEN '🚨 REGRESSION'
    WHEN g.accuracy_pct < h.historical_accuracy - 5 THEN '⚠️ DEGRADED'
    WHEN g.total_predictions < 40 THEN '⚠️ SMALL SAMPLE'
    ELSE '✅ NORMAL'
  END as status
FROM grading_stats g
LEFT JOIN historical_avg h ON g.system_id = h.system_id
ORDER BY accuracy_delta ASC;
EOF

# Run investigation
bq query --use_legacy_sql=false < monitoring/queries/grading_accuracy_investigation.sql
```

**Interpret Results:**
- If status = `🚨 REGRESSION` → Investigate model drift, data quality issues
- If status = `⚠️ DEGRADED` → Monitor closely, may need model retrain
- If status = `⚠️ SMALL SAMPLE` → Expected variance, no action needed
- If status = `✅ NORMAL` → No issue, continue monitoring

**Time:** 15 minutes

---

### ☐ Action 3: Create Daily Health Check Script (30 minutes)

**What:** Automated script for daily orchestration validation

**Why:** Catch issues early instead of manual investigation

**Commands:**
```bash
cd /home/naji/code/nba-stats-scraper

# Create script
cat > scripts/daily_orchestration_check.sh << 'EOF'
#!/bin/bash
# Daily Orchestration Health Check
# Run: ./scripts/daily_orchestration_check.sh

set -e

echo "================================================================"
echo "  NBA Props Platform - Daily Orchestration Health Check"
echo "  Date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "================================================================"
echo ""

# Check 1: Predictions Generated
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. PREDICTIONS GENERATED (Last 3 Days)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT system_id) as systems,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(created_at)) as last_created,
  CASE
    WHEN COUNT(*) >= 280 AND COUNT(DISTINCT player_lookup) >= 50 THEN '✅ GOOD'
    WHEN COUNT(*) >= 200 THEN '⚠️ LOW'
    ELSE '❌ CRITICAL'
  END as status
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND is_active = TRUE
GROUP BY game_date
ORDER BY game_date DESC"

# Check 2: Phase 3 Completion
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. PHASE 3 PROCESSOR COMPLETION (Last 24 Hours)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(started_at)) as last_run,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(started_at), HOUR) as hours_ago,
  CASE
    WHEN MAX(started_at) > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) THEN '✅'
    ELSE '❌'
  END as status
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE processor_name IN (
  'player_game_summary',
  'team_defense_game_summary',
  'team_offense_game_summary',
  'upcoming_player_game_context',
  'upcoming_team_game_context'
)
GROUP BY processor_name
ORDER BY last_run DESC"

# Check 3: Grading Status
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. GRADING STATUS (Last 3 Days)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as accuracy_pct,
  ROUND(AVG(absolute_error), 2) as mae,
  CASE
    WHEN AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) >= 0.39 THEN '✅ GOOD'
    WHEN AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) >= 0.30 THEN '⚠️ LOW'
    ELSE '❌ CRITICAL'
  END as status
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND graded_at IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY game_date
ORDER BY game_date DESC"

# Check 4: Recent Errors
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. RECENT ERRORS (Last 2 Hours)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ERROR_COUNT=$(gcloud logging read 'severity>=ERROR' \
  --limit=100 \
  --format="value(timestamp)" \
  --freshness=2h 2>/dev/null | wc -l)

if [ "$ERROR_COUNT" -eq 0 ]; then
  echo "✅ No errors found in last 2 hours"
else
  echo "⚠️ Found $ERROR_COUNT errors in last 2 hours:"
  gcloud logging read 'severity>=ERROR' \
    --limit=10 \
    --format="table(timestamp,resource.labels.service_name,severity,textPayload)" \
    --freshness=2h 2>/dev/null || echo "Could not fetch error details"
fi

echo ""
echo "================================================================"
echo "  Health Check Complete"
echo "================================================================"
EOF

chmod +x scripts/daily_orchestration_check.sh

# Run immediately
./scripts/daily_orchestration_check.sh
```

**Optional: Set up daily cron job**
```bash
# Add to crontab (runs at 9 AM ET = 2 PM UTC)
(crontab -l 2>/dev/null; echo "0 14 * * * cd /home/naji/code/nba-stats-scraper && ./scripts/daily_orchestration_check.sh >> logs/daily_check.log 2>&1") | crontab -
```

**Time:** 30 minutes

---

### ☐ Action 4: Dependency Audit (30 minutes)

**What:** Scan all services for missing dependencies

**Why:** Prevent similar issues in other services

**Commands:**
```bash
cd /home/naji/code/nba-stats-scraper

# Create audit script
cat > scripts/audit_dependencies.sh << 'EOF'
#!/bin/bash
# Dependency Audit Script

echo "=== Dependency Audit ==="
echo ""

SERVICES=(
  "predictions/coordinator"
  "predictions/worker"
  "data_processors/phase2"
  "data_processors/phase3"
  "data_processors/phase4"
)

IMPORTS=(
  "google.cloud.firestore:google-cloud-firestore"
  "google.cloud.bigquery:google-cloud-bigquery"
  "google.cloud.storage:google-cloud-storage"
  "google.cloud.secretmanager:google-cloud-secret-manager"
  "google.cloud.pubsub:google-cloud-pubsub"
)

MISSING_COUNT=0

for service in "${SERVICES[@]}"; do
  echo "Checking $service..."

  if [ ! -f "$service/requirements.txt" ]; then
    echo "  ⚠️  No requirements.txt found"
    continue
  fi

  for import in "${IMPORTS[@]}"; do
    IFS=':' read -r module package <<< "$import"

    # Check if module is imported in Python files
    if find "$service" -name "*.py" -exec grep -l "from $module import\|import $module" {} \; 2>/dev/null | head -1 | grep -q .; then
      # Check if package is in requirements.txt
      if ! grep -q "$package" "$service/requirements.txt" 2>/dev/null; then
        echo "  ❌ MISSING: $package (imported but not in requirements.txt)"
        MISSING_COUNT=$((MISSING_COUNT + 1))
      fi
    fi
  done

  echo ""
done

echo "=== Audit Complete ==="
echo "Missing dependencies: $MISSING_COUNT"

if [ $MISSING_COUNT -gt 0 ]; then
  echo "⚠️  Action required: Add missing dependencies to requirements.txt"
  exit 1
else
  echo "✅ All dependencies properly declared"
  exit 0
fi
EOF

chmod +x scripts/audit_dependencies.sh

# Run audit
./scripts/audit_dependencies.sh

# If issues found, fix them before proceeding
```

**Time:** 30 minutes

---

## ✅ Immediate Actions Complete

**Before moving to Week 1 improvements, verify:**
- ☐ Firestore dependency deployed and working
- ☐ Grading accuracy investigated and understood
- ☐ Daily health check script created and tested
- ☐ Dependency audit completed

**Total Time:** ~2 hours

---

## 📅 Week 1 Improvements (This Week - 12 hours)

### ☐ Improvement 1: Critical-Path Orchestration (4 hours)

**What:** Change Phase 3→4 trigger from "all processors" to "critical processors only"

**File:** `/home/naji/code/nba-stats-scraper/shared/config/orchestration_config.py`

**Details:** See FIX-AND-ROBUSTNESS-PLAN.md → Improvement 1

**Time:** 4 hours

---

### ☐ Improvement 2: Phase 3 Retry Logic (4 hours)

**What:** Add retry logic when Phase 3 creates insufficient records

**Files:**
- `data_processors/analytics/processor_base.py`
- `data_processors/analytics/upcoming_player_game_context.py`

**Details:** See FIX-AND-ROBUSTNESS-PLAN.md → Improvement 2

**Time:** 4 hours

---

### ☐ Improvement 3: Comprehensive Alerting (4 hours)

**What:** Set up email/Slack alerts for critical failures

**Files:**
- `shared/alerting/alert_manager.py` (new)
- `shared/alerting/alert_config.py` (new)

**Details:** See FIX-AND-ROBUSTNESS-PLAN.md → Improvement 3

**Time:** 4 hours

---

## 📊 Success Metrics

After completing immediate actions, monitor these metrics daily:

**Predictions:**
- [ ] Volume ≥280 per day
- [ ] Players ≥50 per day
- [ ] Systems = 6 (all active)

**Phase 3:**
- [ ] Completion rate ≥90% (at least 4/5 processors)
- [ ] Data freshness <2 hours

**Grading:**
- [ ] Accuracy 39-50% (system average)
- [ ] Coverage ≥99%

**Errors:**
- [ ] Zero ImportError messages
- [ ] <5 errors per hour

---

## 🚨 If Something Goes Wrong

### Firestore Fix Fails
```bash
# Rollback to previous revision
gcloud run services update-traffic prediction-worker \
  --to-revisions=PREVIOUS=100 \
  --region=us-west2
```

### Grading Shows Regression
1. Check data freshness (Phase 3 timing)
2. Compare to historical morning game performance
3. Review model predictions vs actuals
4. Consider model retrain if persistent

### Daily Check Script Errors
- Verify BigQuery permissions
- Check gcloud CLI authentication
- Ensure project ID correct

---

## 📚 Reference Documents

**For Details:**
- [INCIDENT-REPORT.md](./INCIDENT-REPORT.md) - Full incident analysis
- [FIX-AND-ROBUSTNESS-PLAN.md](./FIX-AND-ROBUSTNESS-PLAN.md) - Complete implementation plan
- [EXECUTIVE-SUMMARY.md](./EXECUTIVE-SUMMARY.md) - High-level overview

**For Context:**
- [../RECURRING-ISSUES.md](../RECURRING-ISSUES.md) - Historical patterns
- [../FUTURE-IMPROVEMENTS.md](../FUTURE-IMPROVEMENTS.md) - Planned optimizations
- [../NEXT-STEPS.md](../NEXT-STEPS.md) - Long-term roadmap

---

**Checklist Created:** January 18, 2026
**Last Updated:** January 18, 2026
**Status:** Ready for Execution
**Priority:** P1 - High
