# Streaming Buffer Migration Checklist

**Last Updated:** 2025-11-27
**Status:** ✅ All High Priority Complete

---

## Summary

| Priority | Total | Fixed | Remaining |
|----------|-------|-------|-----------|
| P0 Critical | 2 | 2 | 0 |
| P1 High (DELETE+INSERT) | 11 | 11 | 0 |
| Phase 5 Predictions | 2 | 2 | 0 |
| **Total High Priority** | **15** | **15** | **0** |
| Low Priority (Logging) | ~10 | 0 | ~10 |

---

## ✅ P0: CRITICAL - COMPLETE

| File | Status | Fixed |
|------|--------|-------|
| `data_processors/raw/nbacom/nbac_player_boxscore_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/nbacom/nbac_team_boxscore_processor.py` | ✅ | 2025-11-27 |

---

## ✅ P1: DELETE + INSERT Pattern - COMPLETE

| File | Status | Fixed |
|------|--------|-------|
| `data_processors/raw/balldontlie/bdl_boxscores_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/espn/espn_boxscore_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/nbacom/nbac_play_by_play_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/nbacom/nbac_gamebook_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/bigdataball/bigdataball_pbp_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/nbacom/nbac_schedule_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/balldontlie/bdl_standings_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/balldontlie/bdl_active_players_processor.py` | ✅ | 2025-11-27 |
| `data_processors/raw/basketball_ref/br_roster_processor.py` | ✅ | 2025-11-27 |
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | ✅ | 2025-11-27 |
| `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` | ✅ | 2025-11-27 |

---

## ✅ Phase 5: Predictions - COMPLETE

| File | Status | Fixed |
|------|--------|-------|
| `predictions/worker/worker.py` | ✅ | 2025-11-27 |
| `predictions/worker/execution_logger.py` | ✅ | 2025-11-27 |

---

## ✅ Phase 3 & 4: Already Using Batch Loading

These processors use base classes that already implement batch loading:

| Phase | Processor | Base Class | Status |
|-------|-----------|------------|--------|
| Phase 3 | `player_game_summary_processor.py` | `AnalyticsProcessorBase` | ✅ Already OK |
| Phase 3 | `team_defense_game_summary_processor.py` | `AnalyticsProcessorBase` | ✅ Already OK |
| Phase 3 | `team_offense_game_summary_processor.py` | `AnalyticsProcessorBase` | ✅ Already OK |
| Phase 4 | `ml_feature_store_processor.py` | `PrecomputeProcessorBase` | ✅ Already OK |
| Phase 4 | `player_shot_zone_analysis_processor.py` | `PrecomputeProcessorBase` | ✅ Already OK |
| Phase 4 | `team_defense_zone_analysis_processor.py` | `PrecomputeProcessorBase` | ✅ Already OK |
| Phase 4 | `player_composite_factors_processor.py` | `PrecomputeProcessorBase` | ✅ Already OK |
| Phase 4 | `player_daily_cache_processor.py` | `PrecomputeProcessorBase` | ✅ Already OK |

Base classes use `load_table_from_file()` for main data:
- `analytics_base.py:1098`
- `precompute_base.py:726`

---

## Low Priority: Logging Tables Only

These use `insert_rows_json` for single-record logging. Low risk, no DELETE conflicts.

| File | Purpose | Risk |
|------|---------|------|
| `analytics_base.py:1205,1251` | Issue/run logging | Low |
| `precompute_base.py:832,880` | Issue/run logging | Low |
| `nbac_gamebook_processor.py:276,495` | Resolution logging | Low |
| `player_shot_zone_analysis_processor.py:944` | Failure logging | Low |
| `circuit_breaker_mixin.py:281` | State logging | Low |

---

## Low Priority: APPEND_ALWAYS Processors

No DELETE conflicts since they only append. Lower risk.

| File | Notes |
|------|-------|
| `bdl_injuries_processor.py` | APPEND_ALWAYS strategy |
| `nbac_injury_report_processor.py` | APPEND_ALWAYS strategy |
| `nbac_player_movement_processor.py` | APPEND_ALWAYS strategy |

---

## Low Priority: Reference/Registry Processors

Complex batching logic, evaluate separately if needed.

| File | Notes |
|------|-------|
| `database_strategies.py` | Custom batching |
| `registry_processor_base.py` | Single record upserts |
| `roster_registry_processor.py` | Alias processing |

---

## Deployment Status

- [x] Deploy Phase 2 auto-processor (Cloud Run) - **2025-11-27 06:44 UTC**
- [x] Deploy Phase 5 prediction worker (Cloud Run) - **2025-11-27 06:45 UTC**
- [ ] Retry failed backfill (303 dates)
- [ ] Monitor for 24 hours

---

## Verification

After deployment, verify no streaming buffer errors:

```sql
-- Check for DML limit errors (should be 0)
SELECT COUNT(*)
FROM `nba-props-platform.nba_processing.*`
WHERE LOWER(message) LIKE '%too many dml%'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR);
```
