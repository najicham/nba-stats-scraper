# NBA Props Platform - Naming Conventions

**Last Updated:** 2025-11-16 (Phase 1-3 Rename Complete)
**Purpose:** Single source of truth for all resource naming across the NBA Props Platform
**Scope:** Services, Topics, Subscriptions for all 6 pipeline phases

---

## Naming Patterns

### Services
```
Pattern: nba-phase{N}-{function}-{type}

Where:
  {N} = Phase number (1-6)
  {function} = What it does (scrapers, raw, analytics, etc.)
  {type} = processors, coordinator, worker, service (based on architecture)
```

### Topics (Completion Events)
```
Pattern: nba-phase{N}-{content}-complete

Where:
  {N} = Phase number that publishes (1-5, no Phase 6 completion)
  {content} = Type of data (scrapers, raw, analytics, etc.)
```

### Topics (Dead Letter Queues)
```
Pattern: {completion-topic-name}-dlq

Automatically derived from completion topic name
```

### Topics (Fallback Triggers)
```
Pattern: nba-phase{N}-fallback-trigger

Where:
  {N} = Phase number that gets triggered by fallback (2-6)
```

### Subscriptions (Main)
```
Pattern: nba-phase{N}-{destination-type}-sub

Where:
  {N} = Phase number that RECEIVES messages
  {destination-type} = Type of processing (raw, analytics, etc.)
```

### Subscriptions (Fallback)
```
Pattern: nba-phase{N}-fallback-trigger-sub

Matches the fallback topic name exactly
```

### Subscriptions (DLQ Monitoring)
```
Pattern: {topic-name}-dlq-sub

Matches the DLQ topic name exactly
```

---

## PHASE 1: Data Collection (Scrapers)

### Services
- `nba-phase1-scrapers`

### Topics
- `nba-phase1-scrapers-complete` (publishes when scraping completes)
- `nba-phase1-scrapers-complete-dlq` (dead letter queue)

### Subscriptions
- `nba-phase1-scrapers-complete-dlq-sub` (monitors DLQ for failures)

**Note:** Phase 1 has no incoming subscriptions (first in pipeline)

---

## PHASE 2: Raw Data Processing

### Services
- `nba-phase2-raw-processors`

### Topics
- `nba-phase2-raw-complete` (publishes when raw processing completes)
- `nba-phase2-raw-complete-dlq` (dead letter queue)
- `nba-phase2-fallback-trigger` (time-based fallback trigger)

### Subscriptions
- `nba-phase2-raw-sub` (receives from `nba-phase1-scrapers-complete`)
- `nba-phase2-fallback-trigger-sub` (receives from `nba-phase2-fallback-trigger`)
- `nba-phase2-raw-complete-dlq-sub` (monitors DLQ for failures)

**Receives From:** Phase 1 completion events
**Publishes To:** Phase 2 completion events

---

## PHASE 3: Analytics Processing

### Services
- `nba-phase3-analytics-processors`

### Topics
- `nba-phase3-analytics-complete` (publishes when analytics complete)
- `nba-phase3-analytics-complete-dlq` (dead letter queue)
- `nba-phase3-fallback-trigger` (time-based fallback trigger)

### Subscriptions
- `nba-phase3-analytics-sub` (receives from `nba-phase2-raw-complete`)
- `nba-phase3-fallback-trigger-sub` (receives from `nba-phase3-fallback-trigger`)
- `nba-phase3-analytics-complete-dlq-sub` (monitors DLQ for failures)

**Receives From:** Phase 2 completion events
**Publishes To:** Phase 3 completion events

---

## PHASE 4: Precompute Processing

### Services
- `nba-phase4-precompute-processors`

### Topics
- `nba-phase4-precompute-complete` (publishes when precompute completes)
- `nba-phase4-precompute-complete-dlq` (dead letter queue)
- `nba-phase4-fallback-trigger` (time-based fallback trigger)

### Subscriptions
- `nba-phase4-precompute-sub` (receives from `nba-phase3-analytics-complete`)
- `nba-phase4-fallback-trigger-sub` (receives from `nba-phase4-fallback-trigger`)
- `nba-phase4-precompute-complete-dlq-sub` (monitors DLQ for failures)

**Receives From:** Phase 3 completion events
**Publishes To:** Phase 4 completion events

---

## PHASE 5: Predictions (Multi-Service Architecture)

### Services
- `nba-phase5-predictions-coordinator` (orchestrates prediction jobs)
- `nba-phase5-predictions-worker` (executes prediction computations)

### Topics
- `nba-phase5-predictions-complete` (publishes when predictions complete)
- `nba-phase5-predictions-complete-dlq` (dead letter queue)
- `nba-phase5-fallback-trigger` (time-based fallback trigger)

### Subscriptions
- `nba-phase5-predictions-sub` (receives from `nba-phase4-precompute-complete`)
  - Pushes to coordinator service
- `nba-phase5-fallback-trigger-sub` (receives from `nba-phase5-fallback-trigger`)
- `nba-phase5-predictions-complete-dlq-sub` (monitors DLQ for failures)

**Receives From:** Phase 4 completion events
**Publishes To:** Phase 5 completion events
**Architecture Note:** Coordinator receives subscription events and spawns workers

---

## PHASE 6: Publishing/Distribution

### Services
- `nba-phase6-publish-processors`

### Topics
- `nba-phase6-fallback-trigger` (time-based fallback trigger)
- **No completion topic** (final phase - publishes externally, not to Pub/Sub)

### Subscriptions
- `nba-phase6-publish-sub` (receives from `nba-phase5-predictions-complete`)
- `nba-phase6-fallback-trigger-sub` (receives from `nba-phase6-fallback-trigger`)

**Receives From:** Phase 5 completion events
**Publishes To:** External systems (APIs, databases, etc.), not Pub/Sub
**Architecture Note:** Final phase in pipeline - no downstream Pub/Sub events

---

## Utility Services (Not Part of Main Pipeline)

### Services
- `nba-reference-processors` (loads reference data - teams, players, etc.)

**Note:** Utility services follow their own naming based on function

---

## Current Deployment Status (2025-11-16)

### Active Services (Phase-Based Names)

| Phase | Service | URL | Status |
|-------|---------|-----|--------|
| 1 | `nba-phase1-scrapers` | https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app | ✅ ACTIVE |
| 2 | `nba-phase2-raw-processors` | https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app | ✅ ACTIVE |
| 3 | `nba-phase3-analytics-processors` | https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app | ✅ ACTIVE |
| - | `nba-reference-processors` | https://nba-reference-processors-f7p3g7f6ya-wl.a.run.app | ✅ ACTIVE (utility) |

### Future Phases (Not Yet Built)

| Phase | Service | Status |
|-------|---------|--------|
| 4 | `nba-phase4-precompute-processors` | 🔴 NOT BUILT |
| 5 | `nba-phase5-predictions-coordinator` | 🔴 NOT BUILT |
| 5 | `nba-phase5-predictions-worker` | 🔴 NOT BUILT |
| 6 | `nba-phase6-publish-processors` | 🔴 NOT BUILT |

### Old Services (Pending Deletion After 24h Monitoring)

| Old Service | Replaced By | Can Delete After |
|-------------|-------------|------------------|
| `nba-scrapers` | `nba-phase1-scrapers` | 2025-11-17 22:00 UTC |
| `nba-processors` | `nba-phase2-raw-processors` | 2025-11-17 22:00 UTC |
| `nba-analytics-processors` | `nba-phase3-analytics-processors` | 2025-11-17 22:00 UTC |

---

## Migration Notes

### Completed Migrations (2025-11-16)
- ✅ `nba-scrapers` → `nba-phase1-scrapers` (DEPLOYED)
- ✅ `nba-processors` → `nba-phase2-raw-processors` (DEPLOYED)
- ✅ `nba-analytics-processors` → `nba-phase3-analytics-processors` (DEPLOYED)
- ✅ `nba-processors-sub-v2` → `nba-phase2-raw-sub` (RENAMED & ACTIVE)
- ✅ All 4 subscriptions updated to point to new service URLs
- ✅ End-to-end flow tested (Phase 1→2→3)

### Pending Cleanup (After 24h Monitoring)

**Old Services to Delete:**
- `nba-scrapers` (replaced by `nba-phase1-scrapers`)
- `nba-processors` (replaced by `nba-phase2-raw-processors`)
- `nba-analytics-processors` (replaced by `nba-phase3-analytics-processors`)

**Old Topics/Subscriptions to Delete (After Dual Publishing Ends):**
- `nba-processors-sub` (subscribes to old topic `nba-scraper-complete`)
- `nba-scraper-complete` (old Phase 1 completion topic)
- `nba-scraper-complete-dlq` (old Phase 1 DLQ topic)
- `nba-scraper-complete-dlq-sub` (old DLQ subscription)

### Migration Timeline
- **2025-11-16 22:00 UTC:** All new services deployed with phase names
- **2025-11-16 22:30 UTC:** All subscriptions updated to new URLs
- **2025-11-16 22:35 UTC:** End-to-end testing completed successfully
- **2025-11-17 22:00 UTC:** Delete old services (after 24h monitoring)
- **Future (TBD):** End dual publishing and delete old topics

---

## Quick Reference Table

| Component Type | Pattern | Example |
|----------------|---------|---------|
| Service (processor) | `nba-phase{N}-{function}-processors` | `nba-phase2-raw-processors` |
| Service (coordinator) | `nba-phase{N}-{function}-coordinator` | `nba-phase5-predictions-coordinator` |
| Service (worker) | `nba-phase{N}-{function}-worker` | `nba-phase5-predictions-worker` |
| Topic (completion) | `nba-phase{N}-{content}-complete` | `nba-phase2-raw-complete` |
| Topic (DLQ) | `{topic}-dlq` | `nba-phase2-raw-complete-dlq` |
| Topic (fallback) | `nba-phase{N}-fallback-trigger` | `nba-phase2-fallback-trigger` |
| Subscription (main) | `nba-phase{N}-{type}-sub` | `nba-phase2-raw-sub` |
| Subscription (fallback) | `nba-phase{N}-fallback-trigger-sub` | `nba-phase2-fallback-trigger-sub` |
| Subscription (DLQ) | `{topic}-dlq-sub` | `nba-phase2-raw-complete-dlq-sub` |

---

## Naming Principles

1. **Consistency:** All resources follow the same pattern within their type
2. **Phase Numbers:** All resources include phase number for clarity
3. **Descriptive:** Names clearly indicate purpose and position in pipeline
4. **No Versioning:** Use phase numbers, not version suffixes (no `-v2`, `-v3`)
5. **Hyphen-Separated:** All names use hyphens, not underscores
6. **Lowercase:** All names are lowercase
7. **Sport Prefix:** All names start with `nba-` (future: `mlb-`, `nfl-`, etc.)

---

## Related Documentation

- **Topic Configuration:** `shared/config/pubsub_topics.py` (code constants)
- **Architecture:** `docs/architecture/04-event-driven-pipeline-architecture.md`
- **Infrastructure:** `docs/INFRASTRUCTURE_DEPLOYMENT_SUMMARY.md`
- **Migration Plan:** `docs/HANDOFF-2025-11-16-phase3-topics-deployed.md`

---

**For Questions:** This is the authoritative naming reference. When in doubt, follow these patterns.
