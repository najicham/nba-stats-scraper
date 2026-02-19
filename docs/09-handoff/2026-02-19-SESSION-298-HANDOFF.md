# Session 298 Handoff: Post-ASB Retrain, Natural Sizing, Odds Expansion

**Date:** 2026-02-18
**Focus:** Model retrain for ASB return, remove forced pick limits, expand sportsbook coverage, Vegas weight experiments.

## TL;DR

Champion model was 35 days stale and BLOCKED at 44% HR. Retrained and deployed fresh V9 MAE (MAE 4.83, vegas bias -0.14). Removed forced top-5 from best bets (natural sizing). Expanded Odds API from 2 to 12 sportsbooks. Ran Vegas weight experiments showing low-vegas (0.25x) generates 5x more edge picks. Games resume Feb 19 with 10 games — first live test of all changes.

## What's Deployed

### New Champion Model
- **Model:** `catboost_v9_33f_train20260106-20260205_20260218_223530`
- **Training:** Jan 6 → Feb 5 (31 days, 4,279 samples)
- **MAE:** 4.83 (improved from 5.14)
- **Vegas bias:** -0.14 (clean)
- **Gates:** Failed on sample size (N=10 edge 3+), not quality. Eval period (Feb 6-12) was worst week of season. Manual promotion.
- **Cloud Run env var:** `CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost_v9/catboost_v9_33f_train20260106-20260205_20260218_223530.cbm`

### Algorithm: v298_natural_sizing
- Removed `MAX_PICKS_PER_DAY = 5` from `ml/signals/aggregator.py`
- Removed `top_n: 5` from `xm_consensus_4plus` cross-model subset
- All qualifying picks (edge 5+ + negative filters) returned — natural count varies by day
- Same negative filters as v297 (blacklist, quality, UNDER 7+ block, bench UNDER, etc.)

### Odds API: 12 Sportsbooks (was 2)
All 4 scrapers (live + historical, props + game lines) now request 12 verified books:
`draftkings, fanduel, betmgm, williamhill_us, betrivers, bovada, espnbet, hardrockbet, betonlineag, fliff, betparx, ballybet`

Books that DON'T carry NBA player props (excluded): betus, lowvig, mybookieag, rebet, betanysports, pointsbetus, fanatics.

## Key Findings

### February Collapse Was NOT Staleness
The model failed on data **within its training window** (Feb 1-5). Root causes:
- Market regime shift (trade deadline / ASB approach)
- Terrible Odds API coverage (2 books, some days only 11 players)
- Feb 2-3 saw suspicious spike of 20+ edge 5+ picks (normally 1-5/day) — most wrong

### Subset Health: Everything Declined
| Subset | 1st Half (to Jan 22) | 2nd Half (Jan 22-Feb 12) | Delta |
|--------|:---:|:---:|:---:|
| ultra_high_edge | 84.5% | 37.5% | -47.0 |
| high_edge_all | 79.2% | 35.7% | -43.5 |
| best_bets | 74.7% | 46.5% | -28.2 |
| green_light | 79.8% | 52.0% | -27.8 |

### Vegas Weight Experiments (eval Feb 6-12)
| Model | MAE | Edge 3+ HR (N) | Edge 5+ HR (N) | Vegas Importance |
|-------|:---:|:---:|:---:|:---:|
| V9 Production (deployed) | **4.83** | 50% (10) | 100% (1) | ~40% |
| V9 Low-Vegas (0.25x) | 5.06 | **56.3% (48)** | 55.6% (9) | ~10% |
| V9 No-Vegas | 5.24 | 49.4% (83) | 38.1% (21) | 0% |

**Low-Vegas generates 5x more edge 3+ picks** and UNDER HR is 61.1%. Sweet spot is reducing, not removing Vegas weight.

## Uncommitted Changes

`data_processors/publishing/tonight_all_players_exporter.py` — dedup CTE for player_game_summary and days_rest guard (`dr >= 0`). Minor fix, should be committed.

## Commits This Session
```
2d330525 feat: refine sportsbook list to 12 verified books, add experiment results
0df0d16b feat: natural sizing, ASB retrain, 13-sportsbook odds expansion
```

Both pushed to main, auto-deploying via Cloud Build.

## Verification Checklist (Feb 19 — FIRST GAME DAY)

- [ ] `algorithm_version = 'v298_natural_sizing'` in `signal_best_bets_picks`
- [ ] Natural pick count varies (not always 5)
- [ ] All picks have edge >= 5.0
- [ ] No UNDER picks with edge >= 7
- [ ] No duplicate rows in signal_best_bets_picks
- [ ] Odds API returning data from >2 sportsbooks
- [ ] New model generating predictions with reasonable edge distribution
- [ ] `model_performance_daily` tracking fresh model

## Next Session Priorities

### P0: Monitor Feb 19 Games
First live test. Run `/validate-daily` and check best bets output. Verify the new model + natural sizing + expanded odds all work together.

### P1: Deploy Low-Vegas as Shadow
The low-vegas experiment (0.25x weight) is promising. Deploy as shadow model for live observation:
- Model saved: `models/catboost_v9_33f_wt_train20260106-20260205_20260218_231928.cbm`
- Upload to GCS, register with `model_family = 'v9_low_vegas'`
- Define subset definitions in BQ
- Try intermediate weights (0.5x, 0.15x) to find optimal

### P2: Odds API Historical Backfill
Backfill season (Nov 2025 → Feb 2026) with all 12 books. Currently only DraftKings + FanDuel have history.
- **Script:** `python scripts/backfill_historical_props.py --start-date 2025-11-01 --end-date 2026-02-12`
- **Cost:** ~8,300 quota units (0.2% of 4.99M remaining)
- **Also:** Load snap-0200 closing line data from GCS to BQ (multi-snapshot data exists but isn't loaded)

### P3: Retrain All Shadow Models
Once 2-3 days of post-ASB data exists:
```bash
./bin/retrain.sh --all
```
V12 MAE, Q43, Q45, V12-Q43, V12-Q45 are all stale/BLOCKED.

### P4: Scoring Distribution Research
**Hypothesis:** Points distribution between star/role players shifts mid-season (trades, load management). Could explain why model errors spike after regime changes.
- Compute team-level scoring concentration (HHI/Gini) by month
- Check if model errors correlate with scoring redistribution
- If significant: add `team_scoring_concentration` feature

### P5: Vegas Line Movement Features
With 12 books, `multi_book_line_std` (f50) becomes much more informative. Consider:
- Line movement velocity (speed of cross-book convergence)
- "Sharp money" detection (one book moves first)
- Open-to-close movement from multi-snapshot data

### P6: Signal-Confirmed Observation Subset
Deferred from this session. Add observation subset tracking edge 5+ picks where combo_he_ms, combo_3way, or minutes_surge fires. For tracking/grading, not selection.

## Files Changed This Session

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Removed MAX_PICKS_PER_DAY, v298_natural_sizing |
| `data_processors/publishing/signal_annotator.py` | Updated top_n reference |
| `data_processors/publishing/signal_best_bets_exporter.py` | Updated docstrings |
| `shared/config/cross_model_subsets.py` | Removed top_n=5 from xm_consensus_4plus |
| `scrapers/oddsapi/oddsa_player_props.py` | 12 verified sportsbooks |
| `scrapers/oddsapi/oddsa_player_props_his.py` | 12 verified sportsbooks |
| `scrapers/oddsapi/oddsa_game_lines.py` | 12 verified sportsbooks |
| `scrapers/oddsapi/oddsa_game_lines_his.py` | 12 verified sportsbooks |
| `data_processors/publishing/tonight_all_players_exporter.py` | Season stats + dedup fix (uncommitted) |
| `docs/08-projects/current/session-298-post-asb-retrain/README.md` | Full project doc with experiment results |

## Model Experiment Files (local only, not deployed)

| File | Description |
|------|-------------|
| `models/catboost_v9_33f_wt_train20260106-20260205_20260218_231928.cbm` | Low-Vegas (0.25x) — shadow candidate |
| `models/catboost_v9_29f_noveg_train20260106-20260205_20260218_231932.cbm` | No-Vegas — worse, don't deploy |
| `models/catboost_v9_33f_train20251230-20260131_20260218_223649.cbm` | Wider eval window variant — superseded |
