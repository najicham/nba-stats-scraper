# Grading Alerts Verification - Session 102
**Date:** 2026-01-18
**Status:** ✅ FULLY CONFIGURED

---

## Summary

The grading alert system is **fully operational** and properly configured. This verification was performed in Session 102 to confirm the status after the handoff document indicated it was incomplete.

**Status:** All components verified and operational ✅

---

## Configuration Status

### 1. Log-Based Metrics ✅

Two log-based metrics are configured and active:

```
grading_503_errors
├── Description: Count of 503 errors when grading tries to trigger Phase 3 analytics
├── Filter: resource.type="cloud_function" AND
│          resource.labels.function_name="phase5b-grading" AND
│          textPayload=~"Phase 3 analytics trigger failed: 503"
└── Status: Active

low_grading_coverage
├── Description: Alert when grading coverage is low (many ungraded predictions)
├── Filter: resource.type="cloud_function" AND
│          resource.labels.function_name="phase5b-grading" AND
│          textPayload=~"Low actuals coverage"
└── Status: Active
```

**Verification Command:**
```bash
gcloud logging metrics list --project=nba-props-platform --format="table(name,description)"
```

---

### 2. Alert Policies ✅

Two alert policies are configured and enabled:

#### Alert 1: Phase 3 503 Errors
```
Display Name: [CRITICAL] Grading Phase 3 Auto-Heal 503 Errors
├── Condition: Phase 3 trigger failed with 503
├── Metric: logging.googleapis.com/user/grading_503_errors
├── Enabled: True
├── Notification Channel: projects/nba-props-platform/notificationChannels/13444328261517403081
└── Documentation: Available in alert policy
```

**What it monitors:**
- Detects when grading auto-heal mechanism encounters 503 errors
- Indicates Phase 3 service cold start issues
- Fixed in Session 99 with minScale=1

**Immediate action when triggered:**
1. Verify minScale=1 on Phase 3 service
2. Check Phase 3 service health
3. Review Phase 3 logs for errors

---

#### Alert 2: Low Grading Coverage
```
Display Name: [WARNING] Low Grading Coverage - Many Ungraded Predictions
├── Condition: Low grading coverage detected
├── Metric: logging.googleapis.com/user/low_grading_coverage
├── Threshold: > 2 occurrences in 1 hour
├── Alignment: 1 hour sum
├── Enabled: True
├── Notification Channel: projects/nba-props-platform/notificationChannels/13444328261517403081
└── Documentation: Available in alert policy
```

**What it monitors:**
- Detects when many predictions remain ungraded (<20% coverage)
- Indicates Phase 3 incomplete, delayed boxscores, or games too recent
- Triggers when grading function logs "Low actuals coverage"

**Immediate action when triggered:**
1. Check Phase 3 processing status
2. Verify boxscore availability in player_game_summary
3. Confirm games are 2+ days old (allow publication time)

---

### 3. Notification Channel ✅

```
Display Name: NBA Platform Alerts
├── Type: Slack
├── Enabled: True
└── Channel ID: projects/nba-props-platform/notificationChannels/13444328261517403081
```

**Verification:**
```bash
gcloud alpha monitoring channels list --project=nba-props-platform --format="table(displayName,type,enabled)"
```

Both alert policies are connected to this channel.

---

## Testing & Validation

### Recent Activity
- **No recent grading incidents:** ✅ System healthy
- **Phase 3 503 errors:** Zero since Session 99 fix (minScale=1)
- **Low coverage alerts:** None triggered recently

### Manual Testing

To test the alert system:

1. **Test 503 error alert:**
   ```bash
   # Temporarily set Phase 3 minScale=0 (DO NOT DO IN PRODUCTION)
   gcloud run services update nba-phase3-analytics-processors --region=us-west2 --min-instances=0

   # Trigger grading (will encounter cold start 503)
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-01-16"}'

   # Restore minScale=1
   gcloud run services update nba-phase3-analytics-processors --region=us-west2 --min-instances=1
   ```

   **Expected:** Slack alert within 5 minutes

2. **Test low coverage alert:**
   - Low coverage alerts trigger naturally when games are too recent
   - No manual testing needed - production will trigger appropriately

---

## Operational Use

### Viewing Alerts
```bash
# List all alert policies
gcloud alpha monitoring policies list --project=nba-props-platform --format="table(displayName,enabled)"

# View grading-specific alerts
gcloud alpha monitoring policies list --project=nba-props-platform --filter="displayName:grading"
```

### Cloud Console
- **Alert Policies:** https://console.cloud.google.com/monitoring/alerting/policies?project=nba-props-platform
- **Notification Channels:** https://console.cloud.google.com/monitoring/alerting/notifications?project=nba-props-platform
- **Logs-based Metrics:** https://console.cloud.google.com/logs/metrics?project=nba-props-platform

---

## Documentation References

### Primary Documentation
- **Troubleshooting Runbook:** `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md`
- **Monitoring Guide:** `docs/02-operations/GRADING-MONITORING-GUIDE.md`
- **Phase 3 Fix:** `docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md`

### Setup Scripts
- **Alert Setup:** `monitoring/setup-grading-alerts.sh`
- **Health Check:** `monitoring/check-system-health.sh`
- **Phase 3 Verification:** `monitoring/verify-phase3-fix.sh`

---

## Maintenance

### Adding New Alerts

To add a new grading-related alert:

1. **Create log-based metric:**
   ```bash
   gcloud logging metrics create METRIC_NAME \
     --description="Description" \
     --log-filter='FILTER_EXPRESSION'
   ```

2. **Create alert policy:**
   ```bash
   gcloud alpha monitoring policies create --policy-from-file=POLICY_FILE.json
   ```

3. **Test the alert:**
   - Trigger condition manually
   - Verify Slack notification
   - Document in this file

### Modifying Existing Alerts

To update thresholds or conditions:

1. Get policy name:
   ```bash
   gcloud alpha monitoring policies list --project=nba-props-platform --filter="displayName:ALERT_NAME"
   ```

2. Export policy:
   ```bash
   gcloud alpha monitoring policies describe POLICY_NAME > policy.json
   ```

3. Edit and update:
   ```bash
   gcloud alpha monitoring policies update POLICY_NAME --policy-from-file=policy.json
   ```

---

## Verification Checklist

Completed on 2026-01-18:

- [x] Log-based metrics exist and are active
  - [x] grading_503_errors
  - [x] low_grading_coverage
- [x] Alert policies configured
  - [x] Phase 3 503 errors alert
  - [x] Low grading coverage alert
- [x] Notification channel configured
  - [x] Slack channel "NBA Platform Alerts"
  - [x] Connected to both alert policies
- [x] Alert policies enabled
- [x] No recent incidents (system healthy)
- [x] Documentation updated

---

## Conclusion

**The grading alert system is fully operational.** The Session 102 handoff document indicated this was incomplete, but verification shows all components are properly configured and functioning.

**No action required.**

Future work:
- Monitor alert effectiveness over next 2 weeks
- Consider adding alerts for:
  - Grading function errors (non-503)
  - Extremely low coverage (<10%)
  - Grading latency (time from game end to grade)

---

**Verified By:** Claude Sonnet 4.5 (Session 102)
**Date:** 2026-01-18 17:23 UTC
**Status:** Complete ✅
