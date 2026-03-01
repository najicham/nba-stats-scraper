# Intraday Line Movement Signal — Research Findings (Session 371)

## Status: FUTURE EXPERIMENT — Not implemented

## Key Findings

Backtest analysis of intraday line movement between first odds snapshot and game time:

| Movement Bucket | Direction | HR | N | Notes |
|-----------------|-----------|------|-----|-------|
| DOWN_1 (line dropped 0.5-1.5) | ALL | 62.3% | 247 | Strong UNDER signal |
| DOWN_1 | UNDER | 68.6% | 185 | Best single bucket |
| DOWN_1 | OVER | 43.5% | 62 | Avoid OVER when line drops |
| UP_2+ (line jumped 2+) | OVER | 84.6% | 13 | Very promising but tiny N |
| STABLE (no movement) | ALL | 56.8% | 1,847 | Baseline |

## Why Not Implemented Now

**Critical timing issue:** Predictions run at ~6 AM ET, but the first odds snapshot is at ~7 AM ET. The feature would need same-day line movement data that doesn't exist at prediction time.

## Implementation Options for Future Sessions

### Option A: Previous-Day Close to Current Opening
- Compare yesterday's closing line to today's opening line
- Requires: schema for tracking multi-day line trajectories
- Pro: Available at prediction time
- Con: Less precise than intraday movement

### Option B: Delayed Predictions
- Run predictions after 7 AM ET when first snapshot is available
- Requires: pipeline timing change
- Pro: True intraday data
- Con: Reduces time window for publishing picks

### Option C: Post-Prediction Signal Update
- Run initial predictions at 6 AM, then re-evaluate signals at 8 AM with line movement data
- Requires: Phase 6 re-export with updated signal data
- Pro: Best of both worlds
- Con: More complex pipeline

## Data Source

`nba_raw.odds_api_player_points_props` — `snapshot_timestamp` tracks when each line was captured. Multiple snapshots per day per bookmaker.

## Next Steps

1. Quantify how often DOWN_1 fires (coverage analysis)
2. Check if previous-day close → opening is a viable proxy
3. If Option C, design the re-evaluation trigger
