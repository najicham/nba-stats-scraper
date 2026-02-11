# Website Export API — Complete Reference

**Session:** 188, updated 191
**Date:** 2026-02-10
**Status:** Implemented + Audited

## Overview

The Phase 6 publishing system exports pre-computed JSON files to GCS for website consumption. There are **21 active exporters** organized into two tiers:

1. **Matchups Page** — V8 model, full-season data, rich per-player cards
2. **Subset Picks Page** — V9 + QUANT models, curated picks with performance tracking

## Strategy for Rest of Season

**V8 stays on the matchups page.** It has 884 game days of data (since Nov 2021), 125K+ predictions, and a season-long 56.5% graded hit rate. Switching mid-season would break historical context.

**V9/QUANT compete on the subset picks page.** This is where model experimentation plays out. V9 at 5+ edge hits 76.9% (outperforms V8's 63.3%), but produces fewer picks due to quality filtering.

**Both V8 and V9 decay.** V8: 61% (Dec) → 32% (Feb). V9 edge 3+: 71.2% → 47.9% (Jan-Feb). Model staleness is systemic, not model-specific. Edge filters are critical for profitability with either model.

**Next season:** Whichever model wins gets both pages. Fresh retrain, fresh start.

## Model Codenames

All public-facing JSON uses opaque codenames — no model architecture or algorithm details are exposed.

| Internal system_id | Codename | Display Name | Type | Description |
|---|---|---|---|---|
| `catboost_v9` | `phoenix` | Phoenix | `primary` | Our primary prediction engine |
| `catboost_v9_q43_train1102_0131` | `aurora` | Aurora | `specialist` | Specialist engine with a different approach |
| `catboost_v9_q45_train1102_0131` | `summit` | Summit | `specialist` | Conservative specialist engine |

**Champion:** `phoenix` (always sorted first in model_groups).

**Config:** `shared/config/model_codenames.py`

## Model Performance (as of 2026-02-10)

| Model | Edge Filter | Hit Rate | Sample Size | Coverage |
|-------|------------|----------|-------------|----------|
| **V8** | 5+ edge | **63.3%** | 1,647 | 884 game days |
| **V8** | 3-5 edge | **57.9%** | 1,354 | Full season |
| **V9** | 5+ edge | **76.9%** | 156 | 30 game days |
| **V9** | 3-5 edge | **54.7%** | 316 | Jan 9 - Feb 10 |
| **QUANT Q43** | any | n/a | 2 | 1 day (barely producing) |
| **QUANT Q45** | any | n/a | 2 | 1 day (barely producing) |

**Key insight:** V9 is the better model per-prediction at high edge (76.9% vs 63.3%), but V8 has 10x the volume and full-season continuity.

## Complete Exporter Inventory

### Matchups Page Exporters (V8)

| GCS Path | Exporter | Cache | Purpose |
|----------|----------|-------|---------|
| `tonight/all-players.json` | TonightAllPlayersExporter | 5 min | All players by game — homepage main load (~150 KB) |
| `tonight/player/{lookup}.json` | TonightPlayerExporter | 5 min | Individual player detail cards |
| `predictions/{date}.json` | PredictionsExporter | 1 hr | Predictions grouped by game (+ `today.json`) |
| `best-bets/{date}.json` | BestBetsExporter | 24 hr | Tiered picks: premium/strong/value (+ `latest.json`) |
| `results/{date}.json` | ResultsExporter | 24 hr | Post-game results with actuals (+ `latest.json`) |
| `streaks/today.json` | StreaksExporter | 5 min | O/U streaks (3+ games) |
| `live-grading/{date}.json` | LiveGradingExporter | 30 sec | Live prediction grading vs actuals |

### Subset Picks Page Exporters (V9 + QUANT, multi-model)

| GCS Path | Exporter | Cache | Purpose |
|----------|----------|-------|---------|
| `picks/{date}.json` | AllSubsetsPicksExporter | 5 min | Curated subset picks with W-L records (v2 model_groups) |
| `subsets/performance.json` | SubsetPerformanceExporter | 1 hr | 6-window performance by model (v2 model_groups) |
| `systems/subsets.json` | SubsetDefinitionsExporter | 24 hr | Available subset groups (v2 model_groups) |
| `subsets/season.json` | SeasonSubsetPicksExporter | 1 hr | Full-season picks with results (v2 model_groups) |
| `signals/{date}.json` | DailySignalsExporter | 5 min | Market signal: favorable/neutral/challenging |

### Analytics & Trends Exporters (no prediction model)

| GCS Path | Exporter | Cache | Purpose |
|----------|----------|-------|---------|
| `trends/whos-hot-v2.json` | WhosHotColdExporter | 6 hr | Heat scores (hit rate, streak, margin) |
| `trends/bounce-back.json` | BounceBackExporter | 6 hr | Bounce-back candidates (10+ pt shortfall) |
| `trends/what-matters.json` | WhatMattersExporter | 12 hr | Factor impact by archetype (rest, B2B, etc.) |
| `trends/team-tendencies.json` | TeamTendenciesExporter | 12 hr | Pace kings, defense zones, home/away |
| `trends/quick-hits.json` | QuickHitsExporter | 12 hr | 8 rotating situational stats |
| `trends/tonight-plays.json` | TonightTrendPlaysExporter | 1 hr | Streak/momentum/rest plays for tonight |
| `trends/deep-dive-current.json` | DeepDiveExporter | 24 hr | Monthly promo card |

### Live Data Exporters

| GCS Path | Exporter | Cache | Purpose |
|----------|----------|-------|---------|
| `live/{date}.json` | LiveScoresExporter | 30 sec | Live game scores from BDL API |
| `systems/performance.json` | SystemPerformanceExporter | 1 hr | Rolling performance across all systems |

## Subset Picks JSON Structure (v2)

### `picks/{date}.json`

```json
{
  "date": "2026-02-10",
  "generated_at": "2026-02-10T14:30:00Z",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "model_type": "primary",
      "description": "Our primary prediction engine",
      "signal": "favorable",
      "subsets": [
        {
          "id": "1", "name": "Top Pick",
          "record": {
            "season": {"wins": 42, "losses": 18, "pct": 70.0},
            "month": {"wins": 8, "losses": 3, "pct": 72.7},
            "week": {"wins": 3, "losses": 1, "pct": 75.0}
          },
          "picks": [
            {"player": "LeBron James", "team": "LAL", "opponent": "BOS",
             "prediction": 26.1, "line": 24.5, "direction": "OVER"}
          ]
        }
      ]
    },
    {
      "model_id": "aurora",
      "model_name": "Aurora",
      "model_type": "specialist",
      "description": "Specialist engine with a different approach",
      "signal": "favorable",
      "subsets": [
        {"id": "9", "name": "UNDER Top 3", "record": null, "picks": [...]}
      ]
    }
  ]
}
```

### `subsets/performance.json`

```json
{
  "generated_at": "...",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix", "model_name": "Phoenix",
      "windows": {
        "last_1_day": {"start_date": "...", "end_date": "...", "groups": [
          {"id": "1", "name": "Top Pick", "stats": {"hit_rate": 100.0, "roi": -9.1, "picks": 1}}
        ]},
        "last_3_days": {...}, "last_7_days": {...},
        "last_14_days": {...}, "last_30_days": {...}, "season": {...}
      }
    }
  ]
}
```

### `systems/subsets.json`

```json
{
  "generated_at": "...",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix", "model_name": "Phoenix",
      "model_type": "primary", "description": "Our primary prediction engine",
      "subsets": [
        {"id": "1", "name": "Top Pick", "description": "Single best pick"}
      ]
    }
  ]
}
```

### `subsets/season.json` (Session 191 — v2 multi-model)

```json
{
  "generated_at": "...",
  "version": 2,
  "season": "2025-26",
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "model_type": "primary",
      "record": {
        "season": {"wins": 42, "losses": 18, "pct": 70.0},
        "month": {"wins": 8, "losses": 3, "pct": 72.7},
        "week": {"wins": 3, "losses": 1, "pct": 75.0}
      },
      "dates": [
        {
          "date": "2026-02-10",
          "signal": "favorable",
          "picks": [
            {"player": "LeBron James", "team": "LAL", "opponent": "BOS",
             "prediction": 26.1, "line": 24.5, "direction": "OVER",
             "actual": 28, "result": "hit"}
          ]
        }
      ]
    }
  ]
}
```

## Subset Definitions

### Phoenix (`catboost_v9`, codename: `phoenix`, type: `primary`)

| ID | Name | Edge | Direction | Top N | Signal Filter |
|----|------|------|-----------|-------|---------------|
| 1 | Top Pick | 5+ | OVER | 1 | GREEN/YELLOW |
| 2 | Top 3 | 5+ | OVER | 3 | GREEN/YELLOW |
| 3 | Top 5 | 5+ | any | 5 | - |
| 4 | High Edge OVER | 5+ | OVER | - | - |
| 5 | High Edge All | 5+ | any | - | - |
| 6 | Ultra High Edge | 7+ | any | - | - |
| 7 | Green Light | 5+ | any | - | GREEN/YELLOW |
| 8 | All Picks | 3+ | any | - | - |

### Aurora (`catboost_v9_q43_train1102_0131`, codename: `aurora`, type: `specialist`)

| ID | Name | Edge | Direction | Top N |
|----|------|------|-----------|-------|
| 9 | UNDER Top 3 | 5+ | UNDER | 3 |
| 10 | UNDER All | 5+ | UNDER | - |
| 11 | Q43 All Picks | 3+ | any | - |

### Summit (`catboost_v9_q45_train1102_0131`, codename: `summit`, type: `specialist`)

| ID | Name | Edge | Direction | Top N |
|----|------|------|-----------|-------|
| 12 | Q45 UNDER Top 3 | 5+ | UNDER | 3 |
| 13 | Q45 All Picks | 3+ | any | - |

## Website Rendering Notes

1. **Model tabs or sections** — Each `model_group` is a section. Champion (`phoenix`) first, then specialists.
2. **"New" badge** — When `record` is `null`, show "New" instead of W-L record.
3. **Model type styling** — Use `model_type` to differentiate:
   - `primary` = default styling (the main/champion model)
   - `specialist` = specialist styling (e.g., blue/purple theme for UNDER-focused models)
4. **Signal** — One signal for all models (market-level, not model-specific).
5. **Performance windows** — User toggles between 1d, 3d, 7d, 14d, 30d, season.
6. **Empty groups** — New models may have empty performance windows. Show "No data yet".

## Known Issues

| Issue | Severity | Details |
|-------|----------|---------|
| **V8 grading gaps** | High | ~40-60% of Jan-Feb V8 predictions ungraded. Grading pipeline may filter to V9 only. |
| **V8 missing dates** | Medium | Nov 10 and Jan 29 have zero predictions. 8 days in Nov-Dec have < 20 predictions. |
| **QUANT barely producing** | High | Q43/Q45 have only 2 predictions each on 1 day. Zero-tolerance quality gate blocks most. |
| ~~**Performance view 30-day cap**~~ | ~~Low~~ | **FIXED Session 191**: Removed 30-day hard cap from `v_dynamic_subset_performance`. |
| **V8/V9 both decaying** | Info | Systemic model staleness. V8: 61% → 32%. V9 edge 3+: 71.2% → 47.9%. Edge filters essential. |

## Files Modified

### Session 188
| File | Changes |
|------|---------|
| `shared/config/subset_public_names.py` | Added 5 QUANT subset names (IDs 9-13) |
| `shared/config/model_codenames.py` | Added aurora/summit codenames + MODEL_DISPLAY_INFO |
| `data_processors/publishing/subset_materializer.py` | Multi-model loop, system_id per row |
| `data_processors/publishing/all_subsets_picks_exporter.py` | model_groups v2 structure |
| `data_processors/publishing/subset_performance_exporter.py` | 6 time windows, model_groups |
| `data_processors/publishing/subset_definitions_exporter.py` | model_groups v2 structure |
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | Added system_id column |
| `bin/test-phase6-exporters.py` | Updated assertions for v2 structure |

### Session 191
| File | Changes |
|------|---------|
| `schemas/bigquery/predictions/views/v_dynamic_subset_performance.sql` | Removed 30-day cap |
| `data_processors/publishing/season_subset_picks_exporter.py` | Upgraded to v2 multi-model |
| `bin/test-phase6-exporters.py` | Added season exporter v2 tests |
| `docs/08-projects/current/website-export-api/00-PROJECT-OVERVIEW.md` | Fixed stale codenames |
| `docs/08-projects/current/website-export-api/FRONTEND-API-GUIDE.md` | NEW: frontend docs |
