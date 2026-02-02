# Kalshi Integration Project

## Problem Statement

Traditional sportsbooks (DraftKings, FanDuel, BetMGM) limit winning bettors. Kalshi is a CFTC-regulated prediction market that profits from transaction fees (~2%), not bettor losses, so they have no incentive to limit winners.

**Goal:** Integrate Kalshi NBA player props data into our prediction pipeline, giving users an alternative platform that won't limit them for winning.

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Design | In Progress | Architecture and schema design |
| 2. Scraper | Not Started | Kalshi API integration |
| 3. Processor | Not Started | Raw data processor |
| 4. Predictions | Not Started | Integration with prediction pipeline |
| 5. Dashboard | Not Started | UI showing Kalshi availability |

## Key Differences: Kalshi vs Traditional Sportsbooks

| Aspect | Traditional Sportsbook | Kalshi |
|--------|----------------------|--------|
| Profit Model | Bettor losses | Transaction fees (2%) |
| Winner Treatment | Limited/banned | Welcome (more volume) |
| Line Format | Over/Under with odds | Yes/No contracts (0-100¢) |
| Liquidity | High, always filled | Variable, check depth |
| Regulation | State gaming commissions | CFTC (federal) |

## Kalshi Market Structure

```
Series: KXNBA (all NBA markets)
  └── Event: KXNBA-26-GAME-{game_id} (specific game)
       └── Market: KXNBA-26-{player}-PTS-{line} (player prop)
            ├── Yes Contract (player exceeds line)
            └── No Contract (player under line)
```

**Example Market Ticker:** `KXNBA-26-LEBRON-PTS-25.5`
- Yes @ 55¢ = 55% implied probability player scores 26+
- No @ 45¢ = 45% implied probability player scores 25 or less

## Documentation

- [DESIGN.md](./DESIGN.md) - Technical architecture and implementation details
- [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) - Step-by-step execution plan
- [API-NOTES.md](./API-NOTES.md) - Kalshi API specifics and quirks

## Quick Links

- [Kalshi API Docs](https://docs.kalshi.com/welcome)
- [Kalshi Sports Markets](https://kalshi.com/sports/all-sports)
- [BettingPros Scraper](../../../scrapers/bettingpros/bp_player_props.py) (pattern reference)

## Success Criteria

1. **Data Collection:** Scrape Kalshi NBA props daily before 3 AM ET
2. **Coverage:** Capture all available player props (pts/reb/ast/3pm)
3. **Predictions:** Show Kalshi line alongside BettingPros/OddsAPI
4. **Comparison:** Flag when Kalshi line differs significantly (arbitrage)
5. **Liquidity:** Track and display market depth for execution confidence
