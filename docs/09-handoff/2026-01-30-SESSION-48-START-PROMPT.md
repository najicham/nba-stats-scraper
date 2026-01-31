# Session 48 Start Prompt

Continue work on NBA stats scraper pipeline. Session 46 fixed the DNP data corruption issue for 22/25 January dates.

Read the handoff document first:
```bash
cat docs/09-handoff/2026-01-30-SESSION-46-DNP-FIX-HANDOFF.md
```

## What Was Fixed (Session 46)

- **DNP players now correctly have `points = NULL`** instead of `points = 0`
- Added `_derive_team_abbr()` fix for NULL team_abbr in raw data (commit `3509c81b`)
- Reprocessed 22 of 25 January dates through analytics backfill

## Remaining Tasks

### Priority 1: Scrape Missing Gamebook PDFs (Jan 22-23)

16 games need gamebook PDFs scraped from NBA.com:

| Date | Games |
|------|-------|
| Jan 22 | CHA@ORL, HOU@PHI, DEN@WAS, GSW@DAL, CHI@MIN, SAS@UTA, LAL@LAC, MIA@POR |
| Jan 23 | HOU@DET, PHX@ATL, BOS@BKN, SAC@CLE, NOP@MEM, DEN@MIL, IND@OKC, TOR@POR |

Options:
1. Execute `nbac-gamebook-backfill` Cloud Run Job with date filter
2. Call scraper API directly for each game code

After scraping, run analytics backfill for those dates.

### Priority 2: Verify Nov-Dec 2025 DNP Handling

Check if historical data (Nov-Dec 2025) also has the DNP corruption issue:

```sql
SELECT DATE_TRUNC(game_date, MONTH) as month, COUNT(*) as total,
  COUNTIF(is_dnp = TRUE) as dnp_marked, ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2025-11-01' AND game_date < '2026-01-01'
GROUP BY 1 ORDER BY 1;
```

If `dnp_marked = 0` and `pct_zero > 30%`, those months need reprocessing.

### Priority 3: Re-evaluate Model Performance

With clean data, check if model accuracy improves vs Vegas lines.

## Verification Query

```sql
SELECT game_date, COUNTIF(is_dnp = TRUE) as dnp_marked,
  ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero,
  CASE WHEN COUNTIF(is_dnp = TRUE) > 0 THEN 'FIXED' ELSE 'ISSUE' END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2026-01-01' AND game_date < '2026-01-30'
GROUP BY game_date ORDER BY game_date;
```

Expected: All dates show `FIXED` except Jan 8, 22, 23.

## Key Commits
- `3509c81b` - fix: Derive team_abbr from game context for DNP players

---
Session 46 Complete
