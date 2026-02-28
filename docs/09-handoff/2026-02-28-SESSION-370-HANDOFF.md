# Session 370 Handoff — Experiment Suite Results

**Date:** 2026-02-28
**Focus:** 12-experiment suite across filters, calibration, features, and techniques

## What Changed (Production Impact)

### DEPLOYED: Signal count floor raised 2 → 3
- **File:** `ml/signals/aggregator.py` — `MIN_SIGNAL_COUNT = 3`
- **Impact:** 74.5% HR (35W-12L) vs old 64.1% (59W-33L). +10.4pp HR.
- **Volume:** ~50 picks over 50 days (vs ~106 before). Comparable P&L ($+2,180 vs $+2,270).
- **Algorithm version:** `v370_signal_floor_3`
- **NEEDS PUSH TO MAIN to take effect.**

## What Was Built (Not Production)

| Tool | File | Purpose |
|------|------|---------|
| Edge calibrator | `ml/calibration/edge_calibrator.py` | Maps edge → P(win) per model+direction. Result: edge alone doesn't predict wins. |
| Adversarial validation | `bin/adversarial_validation.py` | Identifies features drifting between time periods. Major diagnostic tool. |
| Uncertainty flag | `ml/experiments/quick_retrain.py --uncertainty` | CatBoost virtual ensembles for prediction confidence. |
| Derived features flag | `ml/experiments/quick_retrain.py --derived-features` | D11+D12 computed features. Dead end. |
| Signal count override | `bin/backfill_dry_run.py --min-signal-count N` | Test different floor values without modifying production. |

## Key Findings

### 1. February Drift Root Cause (B6)
`usage_spike_score` collapsed 76% from Dec-Jan to Feb (1.14 → 0.28). This single feature explains 47% of the distribution shift. The model can distinguish Dec-Jan data from Feb data with 99.3% accuracy. **This is likely the root cause of the February OVER collapse.**

### 2. Uncertainty Signal is Real (B7)
Low-uncertainty picks: 77.8% HR. High-uncertainty picks: 61.1% HR. Gap of 16.7pp, NOT correlated with edge (r=0.417). This is a genuinely new filtering signal. **Needs 5-seed stability test before production.**

### 3. Edge Calibration Doesn't Help (B5)
At the raw prediction level, edge magnitude barely predicts wins (~51% at every edge level). The existing filter stack (blacklist, signals, quality) is what separates winners from losers, not edge alone.

## What to Do Next Session

1. **Push to main** — signal count floor change auto-deploys
2. **5-seed stability test for uncertainty** — confirm Q1-Q4 gap holds across seeds
3. **Investigate usage_spike_score** — is this feature worth downweighting or removing?
4. **Referee scraper investigation** — `gsutil ls gs://nba-scraped-data/nba-com/referee-assignments/2025-*` to check if scraper writes to GCS (Phase 2 processing appears broken)

## Dead Ends Confirmed

- Edge calibration (B5): flat edge → P(win) relationship
- Derived features (D11+D12): D11 amplifies drift, D12 has no signal
- Timezone proxy (C9): arena_timezone ALL NULL
- Referee pace (C10): no data for 2025-26 season
- Friday filter (A2): N=14, too small
- Direction-aware AWAY block (A3): blocked families show 50-52% OVER+AWAY
- Model-direction routing (A4): Wilson intervals overlap

## Detailed Results

See: `docs/08-projects/current/session-370-experiment-suite/00-FINDINGS.md`
