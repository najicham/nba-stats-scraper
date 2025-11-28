# Source Coverage System - Implementation Handoff

**Date:** 2025-11-26
**Status:** Design Complete, Ready for Implementation
**Previous Chat:** Completed full design, multiple review cycles, documentation finalized
**Documentation:** `docs/architecture/source-coverage/`

---

## Context for New Chat

This handoff covers the **Source Coverage System** - a system to track data availability from external sources (NBA.com, ESPN, Odds API) and handle gaps gracefully through automatic fallbacks, quality scoring, and silent failure detection.

### What Was Accomplished

1. **Complete system design** (6 documentation files)
2. **Multiple review cycles** incorporating feedback on:
   - Event buffering (prevents 13+ BQ load jobs per game)
   - Alert deduplication (buffer + DB check prevents storms)
   - Timezone handling (PT for game dates, not UTC)
   - Phase 4/5 quality inheritance examples
   - Reprocessing cascade workflow
   - Context manager auto-flush
3. **Conservative defaults** (historical data = silver, not gold)
4. **Future enhancements documented** (deferred items with triggers)

### Key Design Decisions Made (Do Not Change Without Good Reason)

| Decision | Rationale |
|----------|-----------|
| Event log, not state table | Simpler, natural audit trail, no sync issues |
| Quality columns on every table | Performance over storage (no JOINs needed) |
| "Worst wins" propagation | Quality can only degrade through pipeline, never improve |
| Mixin pattern | Composable, testable, gradual adoption |
| 5 quality tiers | Gold → Silver → Bronze → Poor → Unusable |
| Conservative backfill | Unknown historical quality defaults to silver |
| PT timezone for game dates | Matches NBA schedule |
| Buffer + DB alert dedup | Prevents duplicates within batch AND across batches |

---

## Documentation Map

```
docs/architecture/source-coverage/
├── 00-index.md                 # START HERE - overview, quick start, workflows
├── 01-core-design.md           # Architecture, terminology, design decisions
├── 02-schema-reference.md      # DDL, quality columns, migration scripts
├── 03-implementation-guide.md  # Python code: QualityMixin, FallbackSourceMixin
├── 04-testing-operations.md    # Tests, procedures, reprocessing workflow
└── 05-review-enhancements.md   # Optional enhancements, reference material
```

**Reading order for implementation:**
1. `00-index.md` - Get overview
2. `02-schema-reference.md` - Run DDL scripts
3. `03-implementation-guide.md` - Copy mixin code
4. `04-testing-operations.md` - Understand operations

---

## What's Ready (No Further Design Needed)

| Component | Location | Status |
|-----------|----------|--------|
| source_coverage_log table DDL | Part 2, Script 1 | ✅ Ready to run |
| Quality columns DDL | Part 2, Script 2 | ✅ Ready to run |
| QualityMixin class | Part 3 | ✅ Complete with buffering, dedup, auto-flush |
| FallbackSourceMixin class | Part 3 | ✅ Complete with source cascade |
| SourceCoverageAuditProcessor | Part 3 | ✅ Complete with dry-run mode |
| Phase 4 inheritance example | Part 3 | ✅ Shows "worst wins" implementation |
| Phase 5 confidence capping | Part 3 | ✅ Shows quality tier ceilings |
| Reprocessing workflow | Part 4 | ✅ Detection query + decision framework |
| Event type constants | Part 3 | ✅ Complete enum definitions |

---

## Implementation Steps (Priority Order)

### Step 1: Create Infrastructure (30 minutes)

```bash
# 1a. Create source_coverage_log table
# Copy DDL from docs/architecture/source-coverage/02-schema-reference.md (Script 1)
bq query --use_legacy_sql=false "
CREATE TABLE IF NOT EXISTS nba_reference.source_coverage_log (
  event_id STRING NOT NULL,
  event_timestamp TIMESTAMP NOT NULL,
  -- ... rest of schema from Part 2
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY severity, event_type, game_id;
"

# 1b. Add quality columns to player_game_summary
# Copy DDL from Part 2 (Script 2)
bq query --use_legacy_sql=false "
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
-- ... rest of columns from Part 2
"
```

### Step 2: Create Mixin Files (1 hour)

Create these files by copying code from Part 3:

```
shared_services/
├── processors/
│   ├── quality_mixin.py        # QualityMixin class
│   └── fallback_source_mixin.py # FallbackSourceMixin class
├── constants/
│   └── source_coverage.py      # Event types, severity levels, quality tiers
└── utils/
    └── source_coverage_utils.py # aggregate_quality_tiers(), helpers
```

### Step 3: Integrate into One Processor (1-2 hours)

Target: `PlayerGameSummaryProcessor`

```python
# Before:
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    pass

# After:
class PlayerGameSummaryProcessor(FallbackSourceMixin, QualityMixin, AnalyticsProcessorBase):
    REQUIRED_FIELDS = ['points', 'minutes', 'rebounds']
    OPTIONAL_FIELDS = ['plus_minus', 'shot_zones']

    PRIMARY_SOURCES = ['nbac_gamebook_player_stats']
    FALLBACK_SOURCES = ['bdl_player_boxscores', 'espn_game_boxscore']
```

### Step 4: Test with Real Data (30 minutes)

```bash
# Process one game with quality tracking
python -m data_processors.analytics.player_game_summary \
  --game_id 0022400001

# Verify quality columns populated
bq query --use_legacy_sql=false "
SELECT
  universal_player_id,
  quality_tier,
  quality_score,
  quality_issues,
  data_sources
FROM nba_analytics.player_game_summary
WHERE game_id = '0022400001'
LIMIT 5
"

# Verify events logged
bq query --use_legacy_sql=false "
SELECT event_type, severity, description
FROM nba_reference.source_coverage_log
WHERE game_id = '0022400001'
ORDER BY event_timestamp DESC
"
```

### Step 5: Implement Integration Tests (1 day)

The tests in Part 4 are skeletons with `raise NotImplementedError`. Implement in this order:

1. **test_alert_deduplication** - CRITICAL, prevents alert storms
2. **test_end_to_end_with_fallback** - Core functionality
3. **test_quality_propagates_phase3_to_phase5** - Validates design

### Step 6: Roll Out to Other Processors

After one processor works:
1. team_offense_game_summary
2. team_defense_game_summary
3. Phase 4 precompute tables
4. Phase 5 predictions (confidence capping)

---

## Prerequisites to Verify

### 1. Streaming Buffer Migration

Source coverage uses `load_table_from_json()` (batch loading), NOT `insert_rows_json()` (streaming).

```bash
# Check if target processor uses batch loading
grep -r "insert_rows_json\|load_table_from_json" data_processors/analytics/
```

If still using `insert_rows_json`, migrate first. See: `docs/08-projects/current/streaming-buffer-migration/`

### 2. Existing Infrastructure to Reuse

| Need | Use This | Location |
|------|----------|----------|
| Error alerts | `notify_error()` | `shared/utils/notification_system.py` |
| Warning alerts | `notify_warning()` | Same |
| Quality issues list | `self.quality_issues` | `analytics_base.py:86` |
| Source metadata | `self.source_metadata` | `analytics_base.py:83` |

---

## Known Gaps (Acknowledged, Not Blocking)

| Gap | Status | Notes |
|-----|--------|-------|
| Integration tests are skeletons | Implement during Step 5 | Part 4 has test outlines |
| No performance benchmarks | Add after 2 weeks production | Future enhancement |
| Historical data is silver | By design | Conservative, honest |

---

## Future Enhancements (Deferred)

Documented in `00-index.md` under "Future Enhancements". Only implement if pain points emerge:

| Enhancement | Trigger to Implement |
|-------------|---------------------|
| Alert backoff for extended outages | Alert fatigue during 2+ day outages |
| Reconstruction confidence levels | Perfect reconstruction unfairly penalized |
| Historical quality upgrade path | Need to "promote" silver → gold |
| API/frontend quality display | Building Phase 6 publishing |
| Configurable confidence ceilings | Different algorithms need different thresholds |

---

## Quick Reference

### Quality Tiers
```
Gold (95-100)   → Primary source, complete data
Silver (75-94)  → Backup source or reconstruction
Bronze (50-74)  → Thin sample or multiple issues
Poor (25-49)    → Significant gaps
Unusable (0-24) → Missing required fields, skip prediction
```

### Event Types
```python
SOURCE_AVAILABLE = 'source_available'
SOURCE_MISSING = 'source_missing'
FALLBACK_USED = 'fallback_used'
RECONSTRUCTION_APPLIED = 'reconstruction_applied'
QUALITY_DEGRADATION = 'quality_degradation'
SILENT_FAILURE_DETECTED = 'silent_failure_detected'
```

### Mixin Order (MRO Matters!)
```python
# CORRECT - FallbackSourceMixin first, base class last
class MyProcessor(FallbackSourceMixin, QualityMixin, AnalyticsProcessorBase):
    pass
```

---

## Checklist for New Chat

```
[ ] Read docs/architecture/source-coverage/00-index.md
[ ] Verify streaming buffer migration status
[ ] Create source_coverage_log table (Part 2, Script 1)
[ ] Add quality columns to player_game_summary (Part 2, Script 2)
[ ] Create shared_services/processors/quality_mixin.py
[ ] Create shared_services/processors/fallback_source_mixin.py
[ ] Create shared_services/constants/source_coverage.py
[ ] Integrate mixins into PlayerGameSummaryProcessor
[ ] Test with one real game
[ ] Implement test_alert_deduplication
[ ] Implement test_end_to_end_with_fallback
[ ] Roll out to additional processors
```

---

## Estimated Timeline

| Task | Time |
|------|------|
| Create infrastructure (tables, columns) | 30 min |
| Create mixin files | 1 hour |
| Integrate into one processor | 1-2 hours |
| Test with real data | 30 min |
| **First working processor** | **~4 hours** |
| Implement integration tests | 1 day |
| Roll out to all processors | 2-3 days |

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-26 | 2.0 | Initial complete design |
| 2025-11-26 | 2.1 | Adaptation notes for existing infrastructure |
| 2025-11-26 | 2.2 | Review feedback: buffering, dedup, timezone, Phase 4/5 examples |
| 2025-11-26 | 2.3 | Reprocessing workflow, auto-flush, future enhancements |
| 2025-11-26 | 2.4 | Fixed alert buffer deduplication bug |

---

*Handoff complete. Start with `docs/architecture/source-coverage/00-index.md`*
