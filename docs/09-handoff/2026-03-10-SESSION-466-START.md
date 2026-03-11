# Session 466 Start Prompt

**Date:** 2026-03-10
**Previous:** Session 465 (paper trade verified, replay experiments, combo signals, catcher framing, xFIP signal, umpire backfill)

## Current State

S465 code uncommitted — ready to commit. Umpire backfill running in background (2025 full season).

### MLB System Status
- **Model:** `catboost_mlb_v1_40f_train20250517_20250914_20260308_090647.cbm` — L2=10, D4, 69.2% HR
- **Worker:** `mlb-prediction-worker` deployed, /health returning 200
- **Signals:** 18 active + 32 shadow + 6 filters = 56 total
- **4-season replay:** 63.4% HR, +470.7u P&L, 12.8% ROI (4/4 seasons profitable)
- **MLB season opens:** March 27 (17 days away)
- **Catcher framing:** Scraper fixed + tested (57 catchers), BQ table ready, supplemental loader wired
- **Umpire backfill:** 2025 full season loading to BQ (check status on next session)

### Session 465 Signal Results (2025 single-season replay)

| Signal | Replay HR | N | Status |
|--------|----------|---|--------|
| `xfip_elite_over` | **73.8%** | 202 | Shadow — strong candidate for promotion |
| `day_game_elite_peripherals_combo_over` | **86.7%** | 45 | Shadow — exceptional |
| `day_game_high_csw_combo_over` | **82.1%** | 28 | Shadow — needs more N |
| `high_csw_low_era_high_k_combo_over` | 67.3% | 55 | Shadow |

### Bugs Fixed in S465
- `xfip_elite_over` was inside `elif recommendation == 'UNDER'` block — OVER signal never fired
- Combo signals used wrong column `f63_is_day_game` → should be `f25_is_day_game`
- Catcher framing scraper: `DownloadType.CSV` → `.HTML`, `type=pitcher` → `type=catcher`, wrong column names
- Umpire backfill: missing `source_file_path` and `processed_at` BQ required fields

## Priority Tasks

### P0 — Pre-Season Model Retrain (CRITICAL, before Mar 27)
Model was trained with data through Sep 2025. Need fresh model for 2026 season.
```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 --window 120
```
Then: upload to GCS, update env var, deploy worker.

### P1 — Resume MLB Schedulers (Mar 24)
```bash
./bin/mlb-season-resume.sh
# Unpauses 24 scheduler jobs
# Schedule scraper fires first, populates 2026 calendar
```

### P2 — Opening Day Verification (Mar 27)
- [ ] Verify predictions generating
- [ ] Check /best-bets endpoint
- [ ] Monitor filter audit
- [ ] Verify supplemental data flowing (umpire, weather, game context)
- [ ] Run catcher framing scraper manually for Week 1
- [ ] Check shadow combo signals firing
- [ ] Verify umpire backfill completed (check BQ row count)

### P3 — Signal Promotion Candidates (Post Paper Trade)
- `xfip_elite_over` — 73.8% HR, N=202. Strong. Needs live validation.
- `day_game_elite_peripherals_combo_over` — 86.7% but N=45. Wait for more data.
- Consider cross-season replay for xfip_elite_over before promoting.

### P4 — NBA Season Maintenance
- [ ] Check NBA daily pipeline health
- [ ] Weekly retrain should auto-fire Monday 5 AM ET
- [ ] Monitor model staleness

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/mlb/signals.py` | All signal classes (56 signals, ~2000 lines) |
| `ml/signals/mlb/registry.py` | Signal registration |
| `ml/signals/mlb/best_bets_exporter.py` | BB pipeline + pick angles |
| `scripts/mlb/training/season_replay.py` | Walk-forward replay simulator |
| `scripts/mlb/training/train_regressor_v2.py` | Model training script |
| `predictions/mlb/supplemental_loader.py` | Umpire, weather, game context, catcher framing |
| `scrapers/mlb/external/mlb_catcher_framing.py` | Fixed catcher framing scraper |
| `data_processors/raw/mlb/mlb_catcher_framing_processor.py` | Catcher framing processor |
| `scripts/mlb/backfill_umpire_assignments.py` | Historical umpire backfill tool |
| `docs/08-projects/current/mlb-session-464/EXPERIMENT-PLAN.md` | Full experiment results |

## What NOT to Do
- Don't change the 18 active signals without replay validation
- Don't relax the edge floor (0.75 K) — validated sweet spot
- Don't add features to the model — adding features hurts
- Don't enable UNDER in production yet — UNDER signals accumulating shadow data
- Don't deploy dynamic blacklist — only 3 pitchers suppressed in replay
- Don't raise RSC gate from 2 — RSC=2 is best bucket
