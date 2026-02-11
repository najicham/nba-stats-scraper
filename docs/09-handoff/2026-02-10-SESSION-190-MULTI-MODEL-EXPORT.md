# Session 190 Handoff — Multi-Model Subsets + Website Export Audit

**Date:** 2026-02-10
**Previous:** Session 189 (Breakout dead ends, subset planning, QUANT fixes)
**Focus:** Multi-model subset exports, full exporter audit, opaque codenames

## What Was Done

### 1. Multi-Model Subset System (Primary Work)

Parameterized the subset materializer and all 3 subset exporters to support multiple models. Previously hardcoded to `catboost_v9` only.

**Files modified:**

| File | Changes |
|------|---------|
| `shared/config/subset_public_names.py` | Added 5 QUANT subset names (IDs 9-13) |
| `shared/config/model_codenames.py` | Opaque codenames (phoenix/aurora/summit), MODEL_DISPLAY_INFO, CHAMPION_CODENAME |
| `data_processors/publishing/subset_materializer.py` | Multi-model loop, system_id per row, champion signal fallback |
| `data_processors/publishing/all_subsets_picks_exporter.py` | `model_groups` v2 JSON structure, multi-model materialized + on-the-fly paths |
| `data_processors/publishing/subset_performance_exporter.py` | 6 time windows (1d/3d/7d/14d/30d/season), model_groups |
| `data_processors/publishing/subset_definitions_exporter.py` | model_groups v2 structure |
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | Added `system_id` column |
| `bin/test-phase6-exporters.py` | Updated assertions for v2 structure |

**BQ changes (already applied):**
- `ALTER TABLE current_subset_picks ADD COLUMN system_id STRING`
- Inserted 5 QUANT subset definitions into `dynamic_subset_definitions`:
  - `q43_under_top3` (ID 9), `q43_under_all` (ID 10), `q43_all_picks` (ID 11)
  - `q45_under_top3` (ID 12), `q45_all_picks` (ID 13)

### 2. Opaque Codenames for Network Security

Replaced all model-revealing names with opaque codenames so network traffic reveals nothing:

| Internal system_id | Public Codename | Public Display Name |
|-------------------|----------------|---------------------|
| `catboost_v9` | `phoenix` | Phoenix |
| `catboost_v9_q43_train1102_0131` | `aurora` | Aurora |
| `catboost_v9_q45_train1102_0131` | `summit` | Summit |
| `catboost_v8` | `atlas` | (not exported) |

JSON exports show `"model_id": "phoenix"`, `"model_name": "Phoenix"`, `"model_type": "primary"` — zero info about CatBoost, quantile regression, training dates, etc.

Config: `shared/config/model_codenames.py` — single source of truth for all codenames.

### 3. Full Exporter Audit (21 Active Exporters)

**Two-tier architecture:**

**Matchups Page (7 exporters, V8):**
| GCS Path | Exporter | Purpose |
|----------|----------|---------|
| `tonight/all-players.json` | TonightAllPlayers | Homepage main load (~150 KB) |
| `tonight/player/{lookup}.json` | TonightPlayer | Individual player cards |
| `predictions/{date}.json` | Predictions | Predictions by game |
| `best-bets/{date}.json` | BestBets | Tiered picks |
| `results/{date}.json` | Results | Post-game results |
| `streaks/today.json` | Streaks | O/U streaks |
| `live-grading/{date}.json` | LiveGrading | Live grading vs actuals |

**Subset Picks Page (5 exporters, V9 + QUANT):**
| GCS Path | Exporter | Purpose |
|----------|----------|---------|
| `picks/{date}.json` | AllSubsetsPicks | Curated picks with W-L records (v2) |
| `subsets/performance.json` | SubsetPerformance | 6-window performance by model (v2) |
| `systems/subsets.json` | SubsetDefinitions | Available groups (v2) |
| `subsets/season.json` | SeasonSubsetPicks | Full-season picks (V9 only) |
| `signals/{date}.json` | DailySignals | Market signal |

**Analytics (7 exporters, no model):** trends/whos-hot, bounce-back, what-matters, team-tendencies, quick-hits, tonight-plays, deep-dive

**Live (2 exporters):** live scores, system performance

### 4. Model Performance Deep-Dive

**V9 is NOT dead.** The raw 31.8% was unfiltered. With edge filters:

| Model | 5+ edge HR | 3+ edge HR | Volume |
|-------|-----------|-----------|--------|
| **V9** | **76.9%** | 62.1% | 156 / 472 |
| **V8** | 63.3% | 60.0% | 1,647 / 3,001 |

V9 outperforms V8 per-prediction at high edge. But V8 has 10x volume and full-season continuity.

**Both models decay identically:** V8: 61% (Dec) → 32% (Feb). V9 edge 3+: 71.2% → 47.9%. Systemic, not model-specific.

**Only one V9 model file in production.** The `model_version` string changed on Feb 1 but it's the same `.cbm`.

### 5. Model Activation Audit

**3 shadow models running despite `enabled: False` in config** — deployed worker has stale config:
- `catboost_v9_train1102_0208` (18 active, should be retired — contaminated backtest)
- `catboost_v9_train1102_0208_tuned` (18 active, should be retired)
- `catboost_v9_train1102_0131` (543 active, should be retired — redundant with _tuned)

**QUANT models barely producing:** 2 predictions each on 1 day. Quality gate blocking.

**Doesn't affect exports** — only models with active subset definitions appear (catboost_v9, Q43, Q45).

### 6. V8 Backfill Status

V8 generating daily — no backfill needed for current dates.

**Issues:**
- 2 missing dates: Nov 10, Jan 29
- 8 low-volume days Nov-Dec (< 20 predictions)
- **~40-60% of Jan-Feb V8 predictions are ungraded** — grading pipeline may filter V9 only

## Open Items for Next Session

### High Priority
1. **V8 grading gap** — ~40-60% Jan-Feb ungraded. Investigate grading pipeline system_id filter.
2. **QUANT barely producing** — 2 predictions each. Quality gate issue for shadow models.
3. **Deploy worker** — Push to main to disable stale shadow models and deploy export changes.

### Medium Priority
4. **Backfill materialization** — Run SubsetMaterializer for existing QUANT prediction dates.
5. **Model registry sync** — `./bin/model-registry.sh sync`
6. **V8 missing dates** — Nov 10, Jan 29

### Low Priority
7. **Performance view 30-day cap** — `v_dynamic_subset_performance` INTERVAL 30 DAY limit
8. **SeasonSubsetPicksExporter** — Still uses old `groups` format, champion-only

## Strategy for Rest of Season

- **V8 stays on matchups page** — full-season continuity, proven
- **V9/QUANT compete on subset picks page** — experimentation here
- **Next season** — winner gets both pages, fresh retrain

## Key Files

| Purpose | File |
|---------|------|
| Codenames config | `shared/config/model_codenames.py` |
| Subset names config | `shared/config/subset_public_names.py` |
| Materializer | `data_processors/publishing/subset_materializer.py` |
| Picks exporter | `data_processors/publishing/all_subsets_picks_exporter.py` |
| Performance exporter | `data_processors/publishing/subset_performance_exporter.py` |
| Definitions exporter | `data_processors/publishing/subset_definitions_exporter.py` |
| Shadow model config | `predictions/worker/prediction_systems/catboost_monthly.py` |
| Project docs | `docs/08-projects/current/website-export-api/00-PROJECT-OVERVIEW.md` |

## Uncommitted Changes

```
shared/config/model_codenames.py
shared/config/subset_public_names.py
data_processors/publishing/subset_materializer.py
data_processors/publishing/all_subsets_picks_exporter.py
data_processors/publishing/subset_performance_exporter.py
data_processors/publishing/subset_definitions_exporter.py
schemas/bigquery/predictions/06_current_subset_picks.sql
bin/test-phase6-exporters.py
docs/08-projects/current/website-export-api/00-PROJECT-OVERVIEW.md
docs/09-handoff/2026-02-10-SESSION-190-MULTI-MODEL-EXPORT.md
```

BQ changes (ALTER TABLE + INSERT definitions) already applied — permanent regardless of commit.
