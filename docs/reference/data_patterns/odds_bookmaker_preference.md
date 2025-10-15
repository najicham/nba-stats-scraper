# Odds API Bookmaker Preference Pattern

## Overview
When querying game lines, we prefer DraftKings odds but automatically fall back to FanDuel when DraftKings data is unavailable.

## Coverage Statistics
Based on backfill completion (Oct 2021 → Mar 2025):
- **Total games:** 5,260
- **Games using DraftKings:** 5,235 (99.52%)
- **Games using FanDuel fallback:** 25 (0.48%)

### Breakdown
- 13 games missing DraftKings entirely (0.25%)
- 15 games missing DraftKings spreads (0.29%)
- 25 games missing DraftKings totals (0.48%)

---

## Implementation Layers

### Layer 1: BigQuery View (Foundation)
**File:** `schemas/bigquery/raw/odds_game_lines_views.sql`

The view `nba_raw.odds_api_game_lines_preferred` automatically selects the preferred bookmaker using `ROW_NUMBER()` with ranking logic.

**Deploy:**
```bash
bq query --use_legacy_sql=false < schemas/bigquery/raw/odds_game_lines_views.sql
```

### Layer 2: Python Utility (Recommended)
**File:** `shared/utils/odds_preference.py`

The utility wraps the view with convenient Python functions.

**Usage:**
```python
from shared.utils.odds_preference import get_preferred_game_lines, get_game_lines_summary

# Get all lines for a date
lines = get_preferred_game_lines('2024-01-24')

# Get simplified summary (one row per game)
summary = get_game_lines_summary('2024-01-24')

# Filter by team
clippers_lines = get_preferred_game_lines(
    '2024-01-24',
    home_team='Los Angeles Clippers'
)

# Get only spreads
spreads = get_preferred_game_lines(
    '2024-01-24',
    market_keys=['spreads']
)
```

### Layer 3: Direct SQL (For Ad-Hoc Queries)
```sql
-- Query the view directly
SELECT *
FROM `nba_raw.odds_api_game_lines_preferred`
WHERE game_date = '2024-01-24'
  AND home_team = 'Los Angeles Clippers';
```

---

## When to Use Each Layer

| Use Case | Use This | Why |
|----------|----------|-----|
| Application code | Python utility | Type safety, easy to test, consistent |
| Data pipelines | Python utility | Parameterized queries, error handling |
| Jupyter notebooks | Python utility | Pandas DataFrames, easy analysis |
| Ad-hoc analysis | SQL view directly | Quick queries, no code needed |
| Reporting/BI tools | SQL view directly | Tools can query views natively |

---

## Design Philosophy

**The Utility Uses the View**
```
Application Code
    ↓
Python Utility (shared/utils/odds_preference.py)
    ↓
BigQuery View (nba_raw.odds_api_game_lines_preferred)
    ↓
Base Table (nba_raw.odds_api_game_lines)
```

This ensures:
- ✅ Single source of truth
- ✅ Consistent logic everywhere
- ✅ Easy to maintain (change view, utility updates automatically)
- ✅ BigQuery optimizations apply to all consumers

---

## API Reference

### `get_preferred_game_lines(game_date, home_team=None, away_team=None, market_keys=None)`
Get game lines with DraftKings preferred, FanDuel as fallback.

**Parameters:**
- `game_date` (str): Date in 'YYYY-MM-DD' format
- `home_team` (str, optional): Filter for home team name
- `away_team` (str, optional): Filter for away team name
- `market_keys` (list, optional): List of markets ['spreads', 'totals']

**Returns:**
- `pd.DataFrame`: One bookmaker per game/market/outcome

**Example:**
```python
lines = get_preferred_game_lines('2024-01-24')
spreads = get_preferred_game_lines('2024-01-24', market_keys=['spreads'])
clippers = get_preferred_game_lines('2024-01-24', home_team='Los Angeles Clippers')
```

---

### `get_game_lines_summary(game_date, home_team=None)`
Get a simplified summary of game lines (one row per game).

**Parameters:**
- `game_date` (str): Date in 'YYYY-MM-DD' format
- `home_team` (str, optional): Filter for home team

**Returns:**
- `pd.DataFrame` with columns:
  - `game_id`, `game_date`, `home_team`, `away_team`
  - `spread_value`, `spread_home_price`, `spread_away_price`, `spread_bookmaker`
  - `total_value`, `over_price`, `under_price`, `total_bookmaker`

**Example:**
```python
summary = get_game_lines_summary('2024-01-24')
print(summary[['home_team', 'spread_value', 'total_value']])
```

---

### `get_bookmaker_coverage_stats(start_date, end_date)`
Get statistics on bookmaker coverage for a date range.

**Parameters:**
- `start_date` (str): Start date in 'YYYY-MM-DD' format
- `end_date` (str): End date in 'YYYY-MM-DD' format

**Returns:**
- `dict` with keys:
  - `total_games` (int)
  - `games_using_draftkings` (int)
  - `games_using_fanduel` (int)
  - `dk_coverage_pct` (float)

**Example:**
```python
stats = get_bookmaker_coverage_stats('2021-10-01', '2025-03-31')
print(f"DraftKings coverage: {stats['dk_coverage_pct']:.2f}%")
```

---

## Complete Examples

### Example 1: Get Today's Lines
```python
from datetime import date
from shared.utils.odds_preference import get_game_lines_summary

today = date.today().isoformat()
lines = get_game_lines_summary(today)
print(lines[['home_team', 'spread_value', 'total_value']])
```

### Example 2: Analyze Bookmaker Usage
```python
from shared.utils.odds_preference import get_bookmaker_coverage_stats

stats = get_bookmaker_coverage_stats('2021-10-01', '2025-03-31')
print(f"DraftKings coverage: {stats['dk_coverage_pct']:.2f}%")
print(f"FanDuel fallback: {stats['games_using_fanduel']} games")
```

### Example 3: Check Which Bookmaker for Specific Game
```python
from shared.utils.odds_preference import get_preferred_game_lines

lines = get_preferred_game_lines('2024-01-24', home_team='Golden State Warriors')
bookmaker = lines.iloc[0]['bookmaker_key']
print(f"Using {bookmaker} for this game")
```

### Example 4: Get Clippers Spread and Total
```python
from shared.utils.odds_preference import get_game_lines_summary

summary = get_game_lines_summary('2024-01-24', home_team='Los Angeles Clippers')
if len(summary) > 0:
    game = summary.iloc[0]
    print(f"{game['home_team']} vs {game['away_team']}")
    print(f"Spread: {game['spread_value']} (from {game['spread_bookmaker']})")
    print(f"Total: {game['total_value']} (from {game['total_bookmaker']})")
```

---

## Games Using FanDuel Fallback

As of the last backfill, 25 games use FanDuel. See `analysis/odds_bookmaker_coverage.sql` for the current list.

**Common patterns:**
- **January 25, 2023:** 10 games (DraftKings totals unavailable)
- **Early 2022 season:** Several games with incomplete DraftKings data
- **Historical API limitations** for older games

**Specific dates with fallbacks:**
- 2021-11-26: 1 game (DK missing totals)
- 2022-01-05, 01-17, 01-21, 01-31, 02-14, 02-26, 03-05, 03-09: Various games
- 2023-01-25: 10 games (DK missing totals)
- 2023-02-04: 1 game (DK missing totals)

---

## Testing

```python
# Test the utility
from shared.utils.odds_preference import get_preferred_game_lines

# Should return data
lines = get_preferred_game_lines('2024-01-24')
assert len(lines) > 0

# Should prefer DraftKings when available
dk_games = lines[lines['bookmaker_key'] == 'draftkings']
fd_games = lines[lines['bookmaker_key'] == 'fanduel']
assert len(dk_games) > len(fd_games)  # Most games use DK

# Should have both markets
markets = lines['market_key'].unique()
assert 'spreads' in markets
assert 'totals' in markets
```

---

## Maintenance

### When adding new bookmakers or changing preference logic:

1. **Update the VIEW sql file**
   - Edit `schemas/bigquery/raw/odds_game_lines_views.sql`
   - Add new bookmaker to the CASE statement ranking

2. **Redeploy the view**
   ```bash
   bq query --use_legacy_sql=false < schemas/bigquery/raw/odds_game_lines_views.sql
   ```

3. **Utility automatically uses new logic** (no code changes needed!)

4. **Update this documentation**
   - Update coverage stats
   - Add new bookmaker to examples

---

## Troubleshooting

### Issue: View not found
**Error:** `Table 'nba_raw.odds_api_game_lines_preferred' not found`

**Solution:**
```bash
# Deploy the view
bq query --use_legacy_sql=false < schemas/bigquery/raw/odds_game_lines_views.sql
```

### Issue: Getting FanDuel data when expecting DraftKings
**Check:** Is DraftKings data actually available for that game?

```python
from shared.utils.odds_preference import get_preferred_game_lines

# Check which bookmaker for a specific game
lines = get_preferred_game_lines('2024-01-24', home_team='Golden State Warriors')
print(lines[['bookmaker_key', 'market_key']].drop_duplicates())
```

### Issue: Incorrect bookmaker returned
**Verify:** The base table has the expected data

```sql
SELECT bookmaker_key, market_key, COUNT(*) as rows
FROM `nba_raw.odds_api_game_lines`
WHERE game_date = '2024-01-24'
  AND home_team = 'Golden State Warriors'
GROUP BY bookmaker_key, market_key;
```

---

## Performance Notes

- **View is fast:** BigQuery optimizes views well, no performance penalty
- **Filters are pushed down:** When you filter on `game_date`, it uses partition pruning
- **Use parameters:** Always use parameterized queries to leverage query cache

**Good (uses cache):**
```python
lines = get_preferred_game_lines('2024-01-24')  # Parameterized
```

**Bad (doesn't use cache):**
```python
query = f"SELECT * FROM ... WHERE game_date = '{date}'"  # String interpolation
```

---

## Related Files

- **View Definition:** `schemas/bigquery/raw/odds_game_lines_views.sql`
- **Python Utility:** `shared/utils/odds_preference.py`
- **Base Table:** `nba_raw.odds_api_game_lines`
- **Analysis Query:** `analysis/odds_bookmaker_coverage.sql`
- **This Documentation:** `docs/data_patterns/odds_bookmaker_preference.md`

---

## Change Log

### 2025-10-11
- Initial implementation
- Created view with DraftKings preference, FanDuel fallback
- Added Python utility with 3 main functions
- Coverage: 99.52% DraftKings, 0.48% FanDuel

---

## Future Enhancements

Potential improvements to consider:

1. **Add more bookmakers** (Caesars, BetMGM, etc.)
2. **Time-based preferences** (prefer earlier snapshot if multiple exist)
3. **Best price selection** (instead of preferred bookmaker, choose best odds)
4. **Line movement tracking** (if multiple snapshots available)
5. **Confidence scores** (flag when using fallback bookmaker)

---

## Support

For questions or issues:
1. Check the base table data first
2. Verify the view exists and is up-to-date
3. Test with the analysis query to understand coverage
4. Review this documentation for usage patterns

