# Session 283 Handoff — Parameter Sweeps + Angle Optimization

**Date:** 2026-02-17
**Duration:** Full session during All-Star break
**Games resume:** Feb 19 (10-game slate)

---

## What We Did

Ran **40 experiments** across 3 phases to optimize the season replay configuration:

### Phase A: Parameter Sweeps (18 experiments)
- **Blacklist threshold sweep:** BL35, BL45, BL50 x 2 seasons (BL40 already tested)
- **Rolling window sweep:** Roll42, Roll70, Roll84 x 2 seasons (Roll56 already tested)
- **Cadence sweep:** Cad7, Cad10, Cad21 x 2 seasons (Cad14 already tested)

### Phase B: Combo Experiments (8 experiments)
- Cad7+Roll42, Cad10+Roll42, Cad21+Roll42 x 2 seasons
- Phase B dimension experiments with 11 new dimensions x 2 seasons

### Phase C: Targeted Angle Experiments (12 experiments)
- UNDER-only, Line 10-19.5, Edge>=5, Avoid familiar, UNDER+Line combo, Edge5+UNDER combo x 2 seasons

### Phase B: New Dimensions Added (code change)
Added 11 new dimensions to `compute_dimensions()` in `season_replay_full.py`:
- Opponent Defense, Opp Def x Direction, Matchup Familiarity, Fatigue Level, Fatigue x Direction
- Rest Advantage, Location x Direction, Minutes Change, Trend x Direction, Vegas Line Move, Line Move x Direction

### New Experiment Filters Added (code change)
Added 5 new CLI flags to `season_replay_full.py`:
- `--under-only` (Exp H): UNDER predictions only
- `--min-line` / `--max-line` (Exp I): prop line range filter
- `--no-rel-edge-filter` (Exp J): disable rel_edge>=30% smart filter
- `--avoid-familiar` (Exp K): skip players with 6+ games vs opponent

---

## Key Results

### Final Ranking — All Configurations Tested

| Rank | Config | Combined P&L | HR | N | Delta vs S282 |
|------|--------|-------------|-----|------|--------------|
| **1** | **Cad7+Roll42+BL40+AvoidFam** | **+$92,470** | **60.3%** | 5,593 | **+$22,500 (+32%)** |
| 2 | Cad7+Roll42+BL40 | +$90,690 | 60.0% | 5,697 | +$20,720 (+30%) |
| 3 | Cad10+Roll42+BL40 | +$89,210 | 59.6% | 5,888 | +$19,240 (+27%) |
| 4 | Cad21+Roll56+BL40 | +$82,040 | 58.8% | 6,041 | +$12,070 (+17%) |
| 5 | Cad21+Roll42+BL40 | +$79,640 | 58.5% | 6,227 | +$9,670 (+14%) |
| 6 | Cad14+Roll42+BL40 | +$75,340 | 58.4% | 5,995 | +$5,370 (+8%) |
| 7 | Cad14+Roll56+BL40 (S282 baseline) | +$69,970 | 58.3% | 5,662 | — |

### High-Precision Angles (use as "high conviction" tier, not primary)

| Angle | Combined HR | N | $/pick | Both seasons stable? |
|-------|-----------|-----|--------|---------------------|
| **Edge >= 5** | **65.6%** | 886 | $27.7 | YES (65.1% / 66.6%) |
| Edge5 + UNDER | 62.0% | 761 | $20.2 | YES (58.8% / 67.0%) |
| Line 10-19.5 | 61.9% | 2,685 | $20.0 | YES (63.6% / 59.8%) |

### Stable Gold Dimensions (from cross-season analysis)

| Dimension | Combined HR | N | Cross-Season Delta |
|-----------|-----------|------|-------------------|
| Edge 5-7 | 65.1% | 777 | 1pp |
| Line 10-14.5 | 61.2% | 1,378 | 1pp |
| January | 61.0% | 2,555 | 2pp |
| Line 30+ | 60.1% | 484 | 2pp |
| Star high edge (25+ line, 5+ edge) | 60.0% | 502 | 5pp |
| Starter UNDER | 58.2% | 2,590 | 0pp |

### Confirmed Avoid Zones

| Dimension | HR | Action |
|-----------|-----|--------|
| Familiar matchup (6+ games) | 47.5% | **BLOCK** (implemented as --avoid-familiar) |
| High fatigue OVER | 42.3% | Already blocked by UNDER bias |
| Away OVER | 37.5% | Already blocked by UNDER bias |
| Cold snap OVER | 23.1% | Already blocked |
| 3pt bounce OVER | 46.2% | Already blocked |

### Critical Finding: rel_edge>=30% Filter Blocks Profitable Picks

The `rel_edge>=30%` smart filter blocks picks with **62.8% combined HR** (65.5% in 2025-26, 55.7% in 2024-25). This is above breakeven. Consider disabling or making it adaptive.

---

## Key Findings Summary

1. **Cadence is the biggest lever** — 7-day retraining beats 14-day by +$7,670-$20,720
2. **Shorter rolling windows win** — 42d > 56d > 70d > 84d
3. **Blacklist threshold barely matters** — BL35-BL50 all within ~$2K of each other
4. **Cad7 + Roll42 gains stack** — combo is better than either alone
5. **Volume-restriction filters hurt total P&L** — UNDER-only, line range, edge>=5 all raise HR but lose money
6. **Targeted blockers work** — Blacklist + Avoid Familiar remove the worst picks without losing volume
7. **Edge >= 5 is the highest stable HR ever found** — 65.6% across both seasons, but only 886 picks
8. **Phase B dimensions mostly inconclusive** — most features have narrow distributions in replay data

---

## What Needs Implementing (Before Feb 19)

### Priority 0: Production Changes

1. **Player blacklist in production** — Add to signal aggregator or tonight_player_exporter
   - Track per-player rolling HR (8+ graded picks, <40% HR = blacklisted)
   - Implementation options: `ml/signals/aggregator.py` line 124-128 (filter loop) or `data_processors/publishing/tonight_player_exporter.py`

2. **Switch retrain.sh to 42-day rolling window** — Change `TRAINING_START` calculation
   - Currently uses expanding window from 2025-11-02
   - Change to: `TRAINING_START=$(date -d "42 days ago" +%Y-%m-%d)`
   - File: `bin/retrain.sh`

3. **Switch to 7-day retrain cadence** — Change Cloud Scheduler from biweekly to weekly
   - Update `retrain-reminder` CF schedule
   - Modify `bin/retrain.sh` cadence parameter

4. **Raise V12 quantile min edge to 4** — In prediction worker actionability filters
   - File: `predictions/worker/worker.py` lines 2099-2190

5. **Add avoid-familiar filter** — Skip players with 6+ games vs opponent in signal aggregator
   - Use `games_vs_opponent` (feature 30) from `ml_feature_store_v2`

### Priority 1: Consider Implementing

6. **Disable or make adaptive the rel_edge>=30% filter** — Currently blocking 62.8% HR picks
7. **Add "high conviction" tier** — Edge >= 5 picks get special designation (65.6% HR)
8. **Add line range sweet spot indicator** — Line 10-14.5 picks flagged (61.2% HR)

---

## Experiments Still Worth Running

### Not Yet Tested

1. **Adaptive mode + Cad7+Roll42+BL40** — combine dynamic direction gating with best combo
2. **Min training days sweep** — currently 28d minimum, test 14d/21d (more cycles = more fresh models)
3. **V12 feature dimensions** — prop_over/under_streak (feature 51/52), scoring_trend_slope (feature 44) — need to wire V12 features into eval_df
4. **Per-model edge thresholds** — V12 Q43 at edge>=4, V9 MAE at edge>=5, others at edge>=3
5. **Blacklist within consensus only** — more targeted: only blacklist when in xm_consensus_3plus
6. **Cad7+Roll42+BL40+AvoidFam+UNDER-only** — does adding UNDER-only to the new champion help?
7. **Multi-book disagreement filter** — feature 50 (multi_book_line_std) as quality gate
8. **Investigate feature_3_value** — points std dev mostly <5 in 2025-26 (data/scale issue?)
9. **Investigate opponent_def_rating** — mostly 110-114 in 2025-26 (narrow distribution)

### How to Run

```bash
# Best config baseline
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2025-11-04 --season-end 2026-02-17 \
    --cadence 7 --rolling-train-days 42 --player-blacklist-hr 40 \
    --avoid-familiar \
    --save-json ml/experiments/results/replay_2526_EXPERIMENT_NAME.json

# Same for 2024-25 season
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2024-11-06 --season-end 2025-04-13 \
    --cadence 7 --rolling-train-days 42 --player-blacklist-hr 40 \
    --avoid-familiar \
    --save-json ml/experiments/results/replay_2425_EXPERIMENT_NAME.json

# Analysis script for comparing results
PYTHONPATH=. python ml/experiments/analyze_phase_a.py
```

### Available CLI Flags

| Flag | Description | Session Added |
|------|-------------|---------------|
| `--cadence N` | Retrain every N days (default 14) | S280 |
| `--rolling-train-days N` | Rolling training window (default: expanding) | S281 |
| `--player-blacklist-hr N` | Blacklist players below N% HR after 8+ picks | S282 |
| `--under-only` | UNDER predictions only | S283 |
| `--min-line N` / `--max-line N` | Prop line range filter | S283 |
| `--min-edge N` | Min edge threshold (default 3.0) | S280 |
| `--avoid-familiar` | Skip players with 6+ games vs opponent | S283 |
| `--adaptive` | Dynamic direction/filter gating per cycle | S281 |
| `--tier-models` | Train separate models per tier | S282 |

---

## Files Changed

| File | Change |
|------|--------|
| `ml/experiments/season_replay_full.py` | Added 11 dimensions + 5 experiment filters + CLI args |
| `ml/experiments/analyze_phase_a.py` | New — Phase A comparison script |
| `docs/08-projects/current/season-replay-analysis/00-FINDINGS.md` | Added Session 283 results |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Updated with Session 283 state |
| `docs/09-handoff/2026-02-17-SESSION-283-HANDOFF.md` | This file |

## Result Files (in `ml/experiments/results/`, gitignored)

### Phase A (18 files)
- `replay_{2526,2425}_bl{35,45,50}.json` — Blacklist sweep
- `replay_{2526,2425}_roll{42,70,84}_bl40.json` — Rolling window sweep
- `replay_{2526,2425}_cad{7,10,21}_bl40.json` — Cadence sweep

### Combos (6 files)
- `replay_{2526,2425}_cad{7,10,21}_roll42_bl40.json`

### Phase B (2 files)
- `replay_{2526,2425}_cad21_newdims.json` — With 11 new dimensions

### Phase C (12 files)
- `replay_{2526,2425}_best_underonly.json`
- `replay_{2526,2425}_best_line10to20.json`
- `replay_{2526,2425}_best_edge5.json`
- `replay_{2526,2425}_best_avoidfam.json`
- `replay_{2526,2425}_best_under_line10to20.json`
- `replay_{2526,2425}_best_edge5_under.json`
