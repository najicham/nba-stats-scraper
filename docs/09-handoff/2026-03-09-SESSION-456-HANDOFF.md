# Session 456 Handoff — Mar 8 Autopsy Fixes + Slate Observations

*Date: 2026-03-09*

## What Was Done

### Mar 8 Autopsy (3-11, 21.4% HR — worst day on record)

Root causes identified:
1. **FT variance killed UNDER** — 5/11 losses from FT explosions (Booker 15/15, KAT 8/8, Wemby 9/10)
2. **SAS-HOU game concentration** — 3 UNDER picks from 1 game, all lost
3. **Manufactured line anomaly** — Derrick White OVER 8.5 (line dropped 48% from 16.5)
4. **Ultra criteria hollow** — 76% of ultra picks had empty criteria (56.3% HR)
5. **Shadow/base signal inflation** — 8/11 losses had real_sc <= 2
6. **Algorithm version fragmentation** — Picks on v429/v438/v440, not v451
7. **Model UNDER bias -5.41** — Systematically underestimates scoring

### Fixes Deployed (Session 452, v452_mar8_game_cap_ft_rsc)

| Fix | Type | Impact |
|-----|------|--------|
| `ft_variance_under` | PROMOTED to active filter | Blocks UNDER on FTA>=5 + CV>=0.5 (47.8% vs 70.6% HR gap) |
| `under_low_rsc` | PROMOTED to active filter | Blocks UNDER real_sc<2 at edge<7 (8/11 Mar 8 losses) |
| `MAX_PICKS_PER_GAME=3` | New merger constraint | Prevents same-game concentration across both teams |
| Ultra tier derivation | Bug fix | `bool(ultra_criteria)` — no more hollow ultra tags |
| ALGORITHM_VERSION | Architecture | Single source of truth in pipeline_merger.py |

All 5 builds SUCCESS. 136 tests passing (+10 new).

### Slate Observations (Session 453, v453_slate_observations)

Observation-only tags on merged slates (no blocking):
- `slate_heavy_over_lean` / `slate_heavy_under_lean` — >80% directional at 5+ picks
- `slate_same_game_same_dir` — 2+ picks same game same direction
- `slate_game_concentration` — 3+ picks from single game

145 tests passing (+9 new).

## Mar 9 Picks (ran on v451 — 13 min before deploy)

- SGA UNDER 31.5 (edge 3.9, real_sc 2) — documented 62% UNDER HR at 30+ lines
- Chet Holmgren UNDER 17.5 (edge 3.2, real_sc 2)

New filters would NOT have changed these picks (both already pass real_sc >= 2).

## Key Findings

### Ultra Collapse
- Jan-Feb: 72.6% HR (84 picks)
- Mid-Feb onward: 45.8% HR (72 picks)
- Mar 7-8 combined: 4-17 (23.5%)
- Root cause: 76% of ultra picks had empty criteria, running at 56.3% (barely above baseline)

### Model UNDER Bias
- Mar 8 catboost_v12: UNDER bias -5.41 (underestimates by 5.4 pts)
- Wrong-direction calls on Luka (5.2 edge), Reaves (5.6), Mitchell (6.9), Mobley (9.5)
- **MONITOR for 3-5 days before concluding structural**

### Filter Audit (Mar 8)
- `under_star_away` blocked 2 winners, 0 losers (100% CF HR) — investigate for demotion
- `blowout_risk_under_block_obs` correctly blocked 5 losers (16.7% CF HR)
- `med_usage_under` correctly blocked 5 losers (16.7% CF HR)

## What's Next

### P0: Monitor (this week)
- Check v452 filter impact on next full slate (8+ games)
- Track model UNDER bias — if >-3.0 for 3+ days, flag for retrain
- Watch ultra pick volume (should drop significantly)

### P1: Weekly Retraining (Session 455 finding)
- Walk-forward showed 85% HR at edge 3+ with fresh models vs ~55% with stale
- Production models 10-60d stale. Weekly retrain is #1 ROI improvement.
- Scripts ready: `walk_forward_simulation.py`, `bb_pipeline_gap_analysis.py`

### P2: Filter Tuning
- Revisit `under_star_away` after 1 more week of data
- Consider promoting remaining observations after data accumulates (~late March)

## Files Changed

- `ml/signals/pipeline_merger.py` — Game cap, slate obs, version
- `ml/signals/aggregator.py` — Promoted 2 filters, version import
- `data_processors/publishing/signal_best_bets_exporter.py` — Ultra tier, version cleanup
- `tests/unit/signals/test_pipeline_merger.py` — NEW (6 game cap + 9 slate obs tests)
- `tests/unit/signals/test_aggregator.py` — Updated filter keys, added under_low_rsc tests
