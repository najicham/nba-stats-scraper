# Player Deep Dive Analysis

## Purpose

Comprehensive scoring pattern analysis for individual NBA players. Identifies actionable patterns in scoring, prop line performance, rest/fatigue, matchups, shooting, and game context that can inform prediction and betting decisions.

## Tool

```bash
python bin/analysis/player_deep_dive.py PLAYER_LOOKUP [--seasons N] [--output PATH]
```

### Modules

| # | Module | What It Analyzes |
|---|--------|-----------------|
| 1 | Baseline Scoring | Season averages, distribution, monthly patterns |
| 2 | Prop Line Performance | Over/under rates by line range, streaks, margin distribution, line movement |
| 3 | Rest & Fatigue | Days rest impact, B2B, fatigue score correlation |
| 4 | Home vs Away | Scoring splits, prop line by location, combined with rest |
| 5 | Matchup Analysis | Per-opponent averages, defensive rating/pace correlation |
| 6 | Shooting Patterns | Shot zones, 3PT volume, efficiency in above/below avg games |
| 7 | Game Context | Win/loss, minutes, usage rate, spread/blowout, star teammates out |
| 8 | Temporal | Day of week, month trends, season phase, post-big/bad game bounce |
| 9 | Model Performance | Our prediction accuracy on this player by model, direction, edge band |

### Data Sources

- `nba_analytics.player_game_summary` — game stats, prop lines, shot zones
- `nba_predictions.ml_feature_store_v2` — contextual features (rest, pace, matchup, fatigue)
- `nba_predictions.prediction_accuracy` — graded predictions

### Known Data Issues

- `win_flag` is always FALSE — tool uses `plus_minus > 0` as proxy
- `is_dnp` is NULL for older records — tool filters `(is_dnp IS NULL OR is_dnp = FALSE)`

## Documents

| Doc | What |
|-----|------|
| [01 - Curry Findings](./01-CURRY-FINDINGS.md) | Stephen Curry deep dive — 188 games, actionable spots |
| [02 - Systematization Plan](./02-SYSTEMATIZATION-PLAN.md) | Cross-season stability analysis, what works vs doesn't |
| [03 - Signal Findings](./03-SIGNAL-FINDINGS.md) | 10 exploitable findings from player profile research |
| [04 - Implementation Plan](./04-IMPLEMENTATION-PLAN.md) | Signal implementation steps, validation plan, timeline |

## Key Findings

1. Player over/under rates regress to the mean (r=0.14), BUT structural scoring traits interact with our model in exploitable ways
2. **Bounce-back is an AWAY phenomenon** — 56.2% over after bad miss on the road (N=379), disappears at home
3. **Model blind spot** — UNDER after 3 consecutive unders hits only 44.7% (N=515). Model chases trends.
4. **Tier effects** — Stars=UNDER, Starters=OVER (61.1% at edge 3+), Role players=UNDER (60%, highest volume)
5. **Bad shooting bounces harder** than low minutes — FG% < 35% → 54.5% over next game

## Status

- Tool: COMPLETE (`bin/analysis/player_deep_dive.py`)
- Research: COMPLETE (10 findings documented)
- Implementation: PLANNED (P0 signals ready to build)
- Batch deep dives: PLANNED (262 players)
