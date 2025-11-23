# 00: Processor Development Guides - Overview

**Created**: 2025-11-21 15:05 PST
**Last Updated**: 2025-11-21 18:31 PST
**Version**: 1.2

---

## Welcome to Processor Development Guides

This directory contains comprehensive documentation for developing NBA stats processors with the latest patterns and best practices.

---

## Quick Navigation

### Getting Started

**New to processor development?**
1. Start with **[02-quick-start-processor.md](./02-quick-start-processor.md)** (5-minute quickstart)
2. Then read **[01-processor-development-guide.md](./01-processor-development-guide.md)** (comprehensive guide)

**Implementing specific patterns?**
- See **[processor-patterns/](./processor-patterns/)** directory for deep-dives

---

## Guide Structure

### Main Guides

| Guide | Description | Audience | Time |
|-------|-------------|----------|------|
| **[01-processor-development-guide.md](./01-processor-development-guide.md)** | Comprehensive processor development guide (v4.0) | All developers | 30-45 min |
| **[02-quick-start-processor.md](./02-quick-start-processor.md)** | 5-minute quickstart with minimal examples | New developers | 5 min |
| **[03-backfill-deployment-guide.md](./03-backfill-deployment-guide.md)** | Guide for deploying backfill jobs to production | Operations, Developers | 20 min |
| **[04-schema-change-process.md](./04-schema-change-process.md)** | Safe schema change management across all phases | All developers | 25 min |
| **[05-processor-documentation-guide.md](./05-processor-documentation-guide.md)** | Guide for documenting processors (cards vs full docs) | All developers | 15 min |
| **[06-bigquery-best-practices.md](./06-bigquery-best-practices.md)** | Schema enforcement, streaming buffer, graceful failure patterns | All developers | 20 min |

### Pattern Deep-Dives

| Pattern | Description | Phase | Time |
|---------|-------------|-------|------|
| **[01-smart-idempotency.md](./processor-patterns/01-smart-idempotency.md)** | Skip BigQuery writes when data unchanged (~50% reduction) | Phase 2 | 20 min |
| **[02-dependency-tracking.md](./processor-patterns/02-dependency-tracking.md)** | Check upstream data + track source metadata (4 fields/source) | Phase 3 | 25 min |
| **[03-backfill-detection.md](./processor-patterns/03-backfill-detection.md)** | Automatically find historical data gaps for backfill | Phase 3 | 20 min |
| **[04-smart-reprocessing.md](./processor-patterns/04-smart-reprocessing.md)** | Skip Phase 3 processing when Phase 2 source unchanged (~30-50% reduction) | Phase 3 | 20 min |
| **[05-phase4-dependency-tracking.md](./processor-patterns/05-phase4-dependency-tracking.md)** | Phase 4 streamlined dependency tracking (3 fields/source, no hash) | Phase 4 | 15 min |

---

## What's New in v4.0 (2025-11-21)

### Smart Idempotency (Pattern #14) - Phase 2
- **Impact**: 50% reduction in BigQuery writes
- **Adoption**: 22/22 Phase 2 processors (100%)
- **Status**: Deployed in production

### Dependency Tracking - Phase 3
- **What**: Validates upstream data availability & freshness
- **Fields**: 4 per source (last_updated, rows_found, completeness_pct, **hash**)
- **Adoption**: 5/5 Phase 3 processors (100%)
- **Status**: Deployed in production

### Smart Reprocessing - Phase 3
- **What**: Skip Phase 3 processing when Phase 2 source data unchanged
- **Impact**: 30-50% reduction in Phase 3 processing
- **Adoption**: 5/5 Phase 3 processors (100%)
- **Status**: **Just implemented (2025-11-21)**

### Backfill Detection - Phase 3
- **What**: Automatically find games with Phase 2 data but no Phase 3 analytics
- **Automation**: Daily cron job ready to deploy
- **Status**: Ready for deployment

---

## Recommended Reading Path

### Path 1: New Developer (Never Built a Processor)

1. **[02-quick-start-processor.md](./02-quick-start-processor.md)** (5 min)
   - Get basic processor running quickly
   - Understand minimum code needed

2. **[01-processor-development-guide.md](./01-processor-development-guide.md)** (30 min)
   - Learn comprehensive patterns
   - Understand architecture
   - Study best practices

3. **[processor-patterns/01-smart-idempotency.md](./processor-patterns/01-smart-idempotency.md)** (20 min)
   - Implement smart idempotency
   - Test hash tracking

4. Study existing processors:
   - `data_processors/raw/balldontlie/bdl_active_players_processor.py`
   - `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

### Path 2: Experienced Developer (Updating Existing Processor)

1. **[01-processor-development-guide.md](./01-processor-development-guide.md)** - Section "What's New in v4.0"
   - Quick overview of latest changes

2. **[processor-patterns/01-smart-idempotency.md](./processor-patterns/01-smart-idempotency.md)** - "Migration Guide"
   - Upgrade existing Phase 2 processor

3. **[processor-patterns/02-dependency-tracking.md](./processor-patterns/02-dependency-tracking.md)** (if Phase 3)
   - Add dependency checking
   - Implement hash tracking

### Path 3: Operations/Maintenance (Running Backfill Jobs)

1. **[processor-patterns/03-backfill-detection.md](./processor-patterns/03-backfill-detection.md)**
   - Understand backfill detection
   - Run automated backfill job
   - Schedule daily cron job

2. **[01-processor-development-guide.md](./01-processor-development-guide.md)** - "Testing & Debugging"
   - Troubleshoot processor issues
   - Verify data completeness

---

## Architecture Overview

### Processing Pipeline

```
Phase 1: Data Collection (Scrapers)
  ↓ (Raw JSON to GCS)

Phase 2: Raw Processing (INDEPENDENT)
  ├─ Extract from GCS
  ├─ Transform data
  └─ Load to BigQuery
      ├─ Smart Idempotency: Compute data_hash
      ├─ Smart Idempotency: Compare with previous hash
      └─ Smart Idempotency: Skip write if unchanged ✅
  ↓ (If data written)
  Pub/Sub trigger to Phase 3

Phase 3: Analytics Processing (INTEGRATED)
  ├─ Dependency Tracking: Check Phase 2 dependencies
  ├─ Dependency Tracking: Track source hash (4 fields/source)
  ├─ Smart Reprocessing: Compare current vs previous hashes
  ├─ Smart Reprocessing: Skip processing if unchanged ✅
  ├─ Extract data (if not skipped)
  ├─ Transform & compute analytics
  └─ Load to BigQuery
  ↓ (If data written)
  Pub/Sub trigger to Phase 4

Separate Tools:
  Backfill Detection: Find Phase 2 data without Phase 3 analytics
  (Run via cron job or manually)
```

### Pattern Classification

**Processing Optimization Patterns** (Independent)
- **Smart Idempotency** (Phase 2): Skip writes when data unchanged
- **Smart Reprocessing** (Phase 3): Skip processing when source unchanged

**Data Quality Patterns** (Framework)
- **Dependency Tracking** (Phase 3): Validate upstream data availability
- **Backfill Detection** (Phase 3): Find historical data gaps

**How They Work Together:**
```
Smart Idempotency (Phase 2)
  └─ Produces: data_hash column
      ↓
Dependency Tracking (Phase 3)
  ├─ Extracts: data_hash from Phase 2
  └─ Stores: 4 fields per source (including hash)
      ↓
Smart Reprocessing (Phase 3)
  ├─ Uses: Hashes from dependency tracking
  └─ Compares: Current vs previous to decide skip/process
```

**Independent Tool:**
```
Backfill Detection
  └─ Finds: Phase 2 data without Phase 3 analytics
      (Separate BigQuery queries, not part of run flow)
```

---

## File Organization

```
docs/guides/
├── 00-overview.md (this file)
├── 01-processor-development-guide.md (comprehensive guide)
├── 02-quick-start-processor.md (5-minute quickstart)
└── processor-patterns/
    ├── 01-smart-idempotency.md
    ├── 02-dependency-tracking.md
    └── 03-backfill-detection.md
```

---

## Additional Resources

### Implementation Documentation
- **Implementation Plan**: `docs/implementation/IMPLEMENTATION_PLAN.md`
- **Session Summary**: `docs/SESSION_SUMMARY_2025-11-21.md`
- **Handoff Document**: `docs/HANDOFF-2025-11-21-phase3-dependency-enhancement.md`

### Reference Documentation
- **Dependency Checks**: `docs/dependency-checks/00-overview.md`
- **Phase 2 Hash Strategy**: `docs/reference/phase2-processor-hash-strategy.md`
- **Scraper Mapping**: `docs/reference/scraper-to-processor-mapping.md`

### Testing
- **Unit Tests**: `tests/unit/patterns/`
- **Manual Tests**: `tests/manual/`
- **Test All Phase 3**: `python tests/unit/patterns/test_all_phase3_processors.py`

### Automation
- **Backfill Job**: `bin/maintenance/phase3_backfill_check.py`
- **Schema Check**: `bin/maintenance/check_schema_deployment.sh`

---

## Common Tasks

### Create New Phase 2 Processor
```bash
# 1. Read quick start
docs/guides/02-quick-start-processor.md

# 2. Copy template
cp data_processors/raw/balldontlie/bdl_active_players_processor.py \
   data_processors/raw/my_source/my_processor.py

# 3. Update: TABLE_NAME, UNIQUE_KEYS, extract/transform/load
# 4. Smart idempotency works automatically (via mixin)
# 5. Deploy schema, test, deploy to Cloud Run
```

### Create New Phase 3 Processor
```bash
# 1. Read dependency tracking guide
docs/guides/processor-patterns/02-dependency-tracking.md

# 2. Copy template
cp data_processors/analytics/player_game_summary/player_game_summary_processor.py \
   data_processors/analytics/my_analytics/my_processor.py

# 3. Update: DEPENDENCIES, target_table, extract/transform/load
# 4. Add source tracking (4 fields per dependency)
# 5. Deploy schema, test, deploy to Cloud Run
```

### Run Backfill Job
```bash
# 1. Dry run first
python bin/maintenance/phase3_backfill_check.py --dry-run

# 2. Check output (lists games needing processing)

# 3. Process backfill
python bin/maintenance/phase3_backfill_check.py

# 4. Schedule daily (add to crontab)
0 2 * * * cd /path && python bin/maintenance/phase3_backfill_check.py >> logs/backfill.log 2>&1
```

### Troubleshoot Processor Issues
```bash
# 1. Check comprehensive guide troubleshooting section
docs/guides/01-processor-development-guide.md

# 2. Check pattern-specific troubleshooting
docs/guides/processor-patterns/01-smart-idempotency.md (for Phase 2)
docs/guides/processor-patterns/02-dependency-tracking.md (for Phase 3)

# 3. Run manual test
python tests/manual/test_my_processor.py

# 4. Check logs for errors
```

---

## Version History

### v4.0 (2025-11-21)
- Added smart idempotency pattern (100% Phase 2 adoption)
- Added hash tracking (4 fields per source)
- Added backfill detection
- Comprehensive testing infrastructure
- Automated maintenance jobs

### v3.0 (Previous)
- Basic dependency checking
- 3 fields per source tracking
- Manual backfill

---

## Questions?

- **Implementation issues**: See `docs/implementation/IMPLEMENTATION_PLAN.md`
- **Recent changes**: See `docs/SESSION_SUMMARY_2025-11-21.md`
- **Architecture decisions**: See `docs/design/01-architectural-decisions.md`
- **Operations**: See `docs/predictions/operations/` directory

---

**Happy coding!** Start with the quick-start guide and work your way up to the comprehensive patterns.
