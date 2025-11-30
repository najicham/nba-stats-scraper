# Pub/Sub Infrastructure Audit - Complete System Analysis

**Date:** 2025-11-28
**Status:** ✅ Audit Complete
**Purpose:** Comprehensive review of all Pub/Sub infrastructure across Phases 1-5

---

## Executive Summary

**Overall Status:** 🟡 **Partial Implementation**

- ✅ **Phases 1→2→3:** Event-driven architecture FULLY working
- ⚠️ **Phase 3→4:** HYBRID (event-driven for some, time-based for others)
- ❌ **Phase 4→5:** NOT IMPLEMENTED (pure time-based, no events)

**Critical Findings:**
1. Phase 4 has **inconsistent triggering** - some processors event-driven, others time-based
2. **ml_feature_store_v2** (critical Phase 4 processor) uses only Cloud Scheduler
3. **No Pub/Sub event from Phase 4 to Phase 5** - this is the gap we're fixing
4. **No Cloud Functions deployed** - docs mention 4-way dependency orchestration but it's not implemented

---

## Table of Contents

1. [Infrastructure Inventory](#infrastructure-inventory)
2. [Current Architecture by Phase](#current-architecture)
3. [Gap Analysis](#gap-analysis)
4. [Master Implementation Plan](#master-plan)

---

## Infrastructure Inventory {#infrastructure-inventory}

### Pub/Sub Topics (14 total)

| Topic Name | Purpose | Status | Publisher | Subscriber |
|------------|---------|--------|-----------|------------|
| `nba-phase1-scrapers-complete` | Phase 1→2 trigger | ✅ Active | Phase 1 scrapers | Phase 2 processors |
| `nba-phase1-scrapers-complete-dlq` | DLQ for Phase 1 | ✅ Active | Pub/Sub (failures) | Manual review |
| `nba-phase2-raw-complete` | Phase 2→3 trigger | ✅ Active | Phase 2 processors | Phase 3 processors |
| `nba-phase2-raw-complete-dlq` | DLQ for Phase 2 | ✅ Active | Pub/Sub (failures) | Manual review |
| `nba-phase3-analytics-complete` | Phase 3→4 trigger | ✅ Active | Phase 3 processors | Phase 4 processors |
| `nba-phase3-analytics-complete-dlq` | DLQ for Phase 3 | ⚠️ No sub | Pub/Sub (failures) | **MISSING** |
| **`nba-phase4-precompute-complete`** | **Phase 4→5 trigger** | **❌ MISSING** | **NOT CREATED** | **NOT CREATED** |
| `nba-scraper-complete` | Legacy scraper topic | ⚠️ Legacy | Old scrapers | Old processors |
| `nba-scraper-complete-dlq` | Legacy DLQ | ⚠️ Legacy | Pub/Sub (failures) | Manual review |
| `prediction-request-prod` | Phase 5 fan-out | ✅ Active | Coordinator | Workers (100x) |
| `prediction-ready-prod` | Phase 5 completion | ✅ Active | Workers | Coordinator |
| `nba-phase2-fallback-trigger` | Scheduler backup | ✅ Active | Cloud Scheduler | Phase 2 /process |
| `nba-phase3-fallback-trigger` | Scheduler backup | ✅ Active | Cloud Scheduler | Phase 3 /process |
| `nba-phase4-fallback-trigger` | Scheduler backup | ✅ Active | Cloud Scheduler | Phase 4 /process |
| `nba-phase5-fallback-trigger` | Scheduler backup | ✅ Active | Cloud Scheduler | **NOT CONNECTED** |
| `nba-phase6-fallback-trigger` | Future use | ⏳ Unused | None | None |

### Pub/Sub Subscriptions (11 total)

| Subscription Name | Topic | Push Endpoint | Purpose | Status |
|-------------------|-------|---------------|---------|--------|
| `nba-phase2-raw-sub` | `nba-phase1-scrapers-complete` | Phase 2 /process | Phase 1→2 trigger | ✅ Working |
| `nba-phase3-analytics-sub` | `nba-phase2-raw-complete` | Phase 3 /process | Phase 2→3 trigger | ✅ Working |
| `nba-phase3-analytics-complete-sub` | `nba-phase3-analytics-complete` | Phase 4 /process | Phase 3→4 trigger | ✅ Working |
| **`nba-phase5-trigger-sub`** | **`nba-phase4-precompute-complete`** | **Phase 5 /trigger** | **Phase 4→5 trigger** | **❌ MISSING** |
| `prediction-request-prod` | `prediction-request-prod` | Worker /predict | Phase 5 fan-out | ✅ Working |
| `prediction-ready-prod-sub` | `prediction-ready-prod` | Coordinator /complete | Phase 5 completion | ✅ Working |
| `nba-phase3-fallback-sub` | `nba-phase3-fallback-trigger` | Phase 3 /process | Scheduler backup | ✅ Working |
| `nba-processors-sub` | `nba-scraper-complete` (legacy) | Old Phase 2 /process | Legacy | ⚠️ Deprecated |
| `nba-phase1-scrapers-complete-dlq-sub` | `nba-phase1-scrapers-complete-dlq` | None (pull) | DLQ monitoring | ✅ Working |
| `nba-phase2-raw-complete-dlq-sub` | `nba-phase2-raw-complete-dlq` | None (pull) | DLQ monitoring | ✅ Working |
| `nba-scraper-complete-dlq-sub` | `nba-scraper-complete-dlq` | None (pull) | Legacy DLQ | ⚠️ Deprecated |

### Cloud Run Services (6 total)

| Service Name | Purpose | Endpoints | Status |
|--------------|---------|-----------|--------|
| `nba-phase1-scrapers` | Phase 1: Data collection | /scrape, /health | ✅ Deployed |
| `nba-phase2-raw-processors` | Phase 2: Raw processing | /process, /health | ✅ Deployed |
| `nba-phase3-analytics-processors` | Phase 3: Analytics | /process, /health | ✅ Deployed |
| `nba-phase4-precompute-processors` | Phase 4: Precompute | /process, /process-date, /health | ✅ Deployed |
| `prediction-coordinator` | Phase 5: Coordinator | /start, /status, /complete, /health | ✅ Deployed |
| `prediction-worker` | Phase 5: Workers | /predict, /health | ✅ Deployed |

### Cloud Scheduler Jobs (23 total)

**Phase 1 Scrapers (18 jobs):** All time-based, trigger scrapers at scheduled intervals ✅

**Phase 4 Processors (2 jobs):**
| Job Name | Schedule | Endpoint | Purpose | Status |
|----------|----------|----------|---------|--------|
| `player-composite-factors-daily` | 11:00 PM | Phase 4 /process-date | Manual trigger | ✅ Working |
| `ml-feature-store-daily` | 11:30 PM | Phase 4 /process-date | Manual trigger | ✅ Working |

**Phase 5 (0 jobs currently):**
- ❌ No scheduler jobs for Phase 5 coordinator
- ❌ This is a problem - no backup trigger!

**Other (3 jobs):** Cleanup, scheduling, workflow execution ✅

### Cloud Functions (0 total)

**Expected:** Phase 4 dependency orchestration function
**Actual:** ❌ **NOT DEPLOYED**
**Impact:** Docs describe 4-way dependency checking via Cloud Function, but it's not implemented

---

## Current Architecture by Phase {#current-architecture}

### Phase 1 → Phase 2: Event-Driven ✅

```
Phase 1 Scrapers (Cloud Scheduler triggers)
  ↓ Scraper completes
  ↓ Publishes to: nba-phase1-scrapers-complete
  ↓ Message: {scraper: "bdl_box_scores", game_date: "2025-11-28", ...}
  ↓
Phase 2 Raw Processors
  ↓ Subscription: nba-phase2-raw-sub
  ↓ Push endpoint: https://nba-phase2-raw-processors.../process
  ↓ Processes: Converts JSON → BigQuery raw tables
  ✅ WORKING
```

### Phase 2 → Phase 3: Event-Driven ✅

```
Phase 2 Raw Processors
  ↓ Each processor publishes when complete
  ↓ Publishes to: nba-phase2-raw-complete
  ↓ Message: {source_table: "bdl_player_boxscores", analysis_date: "2025-11-28", ...}
  ↓
Phase 3 Analytics Processors
  ↓ Subscription: nba-phase3-analytics-sub
  ↓ Push endpoint: https://nba-phase3-analytics-processors.../process
  ↓ Processes: Creates analytics tables
  ✅ WORKING
```

### Phase 3 → Phase 4: HYBRID ⚠️

**Event-Driven (for some processors):**

```
Phase 3 Analytics Processors
  ↓ Each processor publishes when complete
  ↓ Publishes to: nba-phase3-analytics-complete
  ↓ Message: {source_table: "player_game_summary", analysis_date: "2025-11-28", ...}
  ↓
Phase 4 Precompute Service /process endpoint
  ↓ Subscription: nba-phase3-analytics-complete-sub
  ↓ Push endpoint: https://nba-phase4-precompute-processors.../process
  ↓
  ↓ Triggers SPECIFIC processors based on source_table:
  ├─ player_game_summary → PlayerDailyCacheProcessor ✅
  ├─ team_defense_game_summary → TeamDefenseZoneAnalysisProcessor ✅
  ├─ team_offense_game_summary → PlayerShotZoneAnalysisProcessor ✅
  └─ upcoming_player_game_context → PlayerDailyCacheProcessor ✅
```

**Time-Based (for CASCADE processors):**

```
Cloud Scheduler (11:00 PM PT)
  ↓ Job: player-composite-factors-daily
  ↓ HTTP POST to: /process-date
  ↓ {"analysis_date": "AUTO", "processors": ["PlayerCompositeFactorsProcessor"]}
  ↓
PlayerCompositeFactorsProcessor runs
  ↓ Depends on: team_defense_zone, player_shot_zone, player_daily_cache
  ↓ Has dependency checks built-in (not event-driven)
  ⚠️ RELIES ON TIME-BASED ASSUMPTION THAT UPSTREAMS ARE DONE

Cloud Scheduler (11:30 PM PT)
  ↓ Job: ml-feature-store-daily
  ↓ HTTP POST to: /process-date
  ↓ {"analysis_date": "AUTO", "processors": ["MLFeatureStoreProcessor"]}
  ↓
MLFeatureStoreProcessor runs
  ↓ Depends on: ALL 4 Phase 4 processors above
  ↓ Has dependency checks built-in (fails if upstreams not ready)
  ⚠️ RELIES ON TIME-BASED ASSUMPTION
  ❌ DOES NOT PUBLISH COMPLETION EVENT
```

**Why this is inconsistent:**
- 3 of 5 Phase 4 processors are event-driven ✅
- 2 of 5 Phase 4 processors are time-based ⚠️
- No unification between the two approaches

### Phase 4 → Phase 5: NOT IMPLEMENTED ❌

**Current (Time-Based ONLY):**

```
Cloud Scheduler (6:00 AM PT)
  ↓ Job: ❌ DOES NOT EXIST
  ↓
Phase 5 Coordinator
  ↓ ❌ NO AUTOMATIC TRIGGER
  ↓ ❌ NO PUB/SUB SUBSCRIPTION
  ↓ Must be triggered MANUALLY or via external scheduler

Result: 5.5 hours wasted (Phase 4 @ 12:30 AM, Phase 5 @ 6:00 AM)
```

**Proposed (Event-Driven + Backup):**

```
Phase 4: ml_feature_store_v2 completes
  ↓ NEW: Publishes to nba-phase4-precompute-complete
  ↓ Message: {game_date, players_ready, players_total, ...}
  ↓
Phase 5 Coordinator /trigger endpoint
  ↓ NEW: Subscription nba-phase5-trigger-sub
  ↓ Push endpoint: /trigger
  ↓ Validates Phase 4, starts predictions
  ✅ FAST PATH (~ 12:30 AM)

Cloud Scheduler (6:00 AM PT) - BACKUP
  ↓ NEW: Job phase5-daily-backup
  ↓ Endpoint: /start (with wait logic)
  ↓ If Pub/Sub failed, this catches it
  ✅ RELIABLE FALLBACK

Cloud Scheduler (6:15 AM, 6:30 AM PT) - RETRY
  ↓ NEW: Jobs phase5-retry-1, phase5-retry-2
  ↓ Endpoint: /retry
  ↓ Processes players that became ready after initial run
  ✅ GRACEFUL DEGRADATION
```

### Phase 5 Internal: Fan-Out Pattern ✅

```
Phase 5 Coordinator
  ↓ Queries Phase 3 for player list (450 players)
  ↓ Publishes 450 messages to: prediction-request-prod
  ↓ Message: {player_lookup, game_date, game_id, ...}
  ↓
Phase 5 Workers (100 concurrent instances)
  ↓ Subscription: prediction-request-prod
  ↓ Each worker processes ONE player
  ↓ Queries Phase 4 ml_feature_store_v2 for features
  ↓ Runs 5 prediction systems
  ↓ Publishes to: prediction-ready-prod
  ↓
Phase 5 Coordinator /complete endpoint
  ↓ Subscription: prediction-ready-prod-sub
  ↓ Tracks completion (450/450)
  ✅ WORKING (when manually triggered)
```

---

## Gap Analysis {#gap-analysis}

### Critical Gaps (Must Fix)

| Gap | Impact | Severity |
|-----|--------|----------|
| **No Phase 4 completion event** | Phase 5 waits 5.5 hours unnecessarily | 🔴 High |
| **No Phase 5 scheduler backup** | If manual trigger fails, no predictions | 🔴 High |
| **No Phase 5 retry mechanism** | Incomplete batches stay incomplete | 🟡 Medium |
| **Inconsistent Phase 4 triggering** | Hard to reason about dependencies | 🟡 Medium |
| **No DLQ subscription for Phase 3** | Failed messages not monitored | 🟡 Medium |

### Documentation Gaps

| Doc Says | Reality | Fix Needed |
|----------|---------|------------|
| "Cloud Function for 4-way dependency" | No Cloud Function deployed | Update docs OR implement function |
| "Phase 4 uses Pub/Sub orchestration" | Partially true (3/5 processors) | Clarify hybrid approach in docs |
| "15-minute wait timeout" | Not implemented yet | Will implement with 30 min |

### Architecture Inconsistencies

**Phase 4 Triggering:**
- Event-driven: `TeamDefenseZoneAnalysisProcessor`, `PlayerShotZoneAnalysisProcessor`, `PlayerDailyCacheProcessor`
- Time-based: `PlayerCompositeFactorsProcessor`, `MLFeatureStoreProcessor`

**Why this happened:**
- Simpler processors can be event-driven (1:1 dependency)
- CASCADE processors have complex multi-way dependencies
- Time-based approach was simpler to implement initially
- But creates timing assumptions and wastes time

**Should we fix this?**
- **Option A:** Leave as-is, just add Phase 4→5 event
- **Option B:** Make all Phase 4 event-driven (requires orchestration logic)
- **Recommendation:** Option A for now (don't over-engineer)

---

## Master Implementation Plan {#master-plan}

### Immediate Priorities (This Week)

**Goal:** Get Phase 4→5 event-driven integration working

#### Phase 1: Minimal Viable Integration (Day 1-2, ~4 hours)

1. ✅ **Complete documentation** (DONE)
2. **Add Phase 4 completion publishing** (~30 min)
   - Modify `ml_feature_store_processor.py`
   - Add `_publish_completion_event()` method
   - Publish to `nba-phase4-precompute-complete` topic
3. **Add Phase 5 trigger handling** (~2 hours)
   - Add `/trigger` endpoint to coordinator
   - Add `/start` backup endpoint with validation
   - Add helper functions
4. **Create Pub/Sub infrastructure** (~30 min)
   - Create `nba-phase4-precompute-complete` topic
   - Create `nba-phase5-trigger-sub` subscription
   - Point to coordinator `/trigger` endpoint
5. **Create scheduler backups** (~30 min)
   - Create `phase5-daily-backup` job (6:00 AM PT)
   - Create `phase5-retry-1` job (6:15 AM PT)
   - Create `phase5-retry-2` job (6:30 AM PT)
   - Create `phase5-status-check` job (7:00 AM PT)

#### Phase 2: Testing & Validation (Day 2-3, ~6 hours)

1. **Write unit tests** (~3 hours)
   - Test all 7 helper functions
   - Test 3 new endpoints
   - Test deduplication logic
2. **Integration testing** (~2 hours)
   - Test Pub/Sub trigger path
   - Test scheduler backup path
   - Test retry logic
3. **Deploy to staging** (~1 hour)
   - Deploy Phase 4 changes
   - Deploy Phase 5 changes
   - Deploy infrastructure
   - Monitor overnight run

#### Phase 3: Production Deployment (Day 4, ~2 hours)

1. **Review staging results**
2. **Deploy to production**
3. **Monitor first production run**
4. **Document lessons learned**

**Total Effort:** ~12 hours over 4 days

### Medium-Term Improvements (Next Month)

**Goal:** Strengthen and unify architecture

#### Optional: Unify Phase 4 Triggering

**Current State:**
- 3 processors event-driven
- 2 processors time-based

**Proposal:**
- Add Cloud Function or workflow orchestration
- Make all Phase 4 processors event-driven
- Remove time-based assumptions

**Effort:** ~8-12 hours
**Benefit:** More robust, faster, easier to reason about
**Risk:** Adds complexity, might break existing flows

**Decision:** Defer until Phase 4→5 is stable (month 2+)

#### Add DLQ Monitoring

**Current State:**
- DLQ topics exist
- No subscriptions or monitoring

**Proposal:**
- Add Cloud Function to process DLQ messages
- Send alerts for failed messages
- Dashboard for DLQ metrics

**Effort:** ~4 hours
**Benefit:** Better operational visibility

#### Create Unified Architecture Diagram

**Current State:**
- Architecture spread across multiple docs
- No single source of truth

**Proposal:**
- Create master architecture diagram
- Document all Pub/Sub flows
- Document all scheduler jobs
- Keep updated as system evolves

**Effort:** ~2 hours
**Benefit:** Easier onboarding, fewer surprises

### Long-Term Vision (Month 3+)

**Goal:** Production-grade event-driven system

#### Cloud Workflows Migration

**Replace:** Time-based schedulers + manual orchestration
**With:** Cloud Workflows for full pipeline orchestration
**Benefit:** Native dependency management, retries, monitoring
**Effort:** ~2-3 weeks

#### Real-Time Updates (v1.1)

**Add:** Injury update triggers
**Add:** Line movement triggers
**Requires:** This Phase 4→5 integration as foundation
**Effort:** ~2-3 weeks

#### Multi-Prop Support (v2.0)

**Add:** Rebounds, assists, threes predictions
**Requires:** Phase 5 working reliably
**Effort:** ~1-2 weeks per prop

---

## Decision Matrix

### Should We Fix Phase 4 Internal Inconsistencies?

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **Leave as-is** | Simple, low risk, works | Time-based assumptions, harder to understand | ✅ For now |
| **Make all event-driven** | Cleaner, faster, more robust | Complex orchestration, higher risk | ⏳ Future |
| **Add Cloud Function** | Proper dependency management | More infrastructure to maintain | ⏳ Future |
| **Use Cloud Workflows** | Industry standard, powerful | Learning curve, migration effort | ⏳ Long-term |

**Recommendation:** **Leave Phase 4 internal inconsistencies as-is** for now. Focus on:
1. Phase 4→5 integration (critical gap)
2. Test in production for 2-4 weeks
3. THEN revisit Phase 4 internal architecture if needed

### Should We Deploy to Staging First?

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **Straight to prod** | Faster, simpler | Higher risk | ❌ Too risky |
| **Staging first** | De-risks, validates code | Takes 2-3 extra days | ✅ Recommended |
| **Staging + canary** | Most safe, gradual rollout | Most complex | ⏳ Overkill for now |

**Recommendation:** **Deploy to staging first**, monitor for 2-3 overnight runs, then promote to production.

---

## Next Steps

1. **Review this audit** - Understand current state
2. **Choose approach** - Minimal (Phase 4→5 only) or comprehensive (fix all gaps)
3. **Start implementation** - Follow Phase 1 plan from IMPLEMENTATION-FULL.md
4. **Test thoroughly** - Unit tests + integration tests + staging validation
5. **Deploy to production** - Monitor closely for first week

**Recommendation:** Start with **Minimal Viable Integration** (Phase 4→5 only), then iterate.

---

## Appendix: Infrastructure Commands

### Check Current State

```bash
# List all topics
gcloud pubsub topics list --project=nba-props-platform

# List all subscriptions
gcloud pubsub subscriptions list --project=nba-props-platform

# List all Cloud Run services
gcloud run services list --project=nba-props-platform --region=us-west2

# List all Cloud Scheduler jobs
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2

# List all Cloud Functions
gcloud functions list --project=nba-props-platform
```

### Create Missing Infrastructure

```bash
# Create Phase 4 completion topic
gcloud pubsub topics create nba-phase4-precompute-complete \
    --project=nba-props-platform

# Create Phase 5 trigger subscription
gcloud pubsub subscriptions create nba-phase5-trigger-sub \
    --topic=nba-phase4-precompute-complete \
    --push-endpoint=https://[COORDINATOR-URL]/trigger \
    --project=nba-props-platform

# Create Phase 5 scheduler backup
gcloud scheduler jobs create http phase5-daily-backup \
    --location=us-west2 \
    --schedule="0 6 * * *" \
    --uri="https://[COORDINATOR-URL]/start" \
    --http-method=POST \
    --project=nba-props-platform
```

---

**Document Status:** ✅ Audit Complete
**Date:** 2025-11-28
**Next Action:** Review with team → Choose approach → Start implementation
