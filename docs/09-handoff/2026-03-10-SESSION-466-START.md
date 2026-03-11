# Session 466 Start Prompt

**Date:** 2026-03-10
**Previous:** Session 465 (paper trade verified, replay experiments, combo signals, catcher framing)

## Current State

Everything deployed and committed. Clean working tree (pending commit of S465 changes).

### MLB System Status
- **Model:** `catboost_mlb_v1_40f_train20250517_20250914_20260308_090647.cbm` — L2=10, D4, 69.2% HR
- **Worker:** `mlb-prediction-worker` deployed, /health returning 200
- **Signals:** 19 active + 25 shadow + 6 filters + 2 obs = 52 total
- **4-season replay:** 63.4% HR, +470.7u P&L, 12.8% ROI (4/4 seasons profitable)
- **MLB season opens:** March 27 (17 days away)
- **Catcher framing:** BQ table + processor + supplemental loader all wired, waiting for data

### Session 465 Findings (No Action Needed)
- Dynamic blacklist: only 3 pitchers suppressed — not deploying
- Away edge floor: 1.0/1.25/1.5 all within noise — keeping 1.25
- RSC gate: RSC=2 = 75.9% HR (best bucket!) — keeping gate at 2
- 3 combo signals added as shadow — accumulating data

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

### P3 — NBA Season Maintenance
- [ ] Check NBA daily pipeline health
- [ ] Weekly retrain should auto-fire Monday 5 AM ET
- [ ] Monitor model staleness

### P4 — Signal Research (Ongoing, Lower Priority)
- [ ] Monitor k_rate_bounce_over (76.1% HR, N=46, need more data)
- [ ] Monitor combo signals from live MLB data
- [ ] XFIP regression signal (FanGraphs data available)
- [ ] Historical umpire backfill for 2025 validation

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/mlb/signals.py` | All signal classes (52 signals, 1900+ lines) |
| `ml/signals/mlb/registry.py` | Signal registration |
| `ml/signals/mlb/best_bets_exporter.py` | BB pipeline + pick angles |
| `scripts/mlb/training/season_replay.py` | Walk-forward replay simulator |
| `scripts/mlb/training/train_regressor_v2.py` | Model training script |
| `predictions/mlb/supplemental_loader.py` | Umpire, weather, game context, catcher framing |
| `data_processors/raw/mlb/mlb_catcher_framing_processor.py` | NEW: Catcher framing processor |
| `docs/08-projects/current/mlb-session-464/EXPERIMENT-PLAN.md` | Full experiment results (S464+S465) |
| `docs/08-projects/current/mlb-2026-season-strategy/03-DEPLOY-CHECKLIST.md` | Deploy checklist |
| `docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md` | Season plan |

## What NOT to Do
- Don't change the 19 active signals without replay validation
- Don't relax the edge floor (0.75 K) — validated sweet spot
- Don't add features to the model — adding features hurts
- Don't enable UNDER in production yet — UNDER signals accumulating shadow data
- Don't deploy dynamic blacklist — only 3 pitchers suppressed in replay
- Don't raise RSC gate from 2 — RSC=2 is best bucket
