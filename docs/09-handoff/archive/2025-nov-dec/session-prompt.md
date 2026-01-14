# New Session Prompt - System Health Check

**Copy/paste this into a new Claude Code chat session**

---

## 📋 QUICK START

1. Open a new Claude Code chat session
2. Copy everything below the line into the new chat
3. Claude will run health checks and tell you what to do next

---

I'm continuing work on the NBA Props Platform after deploying Phase 2 and Phase 3 services with new phase-based naming yesterday (2025-11-16).

## CONTEXT FROM PREVIOUS SESSION

**What was deployed:**
- ✅ Phase 2: `nba-phase2-raw-processors` (deployed and active)
- ✅ Phase 3: `nba-phase3-analytics-processors` (deployed and active)
- ✅ All 4 subscriptions updated to point to new service URLs
- ✅ Subscription renamed: `nba-processors-sub-v2` → `nba-phase2-raw-sub`
- ✅ End-to-end tested: Phase 1→2→3 flow working

**Current state:**
- New services running for ~12-18 hours
- Old services still running (scheduled for cleanup after 24h monitoring)
- Dual publishing active: Phase 1 publishes to both old and new topics

## WHAT I NEED YOU TO DO

### 1. IMMEDIATE HEALTH CHECK

Check the health of the entire Phase 1→2→3 pipeline:

**Phase 1 (Scrapers):**
- Check recent scraper executions (last 24h)
- Look for failures or errors
- Verify scrapers are publishing to new topic: `nba-phase1-scrapers-complete`

**Phase 2 (Raw Processors):**
- Check `nba-phase2-raw-processors` service logs for errors
- Verify it's receiving messages from Phase 1
- Check if it's publishing to Phase 3 topic: `nba-phase2-raw-complete`

**Phase 3 (Analytics Processors):**
- Check `nba-phase3-analytics-processors` service logs
- Verify it's receiving messages from Phase 2
- Look for any processing errors

**Pub/Sub Health:**
- Check DLQ depths (should be 0):
  - `nba-phase1-scrapers-complete-dlq-sub`
  - `nba-phase2-raw-complete-dlq-sub`
- Verify subscriptions are delivering messages

### 2. IDENTIFY ANY ISSUES

Look for:
- 🚨 **Critical:** Services crashing, high error rates, DLQ filling up
- ⚠️ **Warning:** Occasional failures, slow processing, missing data
- ℹ️ **Info:** Normal operations, expected "no data" results

### 3. RECOMMEND NEXT STEPS

Based on health check, tell me:
- **If everything is healthy:** Proceed with cleanup of old services
- **If issues found:** What needs to be fixed before cleanup
- **What to work on next:** Prioritized list of next tasks

## USEFUL COMMANDS

```bash
# Check Phase 1 scraper health (orchestration)
./bin/orchestration/quick_health_check.sh

# Check Phase 2 service logs
gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=50

# Check Phase 3 service logs
gcloud run services logs read nba-phase3-analytics-processors --region=us-west2 --limit=50

# Check for any errors across all services
gcloud logging read 'resource.type="cloud_run_revision" severity>=ERROR' --limit=50 --format=json

# Check DLQ depths
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub --format="value(numUndeliveredMessages)"
gcloud pubsub subscriptions describe nba-phase2-raw-complete-dlq-sub --format="value(numUndeliveredMessages)"

# Check subscription health
gcloud pubsub subscriptions list | grep nba-phase
gcloud pubsub subscriptions describe nba-phase2-raw-sub
```

## KEY DOCUMENTS TO REFERENCE

**Current Status:**
- `docs/HANDOFF-2025-11-17-morning-status.md` - This morning's status
- `docs/HANDOFF-2025-11-16-phase-rename-complete.md` - Yesterday's work
- `docs/MONITORING_CHECKLIST.md` - Monitoring schedule

**System Architecture:**
- `docs/infrastructure/PUBSUB_AND_SERVICE_NAMES.md` - Resource naming
- `docs/architecture/04-event-driven-pipeline-architecture.md` - Pipeline design

**Operations:**
- `docs/processors/01-phase2-operations-guide.md` - Phase 2 operations
- `docs/processors/02-phase3-operations-guide.md` - Phase 3 operations

## EXPECTED BEHAVIOR

**On a typical day:**
- Phase 1: 100-120 scraper executions, 97-99% success rate
- Phase 2: Processes data from Phase 1, <60s latency
- Phase 3: Computes analytics from Phase 2, <30s latency
- DLQs: 0 messages (all messages processed successfully)

**Current deployment status:**
- Old services: Still running (will delete after 24h)
- New services: Active and receiving traffic
- Dual publishing: Active (Phase 1 publishes to both topics)

## WHAT TO CHECK FOR CLEANUP DECISION

After 24h (around 2025-11-17 22:00 UTC):
- [ ] New services stable for 24+ hours
- [ ] No errors in new service logs
- [ ] DLQ depths at 0
- [ ] End-to-end flow working (can test with sample message)
- [ ] Old services receiving decreasing/zero traffic

**If all checked:** Ready to run cleanup script
**If any unchecked:** Investigate before cleanup

## CLEANUP PROCEDURE (ONLY IF HEALTH CHECK PASSES)

```bash
# After confirming 24h stability
./bin/infrastructure/cleanup_old_resources.sh

# Script will delete:
# - nba-scrapers (old Phase 1)
# - nba-processors (old Phase 2)
# - nba-analytics-processors (old Phase 3)
```

## OUTPUT FORMAT

Please provide:

1. **Health Check Summary**
   - Phase 1 status: ✅/⚠️/🚨
   - Phase 2 status: ✅/⚠️/🚨
   - Phase 3 status: ✅/⚠️/🚨
   - Pub/Sub status: ✅/⚠️/🚨
   - Overall assessment: HEALTHY / DEGRADED / UNHEALTHY

2. **Issues Found** (if any)
   - Critical issues requiring immediate action
   - Warnings to monitor
   - Information/notes

3. **Recommended Next Steps**
   - Immediate actions (if critical issues)
   - OR: Proceed with cleanup (if healthy)
   - OR: Continue monitoring (if warnings)

4. **Next Work Items** (prioritized)
   - What to work on after cleanup/fixes
   - Links to relevant docs

---

**START HERE:** Run the health check commands and analyze the results.
