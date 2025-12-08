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

**Timestamp Requirements (MANDATORY):**
- **ALWAYS** use Pacific Time with explicit timezone (PST or PDT)
- **ALWAYS** include time: `YYYY-MM-DD HH:MM AM/PM PST`
- **Example:** `2025-11-21 09:30 AM PST` (NOT just `2025-11-21`)
- Update "Last Updated" for significant content changes only
- Both fields required: "Created" and "Last Updated"
- **This applies to ALL documentation files - no exceptions**

### Documentation Organization (Reorganized 2025-11-25)

**Documentation Directory Structure:**
```
docs/
├── 00-start-here/     # Navigation, status, getting started
├── 01-architecture/   # System design & decisions
├── 02-operations/     # Daily ops, backfills, troubleshooting
├── 03-phases/         # Phase-specific documentation
│   ├── phase1-orchestration/
│   ├── phase2-raw/
│   ├── phase3-analytics/
│   ├── phase4-precompute/
│   ├── phase5-predictions/
│   └── phase6-publishing/
├── 04-deployment/     # Deployment status & guides
├── 05-development/    # Guides, patterns, testing
├── 06-reference/      # Quick lookups, processor cards
├── 07-monitoring/     # Grafana, alerts, observability
├── 08-projects/       # Active work tracking
├── 09-handoff/        # Session handoffs
└── archive/           # Historical documentation
```

**Where to Put New Documentation:**

| You're creating... | Put it in... |
|--------------------|--------------|
| Active project/task tracking | `08-projects/current/{project-name}/` |
| Session handoff notes | `09-handoff/sessions/` |
| Backfill documentation | `02-operations/backfill/` |
| Backfill runbooks | `02-operations/backfill/runbooks/` |
| Operational procedures | `02-operations/` |
| Phase-specific docs | `03-phases/phase{N}/` |
| How-to guides | `05-development/guides/` |
| Pattern documentation | `05-development/patterns/` |
| Quick reference/lookups | `06-reference/` |
| Monitoring/alerting | `07-monitoring/` |

**Full guide:** `docs/05-development/docs-organization.md`

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
  - Reference `docs/README.md` for quick "where to put docs" table
  - Reference `docs/05-development/docs-organization.md` for detailed guide
  - Active work/projects go in `docs/08-projects/current/{project-name}/`

## Documentation References

### Key Entry Points
- **Start Here**: `docs/00-start-here/README.md` - Navigation hub
- **System Status**: `docs/00-start-here/SYSTEM_STATUS.md` - Current deployment state
- **Where to Put Docs**: `docs/README.md` - Quick reference table

### Operational Guides by Topic

**Phase 1 Orchestration:**
- `bin/orchestration/README.md` - Workflow schedule system scripts
- `docs/03-phases/phase1-orchestration/how-it-works.md` - System overview
- `docs/03-phases/phase1-orchestration/overview.md` - Architecture & components
- `docs/03-phases/phase1-orchestration/troubleshooting.md` - Common issues & fixes

**Operations:**
- `docs/02-operations/troubleshooting-matrix.md` - Cross-phase troubleshooting
- `docs/02-operations/runbooks/` - Step-by-step runbooks

**Backfill Operations:**
- `docs/02-operations/backfill/README.md` - **START HERE** for backfill work
- `docs/02-operations/backfill/backfill-guide.md` - Comprehensive backfill procedures
- `docs/02-operations/backfill/data-gap-prevention-and-recovery.md` - Gap detection and recovery
- `docs/02-operations/backfill/cascade-contamination-prevention.md` - Preventing cascade failures
- `docs/02-operations/backfill/PHASE4-PERFORMANCE-ANALYSIS.md` - Performance benchmarks
- `docs/02-operations/backfill/runbooks/` - Phase-specific runbooks
- `docs/08-projects/current/backfill/` - Active project tracking (27+ files)

**Phase 5 Predictions:**
- `docs/03-phases/phase5-predictions/README.md` - Overview
- `docs/03-phases/phase5-predictions/tutorials/` - Getting started guides
- `docs/03-phases/phase5-predictions/operations/` - Deployment & operations

**Monitoring:**
- `docs/07-monitoring/grafana/monitoring-guide.md` - Comprehensive monitoring
- `docs/07-monitoring/grafana/daily-health-check.md` - Daily health checks

**Development:**
- `docs/05-development/guides/` - How-to guides
- `docs/05-development/patterns/` - All processing patterns
- `docs/05-development/testing/` - Test strategies

**Reference:**
- `docs/06-reference/processor-cards/` - Quick processor lookups
- `docs/06-reference/data-flow/` - Field mappings between phases

---

*Last Updated: 2025-12-08 11:50 AM PST*
*Recent Changes:*
- **2025-12-08**: Consolidated backfill documentation into `docs/02-operations/backfill/`
  - Added backfill navigation hub with key references
  - Moved data-gap-prevention, cascade-contamination, and performance analysis docs
  - Added "Backfill Operations" section to project instructions
- **2025-11-25**: Major documentation reorganization - 23 directories consolidated to 10 numbered directories
  - New structure: `00-start-here/` through `09-handoff/` + `archive/`
  - All phases consolidated in `03-phases/phase{1-6}/`
  - Active work tracking in `08-projects/current/`
  - All patterns consolidated in `05-development/patterns/`
  - Single archive location for all historical docs
- **2025-11-21**: Emphasized timestamp requirements (date + time + timezone mandatory)
- **2025-11-15**: Initial documentation reorganization

*Project Status:*
- **Phase 1 (Orchestration)**: ✅ Deployed to production (Nov 2025)
- **Phase 2 (Raw Processing)**: ✅ Deployed to production (Nov 2025)
- **Phase 3 (Analytics)**: ✅ Deployed to production (Nov 2025)
- **Phase 4 (Precompute)**: ✅ Deployed to production (Nov 2025)
- **Phase 5 (Predictions)**: 🧪 Testing
- **Phase 6 (Publishing)**: 🚧 Planned
