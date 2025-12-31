# Session Handoff: Frontend API Backend Research

**Date:** 2025-12-17
**Session Focus:** Backend data requirements for Props Web frontend
**Status:** Documentation complete, backfill pending

---

## Executive Summary

Reviewed frontend data requirements for Player Modal and Trends Page. **Key discovery:** The Phase 5B prediction grading infrastructure already exists but tables are EMPTY because the grading job hasn't been running.

---

## Critical Discovery

### Prediction Tracking Infrastructure EXISTS

| Component | Schema | Code | Data |
|-----------|--------|------|------|
| `prediction_accuracy` | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `system_daily_performance` | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `prediction_performance_summary` | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `PredictionAccuracyProcessor` | N/A | :white_check_mark: | N/A |
| Phase 6 JSON Exporters | N/A | :white_check_mark: | N/A |

**The schema and code exist. Only the data is missing because the grading job hasn't been running.**

---

## What Was Created This Session

### New Schema
- `schemas/bigquery/nba_predictions/prediction_performance_summary.sql`
- BigQuery table created: `nba_predictions.prediction_performance_summary`

### New Processor
- `data_processors/grading/performance_summary/__init__.py`
- `data_processors/grading/performance_summary/performance_summary_processor.py`

### Documentation Created/Updated

**Frontend API Backend Project:**
- `docs/08-projects/current/frontend-api-backend/README.md` - Project overview
- `docs/08-projects/current/frontend-api-backend/01-data-infrastructure-audit.md` - Complete audit
- `docs/08-projects/current/frontend-api-backend/02-implementation-plan.md` - Phased plan
- `docs/08-projects/current/frontend-api-backend/03-api-specification.md` - REST API spec
- `docs/08-projects/current/frontend-api-backend/04-schema-changes.md` - Schema changes
- `docs/08-projects/current/frontend-api-backend/05-background-jobs.md` - Background jobs

**Backfill Documentation:**
- `docs/02-operations/backfill/README.md` - Added Phase 5B section
- `docs/02-operations/backfill/runbooks/README.md` - Added Phase 5B reference
- `docs/02-operations/backfill/runbooks/phase5b-prediction-grading-backfill.md` - **NEW** runbook

---

## Immediate Next Steps

### 1. Run Prediction Accuracy Backfill (Handed to another conversation)

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2024-10-22 --end-date 2024-12-16
```

### 2. Run Performance Summary Aggregation

```bash
PYTHONPATH=. .venv/bin/python data_processors/grading/performance_summary/performance_summary_processor.py
```

### 3. Schedule Daily Jobs

- `prediction_accuracy_grading` - 6 AM ET daily
- `performance_summary_aggregation` - 6:30 AM ET daily

---

## Architecture Understanding

### Prediction Tracking Data Flow

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

## Key Files Reference

### Prediction Grading (EXISTS - needs backfill)
- Schema: `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- Processor: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- Backfill: `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`

### Performance Summary (NEW)
- Schema: `schemas/bigquery/nba_predictions/prediction_performance_summary.sql`
- Processor: `data_processors/grading/performance_summary/performance_summary_processor.py`

### Phase 6 Exporters (EXISTS - needs data)
- Results: `data_processors/publishing/results_exporter.py`
- System Performance: `data_processors/publishing/system_performance_exporter.py`

### Frontend Specs (in props-web repo)
- Player Modal: `props-web/docs/06-projects/current/player-modal/data-requirements.md`
- Trends Page: `props-web/docs/06-projects/current/trends-page/backend-data-requirements.md`

---

## What Frontend Needs (Summary)

### Player Modal
- Player profile (archetype, shot profile, years in league)
- Game context (opponent, rest days, B2B)
- Prop lines (current, opening, movement)
- Prediction with angles (supporting, against)
- **Track record: "Our predictions hit 75% on this player"**

### Trends Page
- Who's Hot/Cold (heat score)
- Bounce-Back Watch
- What Matters Most (archetype patterns)
- Team Tendencies (pace, defense)

---

## Data Availability

| Data Need | Source Table | Available |
|-----------|--------------|-----------|
| Player stats | `player_game_summary` | :white_check_mark: |
| Prop lines | `bettingpros_player_points_props` | :white_check_mark: |
| Shot profiles | `player_shot_zone_analysis` | :white_check_mark: |
| Team defense | `team_defense_zone_analysis` | :white_check_mark: |
| Pace | `team_offense_game_summary` | :white_check_mark: |
| Predictions | `player_prop_predictions` | :white_check_mark: |
| **Prediction results** | `prediction_accuracy` | :x: EMPTY |
| **Track record aggregates** | `prediction_performance_summary` | :x: EMPTY |

---

## Future Work (After Backfill)

1. **Build API Layer** - FastAPI service (recommend separate `props-api` repo)
2. **Implement derived computations** - Heat scores, bounce-back detection
3. **Create Trends page exporters** - JSON generation for frontend
4. **Premium gating** - User authentication and tier-based access

---

## Verification Queries

After backfill, verify with:

```sql
-- Check prediction_accuracy populated
SELECT system_id, COUNT(*) as predictions,
       AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as hit_rate
FROM nba_predictions.prediction_accuracy
GROUP BY system_id;

-- Check performance summary populated
SELECT period_type, COUNT(*) as summaries
FROM nba_predictions.prediction_performance_summary
GROUP BY period_type;
```

---

## Session Notes

- Frontend specs are comprehensive and well-documented
- 95% of data infrastructure already exists
- Main gap was discovering grading tables are empty
- Created new `prediction_performance_summary` for multi-dimensional aggregates
- Documentation now clearly communicates the state and next steps
