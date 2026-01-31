# Vegas Sharpness Dashboard Design

**Date:** 2026-01-31
**Status:** Design Complete, Ready for Implementation

---

## Overview

Track Vegas line accuracy over time to understand when the market is sharp (hard to beat) vs soft (opportunities exist).

### Why This Matters

| Vegas State | Model Beats Vegas | Recommended Action |
|-------------|-------------------|-------------------|
| VERY_SHARP (<45%) | Rarely | Raise edge threshold to 5+, reduce bets |
| SHARP (45-50%) | Sometimes | Standard 3+ edge, be selective |
| NORMAL (50-55%) | Even | Standard betting strategy |
| SOFT (>55%) | Often | Lower thresholds ok, more volume |

---

## Data Storage

### Table: `nba_predictions.vegas_sharpness_daily`

**Schema location:** `schemas/bigquery/nba_predictions/vegas_sharpness_daily.sql`

**Key fields:**

| Field | Type | Description |
|-------|------|-------------|
| `game_date` | DATE | Partition key |
| `tier` | STRING | 'Star', 'Starter', 'Rotation', 'Bench', 'All' |
| `system_id` | STRING | 'catboost_v8', etc. |
| `vegas_mae` | FLOAT64 | Vegas Mean Absolute Error |
| `model_mae` | FLOAT64 | Model Mean Absolute Error |
| `model_beats_vegas_pct` | FLOAT64 | % where model is closer |
| `sharpness_score` | FLOAT64 | 0-100 (higher = easier to beat) |
| `sharpness_status` | STRING | 'VERY_SHARP', 'SHARP', 'NORMAL', 'SOFT' |
| `pct_3plus_edge` | FLOAT64 | % with 3+ point edge available |
| `high_edge_win_rate` | FLOAT64 | Win rate on 3+ edge bets |

**Estimated size:** ~20 rows/day, <10MB/season

---

## Dashboard Charts

### 1. Sharpness Score Trend (Line Chart)
- X-axis: Date
- Y-axis: Sharpness score (0-100)
- Horizontal lines at 45 (sharp threshold) and 55 (soft threshold)
- Shows 30/60/90 day trends

### 2. Model vs Vegas MAE (Line Chart)
- Two lines: Vegas MAE (red) vs Model MAE (green)
- Lower is better
- Shows when model is more accurate

### 3. Sharpness by Tier (Bar Chart)
- Compare Star/Starter/Rotation/Bench
- Shows which tiers are sharpest
- Typically: Stars sharpest, Bench softest

### 4. Edge Availability (Area Chart)
- % with 3+ edge and 5+ edge over time
- Shows opportunity windows

---

## API Endpoints

### GET `/api/vegas-sharpness/trend`
```
Params: days=30, tier=All, system_id=catboost_v8
Returns: Daily sharpness data for charts
```

### GET `/api/vegas-sharpness/by-tier`
```
Params: days=30, system_id=catboost_v8
Returns: Aggregated metrics by tier
```

### GET `/api/vegas-sharpness/summary`
```
Params: days=7
Returns: Dashboard card data (current score, trend, recommendation)
```

---

## Example Queries

### Weekly Trend
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  AVG(sharpness_score) as avg_sharpness,
  AVG(model_beats_vegas_pct) as avg_model_beats,
  AVG(pct_3plus_edge) as avg_edge_availability
FROM nba_predictions.vegas_sharpness_daily
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND tier = 'All'
GROUP BY 1
ORDER BY 1
```

### Tier Comparison
```sql
SELECT
  tier,
  AVG(vegas_mae) as vegas_mae,
  AVG(model_mae) as model_mae,
  AVG(model_beats_vegas_pct) as model_beats_pct,
  AVG(high_edge_win_rate) as high_edge_win_rate
FROM nba_predictions.vegas_sharpness_daily
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND tier != 'All'
GROUP BY 1
ORDER BY 1
```

---

## Implementation Plan

### Phase 1: Data Infrastructure (P0)
1. Deploy `vegas_sharpness_daily` schema
2. Create `VegasSharpnessProcessor` class
3. Add to grading pipeline (after prediction_accuracy updates)
4. Backfill 90 days

### Phase 2: API Layer (P0)
1. Create `vegas_sharpness.py` blueprint
2. Implement `/trend`, `/by-tier`, `/summary` endpoints
3. Register blueprint in admin dashboard

### Phase 3: Dashboard UI (P1)
1. Create `vegas_sharpness.html` component
2. Add Chart.js visualizations
3. Add to dashboard navigation

### Phase 4: Alerting (P2)
1. Add sharpness to daily diagnostics
2. Slack alert when status changes (NORMAL → SHARP)
3. Recommend action in alert message

---

## Files to Create

| File | Purpose |
|------|---------|
| `schemas/bigquery/nba_predictions/vegas_sharpness_daily.sql` | Schema |
| `data_processors/grading/vegas_sharpness/vegas_sharpness_processor.py` | Daily processor |
| `services/admin_dashboard/blueprints/vegas_sharpness.py` | API endpoints |
| `services/admin_dashboard/templates/components/vegas_sharpness.html` | Dashboard UI |
| `bin/backfill/vegas_sharpness_backfill.py` | Backfill script |

---

## Dashboard Mockup

```
┌─────────────────────────────────────────────────────────────────┐
│  Vegas Sharpness                    [7d] [30d] [90d]            │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐  │
│  │ Score: 51.2 │ │ Vegas: 5.34 │ │ Beats: 51%  │ │ 3+: 33.4% │  │
│  │ NORMAL      │ │ MAE         │ │ Vegas       │ │ Edge Avail│  │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘  │
│                                                                  │
│  ┌─────────────────────────┐  ┌─────────────────────────┐       │
│  │ Sharpness Trend         │  │ Model vs Vegas MAE      │       │
│  │ [Line Chart 30 days]    │  │ [Line Chart 30 days]    │       │
│  └─────────────────────────┘  └─────────────────────────┘       │
│                                                                  │
│  ┌─────────────────────────┐  ┌─────────────────────────┐       │
│  │ By Tier [Bar Chart]     │  │ Edge Availability       │       │
│  │ Star Starter Rotation   │  │ [Area Chart]            │       │
│  └─────────────────────────┘  └─────────────────────────┘       │
│                                                                  │
│  💡 Vegas is NORMAL. Standard 3+ edge thresholds apply.         │
└─────────────────────────────────────────────────────────────────┘
```

---

*Session 56 Design Document*
