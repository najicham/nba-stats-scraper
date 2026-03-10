# Session 459 Handoff — MLB P0/P1 Experiment Matrix (All Dead Ends)

*Date: 2026-03-09*

## What Was Done

### P0 Experiments (Odds-Aware Ranking + Juice Filter)

Added `--ev-ranking` and `--max-juice` flags to `season_replay.py`. Tested across 4 seasons.

| Experiment | Total Delta | Verdict |
|------------|------------|---------|
| EV ranking (edge x payout_multiplier) | +6.2u | NOISE — flip-flops between seasons (2 pos, 2 neg) |
| Max juice -160 filter | -33.3u | DEAD END — heavy faves actually profitable at 64% HR |

### P1 Experiments (Edge Floor, RSC Cap, Rescue, Max Edge, Training Window)

Added `--max-rsc`, `--no-rescue`, `--max-edge-cap` flags to `season_replay.py`. Tested 10 experiments x 4 seasons (40 runs total).

| Experiment | Total P&L | Delta | Consistent? | Verdict |
|-----------|-----------|-------|-------------|---------|
| **V3 FINAL (baseline)** | **+444.4u** | — | — | **KEEP** |
| Edge floor 0.85 | +400.3u | -44.1u | 2/4 | DEAD END |
| Edge floor 1.00 | +312.8u | -131.6u | 0/4 | DEAD END |
| RSC cap <= 5 | +450.4u | +6.0u | 1/4 | NOISE |
| RSC cap <= 4 | +424.2u | -20.2u | 1/4 | DEAD END |
| No rescue | +375.2u | -69.2u | 0/4 | DEAD END |
| Max edge 1.5 | +369.5u | -74.9u | 0/4 | DEAD END |
| Edge 1.0 + RSC 5 | +315.2u | -129.2u | 0/4 | DEAD END |
| Edge 0.85 + RSC 5 + no rescue | +331.1u | -113.3u | 1/4 | DEAD END |
| Training window 90d | +408.4u | -36.0u | 1/4 | DEAD END |

### Key Findings

1. **Rescue signals are valuable (+69u)** — `opponent_k_prone` rescue adds real profitable picks
2. **RSC 6+ is NOT losing money** — original claim doesn't hold with current data
3. **Edge floor 0.75 is the sweet spot** — raising it cuts profitable picks
4. **Max edge 2.0 is correct** — tightening to 1.5 removes good high-edge predictions
5. **"High HR but low P&L" trap** — triple filter gets 63.1% HR but only +331u (volume kill)
6. **120d training window > 90d** — 120d is more stable across seasons

### Code Changes

Added 5 new CLI flags to `season_replay.py` for experiment replay:
- `--ev-ranking` — rank OVER by EV instead of raw edge
- `--max-juice N` — block picks with odds worse than N
- `--max-rsc N` — cap real signal count
- `--no-rescue` — disable rescue signals
- `--max-edge-cap N` — override max edge cap

These are experiment-only flags. **No production code changes.**

## V3 FINAL Status: LOCKED

```
Training: 120d window, 14d retrains
Edge floor: 0.75 K (home), 1.25 K (away)
Away rescue: BLOCKED
Volume: 5 picks/day
Signals: long_rest_over, k_trending_over → TRACKING_ONLY
Ultra: Home + Projection agrees + edge >= 0.5 + not rescued
Staking: 1u BB, 2u Ultra
Blacklist: OFF
Algorithm: mlb_v8_s456_v3final_away_5picks
```

**12 experiments across 2 sessions (458-459) confirm this is near-optimal.** No parameter tweak improves P&L consistently across all 4 seasons.

## Dead Ends Log (Cumulative from Sessions 458-459)

| Experiment | Result | Why It Failed |
|-----------|--------|---------------|
| Static blacklist (28 pitchers) | Season-specific | 96% of pitchers only bad in 1 season |
| Dynamic BL N>=10/HR<40% | +1.4u | Self-corrects too fast |
| EV ranking | +6.2u | Noise — flip-flops across seasons |
| Max juice -160 | -33.3u | Heavy faves actually profitable |
| Edge floor 0.85 | -44.1u | Cuts profitable volume |
| Edge floor 1.00 | -131.6u | Severe volume kill |
| RSC cap <= 5 | +6.0u | Noise — inconsistent |
| RSC cap <= 4 | -20.2u | Over-filters |
| No rescue | -69.2u | Rescue adds +69u value |
| Max edge 1.5 | -74.9u | Removes good predictions |
| Edge 1.0 + RSC 5 | -129.2u | Compound filter failure |
| Edge 0.85 + RSC 5 + no rescue | -113.3u | High HR but volume kill |
| Training window 90d | -36.0u | 120d is more stable |

## What's Next

### P0: Before Opening Day (March 25)
- [x] V3 FINAL deployed to production (Session 458)
- [x] Odds-aware ranking tested — DEAD END
- [x] Max juice filter tested — DEAD END
- [x] Edge floor tuning tested — DEAD END
- [x] RSC cap tested — DEAD END
- [ ] Push all changes to main
- [ ] Verify builds
- [ ] Check drift
- [ ] Paper trade April 1-14 at 50% stakes
- [ ] Full stakes from April 15+

### Future Experiments (post-launch, lower priority)
- Lineup K rate feature (computed in feature store, add to training)
- Umpire zone features (orthogonal signal)
- Rolling window dynamic BL (last 15-20 picks instead of full season)
- CatBoost hyperparameter sweep (depth, lr, iterations)

## Files Modified

| File | Change |
|------|--------|
| `scripts/mlb/training/season_replay.py` | 5 new experiment flags: ev-ranking, max-juice, max-rsc, no-rescue, max-edge-cap |
