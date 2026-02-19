# Session 298: Post-ASB Retrain, Natural Sizing, Odds Coverage Expansion

**Date:** 2026-02-18
**Status:** In Progress
**Focus:** Model retrain for ASB return, architecture improvements, data quality expansion

## Summary

Games resume Feb 19 after All-Star Break. Champion model was 35 days stale and BLOCKED (44% HR). This session: retrained model, removed forced pick limits, expanded sportsbook coverage.

## Completed

### 1. Champion Model Retrain
- **New model:** `catboost_v9_33f_train20260106-20260205_20260218_223530`
- **Training:** Jan 6 → Feb 5 (31 days, 4,279 quality samples)
- **MAE:** 4.83 (improved from 5.14 baseline)
- **Vegas bias:** -0.14 (clean — Feb disaster was -2.26)
- **Gates:** Failed on sample size (N=10 edge 3+). Eval period (Feb 6-12) was worst week of season. Manual promotion approved.
- **Deployed:** Live on prediction-worker via `CATBOOST_V9_MODEL_PATH`

### 2. Natural Sizing (v298_natural_sizing)
- **Removed:** `MAX_PICKS_PER_DAY = 5` from `ml/signals/aggregator.py`
- **Removed:** `top_n: 5` from `xm_consensus_4plus` cross-model subset
- All qualifying picks (edge 5+ + negative filters) are now returned
- Some days may yield 2 picks, some days 8 — filters determine natural count
- Algorithm version: `v298_natural_sizing`

### 3. Odds API Sportsbook Expansion
- **Before:** 2 books (draftkings, fanduel) on historical scrapers
- **After:** 12 verified books across all 4 Odds API scrapers (live + historical, props + game lines)
- **Books with NBA player points props (verified Feb 18):**

| Book | API Key | Players/Game | Notes |
|------|---------|:---:|-------|
| DraftKings | `draftkings` | 12 | Primary |
| FanDuel | `fanduel` | 12 | Primary |
| Fliff | `fliff` | 12 | Full coverage |
| BetOnline | `betonlineag` | 12 | Full coverage |
| Caesars | `williamhill_us` | 12 | Full coverage |
| ESPN Bet | `espnbet` | 12 | Full coverage |
| BetMGM | `betmgm` | 11 | Near-full |
| Hard Rock | `hardrockbet` | 11 | Near-full |
| Bovada | `bovada` | 70 | Includes alternates |
| BetRivers | `betrivers` | 6 | Partial |
| betPARX | `betparx` | 6 | Partial |
| Bally Bet | `ballybet` | 3 | Minimal |

- **Books with NO player props:** betus, lowvig, mybookieag, rebet, betanysports, pointsbetus, fanatics (1 player only)
- **API quota:** 4.99M remaining (unlimited for our needs)

### 4. Tonight All-Players Exporter
- Added season_fg_pct, season_three_pct, season_plus_minus, season_fta to all-players JSON export

## Key Findings

### February Collapse Was NOT Staleness
| Period | Edge 5+ HR | Edge 5+ N |
|--------|:---:|:---:|
| Early Jan | **80.2%** | 81 |
| Late Jan | **75.0%** | 52 |
| Early Feb | **25.9%** | 54 |
| Late Feb | 45.8% | 24 |

The model failed on data within its training window (Feb 1-5). Staleness was not the root cause. Likely: market regime shift + Odds API coverage collapse (only 2 books, some days 11-15 players).

### Odds API Coverage Was Terrible
- Only 2 sportsbooks (DraftKings, FanDuel) for all of Jan-Feb
- Some days had only 11-15 players with odds
- BettingPros was more reliable (64-233 players/day)
- Feb 10-11 briefly got 5 books — coincided with partial HR recovery

### Subset Health: Everything Declining
Every subset declined from first half to second half. Ultra_high_edge went from 84.5% to 37.5% (-47 points). The higher the edge filter, the worse the collapse — indicating model edge calibration broke down.

### V12 Agreement is ANTI-Correlated (Session 297)
When V12 agrees with champion: OVER HR drops from 66.8% to 33.3%. This was already handled in Session 297 by removing diversity_mult.

## Research Directions (Prioritized)

### P0: Monitor Fresh Model Post-ASB (Feb 19+)
- Verify `algorithm_version = 'v298_natural_sizing'` in BQ
- Track daily HR on edge 5+ picks
- Compare pick count (natural sizing) vs old forced top-5
- Monitor odds coverage from new sportsbooks

### P1: Vegas Weight Experiment — INITIAL RESULTS

**Hypothesis:** V9 MAE relies ~40% on Vegas features. Reducing Vegas weight could make the model more independent and less susceptible to market regime shifts.

**Experiment results (eval Feb 6-12, same training window):**

| Model | MAE | Edge 3+ HR (N) | Edge 5+ HR (N) | Vegas Importance | UNDER HR |
|-------|:---:|:---:|:---:|:---:|:---:|
| V9 Production | **4.83** | 50% (10) | 100% (1) | 40% | 50% |
| V9 Low-Vegas (0.25x) | 5.06 | **56.3% (48)** | 55.6% (9) | ~10% | **61.1%** |
| V9 No-Vegas | 5.24 | 49.4% (83) | 38.1% (21) | 0% | 55.0% |

**Top features for Low-Vegas model:** points_avg_season (20.2%), points_avg_last_5 (12.8%), points_avg_last_10 (10.0%), vegas_points_line (6.8%, down from 25.3%)

**Key findings:**
1. **Low-Vegas generates 5x more edge 3+ picks** (48 vs 10) — less market-anchored, more opinionated
2. **Low-Vegas UNDER is strong** at 61.1% — vegas dependency was hurting UNDER calibration
3. **No-Vegas is definitively worse** — removing vegas entirely wrecks edge 5+ HR (38%)
4. **Sweet spot: reduce, don't remove** — 0.25x weight shifts importance to player stats while keeping market anchor

**Caveat:** Feb 6-12 was the worst week of the season. Need post-ASB validation.

**Next steps:**
- Deploy low-vegas as shadow model once post-ASB games prove concept
- Try intermediate weights (0.5x, 0.15x) to find optimal balance
- Add more streak features (streak length, scoring acceleration) to V15 feature set
- Compare all variants with same filters — apples to apples

### P2: Scoring Distribution Research
**Hypothesis:** Points distribution between star and role players shifts during the season (trade deadline, All-Star break, playoff push, load management). If the model doesn't account for intra-team scoring redistribution, predictions for role players may systematically miss after mid-season trades.

**Research approach:**
1. Query `player_game_summary` to compute team-level scoring concentration (HHI index or Gini coefficient) by month
2. Check if model errors correlate with team-level scoring shifts
3. If significant: add `team_scoring_concentration` feature to Phase 4 precompute
4. Could also create `star_usage_share` and `role_player_scoring_volatility` features

### P2b: Odds API Historical Backfill Plan

**Current state:** DraftKings + FanDuel have 560 days of history. All other books have 3-4 days max.

**Backfill strategy (prioritized):**
1. **Season backfill (Nov 2025 → Feb 2026):** ~113 game dates × ~7.3 games/day × 10 units = ~8,300 quota units (trivial, 0.2% of remaining)
2. **Multi-snapshot:** Add closing line snapshots (snap-0200 data exists in GCS, not yet loaded to BQ). Opening + closing = line movement signal.
3. **Deep backfill (2023-2025):** DK/FanDuel already covered. Other books won't have historical data.

**Execution:**
```bash
# Backfill scripts already exist:
python scripts/backfill_historical_props.py --start-date 2025-11-01 --end-date 2026-02-12
# OR use Cloud Run Job:
# deployment/dockerfiles/nba/Dockerfile.odds-api-backfill
```

**API quota:** 4.99M remaining. Even aggressive backfill would use <1%.

### P3: Odds API Line Movement Features
**Hypothesis:** With more sportsbooks, we can compute true line movement (open → close across books) rather than relying on a single-book snapshot. Cross-book line standard deviation is already feature f50 (`multi_book_line_std`), but with 13 books it becomes much more informative.

**Research:**
- Monitor f50 quality after sportsbook expansion
- Consider adding line movement velocity (how fast lines move) as a new feature
- Look for "sharp money" signals where one book moves before others

### P4: Signal-Confirmed Observation Subset (Deferred)
Originally planned for this session but deferred. The model collapse is the priority. Once the fresh model proves itself post-ASB, add an observation subset tracking edge 5+ picks where combo_he_ms, combo_3way, or minutes_surge fires.

### P5: Retrain All Shadow Models
Once 2-3 days of post-ASB data exists:
- Retrain V12 MAE (also stale/BLOCKED)
- Retrain Q43, Q45 quantile models
- Retrain V12 Q43, V12 Q45
- Use `./bin/retrain.sh --all`

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Removed MAX_PICKS_PER_DAY, v298_natural_sizing |
| `data_processors/publishing/signal_annotator.py` | Updated top_n reference |
| `data_processors/publishing/signal_best_bets_exporter.py` | Updated docstrings |
| `shared/config/cross_model_subsets.py` | Removed top_n=5 from xm_consensus_4plus |
| `scrapers/oddsapi/oddsa_player_props.py` | Expanded to 12 verified sportsbooks |
| `scrapers/oddsapi/oddsa_player_props_his.py` | Expanded to 12 verified sportsbooks |
| `scrapers/oddsapi/oddsa_game_lines.py` | Expanded to 12 verified sportsbooks |
| `scrapers/oddsapi/oddsa_game_lines_his.py` | Expanded to 12 verified sportsbooks |
| `data_processors/publishing/tonight_all_players_exporter.py` | Added season stats |

## Verification Checklist (Post-ASB Feb 19+)

- [ ] `algorithm_version = 'v298_natural_sizing'` in signal_best_bets_picks
- [ ] Natural pick count varies (not always 5)
- [ ] Odds API returning data from >2 sportsbooks
- [ ] New model generating predictions with reasonable edge distribution
- [ ] No duplicate rows in signal_best_bets_picks
- [ ] Model performance daily tracking for new model
