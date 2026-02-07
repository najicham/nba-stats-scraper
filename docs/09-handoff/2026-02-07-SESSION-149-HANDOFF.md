# Session 149 Handoff - BDL Cleanup + Build Optimization

**Date:** 2026-02-07
**Commit:** `5a123df1` (+ follow-up commit for BDL monitoring)
**All 6 services deployed:** SUCCESS

## What Was Done

### Task 1: BDL Query Migration (HIGH) - COMPLETE

Migrated all active `bdl_player_boxscores` queries to `nbac_gamebook_player_stats` across 5 files (8 total queries):

| File | Queries Changed | Notes |
|------|----------------|-------|
| `shared/utils/completeness_checker.py` | 5 | `_query_dnp_games`, `check_raw_boxscore_for_player`, `check_raw_boxscore_batch`, `get_player_game_dates`, `get_player_game_dates_batch` |
| `shared/utils/postponement_detector.py` | 1 | Removed entire BDL CTE + `has_bdl` field (gamebook check already existed) |
| `shared/validation/continuous_validator.py` | 1 | Freshness check `bdl_boxscores` → `gamebook_stats` |
| `shared/validation/context/player_universe.py` | 1 | Fallback function now queries nbac |
| `shared/utils/daily_scorecard.py` | 1 | Bonus find: data completeness query (kept `bdl_games` BQ column name for schema compat) |

**DNP detection fix:** Changed `WHERE (minutes = '00' OR minutes = '' OR minutes IS NULL OR minutes = '0')` to `WHERE (minutes IS NULL OR minutes = '00:00')` to match nbac format (nbac uses MM:SS strings, NULL for DNP).

**Field compatibility verified:** Both tables have identical `player_lookup` (STRING), `game_date` (DATE), `team_abbr` (STRING), `minutes` (STRING) columns.

**NOT changed (per instructions):** Config files (`fallback_config.yaml`, `validation/config.py`, `chain_config.py`, `scraper_retry_config.yaml`) - these correctly declare BDL as a fallback source.

### Task 2: Cloud Build Optimization (MEDIUM) - COMPLETE

| Sub-task | Change | Expected Savings |
|----------|--------|-----------------|
| Lock files | Generated `requirements-lock.txt` for raw (65 packages) + scrapers (82 packages) | ~30-60s per build |
| Dockerfile reorder | All 6 Dockerfiles: requirements COPY → pip install → code COPY | ~1-2min on code-only changes (with caching) |
| Error suppression | Removed `\|\| true` from scrapers pip install | Prevents silent failures |
| GCS model download | Lighter `gsutil` image, conditional skip for non-worker services | ~2min for non-worker builds |

**Note:** Cloud Build doesn't cache Docker layers by default. The reordering helps local builds immediately. To enable Cloud Build caching, add Kaniko or `--cache-from` in the future.

### Bonus: BDL Service Issue Tracking - NEW

Created tools to track and report BDL issues for vendor communication:

1. **BigQuery view** `nba_orchestration.bdl_service_issues` - Consolidates daily BDL health from `bdl_game_scrape_attempts` + `source_discrepancies`. Shows issue_type (FULL_OUTAGE/PARTIAL_OUTAGE/QUALITY_DEGRADATION/OPERATIONAL) per day.

2. **Report script** `bin/monitoring/bdl_issue_report.py` - Generates formatted markdown/text reports for vendor contact.

3. **SQL definition** `schemas/bigquery/views/bdl_service_issues.sql` - Source-controlled view definition.

**Usage:**
```bash
# Quick query
bq query --use_legacy_sql=false "SELECT * FROM nba_orchestration.bdl_service_issues LIMIT 15"

# Generate full report
PYTHONPATH=. python bin/monitoring/bdl_issue_report.py --format markdown --days 45
PYTHONPATH=. python bin/monitoring/bdl_issue_report.py --output bdl_report.md
```

## Current BDL Status

**Verdict: 33 days tracked, 32 full outage days, 2.4% data delivery rate.**

| Metric | Value |
|--------|-------|
| Monitoring period | Jan 1 - Feb 7, 2026 |
| Full outage days | 32/33 (97%) |
| Operational days | 0 |
| Data delivery rate | 2.4% (6/254 games) |
| Major data mismatches | 57 (on the few days data was returned) |
| Status since Jan 28 | FULL_OUTAGE (continuous) |

## Remaining BDL References

These are config/declaration files that correctly reference BDL as a fallback source. They do NOT actively query the disabled table:

- `shared/config/scraper_retry_config.yaml`
- `shared/config/data_sources/fallback_config.yaml`
- `shared/validation/config.py`
- `shared/validation/chain_config.py`
- `shared/processors/patterns/smart_skip_mixin.py`
- `shared/processors/patterns/fallback_source_mixin.py`
- `shared/processors/patterns/quality_columns.py`
- `shared/validation/phase_boundary_validator.py`
- `shared/validation/validators/phase1_validator.py`
- `shared/validation/validators/phase2_validator.py`

These should be cleaned up when BDL is formally decommissioned.

## Deployment Status

All 6 services deployed via Cloud Build auto-deploy at `5a123df1`:

| Service | Build ID | Status |
|---------|----------|--------|
| nba-scrapers | f139f1f2 | SUCCESS |
| nba-phase2-raw-processors | bc96d8d7 | SUCCESS |
| prediction-coordinator | aaf510ac | SUCCESS |
| prediction-worker | 7a7b537d | SUCCESS |
| nba-phase3-analytics-processors | 6a616426 | SUCCESS |
| nba-phase4-precompute-processors | 592207df | SUCCESS |

## Next Session Priorities

1. **Decide on BDL** - Run `PYTHONPATH=. python bin/monitoring/bdl_issue_report.py` to generate cancellation evidence
2. **Breakout V3** - Add contextual features (star_teammate_out, opponent injuries) per Session 135 roadmap
3. **Feature completeness** - Reduce default_feature_count gaps to increase prediction coverage (currently ~75/game)
