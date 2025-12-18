# Frontend API Backend - Project Overview

**Created:** December 17, 2025
**Updated:** December 18, 2025
**Status:** Planning
**Priority:** Critical

---

## CRITICAL DISCOVERY (Read First!)

During the December 2025 audit, we discovered that **prediction result tracking infrastructure already exists** but isn't running:

| Component | Schema | Code | Data |
|-----------|--------|------|------|
| `prediction_accuracy` table | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `system_daily_performance` table | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `PredictionAccuracyProcessor` | N/A | :white_check_mark: | N/A |
| Phase 6 JSON Exporters | N/A | :white_check_mark: | N/A |

**The schema and code exist. Only the data is missing because the grading job hasn't been running.**

### Immediate Action Required

```bash
# Run the backfill to populate prediction accuracy data
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-10-21 \
  --end-date 2025-12-17
```

---

## Executive Summary

This project delivers the backend infrastructure for the Props Web frontend. The infrastructure is **more complete than initially thought**:

### What EXISTS (95% of infrastructure):
- All 8 core BigQuery data tables
- Prediction grading system (Phase 5B) - just needs to run
- Phase 6 JSON exporters - just need data

### What's MISSING:
1. **Prediction grading not running** - Run backfill + schedule daily job
2. **No API Layer** - Need REST endpoints (recommend separate `props-api` repo)
3. **No multi-dimensional summaries** - Need `prediction_performance_summary` table for player/archetype aggregates

---

## Purpose

Backend infrastructure for:
- **Player Modal** - Deep dive into individual player analysis
- **Trends Page** - League-wide trends and patterns
- **Prediction Performance** - Track record of prediction accuracy

---

## Key Documents

| Document | Purpose | Key Content |
|----------|---------|-------------|
| [01 - Data Infrastructure Audit](./01-data-infrastructure-audit.md) | What exists vs what's missing | Prediction tracking architecture diagram |
| [02 - Implementation Plan](./02-implementation-plan.md) | Phased build-out strategy | SQL and Python code |
| [03 - API Specification](./03-api-specification.md) | Endpoint contracts | Full REST API spec |
| [04 - Schema Changes](./04-schema-changes.md) | Database modifications | NEW: prediction_performance_summary |
| [05 - Background Jobs](./05-background-jobs.md) | Scheduled processors | Grading job schedules |

---

## Prediction Tracking Architecture

```
┌─────────────────────────────────────────┐
│  player_prop_predictions                │  Phase 5A - Raw predictions
│  STATUS: Has data                       │
└─────────────────────────────────────────┘
                    │
                    │ PredictionAccuracyProcessor
                    ▼
┌─────────────────────────────────────────┐
│  prediction_accuracy                    │  Phase 5B - Per-prediction grading
│  STATUS: EMPTY - RUN BACKFILL           │
└─────────────────────────────────────────┘
                    │
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────────┐  ┌──────────────────────────┐
│ system_daily_    │  │ prediction_performance_  │
│ performance      │  │ summary                  │  NEW TABLE
│ STATUS: EMPTY    │  │ (by player/archetype/    │
└──────────────────┘  │  confidence/situation)   │
                      └──────────────────────────┘
```

---

## Status Summary

| Component | Status | Action |
|-----------|--------|--------|
| Core Data Tables (8/8) | :white_check_mark: Ready | None needed |
| `prediction_accuracy` | :yellow_circle: Empty | Run backfill |
| `system_daily_performance` | :yellow_circle: Empty | Populated with accuracy |
| `prediction_performance_summary` | :red_circle: New | Create table + processor |
| Days Rest / B2B View | :yellow_circle: Need View | Create view |
| API Layer | :red_circle: Missing | Build FastAPI service |

---

## Quick Start (Priority Order)

### 1. Run Prediction Accuracy Backfill (Do First!)

```bash
# Backfill the season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-10-21 \
  --end-date 2025-12-17
```

### 2. Verify Data

```sql
SELECT system_id, COUNT(*) as predictions,
       AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as hit_rate
FROM nba_predictions.prediction_accuracy
GROUP BY system_id;
```

### 3. Create Performance Summary Table

```bash
# Create the new table
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/prediction_performance_summary.sql

# Run the aggregation processor
PYTHONPATH=. .venv/bin/python data_processors/grading/performance_summary/performance_summary_processor.py
```

### 4. Schedule Daily Jobs

Add to Cloud Scheduler:
- `prediction_accuracy_grading` - Daily 6 AM ET
- `performance_summary_aggregation` - Daily 6:30 AM ET

---

## Key Files Reference

### Prediction Grading (EXISTS)
- Schema: `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- Processor: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- Backfill: `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`

### Performance Summary (NEW)
- Schema: `schemas/bigquery/nba_predictions/prediction_performance_summary.sql`
- Processor: `data_processors/grading/performance_summary/performance_summary_processor.py`

### Phase 6 Exporters (EXISTS - needs data)
- Results: `data_processors/publishing/results_exporter.py`
- System Performance: `data_processors/publishing/system_performance_exporter.py`

---

## Data Sources Available

All tables exist and have data:

| Table | Records | Key Fields |
|-------|---------|------------|
| `player_game_summary` | 500k+ | points, usage_rate, points_line, margin |
| `bettingpros_player_points_props` | 2.2M | points_line, opening_line |
| `player_shot_zone_analysis` | Nightly | paint_rate, three_pt_rate |
| `team_defense_zone_analysis` | Nightly | defense by zone |
| `team_offense_game_summary` | Per game | pace, offensive_rating |
| `nba_players_registry` | All players | first_game_date |
| `player_prop_predictions` | Per game | predictions |
| `nbac_schedule` | All games | schedule data |
| `prediction_accuracy` | **EMPTY** | Needs backfill |
| `system_daily_performance` | **EMPTY** | Needs backfill |

---

## Frontend Spec Links

- **Player Modal:** `props-web/docs/06-projects/current/player-modal/data-requirements.md`
- **Trends Page:** `props-web/docs/06-projects/current/trends-page/backend-data-requirements.md`

---

## Success Criteria

- [ ] `prediction_accuracy` populated with season data
- [ ] `prediction_performance_summary` table created and populated
- [ ] Daily grading job scheduled and running
- [ ] Game Report endpoint < 500ms (uncached)
- [ ] "Our track record on [Player]" displays correctly
