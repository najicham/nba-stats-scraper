# Email Draft for BallDontLie Support

**Subject:** Missing Box Score Data - 33 Games (Jan 1-19, 2026)

---

Hi BallDontLie Team,

We've identified **33 NBA games** from January 1-19, 2026 that are missing from the box scores API endpoint. Our scraper runs correctly and retrieves data for most games, but these specific games are not being returned.

## Pattern Observed
**76% of missing games have Pacific Time Zone home teams:**
- Golden State Warriors: 6 games missing
- Sacramento Kings: 6 games missing
- LA Clippers: 5 games missing
- LA Lakers: 4 games missing
- Portland Trail Blazers: 4 games missing

This suggests possible data ingestion delays for late-night West Coast games.

## Complete List of Missing Games

| Date | Away Team | Home Team |
|------|-----------|-----------|
| Jan 19 | MIA | GSW |
| Jan 18 | POR | SAC |
| Jan 18 | TOR | LAL |
| Jan 17 | WAS | DEN |
| Jan 17 | LAL | POR |
| Jan 16 | WAS | SAC |
| Jan 15 | ATL | POR |
| Jan 15 | CHA | LAL |
| Jan 15 | UTA | DAL |
| Jan 15 | BOS | MIA |
| Jan 15 | NYK | GSW |
| Jan 15 | OKC | HOU |
| Jan 15 | MIL | SAS |
| Jan 15 | PHX | DET |
| Jan 14 | NYK | SAC |
| Jan 14 | WAS | LAC |
| Jan 13 | ATL | LAL |
| Jan 13 | POR | GSW |
| Jan 12 | CHA | LAC |
| Jan 12 | LAL | SAC |
| Jan 7 | MIL | GSW |
| Jan 7 | HOU | POR |
| Jan 6 | DAL | SAC |
| Jan 5 | GSW | LAC |
| Jan 5 | UTA | POR |
| Jan 3 | BOS | LAC |
| Jan 3 | UTA | GSW |
| Jan 2 | MEM | LAL |
| Jan 2 | OKC | GSW |
| Jan 1 | UTA | LAC |
| Jan 1 | BOS | SAC |

## Our Setup
- We're calling the `/games` endpoint with date parameters
- Scraper runs at 2-4 AM ET (after West Coast games complete)
- Other games from the same dates return successfully

Could you please:
1. Confirm if these games are in your database
2. Let us know if there's a data availability delay we should account for
3. Advise if we need to use different parameters to retrieve this data

Thanks for your help!

---

*Note: This email was generated from automated data validation. See full report at: docs/08-projects/current/historical-backfill-audit/2026-01-21-DATA-VALIDATION-REPORT.md*
