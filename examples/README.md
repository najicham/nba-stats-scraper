# Architecture Examples

**Purpose:** Reference implementations and examples extracted from architecture documentation
**Created:** 2025-11-15
**Status:** Active reference directory

---

## Directory Structure

```
examples/
├── pubsub_integration/     # Pub/Sub publishers and message formats
├── monitoring/             # BigQuery queries for pipeline monitoring
└── recovery/               # DLQ replay and recovery scripts
```

---

## Pub/Sub Integration (`pubsub_integration/`)

**Reference implementations for event publishing:**

- `raw_data_publisher.py` - RawDataPubSubPublisher class for Phase 2 processors
- `message_examples.json` - Example messages for all phases

**Related docs:**
- `docs/architecture/01-phase1-to-phase5-integration-plan.md`
- `docs/architecture/04-event-driven-pipeline-architecture.md`

---

## Monitoring (`monitoring/`)

**BigQuery queries for pipeline health monitoring:**

- `pipeline_health_queries.sql` - Production-ready queries for Grafana dashboards
  - Pipeline completion status
  - Phase-by-phase breakdown
  - Recent failures
  - Entity tracking
  - Dependency check failures

**Related docs:**
- `docs/architecture/03-pipeline-monitoring-and-error-handling.md`
- `docs/orchestration/grafana-monitoring-guide.md`

---

## Recovery (`recovery/`)

**Scripts for DLQ monitoring and message replay:**

- `replay_dlq.sh` - Check DLQ health and replay messages

**Usage:**
```bash
# Check all DLQs
./replay_dlq.sh

# Pull messages from specific DLQ (without acking)
./replay_dlq.sh pull nba-raw-data-complete-dlq-sub 10
```

**Related docs:**
- `docs/architecture/03-pipeline-monitoring-and-error-handling.md` (Recovery Procedures)

---

## Usage Notes

**These are reference implementations:**
- Not directly executed (copied/adapted for actual use)
- Kept in sync with architecture docs
- Used as templates for implementation

**When implementing:**
1. Copy relevant example to appropriate location
2. Adapt to specific use case
3. Add error handling and logging as needed
4. Test thoroughly before deployment

---

## Relationship to Documentation

**Example files replace verbose code blocks in docs:**
- Docs focus on concepts and design decisions
- Examples provide working reference code
- Keeps docs concise while preserving detail

**Maintainence:**
- Update examples when architecture changes
- Reference examples from docs (don't duplicate)
- Archive old examples when superseded

---

**Last Updated:** 2025-11-15
**Maintainer:** Architecture documentation standards
