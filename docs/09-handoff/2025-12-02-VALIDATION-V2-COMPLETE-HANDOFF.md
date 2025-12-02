# Validation System V2 - Complete Handoff

**Date:** 2025-12-02
**Status:** Production Ready
**Session Duration:** ~2 hours

---

## Quick Start

```bash
# Run validation for any date (chain view = default)
python3 bin/validate_pipeline.py 2021-10-19

# Run with legacy view (flat P1/P2 lists)
python3 bin/validate_pipeline.py 2021-10-19 --legacy-view

# JSON output
python3 bin/validate_pipeline.py 2021-10-19 --format json

# Date range validation
python3 bin/validate_pipeline.py 2021-10-19 2021-10-25

# With verbose output and missing player details
python3 bin/validate_pipeline.py today --verbose --show-missing
```

---

## What Was Done This Session

### 1. Bug Fixes
- **Fixed duplicate BQ queries** - Skip P1/P2 validation when chain view is used
- **Fixed progress bar** - No longer shows "P1? P2?" when phases are skipped
- **Fixed config mismatch** - odds_api vs bettingpros priority aligned with YAML
- **Fixed registry staleness** - Now uses processor_run_history instead of created_at

### 2. Features Added
- **Quality tier colors** - Gold=green, Silver=yellow, Bronze=orange
- **Wider source names** - 28→32 characters
- **JSON output for chain view** - `--format json` now includes chain data
- **Date range chain view** - Validates chains across date ranges

### 3. Code Quality
- **24 unit tests** - All passing in `tests/validation/test_validation_system.py`
- **Deprecation notes** - PHASE2_SOURCES marked as legacy config

### 4. Deployment Fixed
- **Prediction worker** - Deployed to prod (was failing on dev artifact registry)

---

## File Structure - What to Study

### Core Validation Files

```
shared/validation/
├── config.py                    # Central config (phases, quality tiers, tables)
├── chain_config.py              # Loads fallback chains from YAML
├── time_awareness.py            # Time context (today/yesterday/historical)
├── run_history.py               # Processor run history from BQ
├── firestore_state.py           # Orchestration state from Firestore
│
├── context/
│   ├── schedule_context.py      # Game schedule context
│   └── player_universe.py       # Player roster context
│
├── validators/
│   ├── base.py                  # Base classes (ValidationStatus, PhaseValidationResult)
│   ├── chain_validator.py       # V2 chain-based P1-2 validation
│   ├── maintenance_validator.py # Roster/registry validation
│   ├── phase1_validator.py      # GCS JSON validation (legacy)
│   ├── phase2_validator.py      # BQ raw validation (legacy)
│   ├── phase3_validator.py      # Analytics tables validation
│   ├── phase4_validator.py      # Precompute tables validation
│   └── phase5_validator.py      # Predictions validation
│
└── output/
    ├── terminal.py              # Terminal formatting (chain, legacy, colors)
    └── json_output.py           # JSON output formatting
```

### Configuration Files

```
shared/config/data_sources/
└── fallback_config.yaml         # Source of truth for chains (read this!)
```

### Entry Point

```
bin/validate_pipeline.py         # Main CLI script
```

### Tests

```
tests/validation/
└── test_validation_system.py    # 24 unit tests
```

### Documentation

```
docs/08-projects/current/validation/
├── VALIDATION-SCRIPT-DESIGN.md  # Original design
├── VALIDATION-V2-DESIGN.md      # V2 implementation spec
└── VALIDATION-V2-REVIEW.md      # Review findings and fixes applied
```

---

## Key Concepts

### Chain View vs Legacy View

| Aspect | Chain View (V2, Default) | Legacy View |
|--------|--------------------------|-------------|
| Flag | None (default) | `--legacy-view` |
| P1-P2 Display | Grouped by fallback chains | Flat lists per phase |
| Data Source | `fallback_config.yaml` | `config.py` PHASE2_SOURCES |
| Shows | Primary/fallback status | Individual table counts |
| Quality | Gold/silver/bronze with colors | Basic counts |

### Quality Tiers

| Tier | Score Range | Color | Production Ready |
|------|-------------|-------|------------------|
| Gold | 95-100 | Green | Yes |
| Silver | 75-94 | Yellow | Yes |
| Bronze | 50-74 | Orange | Yes |
| Poor | 25-49 | - | No |
| Unusable | 0-24 | - | No |

### Fallback Chains

The 7 chains defined in `fallback_config.yaml`:

1. **game_schedule** (critical) - nbac_schedule → espn_scoreboard
2. **player_boxscores** (critical) - nbac_gamebook → bdl_boxscores → espn_boxscores
3. **team_boxscores** (critical) - nbac_team → reconstructed → espn_team
4. **player_props** (warning) - odds_api → bettingpros
5. **game_lines** (info) - odds_api_game_lines
6. **injury_reports** (info) - nbac_injury → bdl_injuries
7. **shot_zones** (info) - bigdataball_pbp → nbac_pbp

---

## How the Validation Flow Works

```
validate_date()
    │
    ├─ get_time_context()        → Is today/yesterday/historical?
    ├─ get_schedule_context()    → How many games? Which teams?
    ├─ get_player_universe()     → How many players expected?
    │
    ├─ validate_phase1() ─┐
    ├─ validate_phase2() ─┤      (Skipped in chain view)
    │                     │
    ├─ validate_all_chains()     (Chain view - queries GCS + BQ)
    │
    ├─ validate_phase3()         → Analytics tables
    ├─ validate_phase4()         → Precompute tables
    ├─ validate_phase5()         → Predictions
    │
    └─ ValidationReport
```

---

## Important Implementation Details

### 1. Chain Validator Logic (`chain_validator.py`)

```python
# For each chain:
1. Query GCS file counts for each source
2. Query BQ record counts for each source
3. Determine source status (primary/fallback/available/missing/virtual)
4. Determine chain status (complete/partial/missing)
5. Generate impact message if fallback used
```

### 2. Virtual Sources

Some sources like `reconstructed_team_from_players` and `espn_team_boxscore` are **virtual** - they don't have their own tables but can be derived from other data. These show with `⊘ Virtual` status.

### 3. Time Awareness (`time_awareness.py`)

For today/yesterday dates:
- Shows "maintenance" section (roster/registry status)
- Calculates expected phase statuses based on time of day
- Example: At 3 AM, Phase 3 should be "in_progress"

### 4. Progress Bar Calculation

When chain view is used, phases 1-2 are not in `phase_results`, so:
- Progress bar only shows P3, P4, P5
- Weights are normalized to the validated phases

---

## Testing

```bash
# Run all validation tests
PYTHONPATH=. pytest tests/validation/test_validation_system.py -v

# Expected: 24 tests passed
```

---

## Common Issues and Solutions

### Issue: "P1? P2?" in progress bar
**Fixed:** Progress bar now only shows validated phases.

### Issue: Registry shows "1400+ days old"
**Fixed:** Now checks `processor_run_history` for last sync instead of `created_at`.

### Issue: Duplicate BQ queries
**Fixed:** Added `skip_phase1_phase2` parameter to skip legacy validators in chain view.

### Issue: Prediction worker deployment fails
**Cause:** Default environment is `dev` which lacks artifact registry.
**Solution:** Deploy to `prod`: `./bin/predictions/deploy/deploy_prediction_worker.sh prod`

---

## Remaining Low-Priority Items

1. **Consolidate PHASE2_SOURCES to YAML** - Currently duplicated in config.py and YAML

---

## Future Improvements & Potential Flags

### CLI Flags to Add

| Flag | Purpose | Priority | Effort |
|------|---------|----------|--------|
| `--phase=N` | Validate only phase N (e.g., `--phase=3`) | Medium | 1-2 hrs |
| `--chains=X,Y` | Validate specific chains only (e.g., `--chains=player_boxscores,team_boxscores`) | Low | 2-3 hrs |
| `--show-missing` | Show explicit list of missing players/games | Medium | 2-3 hrs |
| `--show-maintenance` | Force show maintenance section for historical dates | Low | 30 min |
| `--hide-maintenance` | Hide maintenance section for today/yesterday | Low | 30 min |
| `--summary-only` | Show only summary line, skip detailed tables | Low | 1 hr |
| `--quiet/-q` | Exit with code 0/1 only, no output (for CI) | Medium | 1 hr |
| `--fail-on=LEVEL` | Exit non-zero if status worse than LEVEL (e.g., `--fail-on=partial`) | Medium | 1-2 hrs |
| `--watch/-w` | Poll every N seconds, refresh display (for monitoring) | Low | 3-4 hrs |
| `--diff DATE1 DATE2` | Compare two dates side-by-side | Low | 4-5 hrs |
| `--export FILE` | Export results to file (`report.json`, `report.md`, `report.html`) | Low | 2-3 hrs |

### Feature Improvements

| Feature | Description | Priority | Effort |
|---------|-------------|----------|--------|
| **Date Range + Chain Summary** | Summarize chains across date range | High | 4-6 hrs |
| **Player Flow Tracking** | Show how players flow through phases (67→67→22→22→110) | Medium | 4-6 hrs |
| **Trend Analysis** | Show quality trends over last N days | Medium | 6-8 hrs |
| **Alert Integration** | Send Slack/email when validation fails | Medium | 3-4 hrs |
| **Phase 6 Support** | Add validation for published predictions | Low | 4-6 hrs |
| **Web Dashboard** | Visual chain status with drill-down | Low | 2-3 days |
| **GCS Path Auto-Discovery** | Auto-discover GCS paths instead of hardcoding | Low | 3-4 hrs |
| **Registry Sync Tracking** | Track registry sync runs, not just record `created_at` | Low | 2 hrs |
| **Config Consolidation** | Move PHASE2_SOURCES from config.py to YAML | Low | 2-3 hrs |
| **Caching** | Cache BQ results for repeated runs in same session | Low | 3-4 hrs |
| **Async BQ Queries** | Parallelize BQ queries for faster validation | Low | 4-5 hrs |

### Output Improvements

| Improvement | Description | Priority | Effort |
|-------------|-------------|----------|--------|
| **Responsive Width** | Adjust table widths based on terminal size | Low | 2 hrs |
| **Interactive Mode** | Arrow key navigation through phases | Low | 4-5 hrs |
| **Markdown Output** | `--format markdown` for docs/reports | Low | 2 hrs |
| **HTML Output** | `--format html` with styling | Low | 3-4 hrs |
| **Compact Mode** | Single-line-per-phase summary | Low | 1 hr |

### Architectural Improvements

| Improvement | Description | Priority | Effort |
|-------------|-------------|----------|--------|
| **Database-Driven Config** | Move chain config from YAML to database | Low | 1-2 days |
| **Historical Tracking** | Store validation results for trend analysis | Low | 1 day |
| **Processor Integration** | Use same validation logic in processors | Medium | 1-2 days |
| **API Endpoint** | REST API for validation (Cloud Function) | Low | 1 day |
| **CI/CD Integration** | Pre-merge validation checks | Medium | 4-6 hrs |

---

## Session 2 Fixes (2025-12-02)

1. **Removed hardcoded project IDs** - `chain_validator.py` and `maintenance_validator.py` now import `PROJECT_ID` from config
2. **Clarified run history comment** - `validate_pipeline.py:145` now clearly explains why run history is always fetched
3. **Added missing GCS path** - `espn_boxscores` now mapped to `espn/boxscores` in `GCS_PATH_MAPPING`
4. **Added 8 new tests** - Tests for `_build_impact_message()`, `_get_date_column()`, `get_chain_summary()`, and GCS path completeness
5. **Test count: 24 → 32** - All passing
6. **Enhanced date range JSON output** - Added comprehensive summary statistics for `--format json` with date ranges

---

## Related Systems

- **Backfill Project** - Uses validation to check data coverage (`docs/08-projects/current/backfill/`)
- **Monitoring/Alerting** - Validation results can trigger alerts
- **Prediction Pipeline** - Phase 5 validation checks predictions exist

---

## Deployment Status (as of 2025-12-02)

| Service | Status | URL |
|---------|--------|-----|
| Analytics Processors | ✅ Deployed | `https://nba-phase3-analytics-processors-*.run.app` |
| Precompute Processors | ✅ Deployed | `https://nba-phase4-precompute-processors-*.run.app` |
| Prediction Coordinator | ✅ Deployed | `https://prediction-coordinator-756957797294.us-west2.run.app` |
| Prediction Worker | ✅ Deployed | `https://prediction-worker-f7p3g7f6ya-wl.a.run.app` |

---

## For the Next Session

If working on validation:
1. Read `shared/config/data_sources/fallback_config.yaml` first
2. Read `shared/validation/chain_config.py` to understand how YAML is loaded
3. Run `python3 bin/validate_pipeline.py 2021-10-19` to see output
4. Run tests: `PYTHONPATH=. pytest tests/validation/test_validation_system.py -v`

If working on other areas:
- **Backfill**: See `docs/08-projects/current/backfill/00-START-HERE.md`
- **Documentation**: See `docs/09-handoff/NEXT_SESSION.md`

---

*Document created: 2025-12-02*
*Last validated: 2025-12-02*
