# Deployment Drift Prevention Plan

**Created:** 2026-02-05
**Author:** Session 128
**Status:** DRAFT - For Review

## Problem Statement

Deployment drift occurs when code changes are committed to the repository but not deployed to production services. This causes:
- Bug fixes that appear "fixed" but still occur in production
- Features that are merged but not actually live
- Confusion during debugging (code looks correct, but old version running)
- Degraded system performance due to missing optimizations

**Recent Examples:**
- Session 128: 3 services (phase3, coordinator, worker) were 8+ hours stale
- Session 97, 81, 82, 64: Similar drift issues caused recurring bugs

## Root Causes

1. **Manual Deployment Process:** Deployments require manual execution of `./bin/deploy-service.sh`
2. **No Drift Alerts:** No automated monitoring for deployment staleness
3. **Async Commits:** Multiple developers/sessions commit without coordinating deployments
4. **No CI/CD Automation:** No automatic deployment on merge to main
5. **Split Responsibility:** Code changes vs infrastructure changes handled separately

## Prevention Mechanisms

### Layer 1: Automated Drift Monitoring (IMMEDIATE)

**Goal:** Detect drift within 1 hour of occurrence

**Implementation:**
1. Create Cloud Scheduler job: `deployment-drift-checker`
   - Frequency: Every 2 hours (8 AM, 10 AM, 12 PM, 2 PM, 4 PM PT)
   - Action: Run `./bin/check-deployment-drift.sh`
   - Alert: Slack #nba-alerts if drift > 2 commits OR age > 6 hours

2. Cloud Function: `deployment-drift-monitor`
   ```python
   # Triggered by scheduler
   # Runs check-deployment-drift.sh logic
   # Posts to Slack with severity levels:
   #   - INFO: 1-2 commits, < 6 hours
   #   - WARNING: 3-5 commits, 6-12 hours
   #   - CRITICAL: 6+ commits, > 12 hours
   ```

3. Add to morning validation checklist (already done in Session 128)

**Files to Create:**
- `cloud_functions/deployment_drift_monitor/main.py`
- `cloud_functions/deployment_drift_monitor/requirements.txt`
- `bin/infrastructure/setup-drift-monitoring.sh`

### Layer 2: Pre-Commit Hook (MEDIUM PRIORITY)

**Goal:** Remind developers to deploy after committing

**Implementation:**
1. `.git/hooks/post-commit` hook:
   ```bash
   # After each commit, check if shared/ or service directories changed
   # Show reminder message:
   # "⚠️  You modified [service]. Remember to deploy:
   #     ./bin/deploy-service.sh [service]"
   ```

2. Make it non-blocking (reminder only, not enforcement)

**Files to Create:**
- `.githooks/post-commit` (committed to repo)
- `bin/setup-git-hooks.sh` (install script)

### Layer 3: Pre-Prediction Validation Gate (HIGH PRIORITY)

**Goal:** Block predictions from running with stale code

**Implementation:**
1. Modify `prediction-coordinator` to check drift before creating batches:
   ```python
   # In start() method:
   drift_status = check_deployment_drift()
   if drift_status['worker_commits_behind'] > 3:
       logger.error("BLOCKED: prediction-worker is 3+ commits stale")
       raise DeploymentDriftError("Deploy prediction-worker before running")
   ```

2. Add `--skip-drift-check` flag for emergencies

3. Alert to Slack when blocked

**Files to Modify:**
- `predictions/coordinator/coordinator.py`
- `shared/utils/deployment_checker.py` (new)

### Layer 4: CI/CD Auto-Deploy (ASPIRATIONAL)

**Goal:** Automatic deployment on merge to main

**Implementation:**
1. GitHub Actions workflow:
   ```yaml
   # .github/workflows/auto-deploy.yml
   on:
     push:
       branches: [main]

   jobs:
     detect-changes:
       # Detect which services changed
       # Deploy only affected services
       # Run smoke tests
       # Rollback on failure
   ```

2. Service mapping:
   - `shared/**` → Deploy all services
   - `predictions/worker/**` → Deploy prediction-worker
   - `data_processors/phase3/**` → Deploy nba-phase3-analytics-processors
   - etc.

**Benefits:**
- Zero manual intervention
- Immediate deployment after merge
- Automatic rollback on failure

**Challenges:**
- Requires robust testing
- Need safe rollback mechanism
- May deploy too frequently

**Files to Create:**
- `.github/workflows/auto-deploy.yml`
- `bin/ci/detect-changed-services.sh`
- `bin/ci/smoke-test.sh`

### Layer 5: Deployment Dashboard (NICE TO HAVE)

**Goal:** Visibility into deployment status

**Implementation:**
1. Add to admin dashboard:
   - Service deployment status table
   - "Deploy Now" buttons for each service
   - Drift timeline chart (hours stale)
   - Recent deployment history

2. Update every 5 minutes

**Files to Create:**
- `services/unified_dashboard/frontend/src/components/DeploymentStatus.tsx`
- `services/unified_dashboard/backend/api/deployment_status.py`

## Recommended Implementation Order

1. **Week 1 (Immediate):**
   - ✅ Add deployment drift check to morning validation (DONE in Session 128)
   - ⏳ Create Cloud Scheduler + Cloud Function for automated monitoring
   - ⏳ Add drift alerts to Slack #nba-alerts

2. **Week 2 (High Priority):**
   - Add pre-prediction validation gate (block stale worker)
   - Test gate with manual drift simulation
   - Document emergency bypass procedure

3. **Week 3 (Medium Priority):**
   - Create post-commit hook reminder
   - Setup deployment tracking in BigQuery table
   - Add drift metrics to weekly reports

4. **Month 2 (Aspirational):**
   - Design CI/CD auto-deploy workflow
   - Create smoke test suite
   - Pilot auto-deploy for non-critical services

## Success Metrics

**Targets (30 days after implementation):**
- Deployment drift incidents: 0 per week (vs current 1-2)
- Average drift age: < 2 hours (vs current 8+ hours)
- Time to detect drift: < 2 hours (vs current 12-24 hours)
- Manual intervention required: < 1 per week

**Monitoring:**
- Track drift incidents in `nba_orchestration.deployment_drift_log`
- Weekly Slack report: "Deployment Health Summary"
- Alert fatigue metric (false positive rate)

## Alert Thresholds

| Severity | Commits Behind | Age | Action |
|----------|----------------|-----|--------|
| ℹ️ INFO | 1-2 | < 6 hours | Slack notification |
| ⚠️ WARNING | 3-5 | 6-12 hours | Slack alert + email |
| 🔴 CRITICAL | 6+ | > 12 hours | Slack critical + block predictions |

## Rollout Plan

**Phase 1: Monitoring Only (Week 1)**
- Deploy drift monitor Cloud Function
- Observe alert volume and false positives
- Tune thresholds if needed

**Phase 2: Soft Enforcement (Week 2)**
- Add pre-prediction drift check (log warnings only)
- Collect data on would-be blocks
- Refine blocking logic

**Phase 3: Hard Enforcement (Week 3)**
- Enable blocking in pre-prediction gate
- Monitor for emergency bypass usage
- Iterate on developer experience

**Phase 4: Full Automation (Month 2)**
- Deploy CI/CD auto-deploy for pilot services
- Gradual rollout to all services
- Remove manual deployment scripts (optional)

## Related Documentation

- `bin/check-deployment-drift.sh` - Current drift detection script
- `docs/09-handoff/2026-02-05-SESSION-128-HANDOFF.md` - This session's findings
- `docs/02-operations/session-learnings.md` - Historical drift incidents
- CLAUDE.md (ENDSESSION section) - Deployment checklist

## Open Questions

1. Should we auto-deploy on every commit or only on tagged releases?
2. What's the emergency bypass procedure if gate blocks critical predictions?
3. How to handle shared/ changes that affect multiple services?
4. Should we batch deployments (e.g., deploy all at 9 AM daily)?

## Next Steps

- [ ] Review this plan with team
- [ ] Prioritize which layers to implement first
- [ ] Create GitHub issues for each layer
- [ ] Assign owners for implementation
- [ ] Set target dates for each phase
