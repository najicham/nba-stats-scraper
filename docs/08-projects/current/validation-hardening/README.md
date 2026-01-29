# Validation Hardening Project

**Project Status:** ✅ Complete
**Completion Date:** 2026-01-28
**Session:** Session 8, Workstream 1

## Overview

This project hardens the daily validation system to catch issues BEFORE they become problems. The goal is to eliminate manual morning validation by providing automated alerts and fast health dashboards.

## Problem Statement

**Before this project:**
- User manually ran validation every morning to discover overnight issues
- No pre-flight checks before games started
- Issues like 63% minutes coverage were not caught as CRITICAL
- No automated Slack alerts for failures
- Validation took too long (> 60 seconds)

**After this project:**
- Morning health dashboard shows overnight status in < 30 seconds
- Pre-flight checks verify data readiness at 5 PM before games
- CRITICAL thresholds properly detect severe issues
- Automatic Slack alerts to #app-error-alerts for critical failures
- Clear action items when issues are detected

## Deliverables

### 1. Morning Health Dashboard
**File:** `bin/monitoring/morning_health_check.sh`

Fast health check script that runs in < 30 seconds and provides clear status overview.

**Features:**
- Single comprehensive BigQuery query for all phase data
- Color-coded output (green/yellow/red)
- Phase 3 completion check (must be 5/5 processors)
- Stuck phase detection
- Recent error summary
- Actionable recommendations when issues found

**Usage:**
```bash
# Run for yesterday's games (default)
./bin/monitoring/morning_health_check.sh

# Run for specific date
./bin/monitoring/morning_health_check.sh 2026-01-27
```

**Output Example:**
```
================================================
Morning Health Check - 2026-01-28
Validating data for games on: 2026-01-27
================================================

[1] OVERNIGHT PROCESSING SUMMARY
  Games Processed: 7
  Player Records: 239

  Phase 3 (Analytics):
    - Minutes coverage: ❌ 63.2% (CRITICAL)
    - Usage rate coverage: ❌ 60.7% (CRITICAL)
  Phase 4 (Features): ✅ 236 features
  Phase 5 (Predictions): ✅ 697 predictions

[2] PHASE 3 PROCESSOR COMPLETION
  ❌ Processors: 2/5 complete (CRITICAL)
  ❌ Phase 4 triggered: not_triggered
     Missing: team_offense_game_summary, team_defense_game_summary, upcoming_team_game_context

[3] STUCK PHASE DETECTION
  ✅ No stuck phases detected

[4] RECENT ERRORS (Last 2h)
  ✅ No errors in last 2 hours

================================================
SUMMARY
================================================
❌ 2 critical issue(s) detected - immediate action required

Recommended actions:
  1. Run full validation: python scripts/validate_tonight_data.py --date 2026-01-27
  2. Check Cloud Run logs for failed processors
  3. Review handoff docs: docs/09-handoff/
```

### 2. Pre-Flight Validation Mode
**File:** `scripts/validate_tonight_data.py`
**Enhancement:** Added `--pre-flight` flag

Validates data readiness before games start (recommended: 5 PM ET).

**Checks:**
- Betting data loaded (props and lines)
- Game context ready for all scheduled games
- ML features generated for tonight's players
- Prediction worker health

**Usage:**
```bash
# Run pre-flight checks for tonight
python scripts/validate_tonight_data.py --pre-flight

# Run pre-flight checks for specific date
python scripts/validate_tonight_data.py --pre-flight --date 2026-01-28
```

**Exit Codes:**
- `0` = All pre-flight checks passed
- `1` = At least one issue found (check output)

### 3. Enhanced Slack Alerting
**File:** `orchestration/cloud_functions/daily_health_check/main.py`
**Enhancement:** Multi-channel routing based on severity

**Alert Routing:**
- **CRITICAL issues** → `#app-error-alerts` (SLACK_WEBHOOK_URL_ERROR)
  - Includes specific error details
  - Clear action items
  - Red alert formatting

- **WARNING issues** → `#nba-alerts` (SLACK_WEBHOOK_URL_WARNING)
  - Non-critical but needs attention
  - Yellow warning formatting

- **Daily summary** → `#daily-orchestration` (SLACK_WEBHOOK_URL)
  - All checks with pass/warn/fail/critical counts
  - Sent every morning at 8 AM ET

**Example Critical Alert:**
```
🚨 CRITICAL: Daily Health Check Failed

2 critical issue(s) detected

🚨 BigQuery Quota: nba_orchestration.run_history: 1425/1500 (95%) - QUOTA EXHAUSTION IMMINENT
🚨 Phase 3→4 (2026-01-27): Phase 3 complete but Phase 4 never triggered

Recommended Actions:
• Run morning health check: ./bin/monitoring/morning_health_check.sh
• Check Cloud Run logs for failed services
• Review recent handoff docs
```

### 4. Updated Documentation
**File:** `.claude/skills/validate-daily/SKILL.md`
**Enhancement:** Added morning workflow section

Documents recommended morning validation workflow:
1. Start with fast morning dashboard
2. Run full validation if issues detected
3. Use pre-flight checks before games

## Key Improvements

### Better Thresholds
**Before:** Single threshold for all metrics
**After:** Two-level thresholds (WARNING/CRITICAL)

| Metric | Good | WARNING | CRITICAL |
|--------|------|---------|----------|
| Minutes Coverage | ≥90% | 80-89% | <80% |
| Usage Rate Coverage | ≥90% | 80-89% | <80% |
| Phase 3 Completion | 5/5 | 3-4/5 | 0-2/5 |

**Example:** 63% minutes coverage is now correctly flagged as CRITICAL (not just low).

### Faster Validation
**Before:** Multiple queries, sequential checks, > 60 seconds
**After:** Single comprehensive query, parallel checks, < 30 seconds

**Performance:**
- Overnight summary: 1 query instead of 4
- Phase checks: Combined into single Python execution
- Total time: ~25-30 seconds (50% reduction)

### Proactive Detection
**Before:** Reactive - run validation after problems occur
**After:** Proactive - catch issues before games start

**Timeline:**
- **5 PM ET:** Pre-flight checks verify data readiness
- **7-11 PM ET:** Games are played
- **6 AM ET (next day):** Morning dashboard shows overnight health
- **8 AM ET:** Automated Slack alerts if issues detected

## Testing Results

Tested against recent data to verify issue detection:

### Test 1: 2026-01-27 Data (Known Issues)
**Expected:** Should detect 63% minutes coverage as CRITICAL
```bash
$ ./bin/monitoring/morning_health_check.sh 2026-01-27
```

**Result:** ✅ PASS
- Correctly flagged 63.2% minutes coverage as CRITICAL
- Correctly flagged 60.7% usage rate coverage as CRITICAL
- Exit code 1 (indicating issues found)

### Test 2: Pre-Flight Mode
**Expected:** Should validate data readiness for tonight
```bash
$ python scripts/validate_tonight_data.py --pre-flight
```

**Result:** ✅ PASS
- Checked betting data (props and lines)
- Checked game context for all 9 games
- Checked ML features (305 features ready)
- Checked prediction worker health
- Exit code 0 (ready for games)

### Test 3: Slack Alerting
**Expected:** Cloud Function should route alerts correctly
**Result:** ✅ PASS (verified code, not deployed yet)
- CRITICAL issues routed to #app-error-alerts
- WARNINGS routed to #nba-alerts
- Daily summary to #daily-orchestration

## Files Modified

| File | Type | Changes |
|------|------|---------|
| `bin/monitoring/morning_health_check.sh` | NEW | Fast morning dashboard script |
| `scripts/validate_tonight_data.py` | MODIFIED | Added --pre-flight flag and run_preflight_checks() |
| `orchestration/cloud_functions/daily_health_check/main.py` | MODIFIED | Multi-channel Slack alerting |
| `.claude/skills/validate-daily/SKILL.md` | MODIFIED | Added morning workflow documentation |

## Usage Guide

### Daily Morning Workflow

**Recommended approach:**

```bash
# 1. Quick health check (< 30 seconds)
./bin/monitoring/morning_health_check.sh

# 2. If issues detected, run full validation
python scripts/validate_tonight_data.py --date $(date -d "yesterday" +%Y-%m-%d)

# 3. Check Cloud Run logs for specific failures
gcloud run services logs read SERVICE_NAME --limit=50
```

### Pre-Game Workflow (5 PM ET)

**Before games start:**

```bash
# 1. Run pre-flight checks
python scripts/validate_tonight_data.py --pre-flight

# 2. If betting data missing, check workflow schedule
gcloud scheduler jobs describe betting-data-workflow

# 3. If game context missing, check Phase 2 completion
```

### When Alerts Fire

**If you receive a Slack alert in #app-error-alerts:**

1. **Read the alert** - specific issue and recommended actions
2. **Run morning dashboard** - get full context
3. **Check Cloud Run logs** - identify root cause
4. **Review handoff docs** - check for known issues
5. **Fix and verify** - run validation to confirm fix

## Integration Points

### Automated Scheduling

The Cloud Function `daily_health_check` is triggered by Cloud Scheduler:
- **Trigger:** Every morning at 8 AM ET
- **Action:** Runs all health checks
- **Alerts:** Sends to Slack based on results

**To manually trigger:**
```bash
curl -X POST https://daily-health-check-XXXXX.cloudfunctions.net/daily_health_check
```

### Environment Variables

Required Slack webhook URLs:
- `SLACK_WEBHOOK_URL` - #daily-orchestration (primary)
- `SLACK_WEBHOOK_URL_ERROR` - #app-error-alerts (critical)
- `SLACK_WEBHOOK_URL_WARNING` - #nba-alerts (warnings)

**Set in Cloud Function environment:**
```bash
gcloud functions deploy daily_health_check \
  --set-env-vars SLACK_WEBHOOK_URL=$PRIMARY_WEBHOOK,SLACK_WEBHOOK_URL_ERROR=$ERROR_WEBHOOK
```

## Lessons Learned

### What Worked Well
1. **Single comprehensive query** - Faster than multiple queries
2. **Color-coded output** - Easy to spot issues at a glance
3. **Two-level thresholds** - Better severity classification
4. **Pre-flight checks** - Catches issues before games start

### What to Improve
1. **Firestore error handling** - Need better fallbacks when tables missing
2. **Timeout handling** - Prediction worker checks can be slow
3. **Historical tracking** - Store validation results in BigQuery for trends
4. **Auto-remediation** - Automatically trigger fixes for common issues

## Next Steps

### Short Term (This Week)
- [ ] Deploy enhanced Cloud Function with Slack alerting
- [ ] Set up Cloud Scheduler trigger for morning dashboard
- [ ] Test Slack alerts in production
- [ ] Update runbooks with new workflow

### Medium Term (This Month)
- [ ] Add validation result tracking to BigQuery
- [ ] Create dashboard in Looker Studio for trends
- [ ] Add auto-remediation for quota issues
- [ ] Implement pre-flight checks as scheduled job

### Long Term (Next Quarter)
- [ ] Machine learning for anomaly detection
- [ ] Predictive alerts (catch issues before they happen)
- [ ] Integration with PagerDuty for on-call
- [ ] Self-healing for common failure patterns

## References

- **Handoff Document:** `docs/09-handoff/2026-01-28-SESSION-8-WORKSTREAM-1-VALIDATION.md`
- **SKILL Documentation:** `.claude/skills/validate-daily/SKILL.md`
- **Slack Channels:** `shared/utils/slack_channels.py`
- **Validation Script:** `scripts/validate_tonight_data.py`
- **Health Check Script:** `bin/monitoring/morning_health_check.sh`

## Success Metrics

**How we'll measure success:**

1. **Time to detect issues:** < 30 seconds (from manual 60+ seconds)
2. **False positive rate:** < 5% (graceful handling of edge cases)
3. **Manual validation runs:** Reduce from 7/week to 1/week
4. **Issue detection rate:** Catch 95%+ of issues before impact
5. **Mean time to awareness:** < 15 minutes (via Slack alerts)

**Current Status (2026-01-28):**
- ✅ Time to detect: 25-30 seconds (target: < 30s)
- ✅ Scripts implemented and tested
- ⏳ Slack alerts ready for deployment
- ⏳ Production validation pending

## Contributors

- **Claude Sonnet 4.5** - Implementation and documentation
- **User** - Requirements and testing

---

**Last Updated:** 2026-01-28
**Status:** Complete - Ready for deployment
