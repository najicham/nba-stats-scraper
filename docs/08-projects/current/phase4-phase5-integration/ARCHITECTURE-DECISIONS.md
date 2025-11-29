# Architecture Decisions - v1.0 Event-Driven Pipeline

**Created:** 2025-11-28 9:06 PM PST
**Last Updated:** 2025-11-28 9:06 PM PST
**Status:** ✅ Finalized
**Participants:** User, Claude
**Next Action:** Begin implementation per V1.0-IMPLEMENTATION-PLAN-FINAL.md

---

## Summary of Key Decisions

### ✅ Decision 1: No Orchestrator for Phase 2→3

**Context:** Phase 2 has 21 raw processors, Phase 3 has 5 analytics processors

**Decision:** NO orchestrator between Phase 2→3

**Rationale:**
- Each Phase 3 processor depends on DIFFERENT Phase 2 tables
- PlayerGameSummaryProcessor needs: ~4 specific tables (bdl_player_boxscores, etc.)
- TeamDefenseProcessor needs: ~3 different tables (nbac_team_boxscore, etc.)
- No single "all Phase 2 complete" trigger makes sense
- Dependency checks in each processor handle coordination perfectly

**Implementation:**
- Each Phase 2 processor publishes to `nba-phase2-raw-complete` independently
- Phase 3 processors receive multiple triggers (one per Phase 2 processor)
- Deduplication in Phase 3 (via RunHistoryMixin) prevents duplicate work
- First trigger: check dependencies → if ready, process; if not, skip
- Subsequent triggers: deduplication check → already processed, skip

**Trade-off:**
- More Pub/Sub messages (~21 per day to Phase 3)
- But simpler architecture, no additional orchestration needed

---

### ✅ Decision 2: YES Orchestrators for Phase 3→4 and Phase 4 Internal

**Context:**
- Phase 4 processors need ALL 5 Phase 3 processors complete
- Phase 4 has 3-level dependency cascade (Level 1 → Level 2 → Level 3)

**Decision:** Build orchestrators using Cloud Functions + Firestore

**Phase 3→4 Orchestrator:**
- Listens to `nba-phase3-analytics-complete`
- Tracks all 5 Phase 3 processors in Firestore
- Document: `phase3_completion/{analysis_date}/{processor_name: {completed_at, correlation_id}}`
- When all 5 complete → publishes ONE message to `nba-phase4-trigger`

**Phase 4 Internal Orchestrator:**
- Tracks 5 Phase 4 processors across 3 dependency levels
- Level 1 (parallel): team_defense_zone, player_shot_zone, player_daily_cache
- Level 2 (depends on Level 1): player_composite_factors
- Level 3 (depends on all): ml_feature_store_v2
- Triggers each level when dependencies ready

**Rationale:**
- Clean separation of concerns
- Reduces noise (1 trigger vs 5)
- Atomic state tracking with Firestore
- Proper dependency management

**Implementation:**
- Cloud Functions (lightweight, event-driven)
- Firestore (atomic updates, purpose-built for state)
- Alternative considered: processor_run_history queries (simpler but slower)

**Trade-off:**
- More infrastructure (Cloud Functions + Firestore)
- But proper orchestration, clear handoffs, easier to debug

---

### ✅ Decision 3: Use Firestore for Orchestrator State

**Context:** Need reliable state tracking for orchestrators

**Decision:** Use Firestore (not processor_run_history)

**Rationale:**
- **Atomic updates:** Firestore transactions prevent race conditions
- **Fast reads/writes:** Sub-100ms latency
- **Purpose-built:** Designed for operational state tracking
- **Easy debugging:** View state in Firebase console

**Alternative Considered:** Query processor_run_history table
- Pros: Reuses existing table, no new infrastructure
- Cons: BigQuery not meant for operational state, slower queries (1-2 seconds)

**Conclusion:** Firestore is the right tool for the job

---

### ✅ Decision 4: Implement Correlation ID Across All Phases

**Context:** Need to trace predictions back to original scraper run

**Decision:** Implement correlation_id propagation in all phases

**Implementation:**
```python
# Phase 1 (source)
correlation_id = execution_id  # Same value

# Phases 2-5 (propagate)
upstream_msg = parse_pubsub_message(envelope)
correlation_id = upstream_msg.get('correlation_id') or upstream_msg.get('execution_id')

# Include in all published messages
message = {
    "execution_id": self.run_id,       # This run's unique ID
    "correlation_id": correlation_id,   # Original scraper run ID
    # ... other fields
}
```

**Benefit:**
- Trace any prediction back to scraper run
- Debug data quality issues
- Audit trail for compliance

**Status:** Currently documented but not implemented - needs implementation

---

### ✅ Decision 5: Add Backfill Mode to Unified Message Format

**Context:** Need to load 4 seasons of historical data without triggering predictions

**Decision:** Add backfill mode fields to unified message format

**New Fields:**
```python
{
    # ... existing fields ...
    "skip_downstream_trigger": bool,  # If true, don't publish to next phase
    "backfill_mode": bool,            # Indicates historical data processing
    "backfill_reason": str,           # "historical_load", "reprocessing", etc.
}
```

**Implementation:**
```python
# In all base classes (_publish_completion_event method)
def _publish_completion_event(self, ...):
    # Check backfill mode
    if self.opts.get('skip_downstream_trigger'):
        logger.info("Backfill mode - skipping downstream trigger")
        return  # Don't publish

    # Normal publishing
    publisher.publish(topic, message)
```

**Use Cases:**
- Load historical data (4 seasons) without generating old predictions
- Reprocess data at any phase without cascading to downstream
- Manual override for testing

**Status:** Documented in some places but not consistently implemented

---

### ✅ Decision 6: Defer Change Detection to v1.1

**Context:** Change detection adds complexity but improves efficiency

**Decision:** Do NOT implement change detection in v1.0

**v1.0 Scope (Batch Processing):**
- Process all players every run
- Simple, predictable, testable
- Focus on getting event-driven pipeline working

**v1.1 Scope (Add Optimizations):**
- Query-based change detection
- Process only changed entities (e.g., injury status change)
- 99% efficiency gain for incremental updates
- Sub-5 minute updates

**Rationale:**
- Focus on core pipeline first
- Add optimizations based on real usage patterns
- Change detection requires custom queries per processor (more testing surface)
- v1.0 is already a huge improvement (event-driven vs time-based)

**Timeline:** Add change detection 2-3 months after v1.0 stable

---

### ✅ Decision 7: Unified Message Format Across All Phases

**Context:** Current message formats inconsistent (different field names per phase)

**Decision:** Standardize on unified message format for ALL phases

**Standard Fields (All Phases):**
```python
{
    # Identity
    "processor_name": str,
    "phase": str,
    "execution_id": str,
    "correlation_id": str,

    # Data reference
    "game_date": str,
    "output_table": str,
    "output_dataset": str,

    # Status
    "status": str,  # "success" | "partial" | "no_data" | "failed"
    "record_count": int,
    "records_failed": int,

    # Timing
    "timestamp": str,
    "duration_seconds": float,

    # Tracing
    "parent_processor": str,
    "trigger_source": str,
    "trigger_message_id": str,

    # Backfill (NEW)
    "skip_downstream_trigger": bool,
    "backfill_mode": bool,
    "backfill_reason": str,

    # Errors
    "error_message": str | null,
    "error_type": str | null,

    # Phase-specific
    "metadata": dict
}
```

**Benefits:**
- Consistent tooling (monitoring, debugging)
- Easy correlation tracing
- Clear audit trail
- Simplified code (one publisher class)

**Migration Strategy:**
- Week 1: Phase 1 publishes BOTH old + new fields (dual format)
- Week 1-2: Phase 2 accepts both formats, publishes only new
- Week 2-3: Phases 3-5 built with new format only
- Week 4: Remove old fields from Phase 1

---

### ✅ Decision 8: Deduplication via processor_run_history

**Context:** Pub/Sub delivers at-least-once (can duplicate messages)

**Decision:** Use processor_run_history table for deduplication (already implemented via RunHistoryMixin)

**Implementation:**
```python
def run(self, opts):
    game_date = opts.get('game_date')

    # Check if already processed
    if self._already_processed(game_date):
        logger.info("Already processed, skipping")
        return True  # ACK message without reprocessing

    # Process normally
    # ...
```

**Query:**
```sql
SELECT status
FROM processor_run_history
WHERE processor_name = @processor_name
  AND data_date = @game_date
  AND status IN ('success', 'partial')
ORDER BY processed_at DESC
LIMIT 1
```

**Benefits:**
- Idempotent operations
- Safe Pub/Sub retries
- Safe manual re-triggers
- No duplicate data

**Trade-off:**
- Can't automatically retry failed dates (must manually clear history)
- But this is actually a FEATURE (prevents accidental reprocessing)

**Status:** Already implemented in all base classes via RunHistoryMixin ✅

---

## Implementation Priorities

### Must Have (v1.0)
1. ✅ Unified message format
2. ✅ Correlation ID propagation
3. ✅ Backfill mode support
4. ✅ Deduplication (already done via RunHistoryMixin)
5. ✅ Orchestrators for Phase 3→4 and Phase 4 internal
6. ✅ Event-driven triggers (Pub/Sub)
7. ✅ Backup schedulers (Phase 5)

### Nice to Have (v1.1)
- ⏳ Change detection queries
- ⏳ Real-time incremental updates
- ⏳ Per-player processing endpoints
- ⏳ Prediction versioning (supersede old predictions)

### Future (v2.0+)
- 🔮 Multi-prop support (rebounds, assists, threes)
- 🔮 Multi-sport support (NHL, NFL, MLB)
- 🔮 User-triggered predictions

---

## Open Questions / Clarifications Needed

### 1. Testing Strategy
**Question:** How should we test this before production?

**Options:**
- A) Create separate test GCP project
- B) Use test dataset in same project
- C) Test directly in production with test dates
- D) Local emulator for Pub/Sub + Firestore

**Recommendation:** Option B (test dataset) for speed, Option A (test project) for safety

**Decision Needed:** User preference?

---

### 2. Backfill Execution Plan
**Question:** When we backfill 4 seasons of historical data, what's the process?

**Proposed Flow:**
```bash
# 1. Backfill Phases 1-2 (get data into raw tables)
for season in 2020-21 2021-22 2022-23 2023-24; do
    trigger_scrapers --season $season --skip_downstream_trigger=true
done

# 2. Manually trigger Phases 3-4 for historical dates
for date in <all_game_dates>; do
    trigger_phase3 --date $date --skip_downstream_trigger=true
    trigger_phase4 --date $date --skip_downstream_trigger=true
done

# 3. DON'T trigger Phase 5 (we don't need predictions for 2020 games)
```

**Decision Needed:** Confirm this approach?

---

### 3. Current Season Start Date
**Question:** When do we start processing 2024-25 season?

**Options:**
- A) As soon as v1.0 deployed (current games)
- B) Wait until tested with backfill data
- C) Start from season opener (backfill this season too)

**Recommendation:** Option B (test with historical data first, then enable current season)

**Decision Needed:** User timeline preference?

---

### 4. Monitoring/Alerting Thresholds
**Question:** What should trigger alerts?

**Proposed Thresholds:**
- **Critical (immediate):**
  - Phase 5 predictions <90% coverage
  - Any phase 100% failure rate
  - End-to-end latency >2 hours

- **Warning (same day):**
  - Phase 5 predictions <95% coverage
  - Any phase >10% failure rate
  - End-to-end latency >1 hour
  - Pub/Sub publish failures

- **Info (daily summary):**
  - Successful runs
  - Performance metrics
  - Coverage statistics

**Decision Needed:** Adjust these thresholds?

---

### 5. Rollback Strategy
**Question:** If something breaks in production, how do we rollback?

**Proposed Strategy:**
- Each phase can rollback independently (Cloud Run revisions)
- Orchestrators can be disabled (delete Cloud Function)
- System gracefully degrades to time-based schedulers
- Keep old code deployable for 1 week

**Decision Needed:** Confirm this is acceptable?

---

## Risk Assessment

### High Risk Items
1. **Orchestrator complexity** - New infrastructure (Cloud Functions + Firestore)
   - Mitigation: Extensive testing, simple logic, manual overrides

2. **Migration breakage** - Unified format changes existing flow
   - Mitigation: Dual format period, gradual rollout, thorough testing

3. **Production data edge cases** - Real data may differ from test data
   - Mitigation: Start small (one day), monitor closely, rollback ready

### Medium Risk Items
1. **Timing/race conditions** - Concurrent message processing
   - Mitigation: Firestore atomic updates, deduplication, testing

2. **Correlation ID tracking** - New field propagation might break
   - Mitigation: Optional field (backward compatible), logging

### Low Risk Items
1. **Backfill mode** - Simple flag, isolated change
2. **Deduplication** - Already implemented and working
3. **Pub/Sub infrastructure** - Standard GCP service

---

## Success Metrics

### Technical Metrics
- **Pipeline Latency:** <60 minutes end-to-end (scraper → predictions)
- **Completion Rate:** >95% of expected predictions generated
- **Error Rate:** <5% per phase
- **Correlation Tracking:** 100% of runs traceable to source scraper

### Business Metrics
- **SLA Compliance:** Predictions ready by 10 AM ET (7 AM PT) >99% of days
- **Coverage:** >450 players with predictions daily
- **Uptime:** >99% system availability

### Quality Metrics
- **Test Coverage:** >90% unit test coverage
- **Documentation:** All operational procedures documented
- **Monitoring:** Dashboards created for all critical metrics

---

## Approval Checklist

- [x] Architecture decisions reviewed and approved
- [x] Implementation plan reviewed (V1.0-IMPLEMENTATION-PLAN.md)
- [x] Timeline realistic (3-4 weeks, ~68 hours)
- [x] Risks identified and mitigations in place
- [x] Testing strategy defined
- [ ] Open questions answered
- [ ] Ready to begin implementation

---

## Next Steps

1. **User:** Review this document and V1.0-IMPLEMENTATION-PLAN.md
2. **User:** Answer open questions above
3. **User:** Approve to proceed or request changes
4. **Claude:** Begin Week 1 Day 1 implementation
   - Create UnifiedPubSubPublisher
   - Update Phase 1 ScraperPubSubPublisher
   - Test Phase 1 publishing

---

**Document Status:** ✅ Decisions Finalized, Awaiting User Approval
**Last Updated:** 2025-11-28
**Next Review:** After user feedback on open questions
