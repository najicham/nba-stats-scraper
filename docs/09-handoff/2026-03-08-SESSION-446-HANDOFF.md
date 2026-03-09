# Session 446 Handoff — MLB Ultra Tier + Umpire/Weather Pipeline

**Date:** 2026-03-08
**Focus:** Ultra tier production implementation, umpire/weather data pipeline wiring
**Commits:** 2 (eb037bed, 48c47ad5)
**Tests:** 137 passing (19 MLB exporter + 7 V2 regressor + 109 aggregator + 2 NBA exporter)

## What Was Done

### 1. Ultra Tier in Production Exporter (DEPLOYED)

Ported `check_ultra()` from `scripts/mlb/training/season_replay.py` into `ml/signals/mlb/best_bets_exporter.py`.

**Ultra criteria (ALL must pass):**
- Direction: OVER
- Line type: half-line (X.5)
- Edge: >= 1.1 K
- Location: home pitcher
- Projection: `projection_agrees_over` OR `regressor_projection_agrees_over` in signal_tags
- Not on pitcher blacklist

**Ultra pick flow:**
1. After ranking, top-3 picks checked for ultra → tagged with `staking_multiplier=2`
2. Remaining picks also checked → ultra-qualifying picks published via **overlay** (extra picks beyond top-3)
3. BQ rows include `ultra_tier`, `ultra_criteria`, `staking_multiplier` fields

**Season replay validation:** 81.4% HR (N=70), +88u at 2u staking

**Algorithm version:** `mlb_v6_season_replay_validated`

**11 new tests covering:** tagging, edge threshold, home requirement, half-line, projection agrees, blacklist safety, overlay mechanics, pick angles, BQ fields

### 2. Umpire + Weather Processors (Code DEPLOYED, BQ tables NOT yet created)

Built 3 Phase 2 processors to wire existing scrapers into BigQuery:

| Processor | GCS Path | BQ Table | Strategy |
|-----------|----------|----------|----------|
| `MlbUmpireAssignmentsProcessor` | `mlb-stats-api/umpire-assignments/{date}` | `mlb_raw.mlb_umpire_assignments` | MERGE per game_date |
| `MlbUmpireStatsProcessor` | `mlb-external/umpire-stats/{season}` | `mlb_raw.mlb_umpire_stats` | MERGE per season |
| `MlbWeatherProcessor` | `mlb-external/weather/{date}` | `mlb_raw.mlb_weather` | MERGE per scrape_date |

All registered in `main_processor_service.py` for auto-triggering via GCS path matching.

### 3. Committed Session 444 Changes

All Session 444 work (previously uncommitted):
- 36 features (5 dead removed), 23-pitcher blacklist, swstr_surge removed from rescue
- Season replay script, strategy/deploy/goals/dead-ends docs

## Files Changed

```
# Ultra tier
ml/signals/mlb/best_bets_exporter.py           — _check_ultra(), ultra overlay, BQ fields, algo v6
tests/mlb/test_exporter_with_regressor.py       — 11 new TestUltraTier tests

# Processors
data_processors/raw/mlb/mlb_umpire_assignments_processor.py  — NEW
data_processors/raw/mlb/mlb_umpire_stats_processor.py        — NEW
data_processors/raw/mlb/mlb_weather_processor.py             — NEW
data_processors/raw/mlb/__init__.py              — 3 new imports
data_processors/raw/main_processor_service.py    — 3 new registry entries
schemas/bigquery/mlb_raw/mlb_umpire_*_tables.sql — NEW (2 files)
schemas/bigquery/mlb_raw/mlb_weather_tables.sql  — NEW

# Session 444 (committed this session)
ml/signals/mlb/signals.py                       — blacklist 18→23
predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py — 36 features
scripts/mlb/training/*.py                       — 36 features + season replay
docs/08-projects/current/mlb-2026-season-strategy/*.md
```

## What Was NOT Done (Next Session TODO)

### Priority 1: Create BQ Tables (5 min)

Run schema SQL in BigQuery:

```bash
bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/mlb_umpire_assignments_tables.sql
bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/mlb_umpire_stats_tables.sql
bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/mlb_weather_tables.sql
```

Also add to `mlb_predictions.signal_best_bets_picks`:
- `ultra_tier` (BOOL)
- `ultra_criteria` (REPEATED STRING)
- `staking_multiplier` (INT64)

### Priority 2: Wire Supplemental Data Queries (30 min)

Signals already exist and look for:
- `supplemental['umpire_k_rate']` → `UmpireKFriendlySignal` (active)
- `supplemental['temperature']` → `WeatherColdUnderSignal` (shadow)

Need queries that:
1. Join `mlb_umpire_assignments` (game → umpire) with `mlb_umpire_stats` (umpire → K tendency) to get per-game umpire K rate
2. Query `mlb_weather` for stadium temperature
3. Pass both into `supplemental_by_pitcher` dict when calling `exporter.export()`

**Where:** Check `predictions/mlb/worker.py` for how it builds `supplemental_by_pitcher`.

### Priority 3: Train Final Model (Mar 18-20)

```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 --window 120
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/
```

### Priority 4: Deploy MLB Worker (Mar 21-22)

Full checklist: `docs/08-projects/current/mlb-2026-season-strategy/03-DEPLOY-CHECKLIST.md`

### Priority 5: Resume Schedulers (Mar 24)

### Priority 6: UNDER Enablement (May 1 decision point)

## Key Decisions Made

1. **Per-model pipeline NOT needed for MLB** — only 2 models. Skip unless fleet grows.
2. **No new scrapers needed** — umpire/weather scrapers already exist. Only BQ pipeline was missing.
3. **No new features/models to experiment** — dead ends extensive. CatBoost 36-feature is champion.
4. **Ultra edge 1.1 not 1.0** — 1.0-1.1 was 63% HR (noise), 1.1+ = 81.4%

## Dead Ends — Do NOT Revisit

See `docs/08-projects/current/mlb-2026-season-strategy/05-DEAD-ENDS.md`
