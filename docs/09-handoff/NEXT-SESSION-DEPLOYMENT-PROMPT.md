# Copy-Paste Prompt for Next Session

Copy everything below the line and paste into a new Claude Code session:

---

## Session 136: Complete Resilience System Deployment

**Context:** Session 135 built complete 6-layer resilience monitoring system (30 files, 6,788 lines). All code written, tested, and committed. Deployment started but failed due to dependency conflicts. Your task: deploy all 3 Cloud Run Jobs + Schedulers.

**Status:**
- ✅ All code ready and tested
- ✅ Slack channels created (#deployment-alerts, #canary-alerts)
- ✅ Webhook secrets stored in GCP Secret Manager
- ❌ Cloud Run deployment failed (dependency issues)
- ⏳ Need to deploy 3 jobs with simpler approach

**Your Tasks:**
1. Read the handoff: `docs/09-handoff/2026-02-05-SESSION-135-HANDOFF-DEPLOYMENT.md`
2. Choose deployment approach (Option A/B/C recommended in handoff)
3. Deploy 3 Cloud Run Jobs:
   - `nba-deployment-drift-alerter` (every 2 hours)
   - `nba-pipeline-canary` (every 30 minutes)
   - `nba-auto-batch-cleanup` (every 15 minutes)
4. Create 3 Cloud Schedulers for each job
5. Test all components
6. Verify Slack alerts working

**Estimated Time:** 40 minutes

**Key Files:**
- `bin/monitoring/deployment_drift_alerter.py` - Layer 1
- `bin/monitoring/pipeline_canary_queries.py` - Layer 2
- `bin/monitoring/auto_batch_cleanup.py` - Layer 4
- `schemas/nba_orchestration/healing_events.json` - BigQuery schema

**Secrets Already Created:**
- `slack-webhook-deployment-alerts`
- `slack-webhook-canary-alerts`
- `slack-webhook-url` (for #nba-alerts)

**Start by reading the handoff doc, then choose your deployment approach and execute!**
