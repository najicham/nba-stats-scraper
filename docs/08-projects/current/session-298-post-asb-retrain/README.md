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
- **After:** 13 books across all 4 Odds API scrapers (live + historical, props + game lines)
- **New books:** betmgm, williamhill_us, betrivers, bovada, fanatics, espnbet, hardrockbet, ballybet, fliff, betus, lowvig
- **Impact:** More price points → better consensus lines → better feature quality → better model predictions
- **Note:** Not all books carry NBA player props. The API returns only available books — no harm in requesting more.

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

### P1: Vegas Weight Experiment
**Hypothesis:** V9 MAE relies ~40% on Vegas features. Reducing Vegas weight could make the model more independent and less susceptible to market regime shifts.

**Experiment design:**
- Train V9 variant with Vegas features downweighted to ~10% total importance
- Add more streak/momentum features to compensate
- Compare with same filters (edge 5+, UNDER 7+ block, negative filters) — apples to apples
- Key metric: edge 5+ HR, not just MAE

**Implementation path:**
- Use `--feature-weights` parameter in quick_retrain.py to reduce vegas_points_line, vegas_opening_line, vegas_line_move weights
- Or: create V15 feature set with reduced vegas columns and added streak features
- Compare using `/model-experiment` skill

### P2: Scoring Distribution Research
**Hypothesis:** Points distribution between star and role players shifts during the season (trade deadline, All-Star break, playoff push, load management). If the model doesn't account for intra-team scoring redistribution, predictions for role players may systematically miss after mid-season trades.

**Research approach:**
1. Query `player_game_summary` to compute team-level scoring concentration (HHI index or Gini coefficient) by month
2. Check if model errors correlate with team-level scoring shifts
3. If significant: add `team_scoring_concentration` feature to Phase 4 precompute
4. Could also create `star_usage_share` and `role_player_scoring_volatility` features

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
| `scrapers/oddsapi/oddsa_player_props.py` | Expanded to 13 sportsbooks |
| `scrapers/oddsapi/oddsa_player_props_his.py` | Expanded to 13 sportsbooks |
| `scrapers/oddsapi/oddsa_game_lines.py` | Expanded to 13 sportsbooks |
| `scrapers/oddsapi/oddsa_game_lines_his.py` | Expanded to 13 sportsbooks |
| `data_processors/publishing/tonight_all_players_exporter.py` | Added season stats |

## Verification Checklist (Post-ASB Feb 19+)

- [ ] `algorithm_version = 'v298_natural_sizing'` in signal_best_bets_picks
- [ ] Natural pick count varies (not always 5)
- [ ] Odds API returning data from >2 sportsbooks
- [ ] New model generating predictions with reasonable edge distribution
- [ ] No duplicate rows in signal_best_bets_picks
- [ ] Model performance daily tracking for new model
