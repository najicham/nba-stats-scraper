# Session 447 Handoff — MLB Supplemental Pipeline + Season Optimization

**Date:** 2026-03-08
**Focus:** Wire umpire/weather into production, optimize blacklist/rescue/signals from replay data
**Tests:** 38 passing (19 exporter + 19 supplemental loader)

## What Was Done

### 1. BQ Tables Created
- `mlb_raw.mlb_umpire_assignments` (partitioned by game_date)
- `mlb_raw.mlb_umpire_stats` (clustered by umpire_name, season)
- `mlb_raw.mlb_weather` (partitioned by scrape_date)
- Added `ultra_tier` (BOOL), `ultra_criteria` (REPEATED STRING), `staking_multiplier` (INT64) to `mlb_predictions.signal_best_bets_picks`

### 2. Supplemental Data Loader (NEW)
`predictions/mlb/supplemental_loader.py` — loads umpire K-rate + weather temperature per pitcher.

**Architecture:**
```
schedule (game_pk → teams + pitchers)
  → umpire_assignments (game_pk → umpire_name)
  → umpire_stats (umpire_name → k_zone_tendency → mapped K-rate)
  → weather (team_abbr → temperature_f, is_dome)
  → supplemental_by_pitcher dict
```

- Maps `k_zone_tendency` (wide/tight/average) to K-rate (0.190-0.245)
- Gracefully returns empty dict when tables have no data (pre-season)
- 19 tests covering: K-zone mapping, BQ error handling, partial data, pitcher filtering

### 3. Worker Wiring
- `supplemental_by_pitcher` loaded in `run_multi_system_batch_predictions()`
- New `/best-bets` endpoint: predictions → signals → filters → ranking → ultra → BQ
- Full pipeline with umpire + weather data flowing to signals

### 4. Replay Analysis + Optimizations
Deep analysis of V3 replay (470 picks, 63.4% HR) identified 3 improvements:

**a. Blacklist expanded 23 → 28 (+1.9pp)**
| Pitcher | HR | N |
|---------|----|----|
| ranger_suárez | 33.3% | 6 |
| cade_horton | 37.5% | 8 |
| blake_snell | 40.0% | 5 |
| luis_castillo | 42.9% | 7 |
| paul_skenes | 44.4% | 9 |
Combined: 40.0% HR on 35 picks removed → +4u P&L lift

**b. ballpark_k_boost removed from rescue**
Solo rescue HR was 41.2% (N=17) — net negative. opponent_k_prone kept (59.2% solo HR, N=76).

**c. swstr_surge demoted to shadow**
55.2% HR on 58 picks — inflates signal_count without adding value. Already removed from rescue in Session 444.

### 5. Season Plan Written
`docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md`
- Full timeline: training → deploy → resume → checkpoints
- Decision points: UNDER enablement (May 1), signal promotions (May 5), blacklist review (Jun 1)
- Data gap analysis: all core data complete, umpire/weather populates on season start

## Files Changed

```
# New files
predictions/mlb/supplemental_loader.py               — Umpire/weather loader
tests/mlb/test_supplemental_loader.py                 — 19 tests
docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md

# Modified files
predictions/mlb/worker.py                             — Import supplemental, /best-bets endpoint
ml/signals/mlb/signals.py                             — +5 blacklist, swstr_surge → shadow, docstring
ml/signals/mlb/best_bets_exporter.py                  — Remove ballpark_k_boost rescue, algo v7
scripts/mlb/training/season_replay.py                 — +5 blacklist, remove ballpark_k_boost rescue
tests/mlb/test_exporter_with_regressor.py             — Update algo version assertion
docs/08-projects/current/mlb-2026-season-strategy/03-DEPLOY-CHECKLIST.md — Updated header
```

## Algorithm Version
`mlb_v7_s447_blacklist28_rescue_tightened`

## What Was NOT Done (Next Session TODO)

### Priority 1: Train Model (Mar 18-20)
See deploy checklist step 1.

### Priority 2: Deploy MLB Worker (Mar 21-22)
Manual deploy: `gcloud builds submit --config cloudbuild-mlb-worker.yaml`

### Priority 3: Resume Schedulers (Mar 24)
`./bin/mlb-season-resume.sh`

### Priority 4: Optional 2025 Umpire Backfill
Run umpire scraper for 2025 dates to validate umpire_k_friendly signal against replay data.
Not blocking — signal starts accumulating data on season resume.

### Priority 5: UNDER Enablement (May 1)
If OVER HR >= 58% live.

## Key Findings

### Replay Data Insights (470 picks, Apr-Sep 2025)
- **Home pitchers dominate:** 68.1% HR vs 57.9% away (+10.2pp)
- **Edge 1.0+ is the sweet spot:** 71.6% HR (190 picks) vs 57.5% below
- **Rescue is marginal:** 58.6% rescued vs 65.2% organic — only opponent_k_prone works
- **Rank 2 picks are weaker:** 59.9% vs 66.7% for rank 1 (lower edge, more rescued)
- **Ultra is the profit engine:** 81.4% HR, +88u (52% of total P&L from 15% of picks)
- **No losing months** across all 6 months (Apr-Sep)
- **No replay needed now** — changes are config tweaks, not algorithmic
