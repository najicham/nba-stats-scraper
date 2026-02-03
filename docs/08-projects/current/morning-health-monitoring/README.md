# Morning Health Monitoring Project

**Status:** 🚧 In Progress
**Created:** 2026-02-03
**Purpose:** Prevent stale service deployments through automated monitoring

---

## Problem Statement

**Stale services are a recurring issue** that has caused multiple incidents:
- Session 81-82: Phase 3 deployed with old code, usage_rate calculation broken
- Session 64: Bug fixed but not deployed for 12+ hours
- Session 80: Missing dependencies caused 38-hour outage

**Root cause:** No automated alerting when services fall out of sync with code.

---

## Solution

Created `bin/monitoring/morning_deployment_check.py` - an automated check that:
1. Compares deployment timestamps vs code change timestamps for all critical services
2. Sends Slack alerts when drift is detected
3. Can be scheduled to run every morning (6 AM ET recommended)

### Files

| File | Location | Purpose |
|------|----------|---------|
| `morning_deployment_check.py` | `bin/monitoring/` | The actual script |
| `MORNING_CHECK_SETUP.md` | This directory | Setup guide |
| `morning_deployment_check.py.example` | This directory | Reference copy |

---

## Did Stale Services Cause the Feb 2 Issues?

### Evidence Analysis

**Timeline:**
- Feb 2, 19:26 PT: Phase 3 processor deployed
- Feb 2, 19:36 PT: Code commits (execution logger fix + Phase 6 exporters)
- Feb 2, ~23:00 PT: Games finish
- Feb 3, ~00:00-05:00 PT: Overnight processing runs
- Feb 3, 00:41 PT: Validation finds 0% usage_rate

**Feb 1 vs Feb 2 Comparison:**
| Metric | Feb 1 | Feb 2 | Analysis |
|--------|-------|-------|----------|
| Usage rate coverage | 95.9% | 0% | **BROKE** between Feb 1 and Feb 2 |
| Minutes coverage | 100% | 47% | Partially explained by missing game |
| Orchestrator | 4/5 processors | No record | **BROKE** between Feb 1 and Feb 2 |

**Conclusion:** The timing strongly suggests the 19:26 Phase 3 deployment introduced a regression. However, the 19:36 commits (which weren't deployed) were for **unrelated features** (execution logger, Phase 6).

### Likely Root Causes

1. **Code in 19:26 deployment had a bug** - The usage_rate calculation or team data JOIN broke
2. **Not related to 19:36 commits** - Those were for different features
3. **Would have been caught** by morning check alerting if it existed

### Should We Have Prevented This?

**YES.** Here's what would have helped:

| Prevention Mechanism | Status | Impact |
|---------------------|--------|--------|
| Morning deployment check | ✅ Created now | Would alert before issues impact data |
| Post-deployment validation | ⚠️ Partial | Exists but didn't catch usage_rate bug |
| Automated deployment on commit | ❌ Not implemented | Would eliminate drift entirely |
| Pre-merge integration tests | ❌ Not implemented | Would catch bugs before merge |

---

## Implementation Plan

### Phase 1: Manual Checks (Complete)
- [x] Create `morning_deployment_check.py`
- [x] Document setup guide
- [ ] Add to morning workflow

### Phase 2: Scheduled Automation (Next)
- [ ] Create Cloud Function for scheduled execution
- [ ] Create Cloud Scheduler job (6 AM ET daily)
- [ ] Set up Slack webhook

### Phase 3: CI/CD Integration (Future)
- [ ] Add deployment drift check to PR workflow
- [ ] Auto-deploy on merge to main
- [ ] Block deploys if previous services are stale

---

## Quick Start

```bash
# Check deployment drift now (manual)
python bin/monitoring/morning_deployment_check.py

# Dry run (no Slack alert)
python bin/monitoring/morning_deployment_check.py --dry-run

# Test Slack webhook
export SLACK_WEBHOOK_URL_WARNING="https://hooks.slack.com/..."
python bin/monitoring/morning_deployment_check.py --slack-test
```

---

## Related

- Issue analysis: `docs/08-projects/current/feb-2-validation/`
- Deployment runbook: `docs/02-operations/runbooks/deployment-runbook.md`
- Drift check script: `bin/check-deployment-drift.sh`
