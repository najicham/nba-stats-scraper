# Deployment History Log

Track all production deployments here for audit and troubleshooting purposes.

**Instructions:**
1. Copy the template section below for each deployment
2. Fill in all fields
3. Keep in reverse chronological order (newest first)

---

## Template (Copy This)

```markdown
### [YYYY-MM-DD HH:MM] - [Service Name]

**Deployed By:** [Your Name/Email]
**Commit SHA:** [git commit SHA]
**Branch:** [branch name]
**Environment:** [prod/dev/staging]

**Reason for Deployment:**
- [Describe why this deployment is needed]
- [List features, fixes, or improvements]

**Files Changed:**
- `path/to/file1.py` - [brief description]
- `path/to/file2.py` - [brief description]

**Pre-Deployment Checks:**
- [ ] Tests passing locally
- [ ] Code reviewed
- [ ] Backup plan documented
- [ ] Stakeholders notified

**Deployment Method:**
- [ ] Quick script (`./scripts/deploy/deploy-*.sh`)
- [ ] Full script (`./bin/*/deploy/*.sh`)
- [ ] Manual gcloud commands

**Deployment Duration:** [X minutes]

**Post-Deployment Verification:**
- [ ] Service status healthy (green ✔)
- [ ] Health endpoint returns 200 OK
- [ ] Logs show no errors
- [ ] Functionality test passed
- [ ] Metrics normal

**Issues Encountered:**
- [None / List any issues]

**Rollback Required:** [Yes/No]
[If yes, explain reason and rollback procedure used]

**Notes:**
- [Any additional notes for future reference]

---
```

---

## Deployment History

### 2026-01-27 16:11 - nba-phase3-analytics-processors

**Deployed By:** Claude Sonnet 4.5 / nchammas@gmail.com
**Commit SHA:** 075fab1e
**Branch:** main
**Environment:** prod

**Reason for Deployment:**
- Deploy 3 critical analytics fixes that were committed but not yet deployed
- Fix: Re-trigger upcoming_player_game_context when betting lines arrive (3d77ecaa)
- Fix: Add team stats availability check to prevent NULL usage_rate (3c1b8fdb)
- Fix: Prevent duplicate records via streaming buffer handling and pre-save dedup (217c5541)

**Files Changed:**
- Multiple analytics processor files related to the 3 fixes above
- Changes span upstream_player_game_context, team stats validation, and duplicate prevention

**Pre-Deployment Checks:**
- [x] Tests passing locally
- [x] Code reviewed
- [x] Backup plan documented (rollback procedure available)
- [x] Stakeholders notified (via deployment runbook)

**Deployment Method:**
- [x] Manual gcloud commands (following DEPLOYMENT.md runbook)

**Deployment Duration:** ~11 minutes

**Post-Deployment Verification:**
- [x] Service status healthy (green checkmark)
- [x] Health endpoint returns 200 OK: {"service":"analytics-processor","status":"healthy"}
- [x] Logs reviewed (expected scraper trigger errors present, no deployment errors)
- [x] New revision deployed: nba-phase3-analytics-processors-00125-42w
- [x] Commit SHA verified: 075fab1e
- [x] Environment variables set correctly

**Issues Encountered:**
- None - deployment completed successfully
- Expected errors in logs related to missing nba-scraper-trigger resource (pre-existing issue)

**Rollback Required:** No

**Notes:**
- Previous revision: nba-phase3-analytics-processors-00124-hfl
- New revision: nba-phase3-analytics-processors-00125-42w
- All 3 pending fixes from notes in previous deployment are now deployed
- Service configuration: 8Gi memory, 4 CPU, 3600s timeout, concurrency=1
- Deployment used source deploy method with Artifact Registry
- This deployment includes all commits up to 075fab1e including the 3 specific fixes

---

### 2026-01-27 22:39 - nba-phase3-analytics-processors

**Deployed By:** nchammas@gmail.com
**Commit SHA:** fa4d51ff
**Branch:** main
**Environment:** prod

**Reason for Deployment:**
- Fix: analytics-dockerfile
- Update analytics processor Dockerfile structure

**Files Changed:**
- `docker/analytics-processor.Dockerfile` - Dockerfile structure update

**Pre-Deployment Checks:**
- [x] Tests passing locally
- [x] Code reviewed
- [x] Backup plan documented
- [x] Stakeholders notified

**Deployment Method:**
- [x] Full script (`./bin/analytics/deploy/deploy_analytics_processors.sh`)

**Deployment Duration:** ~5 minutes

**Post-Deployment Verification:**
- [!] Service status showing warning (yellow !)
- [ ] Health endpoint returns 200 OK
- [ ] Logs show no errors
- [ ] Functionality test passed
- [ ] Metrics normal

**Issues Encountered:**
- Service showing yellow warning icon
- Need to investigate health check status

**Rollback Required:** No (pending verification)

**Notes:**
- Last analytics deployment was 8 days prior
- 3 pending fixes not yet deployed:
  - 3d77ecaa - Re-trigger upcoming_player_game_context when betting lines arrive
  - 3c1b8fdb - Add team stats availability check to prevent NULL usage_rate
  - 217c5541 - Prevent duplicate records via streaming buffer handling

---

### 2026-01-27 19:41 - nba-phase3-analytics-processors

**Deployed By:** nchammas@gmail.com
**Commit SHA:** [unknown]
**Branch:** main
**Environment:** prod

**Reason for Deployment:**
- Routine update to analytics processors

**Post-Deployment Verification:**
- [x] Service status healthy (green ✔)

**Notes:**
- Previous deployment before warning status appeared
- Working correctly at time of deployment

---

### 2026-01-27 04:30 - nba-phase4-precompute-processors

**Deployed By:** nchammas@gmail.com
**Commit SHA:** [unknown]
**Branch:** main
**Environment:** prod

**Reason for Deployment:**
- Precompute processor updates

**Post-Deployment Verification:**
- [x] Service status healthy (green ✔)

**Notes:**
- Deployed successfully

---

### 2026-01-27 03:26 - nba-phase2-raw-processors

**Deployed By:** nchammas@gmail.com
**Commit SHA:** [unknown]
**Branch:** main
**Environment:** prod

**Reason for Deployment:**
- Raw processor updates

**Post-Deployment Verification:**
- [x] Service status healthy (green ✔)

**Notes:**
- Deployed successfully

---

### 2026-01-25 21:00 - prediction-coordinator

**Deployed By:** nchammas@gmail.com
**Commit SHA:** 2de48c04
**Branch:** main
**Environment:** prod

**Reason for Deployment:**
- Prediction coordinator improvements

**Files Changed:**
- [To be documented from git log]

**Post-Deployment Verification:**
- [x] Service status healthy (green ✔)

**Notes:**
- Deployed successfully
- Dev environment also updated (prediction-coordinator-dev)

---

## Statistics

**Total Deployments This Month:** [Count]
**Success Rate:** [X%]
**Average Deployment Time:** [X minutes]
**Rollbacks Required:** [Count]

**Most Frequently Deployed:**
1. nba-phase3-analytics-processors: [X times]
2. prediction-coordinator: [X times]
3. nba-phase2-raw-processors: [X times]

---

## Lessons Learned

### January 2026

**What Went Well:**
- [To be filled in at end of month]

**What Needs Improvement:**
- [To be filled in at end of month]

**Action Items:**
- [To be filled in at end of month]

---

## Archive

Older deployments (>3 months) should be moved to:
`/docs/02-operations/deployment-history/YYYY-MM.md`

---

**Last Updated:** 2026-01-27
**Next Review:** End of month
