# Kalshi Integration Project

**Status: COMPLETE** - Deployed and operational as of Feb 2, 2026

## Problem Statement

Traditional sportsbooks (DraftKings, FanDuel, BetMGM) limit winning bettors. Kalshi is a CFTC-regulated prediction market that profits from transaction fees (~2%), not bettor losses, so they have no incentive to limit winners.

**Goal:** Integrate Kalshi NBA player props data into our prediction pipeline, giving users an alternative platform that won't limit them for winning.

## Implementation Status

| Component | Status | Details |
|-----------|--------|---------|
| Scraper | ✅ Deployed | `nba-scrapers` service |
| Scheduler | ✅ Active | `kalshi-props-scraper` - daily 2 AM ET |
| BigQuery Table | ✅ Created | `nba_raw.kalshi_player_props` |
| GCS Storage | ✅ Working | `gs://nba-scraped-data/kalshi/player-props/` |
| Raw Processor | ✅ Created | `KalshiPropsProcessor` |
| Predictions Integration | 🔲 Not Started | Future enhancement |

## Key Differences: Kalshi vs Traditional Sportsbooks

| Aspect | Traditional Sportsbook | Kalshi |
|--------|----------------------|--------|
| Profit Model | Bettor losses | Transaction fees (2%) |
| Winner Treatment | Limited/banned | Welcome (more volume) |
| Line Format | Over/Under with odds | Yes/No contracts (0-100¢) |
| Liquidity | High, always filled | Variable, check depth |
| Regulation | State gaming commissions | CFTC (federal) |
| Lines per Player | 1 | 3-5 (multiple thresholds) |

## Data Overview (Feb 2, 2026)

| Metric | Value |
|--------|-------|
| Total Props Scraped | 272 |
| Prop Types | Points (60), Rebounds (65), Assists (45), Threes (60), Blocks (21), Steals (21) |
| Players with Props | 15 |
| High Liquidity Markets | 93% |
| Overlap with BettingPros | 100% (all 15 players) |

## Kalshi Market Structure

```
Series: KXNBAPTS (points), KXNBAREB (rebounds), etc.
  └── Event: KXNBAPTS-26FEB02PHILAC (PHI at LAC, Feb 2)
       └── Markets: Multiple lines per player
            ├── KXNBAPTS-26FEB02PHILAC-LACIZUBAC40-10 (Zubac 10+ pts)
            ├── KXNBAPTS-26FEB02PHILAC-LACIZUBAC40-15 (Zubac 15+ pts)
            ├── KXNBAPTS-26FEB02PHILAC-LACIZUBAC40-20 (Zubac 20+ pts)
            └── KXNBAPTS-26FEB02PHILAC-LACIZUBAC40-25 (Zubac 25+ pts)
```

**Example: Kawhi Leonard Points (Feb 2)**

| Platform | Line | Over Price |
|----------|------|------------|
| BettingPros | 24.5 | -110 |
| Kalshi | 19.5 | 74¢ (implied -285) |
| Kalshi | 24.5 | 51¢ (implied -104) |
| Kalshi | 29.5 | 28¢ (implied +257) |
| Kalshi | 34.5 | 15¢ (implied +567) |

## Technical Implementation

### API Details

- **Base URL**: `https://api.elections.kalshi.com/trade-api/v2`
- **Authentication**: RSA key signing (stored in Secret Manager)
- **Rate Limit**: 10 req/sec (we use 5 for safety)
- **Series Tickers**: KXNBAPTS, KXNBAREB, KXNBAAST, KXNBA3PT, KXNBABLK, KXNBASTL

### Credentials (Secret Manager)

| Secret | Purpose |
|--------|---------|
| `kalshi-api-private-key` | RSA private key for signing |
| `kalshi-api-key-id` | API key identifier |

### Files Created

```
scrapers/kalshi/
├── __init__.py
├── kalshi_auth.py          # RSA authentication
└── kalshi_player_props.py  # Main scraper

data_processors/raw/kalshi/
├── __init__.py
└── kalshi_props_processor.py  # GCS → BigQuery processor

schemas/bigquery/raw/
└── kalshi_player_props_tables.sql

schemas/bigquery/predictions/
└── kalshi_fields_alter.sql  # Added Kalshi fields to predictions
```

### BigQuery Schema

**Table**: `nba_raw.kalshi_player_props`

| Field | Type | Description |
|-------|------|-------------|
| game_date | DATE | Partition key |
| series_ticker | STRING | KXNBAPTS, KXNBAREB, etc. |
| event_ticker | STRING | Game identifier |
| market_ticker | STRING | Unique market ID |
| prop_type | STRING | points, rebounds, assists, threes, blocks, steals |
| kalshi_player_name | STRING | Player name from Kalshi |
| player_lookup | STRING | Normalized name for joining |
| line_value | FLOAT64 | The prop line (e.g., 24.5) |
| yes_bid/yes_ask | INT64 | Contract prices in cents |
| no_bid/no_ask | INT64 | Contract prices in cents |
| implied_over_prob | FLOAT64 | yes_ask / 100 |
| equivalent_over_odds | INT64 | American odds conversion |
| liquidity_score | STRING | HIGH, MEDIUM, LOW |
| market_status | STRING | active, closed, settled |

### Scheduler

```bash
# Job: kalshi-props-scraper
# Schedule: 0 7 * * * (7 AM UTC = 2 AM ET)
# Endpoint: POST /scrape
# Body: {"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}
```

## Usage

### Manual Scrape

```bash
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper":"kalshi_player_props","date":"2026-02-02","group":"prod"}'
```

### Query Data

```sql
-- Get today's Kalshi props
SELECT player_lookup, prop_type, line_value, yes_ask, liquidity_score
FROM nba_raw.kalshi_player_props
WHERE game_date = CURRENT_DATE()
  AND prop_type = 'points'
ORDER BY player_lookup, line_value;

-- Compare with BettingPros
WITH kalshi AS (
  SELECT player_lookup, line_value, yes_ask
  FROM nba_raw.kalshi_player_props
  WHERE game_date = CURRENT_DATE() AND prop_type = 'points'
),
bp AS (
  SELECT DISTINCT player_lookup, points_line
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = CURRENT_DATE() AND is_best_line = TRUE
)
SELECT k.player_lookup, k.line_value as kalshi_line, bp.points_line as vegas_line
FROM kalshi k
JOIN bp ON k.player_lookup = bp.player_lookup
  AND ABS(k.line_value - bp.points_line) <= 0.5;
```

## Future Enhancements

1. **Predictions Integration** - Add Kalshi line to prediction output
2. **Arbitrage Detection** - Alert when Kalshi differs significantly from Vegas
3. **Liquidity Tracking** - Monitor orderbook depth over time
4. **Historical Analysis** - Compare Kalshi vs Vegas line movements

## Documentation

- [DESIGN.md](./DESIGN.md) - Technical architecture
- [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) - Original task breakdown
- [API-NOTES.md](./API-NOTES.md) - Kalshi API specifics

## Commits

| Commit | Description |
|--------|-------------|
| `a2ee739d` | fix: Set self.data in Kalshi scraper for proper GCS export |
| `6f195068` | feat: Add Kalshi player props raw data processor |
| (earlier) | feat: Register Kalshi player props scraper |
| (earlier) | BigQuery schema and GCS path config |

## Quick Links

- [Kalshi API Docs](https://docs.kalshi.com/welcome)
- [Kalshi Sports Markets](https://kalshi.com/sports/all-sports)
- BigQuery Table: `nba_raw.kalshi_player_props`
- GCS Path: `gs://nba-scraped-data/kalshi/player-props/`
