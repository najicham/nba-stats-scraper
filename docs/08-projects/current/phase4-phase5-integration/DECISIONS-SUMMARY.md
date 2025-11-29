# Final Architecture Decisions Summary

**Created:** 2025-11-28 9:06 PM PST
**Last Updated:** 2025-11-28 9:06 PM PST
**Status:** ✅ APPROVED - Ready to Implement
**Participants:** User, Claude

---

## Executive Summary

All architecture decisions finalized. Key changes from original plan:
1. ✅ **Change detection moved to v1.0** (from v1.1) - Critical for sports betting
2. ✅ **Phase 2→3 orchestrator added** - Consistency across all phases
3. ✅ **Test dataset support added** - Safe testing without production impact
4. ✅ **Comprehensive backfill scripts** - Professional execution tooling
5. ✅ **Smart alert manager** - Rate limiting + backfill mode awareness

**Updated Timeline:** 72 hours over 3-4 weeks + 5-7 days backfill execution

---

## User Questions & Answers

### Q1: Mid-Day Updates - What happens when one player's data changes?

**User Note:** "What happens if later in the day one player's data changes such as injury report, only that player's data will be processed downstream?"

**Answer:** YES - with change detection in v1.0

**How it works:**
```
2:00 PM - Injury scraper runs, gets ALL 450 players
  → Phase 2 detects ONLY LeBron changed (hash comparison)
  → Publishes: {entities_changed: ["lebron-james"]}
  → Phase 3 processes ONLY LeBron
  → Phase 4 processes ONLY LeBron
  → Phase 5 generates predictions ONLY for LeBron
2:03 PM - LeBron's updated prediction ready!
```

**Decision:** Add change detection to v1.0 (originally planned for v1.1)

**Rationale:** Sports betting requires fresh injury data mid-day. The 99% efficiency gain is worth 8 additional hours of development.

---

### Q2: Phase 2→3 Orchestrator - Should we add it?

**User Question:** "are you confident in that decision? I don't mind implementing if you think it's worth it"

**Answer:** YES - Add Phase 2→3 orchestrator

**Rationale:**
- **Consistency:** All phase transitions have orchestrators
- **Cleaner logs:** 1 trigger to Phase 3 instead of 21
- **Professional:** Proper separation of concerns
- **Marginal cost:** One more Cloud Function (same pattern as others)

**Decision:** Build Phase 2→3 orchestrator

**Implementation:**
- Cloud Function tracks all 21 Phase 2 processors in Firestore
- Publishes ONE message when all complete
- Aggregates changed entities from all processors

---

### Q3: Testing Strategy

**User Context:** "I don't really have a test environment. Not sure if you recommend creating a test database and possibly test cloud functions to test things. Right now we've just been using unit tests for testing. I'm open to anything, what do you recommend?"

**Answer:** Hybrid Approach - Test datasets in same project

**Recommendation:**
```bash
# Production datasets
nba_raw, nba_analytics, nba_precompute, nba_predictions

# Test datasets (same project)
nba_raw_test, nba_analytics_test, nba_precompute_test, nba_predictions_test

# Environment variable controls which to use
export DATASET_ID=nba_analytics_test  # For testing
export DATASET_ID=nba_analytics       # For production (default)
```

**Benefits:**
- Same infrastructure (Pub/Sub, Cloud Functions)
- Easy to switch
- No extra GCP project
- Parallel testing during development

**Testing Flow:**
1. **Unit tests:** Individual functions (pytest)
2. **Manual testing:** Test datasets with specific dates
3. **Backfill testing:** One season in test datasets
4. **Production:** Real datasets once confident

**Decision:** Implement test dataset support via environment variable

---

### Q4: Backfill Plan

**User Context:** "I really don't have a backfill plan yet. What I've been doing so far is picking one scraper and running a backfill job on it for the 4 seasons. Sometimes with 12 threads and after each scrape, a pub/sub triggers phase 2 processor. Other than that, I have not performed any backfills. We can design a plan however is best, it's still open for design."

**Answer:** Comprehensive 4-phase backfill plan

**Phase 1: Historical Seasons (Phases 1-2 only)**
```bash
# For each season: 2020-21, 2021-22, 2022-23, 2023-24
./bin/backfill/backfill_season.sh \
    --season=2023-24 \
    --phases=1,2 \
    --skip-downstream \
    --threads=12 \
    --parallel-scrapers=5

# Time: ~2-3 days per season (with parallelization)
# Total: ~6-9 days for 4 seasons
```

**Phase 2: Historical Analytics (Phases 3-4)**
```bash
# Get all historical game dates
# Trigger Phase 3-4 for each date
./bin/backfill/trigger_phase3_batch.sh \
    --start-date=2020-10-01 \
    --end-date=2024-06-30 \
    --skip-downstream

# Time: ~1-2 days (~500 dates)
```

**Phase 3: Current Season (Phases 1-4)**
```bash
# Backfill from season opener to yesterday
./bin/backfill/backfill_season.sh \
    --season=2024-25 \
    --start-date=2024-10-22 \
    --end-date=$(date -d "yesterday" +%Y-%m-%d) \
    --phases=1,2,3,4 \
    --skip-downstream

# Time: ~1 day (~50 dates)
```

**Phase 4: Enable Daily Processing**
```bash
# Verify all data loaded
./bin/backfill/verify_completeness.sh --all-seasons

# Enable Cloud Scheduler for overnight runs
# Monitor first overnight run
```

**Total Timeline:** ~5-7 days execution

**Scripts to Create:**
- `bin/backfill/backfill_season.sh` - Seasonal orchestration
- `bin/backfill/trigger_phase3_batch.sh` - Batch Phase 3 trigger
- `bin/backfill/trigger_phase4_batch.sh` - Batch Phase 4 trigger
- `bin/backfill/verify_completeness.sh` - Completeness check

**Decision:** Create comprehensive backfill scripts with progress tracking

---

### Q5: When to Start Current Season Processing

**User Answer:** "My plan is to first backfill the last 4 seasons. After that is done and complete and confirmed, I plan to backfill this season, but first I want to have a solid plan for daily processing and filling in dates for the current season. So the plan is to backfill the current season the night before daily processing is set to run."

**Answer:** Perfect! Matches our backfill plan.

**Timeline:**
1. ✅ Backfill historical 4 seasons
2. ✅ Verify completeness
3. ✅ Backfill current season (opener → yesterday)
4. ✅ Test one current date end-to-end
5. ✅ Enable daily processing (overnight before first auto run)
6. ✅ Monitor first overnight automatic run

**Decision:** Follow user's phased approach - historical first, then current, then daily

---

### Q6: Alert Strategy

**User Answer:** "I'm not sure about alerts. I'm okay with slack alerts for any error. But I've noticed that email alerts during a backfill can get excessive, I remember there was some talk or documentation about preventing the mass emails, but I forgot the specific details."

**Answer:** Smart Alert Manager with rate limiting and backfill mode

**Alert Strategy:**

**Normal Daily Processing:**
- **Critical:** Slack + Email (Phase 5 <90% coverage, total failure)
- **Error:** Slack only (processor failures, partial failures)
- **Warning:** Slack only (performance issues, data quality)
- **Info:** Logs only (successful runs, metrics)

**Backfill Mode (set BACKFILL_MODE=true):**
- **Critical:** Slack + Email (only truly critical issues)
- **Error:** Batched Slack summary every 30 minutes
- **Warning:** Batched Slack summary every hour
- **Info:** Logs only

**Rate Limiting:**
- Email: Max 10 per hour, 50 per day
- Slack: Max 30 per hour, 200 per day
- If exceeded: Batch into hourly summary

**Implementation:**
```python
# In backfill scripts
export BACKFILL_MODE=true

# AlertManager automatically:
# - Suppresses most emails
# - Batches error/warning alerts to Slack
# - Only sends critical issues to email
```

**Decision:** Implement smart alert manager with backfill awareness

---

### Q7: Rollback Strategy

**User Answer:** "I like that you are thinking about this! But the system is very new and it's okay if things break, we can fix them. This is something we should worry about for the future or document, but I think we are fine for now"

**Answer:** Document but don't test rollback procedures

**Decision:**
- Document rollback steps in implementation plan
- Don't spend time testing rollbacks
- Fix forward if issues arise
- Future concern once system mature

---

## Final Architecture Decisions

### 1. Orchestrators

**Decision:** Add orchestrators for ALL phase transitions

**Implementation:**
- ✅ Phase 2→3 Orchestrator (NEW - tracks 21 Phase 2 processors)
- ✅ Phase 3→4 Orchestrator (tracks 5 Phase 3 processors)
- ✅ Phase 4 Internal Orchestrator (tracks 5 Phase 4 processors across 3 levels)

**Benefits:**
- Consistent architecture
- Clean handoffs (1 trigger per phase)
- Proper aggregation of changed entities
- Professional separation of concerns

---

### 2. Change Detection

**Decision:** Include in v1.0 (moved from v1.1)

**Implementation:** Hash-based change detection
- Add `row_hash` column to all tables
- Compare current vs previous row hashes
- Track changed entity IDs in messages
- Processors process EITHER full batch OR changed entities only

**Benefits:**
- 99% efficiency for mid-day updates
- Sub-5 minute prediction updates for injury changes
- Critical for sports betting use case

**Trade-off:**
- 8 additional hours development
- <5% overhead for hash computation
- Worth it for 99% efficiency gain

---

### 3. Test Dataset Support

**Decision:** Add environment variable support

**Implementation:**
```python
DATASET_ID = os.environ.get('DATASET_ID', 'nba_analytics')  # Default prod

# Test mode:
export DATASET_ID=nba_analytics_test

# Production (default):
export DATASET_ID=nba_analytics
```

**Benefits:**
- Safe testing without production impact
- Same infrastructure (no test project needed)
- Easy switching
- Parallel development/testing

---

### 4. Backfill Scripts

**Decision:** Create comprehensive backfill tooling

**Scripts:**
- `backfill_season.sh` - Orchestrate seasonal backfill
- `trigger_phase3_batch.sh` - Batch Phase 3 trigger
- `trigger_phase4_batch.sh` - Batch Phase 4 trigger
- `verify_completeness.sh` - Check all data loaded

**Benefits:**
- Repeatable process
- Progress tracking
- Error handling
- Professional execution

---

### 5. Smart Alert Manager

**Decision:** Implement rate limiting + backfill mode awareness

**Features:**
- Rate limits: 10 emails/hour, 30 Slack/hour
- Backfill mode: Suppress emails, batch Slack alerts
- Normal mode: Immediate alerts based on severity
- Prevents spam during backfills

**Benefits:**
- No email spam during backfills
- Important alerts still delivered
- Professional alerting system

---

## Updated Scope Summary

### What's IN v1.0 (FINAL)

1. ✅ Unified message format across all phases
2. ✅ Event-driven orchestration (ALL phases)
3. ✅ **Change detection** (hash-based, process only changed entities)
4. ✅ Correlation ID tracing
5. ✅ Backfill mode support
6. ✅ Deduplication everywhere
7. ✅ **3 Orchestrators** (Phase 2→3, Phase 3→4, Phase 4 internal)
8. ✅ **Test dataset support**
9. ✅ **Comprehensive backfill scripts**
10. ✅ **Smart alert manager**

### What's OUT (v1.1+)

1. ❌ Real-time per-player endpoints
2. ❌ Prediction versioning/superseding
3. ❌ Line movement triggers
4. ❌ Webhook integrations

### Why This Scope

**v1.0 is now production-grade from day 1:**
- Change detection solves mid-day update problem
- Consistent orchestration architecture
- Professional backfill tooling
- Smart alerting prevents spam
- Test datasets enable safe development

**Worth the extra 8 hours:**
- Change detection critical for sports betting
- Orchestrators provide consistency
- Backfill scripts save time in execution
- Alert manager prevents operational pain

---

## Updated Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| **Implementation** | 3-4 weeks (72 hours) | Complete v1.0 code |
| **Historical Backfill** | 2-3 days | 4 seasons loaded (Phases 1-2) |
| **Analytics Backfill** | 1-2 days | Phases 3-4 for historical dates |
| **Current Season** | 1 day | 2024-25 season loaded |
| **Testing & Enable** | 1 day | Daily processing enabled |
| **TOTAL** | ~4-5 weeks | Production-ready system |

---

## Success Criteria

### Technical Success
- [ ] Change detection: 1 player changed = 1 player processed (99% efficiency)
- [ ] Mid-day injury update → prediction ready in <5 minutes
- [ ] Full batch overnight run processes all 450 players
- [ ] All 3 orchestrators working correctly
- [ ] Backfill mode skips downstream triggers
- [ ] Test datasets work without affecting production
- [ ] Smart alerts prevent email spam during backfills

### Business Success
- [ ] Predictions ready by 10 AM ET (7 AM PT SLA)
- [ ] >95% prediction completion rate
- [ ] Fresh injury data reflected in predictions within minutes
- [ ] Historical 4 seasons + current season all loaded

### Quality Success
- [ ] >90% unit test coverage
- [ ] All integration tests passing
- [ ] End-to-end pipeline tested
- [ ] Comprehensive documentation
- [ ] Operational runbooks created

---

## Next Steps

1. ✅ **All decisions finalized** - This document is the record
2. ✅ **Implementation plan updated** - V1.0-IMPLEMENTATION-PLAN-FINAL.md
3. ⏭️ **Begin Week 1 Day 1** - Create UnifiedPubSubPublisher + ChangeDetector
4. ⏭️ **Follow the plan** - 72 hours over 3-4 weeks
5. ⏭️ **Execute backfills** - ~5-7 days
6. ⏭️ **Enable daily processing** - Go live!

---

**Approval Status:** ✅ APPROVED by user on 2025-11-28

**Ready to implement:** YES

**Next action:** Begin implementation per V1.0-IMPLEMENTATION-PLAN-FINAL.md

**Questions remaining:** NONE - all answered

---

## Appendix: Key Design Patterns

### Pattern 1: Change Detection Flow
```
Current Data → Compute Hashes → Compare vs Previous → Changed Entity IDs → Selective Processing
```

### Pattern 2: Orchestrator Pattern
```
Listen to Phase N Complete → Track in Firestore → All Complete? → Aggregate Changed Entities → Trigger Phase N+1
```

### Pattern 3: Backfill Mode
```
Check skip_downstream_trigger → If true: Process data but don't publish → If false: Normal flow
```

### Pattern 4: Smart Alerting
```
Check BACKFILL_MODE → If true: Batch alerts → If false: Immediate alerts → Apply rate limits → Send
```

### Pattern 5: Test Datasets
```
Check DATASET_ID env var → Use test datasets if set → Use production datasets if not set (default)
```

---

**Document Status:** ✅ FINAL - All Decisions Approved
**Last Updated:** 2025-11-28
**Valid Until:** Implementation complete
