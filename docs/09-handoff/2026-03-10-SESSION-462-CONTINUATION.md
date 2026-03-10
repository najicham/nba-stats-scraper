# Session 462 Continuation — Implement Validated Signals + Find More Structural Edges

**Date:** 2026-03-10
**Previous:** Session 461 (BB Pipeline Simulator, 5-season experiments)
**Handoff:** `docs/09-handoff/2026-03-10-SESSION-461-HANDOFF.md`

## Context

Session 461 built a BB pipeline simulator and tested signals across 5 seasons (2021-22 through 2025-26). The raw model is 53% HR — all edge comes from the BB pipeline's signal/filter selection. We found several validated structural signals AND discovered that some existing signals/filters are actively destroying value.

## P0: Implement Validated Signal Changes

### New Signals to Add

**1. `hot_3pt_under` — 62.5% HR, N=670, consistent ALL 5 seasons**
- Fires: direction=UNDER AND (three_pct_last_3 - three_pct_season >= 0.10)
- Data source: `three_pct_last_3` and `three_pct_season` from supplemental_data.py (pre-game, uses `ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING`)
- Mechanism: Books anchor to season avg; recent hot 3PT streak is temporary regression bait
- Implementation: New signal class in `ml/signals/`, add to signal registry
- **This is the highest-impact change available. 62.5% HR at N=670 across 5 seasons.**

**2. `cold_3pt_over` — 60.2% HR, N=123, consistent 5 seasons**
- Fires: direction=OVER AND (three_pct_last_3 - three_pct_season <= -0.15)
- Mechanism: Player shooting cold from 3 bounces back. Regression to mean.
- Smaller N but validates the inverse of hot_3pt_under

**3. `line_drifted_down_under` — 59.8% HR, N=336, consistent 5 seasons**
- Fires: direction=UNDER AND BettingPros line_movement in [-0.5, -0.1)
- Data source: `nba_raw.bettingpros_player_points_props` (opening_line vs points_line)
- Mechanism: Smart money nudging line down but books haven't moved far enough
- Need to compute this from BettingPros data in the prediction pipeline

### New Filters to Add

**4. `cold_fg_under_filter` — blocks 38.5% HR picks (N=457)**
- Block when: direction=UNDER AND (fg_pct_last_3 - fg_pct_season <= -0.10)
- Mechanism: Cold shooter regresses UP, making UNDER dangerous
- This is the single most impactful filter — blocking 34.5-38.5% HR picks

**5. `cold_3pt_under_filter` — blocks 45.6% HR picks (N=735)**
- Block when: direction=UNDER AND (three_pct_last_3 - three_pct_season <= -0.10)
- Same mechanism for 3PT specifically

**6. `over_line_rose_heavy_filter` — blocks 38.9% HR picks (N=54)**
- Block when: direction=OVER AND BettingPros line rose >= 1.0
- Mechanism: Fighting the market

### Existing Filters to Remove

**7. Remove `ft_variance_under`** — 56.0% CF HR, N=1,001. Blocking winners.
**8. Remove `b2b_under`** — 54.0% CF HR, N=2,060. Blocking winners.
**9. Remove `familiar_matchup`** — 54.4% CF HR, N=1,151. Blocking winners.

### Existing Signals to Remove

**10. Remove `starter_away_overtrend_under`** — 48.2% HR, actively harmful
**11. Remove `sharp_book_lean_over`** — 41.7% HR, actively harmful
**12. Remove `over_streak_reversion_under`** — 51.6% HR, no edge

## P1: Find More Structural Signals

The 3PT reversion signal works because of a known market inefficiency: books anchor to season averages while short-term shooting fluctuations are random. What other market mechanics can we exploit?

### Hypotheses to Test (from Session 461 initial scan)

**Already confirmed promising (need deeper validation):**
- UNDER + line > season_avg + 2: 53.2% (N=1,389) — weak standalone but may combo well
- UNDER + hot FG + hot 3PT combined: 63.8% (N=494) but market adapted in recent seasons — 3PT alone is safer

**New hypotheses to explore:**
1. **Free throw rate anomaly** — Players whose recent FTA is 50%+ above season avg → UNDER (inflated scoring from unsustainable FT rate)
2. **Minutes trend** — Players whose recent minutes are declining → UNDER (role reduction the market hasn't priced)
3. **Opponent defensive strength** — Against top-5 defense → UNDER, against bottom-5 → OVER
4. **Game total environment** — Very high game total (240+) → OVER boost, very low (<210) → UNDER boost
5. **Back-to-back OVER** — The b2b_under filter was blocking winners (54% CF HR), suggesting B2B might actually favor UNDER less than expected. Test B2B effect by position.
6. **Referee tendencies** — Covers referee data in `nba_raw.covers_referee_stats`. Some refs call more fouls → more FTs → higher scoring
7. **Line staleness** — How old is the line? Lines set 24h+ ago may not reflect latest news
8. **Consensus vs sharp line** — When sharp books (Pinnacle) differ from consensus → follow sharp

### Approach

Use the BB enriched simulator infrastructure:
```bash
# The simulator and all enrichment data are ready:
PYTHONPATH=. python scripts/nba/training/bb_enriched_simulator.py

# Enrichment data files (all seasons):
results/bb_simulator/feature_store_enrichment.csv     # 133K rows
results/bb_simulator/feature_store_extra.csv          # 133K rows
results/bb_simulator/player_game_summary_enrichment.csv  # 132K rows
results/bb_simulator/bettingpros_multibook.csv        # 81K rows
results/bb_simulator/schedule_enrichment.csv          # 6K games

# Walk-forward predictions (all seasons):
results/nba_walkforward_clean/predictions_w56_r7.csv  # 2023-24 + 2024-25
results/nba_walkforward_2021/predictions_w56_r7.csv   # 2021-22
results/nba_walkforward_2022/predictions_w56_r7.csv   # 2022-23
results/bb_simulator/predictions_2025_26_v9.csv       # 2025-26
```

**CRITICAL: Avoid look-ahead bias.** Session 461 found that `starter_flag`, `usage_rate`, `minutes_played`, and `fg_pct_season` from PGS include current-game data. For any new signal:
- Use feature store columns (pre-game by construction)
- Use PGS rolling stats with `PRECEDING` windows (confirmed clean: `fg_pct_last_3`, `three_pct_last_3`, `mean_points_10g`, `fta_avg_last_10`, `prev_pm_*`)
- NEVER use current-game PGS raw columns (`starter_flag`, `usage_rate`, `minutes_played`, `fg_pct_season`, `three_pct_season`)
- When in doubt, verify with manual game-by-game trace (Session 461 method)

### Signal Quality Bar

From Session 461 peer review:
- **Minimum N >= 50** for any signal consideration
- **Must be consistent across 3+ seasons** (> 50% HR in each with N >= 10)
- **Must use pre-game data only** — verify data availability at prediction time
- **Filter candidates need CF HR < 48%** with N >= 100

## P2: Edge Strategy Changes

**Edge 6-8 band** should be a priority/ultra tier — 61.4% HR across 5 seasons. Currently all edge 3+ goes into the same bucket.

**sc>=4 rsc>=2 top3** is the best signal-gated strategy — 58.6% HR, 1.9/day.

## P3: Investigate Pre-Game Bench Identification

bench_under's 76.5% HR was look-ahead biased (post-game starter_flag). But the MARKET INEFFICIENCY IS REAL — books systematically overprice bench player scoring. The question is: can we identify bench players pre-game?

Check:
1. `nba_raw.rotowire_lineups` — does it have expected starters? What's the accuracy?
2. Season rolling starter_flag (% of games started in last N) — threshold at < 50%?
3. Player's previous game starter_flag — 80.7% match rate with current game

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | Main signal evaluation + BB pipeline |
| `ml/signals/pipeline_merger.py` | Per-model merger, caps, ranking |
| `ml/signals/signal_registry.py` | Signal class registry |
| `shared/config/cross_model_subsets.py` | Dynamic subset definitions |
| `predictions/supplemental_data.py` | Pre-game data queries |
| `scripts/nba/training/bb_enriched_simulator.py` | 5-season simulator |

## Key Principles from Session 461

1. **Market structural inefficiencies > model cleverness.** The model is 53%. All alpha comes from selection.
2. **3PT shooting reversion is the archetype** — a mathematical certainty (regression to mean) that books don't fully price.
3. **Cold shooting UNDER is a trap** — 34.5% HR. Regression works both ways. Block it.
4. **Always verify pre-game data availability** before claiming a signal works.
5. **FG% reversion decayed (2024-25+)** but 3PT reversion didn't — markets adapt at different speeds for different stats.
6. **Fewer picks = better quality.** Top 3/day beats top 15/day every time.
