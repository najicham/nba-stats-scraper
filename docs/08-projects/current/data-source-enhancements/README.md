# Data Source Enhancements Project

**Created:** 2026-01-12
**Status:** Planning
**Priority:** Medium (nice-to-have improvements)

## Overview

This project tracks potential data source enhancements to improve prediction accuracy beyond the current ~55% target. Based on analysis of the existing system and available market data.

## Current Data Sources (Already Have)

| Category | Sources | Status |
|----------|---------|--------|
| Betting Lines | OddsAPI, BettingPros | ✅ Complete |
| Player Stats | NBA.com, Ball Don't Lie, ESPN | ✅ Complete |
| Injuries | NBA.com official injury report | ✅ Complete |
| Schedule | NBA.com, ESPN | ✅ Complete |
| Play-by-Play | BigDataBall, PBPStats | ✅ Complete |
| Travel/Fatigue | Static distance matrix + fatigue scoring | ✅ Complete |
| Referee Assignments | NBA.com official assignments | ✅ Complete |

## Recommended Enhancements

### Priority 1: Referee Tendencies Processor (High Value, Low Cost)

**Gap:** Have assignments but NOT historical tendencies
**Impact:** Referee crews significantly affect pace and total points
**Effort:** Medium (build processor from existing data)

See: [01-referee-tendencies.md](./01-referee-tendencies.md)

### Priority 2: Player-Level Travel Impact (Medium Value, Low Cost)

**Gap:** Schema exists but `travel_adj = 0.0` (not calculated)
**Impact:** Cumulative travel fatigue affects performance
**Effort:** Low (infrastructure exists, just wire it up)

See: [02-player-travel-impact.md](./02-player-travel-impact.md)

### Priority 3: NBA.com Tracking Stats (High Value, Free)

**Gap:** Not currently scraping Second Spectrum derived stats
**Impact:** Better ML features (speed, touches, contested shots)
**Effort:** Medium (new scraper + processor)

See: [03-tracking-stats.md](./03-tracking-stats.md)

### Priority 4: Line Movement / Sharp Signals (High Value, Paid)

**Gap:** Have static lines but not movement/sharp indicators
**Impact:** Know when to bet, not just what to bet
**Effort:** Low (API integration) but ongoing cost

See: [04-line-movement.md](./04-line-movement.md)

## Future Considerations (Lower Priority)

See: [05-future-considerations.md](./05-future-considerations.md)

- Confirmed lineups/rotations (pre-game)
- Teammate availability cascade effects
- Coach rotation tendencies
- Blowout/garbage time risk modeling
- Historical closing line value tracking
- Altitude effects (Denver games)
- National TV game adjustments

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-12 | Created project | Research session identified gaps |
| | | |

## Files in This Project

```
data-source-enhancements/
├── README.md                    # This file
├── 01-referee-tendencies.md     # Referee historical stats
├── 02-player-travel-impact.md   # Complete travel fatigue calc
├── 03-tracking-stats.md         # NBA.com tracking data
├── 04-line-movement.md          # Sharp money / line movement
└── 05-future-considerations.md  # Lower priority ideas
```
