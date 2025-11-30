# Streaming Buffer Migration - Complete Processor Analysis

**Generated:** 2025-11-27
**Purpose:** Comprehensive analysis of all processors to determine migration priority

---

## Executive Summary

| Category | Count | Action Required |
|----------|-------|-----------------|
| Already Fixed/Using Batch | 6 | None |
| HIGH Priority (MERGE_UPDATE + Backfill risk) | 9 | Migrate ASAP |
| MEDIUM Priority (APPEND_ALWAYS) | 3 | Migrate when convenient |
| LOW Priority (Logging tables) | 5 | Optional |
| Reference Processors | 3 | Evaluate separately |

---

## Category 1: Already Using Batch Loading (No Action Required)

These processors already use `load_table_from_json()` or `load_table_from_file()`:

| Processor | Method | Notes |
|-----------|--------|-------|
| `nbac_player_boxscore_processor.py` | `load_table_from_json` | Fixed 2025-11-27 |
| `nbac_team_boxscore_processor.py` | `load_table_from_json` | Fixed 2025-11-27 |
| `odds_api_props_processor.py` | `load_table_from_json` | Already correct |
| `bettingpros_player_props_processor.py` | `load_table_from_json` | Already correct |
| `analytics_base.py` (save_analytics) | `load_table_from_file` | Line 1098 - main data |
| `precompute_base.py` (save_precompute) | `load_table_from_file` | Line 726 - main data |

---

## Category 2: HIGH Priority - MERGE_UPDATE with DELETE + INSERT

**Risk:** These do DELETE before INSERT. If streaming buffer exists, DELETE fails.
**Impact:** Breaks during backfills with multiple concurrent workers.

| Processor | Table | Strategy | Line | Backfill Risk |
|-----------|-------|----------|------|---------------|
| `bdl_boxscores_processor.py` | `nba_raw.bdl_player_boxscores` | MERGE_UPDATE | 632 | HIGH |
| `espn_boxscore_processor.py` | `nba_raw.espn_boxscores` | MERGE_UPDATE | 451 | HIGH |
| `nbac_play_by_play_processor.py` | `nba_raw.nbac_play_by_play` | MERGE_UPDATE | 642 | HIGH |
| `nbac_gamebook_processor.py` | `nba_raw.nbac_gamebook_player_stats` | MERGE_UPDATE | 1119 | HIGH |
| `bigdataball_pbp_processor.py` | `nba_raw.bigdataball_play_by_play` | MERGE_UPDATE | 509 | MEDIUM |
| `nbac_schedule_processor.py` | `nba_raw.nbac_schedule` | MERGE_UPDATE | 610 | LOW |
| `bdl_standings_processor.py` | `nba_raw.bdl_standings` | MERGE_UPDATE | 352 | LOW |
| `bdl_active_players_processor.py` | `nba_raw.bdl_active_players_current` | MERGE_UPDATE | 402 | LOW |
| `br_roster_processor.py` | `nba_reference.br_rosters_current` | MERGE_UPDATE | 297 | LOW |

### Recommendation: Migrate All 9 Processors

These should all be migrated to prevent issues during any future backfills or high-volume processing.

---

## Category 3: MEDIUM Priority - APPEND_ALWAYS Strategy

**Risk:** No DELETE/streaming buffer conflict, but still counts against 20 DML limit.
**Impact:** Could hit DML limit during very high-volume concurrent processing.

| Processor | Table | Strategy | Line |
|-----------|-------|----------|------|
| `bdl_injuries_processor.py` | `nba_raw.bdl_injuries` | APPEND_ALWAYS | 464 |
| `nbac_injury_report_processor.py` | `nba_raw.nbac_injury_report` | APPEND_ALWAYS | 403 |
| `nbac_player_movement_processor.py` | `nba_raw.nbac_player_movement` | APPEND_ALWAYS | 363 |

### Recommendation: Migrate for Consistency

Lower risk than MERGE_UPDATE processors, but worth migrating for consistency and to avoid DML limit issues.

---

## Category 4: LOW Priority - Logging/Metadata Tables

**Risk:** Low volume, single records at a time.
**Impact:** Unlikely to cause issues in practice.

| Processor | Table | Purpose | Line |
|-----------|-------|---------|------|
| `analytics_base.py` | `nba_processing.analytics_data_issues` | Issue logging | 1205 |
| `analytics_base.py` | `nba_processing.analytics_processor_runs` | Run logging | 1251 |
| `precompute_base.py` | `nba_processing.precompute_data_issues` | Issue logging | 832 |
| `precompute_base.py` | `nba_processing.precompute_processor_runs` | Run logging | 880 |
| `nbac_gamebook_processor.py` | `nba_processing.name_resolution_log` | Resolution logging | 276 |
| `nbac_gamebook_processor.py` | `nba_processing.resolution_performance` | Performance logging | 495 |
| `player_shot_zone_analysis_processor.py` | `nba_processing.precompute_failures` | Failure logging | 944 |

### Recommendation: Optional

These are low-volume logging operations. They could be migrated for consistency, but the risk is minimal.

---

## Category 5: Analytics Processors (Custom save_data)

**Note:** These override the base class and use `insert_rows_json` directly.

| Processor | Table | Strategy | Line |
|-----------|-------|----------|------|
| `upcoming_player_game_context_processor.py` | `nba_analytics.upcoming_player_game_context` | MERGE_UPDATE | 1536 |
| `upcoming_team_game_context_processor.py` | `nba_analytics.upcoming_team_game_context` | MERGE_UPDATE | 1674 |

### Recommendation: Migrate

These are important analytics tables. They do DELETE + INSERT and should be migrated.

---

## Category 6: Reference Processors

**Note:** Complex registry logic with custom batching.

| Processor | Table | Purpose | Lines |
|-----------|-------|---------|-------|
| `registry_processor_base.py` | Various | Single record upserts | 457 |
| `database_strategies.py` | Various | REPLACE mode with batching | 76, 367 |
| `roster_registry_processor.py` | Aliases/Unresolved | Processing records | 1481, 1551 |

### Recommendation: Evaluate Separately

These have complex batching logic and may need careful migration to preserve existing behavior.

---

## Migration Priority Order

### Phase 1: Immediate (Backfill Blockers)
1. ~~`nbac_player_boxscore_processor.py`~~ - DONE
2. ~~`nbac_team_boxscore_processor.py`~~ - DONE
3. `bdl_boxscores_processor.py` - Used in boxscore backfills
4. `espn_boxscore_processor.py` - Backup boxscore source

### Phase 2: High Priority (Other MERGE_UPDATE)
5. `nbac_play_by_play_processor.py` - Play-by-play backfill
6. `nbac_gamebook_processor.py` - Gamebook data
7. `bigdataball_pbp_processor.py` - BigDataBall PBP
8. `upcoming_player_game_context_processor.py` - Analytics
9. `upcoming_team_game_context_processor.py` - Analytics

### Phase 3: Medium Priority (Remaining MERGE_UPDATE)
10. `nbac_schedule_processor.py` - Schedule updates
11. `bdl_standings_processor.py` - Standings
12. `bdl_active_players_processor.py` - Active players
13. `br_roster_processor.py` - Rosters

### Phase 4: Lower Priority (APPEND_ALWAYS)
14. `bdl_injuries_processor.py`
15. `nbac_injury_report_processor.py`
16. `nbac_player_movement_processor.py`

### Phase 5: Optional (Logging/Reference)
17-23. Logging tables and reference processors

---

## Migration Template

For each processor, apply this pattern:

```python
# BEFORE: Streaming insert (causes DML limit + buffer issues)
result = self.bq_client.insert_rows_json(table_id, rows)
if result:
    errors.extend([str(e) for e in result])

# AFTER: Batch loading (no DML limit, no buffer)
table = self.bq_client.get_table(table_id)
job_config = bigquery.LoadJobConfig(
    schema=table.schema,
    autodetect=False,
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
)
load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
load_job.result()
```

---

## Decision Matrix

| If you want to... | Then migrate... |
|-------------------|-----------------|
| Run player boxscore backfill | Phase 1 (DONE) |
| Run any boxscore backfill safely | Phase 1 + Phase 2 (4 processors) |
| Run any backfill without issues | Phase 1-3 (13 processors) |
| Full migration for consistency | Phase 1-5 (all 23 processors) |
