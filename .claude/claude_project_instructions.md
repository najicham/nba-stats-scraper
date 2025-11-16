# NBA Props Platform - Project Context

## Mission
Build profitable NBA player props prediction system (55%+ accuracy on over/under bets).

## Architecture Overview

### Six-Phase Data Pipeline
1. **Data Collection** (Phase 1): Scrapers → Cloud Storage JSON
   - 30+ scrapers: Odds API, NBA.com, Ball Don't Lie, BigDataBall, ESPN, Basketball Reference
2. **Raw Processing** (Phase 2): JSON → BigQuery raw tables
   - 21 processors with comprehensive validation
3. **Analytics** (Phase 3): Player/team game summaries, advanced metrics
4. **Precompute** (Phase 4): Performance aggregates, matchup history
5. **Predictions** (Phase 5): Rule-based + ML models + ensemble
6. **Publishing** (Phase 6): Firestore/JSON reports for frontend

Phases connected via **Pub/Sub event triggers**. Daily workflow: 6 AM scrapers → sequential execution.

### Phase 1 Orchestration (DEPLOYED)
**Status**: Production (deployed Nov 2025)

The orchestration system automates the daily data collection workflow:
- **Master Controller** (`orchestration/master_controller.py`): Makes workflow decisions based on schedule
- **Workflow Executor** (`orchestration/workflow_executor.py`): Executes scrapers via HTTP calls
- **Parameter Resolver** (`orchestration/parameter_resolver.py`): Resolves date/game parameters dynamically
- **BigQuery Tables** (`nba_orchestration` dataset):
  - `daily_expected_schedule`: Game schedule driving workflows
  - `workflow_decisions`: RUN/SKIP/ABORT decisions logged here
  - `workflow_executions`: Execution results and metrics
  - `scraper_execution_log`: Individual scraper run details

**Daily Health Check**: Run `./bin/orchestration/quick_health_check.sh` to verify orchestration health

**Script Documentation**: See `bin/orchestration/README.md` for detailed script usage

**Grafana Monitoring**:
- `docs/orchestration/grafana-daily-health-check-guide.md` - Quick 6-panel dashboard (start here!)
- `docs/orchestration/grafana-monitoring-guide.md` - Comprehensive monitoring queries

**Key Metrics** (typical day with 19 games):
- 38 workflow executions (morning_operations, betting_lines, injury_discovery, etc.)
- 500+ scraper runs (many are "no_data" hourly checks)
- 97-99% success rate expected

**Common Issues**:
- "no_data" status = successful run with no new data (not an error)
- Failed scrapers: Check `scraper_execution_log` for error_type and error_message
- Missing executions: Check `workflow_decisions` vs `workflow_executions` for gaps

## Technology Stack

- **GCP**: BigQuery (analytics), Cloud Storage (raw JSON), Cloud Run (services), Pub/Sub (orchestration)
- **Python**: pandas (transforms), XGBoost (ML), pytest (testing)
- **Data Sources**: Odds API (betting lines), NBA.com (official), Ball Don't Lie (backup), BigDataBall (play-by-play)

## Core Principles

### Data Quality First
- Discovery queries before assumptions about coverage
- Systematic validation, not quick fixes
- Season-aware thresholds (offseason ≠ playoffs)
- "Show must go on" - graceful degradation
- 99.2% player name resolution via universal registry

### BigQuery Optimization
- **Always filter partitions explicitly** (massive performance gains)
- Batch loading over streaming (avoid 90-min DML locks)
- MERGE for atomic updates

### Development Process
- **One small thing at a time** with comprehensive testing
- Documentation-first for complex features
- Phase-specific processors with clear contracts
- 180+ tests for Phase 5 alone

## File Organization

```
nba-props-platform/
├── orchestration/         # Phase 1: Workflow orchestration
│   ├── master_controller.py    # Workflow decision engine
│   ├── workflow_executor.py    # Scraper execution coordinator
│   ├── parameter_resolver.py   # Dynamic parameter resolution
│   └── cleanup_processor.py    # Missing file recovery
├── scrapers/              # Phase 1: Data collection
│   ├── oddsapi/          # Revenue-critical betting lines
│   ├── nbacom/           # Official NBA data
│   ├── balldontlie/      # Third-party backup
│   └── utils/            # Shared scraper utilities
├── processors/            # Phase 2-4: Data processing
│   ├── phase2_raw/       # JSON → BigQuery raw tables
│   ├── phase3_analytics/ # Game summaries and metrics
│   └── phase4_precompute/# Performance optimization layer
├── predictions/           # Phase 5: Prediction system
│   ├── algorithms/       # Moving Avg, Zone Matchup, XGBoost, Ensemble
│   └── features/         # ML feature engineering
├── shared/               # Cross-phase utilities
│   ├── nba_schedule.py   # Schedule and season logic
│   ├── team_mapping.py   # Team abbreviation mapping
│   ├── player_registry.py # Universal player IDs
│   └── notifications.py  # Slack/email alerts
├── config/               # Configuration files
├── tests/                # Comprehensive test suite
└── docs/                 # Technical documentation
```

## Key Patterns

### Scraper Parameters
- **Reference**: `docs/scrapers/parameter-formats-reference.md` (authoritative)
- Date formats: Mix of `YYYYMMDD` and `YYYY-MM-DD` depending on scraper
- Historical Odds API: **CRITICAL** - same timestamp for Events → Props to avoid 404s
- Always run `GetOddsApiEvents` before `GetOddsApiCurrentEventOdds`

### Processor Development
- **Reference**: `docs/processors/processor-development-guide.md`
- Inherit from base classes to reduce code duplication
- Include CLI tools for testing (`python -m processors.phase3.player_game_summary`)
- Comprehensive validation queries (expected patterns, not absolute truth)

### Testing Standards
- **Reference**: `docs/testing/unit-test-writing-guide-phase4.md`
- Unit tests for data transformations
- Integration tests for BigQuery queries
- Validation queries for data quality checks

### Season Logic
- October-December dates → current year is season start (e.g., 2024-12-15 = 2024-25 season)
- January-September dates → previous year is season start (e.g., 2025-01-15 = 2024-25 season)
- Season format: 4-digit year (e.g., `"2025"`) auto-converts to NBA format `"2025-26"`

### Player Name Resolution
- Basketball Reference rosters provide full names for NBA.com gamebook PDF parsing
- Universal Player IDs solve cross-source identification (99.2% accuracy)
- "Morant" → "Ja Morant" mapping critical for DNP reason extraction

## Common Commands

```bash
# === Orchestration Health Checks ===
# Quick health check (30 seconds) - START HERE for daily status
./bin/orchestration/quick_health_check.sh

# Detailed system status
./bin/orchestration/check_system_status.sh

# Verify Phase 1 orchestration is complete
./bin/orchestration/verify_phase1_complete.sh

# Query workflow execution results
bq query < bin/orchestration/check_workflow_results.sql

# View today's event timeline
./bin/orchestration/view_today_timeline.sh

# Investigate scraper failures in detail
./bin/orchestration/investigate_scraper_failures.sh

# === Scraper Operations ===
# Run scraper with debug output
python tools/fixtures/capture.py <scraper_name> --<param> <value> --debug

# === Processor Operations ===
# Run processor locally
python -m processors.phase3.player_game_summary

# === Testing ===
# Run tests for specific module
pytest tests/unit/processors/phase3/test_player_game_summary.py -v

# === Validation ===
# Validate BigQuery data
python tools/validation/validate_phase3_analytics.py --date 2025-01-15
```

## Critical Dependencies

### Scraper Dependencies (Must Run in Order)
1. `GetOddsApiEvents` → `GetOddsApiCurrentEventOdds` (props need event IDs)
2. `GetOddsApiEvents` → `GetOddsApiCurrentGameLines` (lines need event IDs)
3. For historical: Use **same timestamp** for Events → Odds to avoid 404s

### Data Dependencies
- Player registry must be populated before processing player stats
- Schedule data required before game-based processing
- Team mapping service needed for cross-source data integration

## Known Issues & Gotchas

- **Historical Odds API**: Events disappear at game time, use early morning timestamps (04:00-10:00 UTC)
- **ESPN Scoreboard**: Strict `YYYYMMDD` format (no dashes), unlike other scrapers
- **Playoff Handling**: Different data patterns require special processing
- **Team Mapping**: ESPN vs NBA.com format differences (resolved with mapping service)

## Documentation Standards

### Document Metadata Format

**All documentation files must include this header:**

```markdown
# Document Title

**File:** `docs/category/NN-document-name.md`
**Created:** YYYY-MM-DD HH:MM PST
**Last Updated:** YYYY-MM-DD HH:MM PST
**Purpose:** Brief description of document purpose
**Status:** Current|Draft|Superseded|Archive
```

**Timestamp Requirements:**
- Use Pacific Time with explicit timezone (PST or PDT)
- Format: `2025-11-15 14:30 PST` (date, time, timezone)
- Update "Last Updated" for significant content changes only
- Both fields required: "Created" and "Last Updated"

### Documentation Organization

**Two complementary guides for documentation:**

1. **`docs/DOCS_DIRECTORY_STRUCTURE.md`** - WHERE to put docs (which directory)
   - 6 top-level doc directories with clear purposes
   - Decision tree: "I have a doc about X, where does it go?"
   - Migration guide from old structure

2. **`docs/DOCUMENTATION_GUIDE.md`** - HOW to organize files within directories
   - Chronological numbering (01-99) for files
   - README.md with reading order
   - Archive pattern for completed docs

**Documentation Directory Structure:**
```
docs/
├── architecture/       # Design, planning, future vision
├── orchestration/      # Phase 1: Scheduler & daily workflows
├── infrastructure/     # Cross-phase: Pub/Sub, shared services
├── processors/         # Phase 2+: Data processor operations
├── monitoring/         # Cross-phase: Grafana, observability
└── data-flow/          # Phase-to-phase data mappings
```

**When creating new documentation:**
1. Determine which directory using `DOCS_DIRECTORY_STRUCTURE.md`
2. Find next available number (chronological)
3. Use standard metadata header
4. Update directory's README.md with reading order

### Documentation Types

**Evergreen (update in place):**
- Operations guides
- How-to documentation
- System architecture (current)
- Monitoring guides

**Point-in-Time (archive when superseded):**
- Status reports
- Gap analyses
- Session handoffs
- Implementation plans (after complete)

## Working Style Preferences

- Prefer creating files/artifacts unless content is very small
- Include file paths in comments near top of files
- For markdown docs, include path in backticks below title AND use standard metadata header
- When unsure, ask clarifying questions rather than making assumptions
- When organizing documentation:
  - Reference `docs/DOCS_DIRECTORY_STRUCTURE.md` for WHERE to put docs
  - Reference `docs/DOCUMENTATION_GUIDE.md` for HOW to organize files

## Documentation References

### Documentation Organization Guides
- **Directory Structure**: `docs/DOCS_DIRECTORY_STRUCTURE.md` - Where to put docs
- **File Organization**: `docs/DOCUMENTATION_GUIDE.md` - How to organize within directories

### Operational Guides by Topic

**Phase 1 Orchestration:**
- `bin/orchestration/README.md` - Workflow schedule system scripts
- `docs/orchestration/01-how-it-works.md` - System overview
- `docs/orchestration/02-phase1-overview.md` - Architecture & components
- `docs/orchestration/03-bigquery-schemas.md` - Orchestration table schemas
- `docs/orchestration/04-troubleshooting.md` - Common issues & fixes

**Infrastructure (Cross-Phase):**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub testing
- `docs/infrastructure/02-pubsub-schema-management.md` - Message schemas

**Data Processors:**
- `docs/processors/01-phase2-operations-guide.md` - Phase 2 raw processors

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring
- `docs/monitoring/02-grafana-daily-health-check.md` - Daily health checks

**Other Technical Docs:**
- **Scrapers**: `docs/scrapers/parameter-formats-reference.md` (comprehensive params)
- **Testing**: `docs/testing/unit-test-writing-guide-phase4.md` (test patterns)
- **Schema Changes**: `docs/data/schema-change-management-process.md` (change process)

---

*Last Updated: 2025-11-15*
*Recent Changes:*
- Reorganized documentation into 6 focused directories (architecture, orchestration, infrastructure, processors, monitoring, data-flow)
- Created `docs/DOCS_DIRECTORY_STRUCTURE.md` - guide for directory organization
- Updated documentation references to reflect new structure
- Split orchestration docs: Phase 1 only in orchestration/, cross-phase in infrastructure/, monitoring in monitoring/

*Project Status:*
- **Phase 1 (Orchestration)**: ✅ Deployed to production (Nov 2025)
- **Phase 5 (Predictions)**: ✅ Complete
- **Phase 4 (Precompute)**: 🚧 In progress
