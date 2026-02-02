# Session 78 Handoff - Kalshi Integration

**Date:** February 2, 2026
**Focus:** Kalshi prediction market integration for NBA player props

## Session Summary

Implemented full Kalshi integration - a CFTC-regulated prediction market that doesn't limit winning bettors (unlike traditional sportsbooks like DraftKings/FanDuel). Users can now access an alternative betting platform through our data pipeline.

## What Was Accomplished

### 1. Kalshi Scraper (COMPLETE)
- **File:** `scrapers/kalshi/kalshi_player_props.py`
- **Auth:** RSA key signing via `kalshi_auth.py`
- **API:** `https://api.elections.kalshi.com/trade-api/v2`
- **Props:** Points, rebounds, assists, threes, blocks, steals
- **Deployed:** ✅ `nba-scrapers` service

### 2. Scheduler (COMPLETE)
- **Job:** `kalshi-props-scraper`
- **Schedule:** Daily at 2 AM ET (7 AM UTC)
- **Endpoint:** `POST /scrape` with `{"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}`

### 3. BigQuery Schema (COMPLETE)
- **Table:** `nba_raw.kalshi_player_props`
- **Schema file:** `schemas/bigquery/raw/kalshi_player_props_tables.sql`
- **Partitioned by:** `game_date`
- **Clustered by:** `player_lookup`, `prop_type`, `market_status`

### 4. Predictions Table (COMPLETE)
- Added Kalshi fields to `nba_predictions.player_prop_predictions`:
  - `kalshi_available`, `kalshi_line`, `kalshi_yes_price`, `kalshi_no_price`
  - `kalshi_liquidity`, `kalshi_market_ticker`, `line_discrepancy`

### 5. Raw Processor (CODE COMPLETE, DEPLOYMENT IN PROGRESS)
- **File:** `data_processors/raw/kalshi/kalshi_props_processor.py`
- **Registered:** In `main_processor_service.py`
- **Status:** Deployment to `nba-phase2-raw-processors` was in progress at session end

### 6. Credentials (STORED)
- `kalshi-api-private-key` - RSA private key in Secret Manager
- `kalshi-api-key-id` - API key ID in Secret Manager
- Access granted to `bigdataball-puller` service account

## Test Results (Feb 2, 2026)

| Metric | Value |
|--------|-------|
| Props Scraped | 272 |
| Points Props | 60 |
| Rebounds Props | 65 |
| Players Covered | 15 |
| High Liquidity | 93% |
| BettingPros Overlap | 100% |

### Sample Data (Kawhi Leonard Points)
| Platform | Line | Price |
|----------|------|-------|
| BettingPros | 24.5 | -110 |
| Kalshi | 19.5 | 74¢ |
| Kalshi | 24.5 | 51¢ |
| Kalshi | 29.5 | 28¢ |
| Kalshi | 34.5 | 15¢ |

## Key Insight: Kalshi Offers Multiple Lines

Unlike traditional sportsbooks (1 line per player), Kalshi offers 3-5 lines per player at different thresholds. This provides:
- Alternative entry points
- Arbitrage opportunities
- Better risk management

## Commits This Session

| Commit | Description |
|--------|-------------|
| `a2ee739d` | fix: Set self.data in Kalshi scraper for proper GCS export |
| `6f195068` | feat: Add Kalshi player props raw data processor |
| (earlier) | feat: Register Kalshi player props scraper |

## Files Created/Modified

```
NEW:
├── scrapers/kalshi/__init__.py
├── scrapers/kalshi/kalshi_auth.py
├── scrapers/kalshi/kalshi_player_props.py
├── data_processors/raw/kalshi/__init__.py
├── data_processors/raw/kalshi/kalshi_props_processor.py
├── schemas/bigquery/raw/kalshi_player_props_tables.sql
├── schemas/bigquery/predictions/kalshi_fields_alter.sql
├── docs/08-projects/current/kalshi-integration/README.md (updated)

MODIFIED:
├── scrapers/registry.py (added kalshi_player_props)
├── scrapers/utils/gcs_path_builder.py (added kalshi path)
├── data_processors/raw/main_processor_service.py (added processor)
```

## Issues Encountered & Resolved

### 1. API URL Changed
- **Issue:** Old URL `trading-api.kalshi.com` returned 401
- **Fix:** Updated to `api.elections.kalshi.com` (serves all markets despite name)

### 2. Empty GCS Export
- **Issue:** First scrape wrote empty `{}` to GCS (2 bytes)
- **Cause:** `transform_data()` returned data but didn't set `self.data`
- **Fix:** Added `self.data = self.download_data` in `transform_data()`

### 3. Series Tickers Discovery
- **Issue:** Thought player props used `KXNBA` series
- **Finding:** Props use separate series: `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`, etc.

## CRITICAL: Next Session Must Do

### 1. Deploy Processor (NOT YET DEPLOYED)
The raw processor deployment did NOT complete this session. Run:
```bash
./bin/deploy-service.sh nba-phase2-raw-processors
```
Then verify commit is `6f195068`:
```bash
gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="value(metadata.labels.commit-sha)"
```

### 2. Test Processor
Once deployed, trigger processing to load GCS data to BigQuery automatically.

## Other Next Session Tasks

### Should Do
- [ ] Add Kalshi data to prediction output (populate the new fields)
- [ ] Create arbitrage detection alert (when Kalshi differs from Vegas by >2 points)

### Could Do
- [ ] Build Kalshi-specific dashboard view
- [ ] Track line movements over time
- [ ] Add Kalshi to daily validation checks

## Useful Commands

```bash
# Manual scrape
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}'

# Check data
bq query --use_legacy_sql=false "
SELECT prop_type, COUNT(*) as props, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.kalshi_player_props
WHERE game_date = CURRENT_DATE()
GROUP BY prop_type"

# Compare with BettingPros
bq query --use_legacy_sql=false "
SELECT k.player_lookup, k.line_value as kalshi, bp.points_line as vegas
FROM nba_raw.kalshi_player_props k
JOIN nba_raw.bettingpros_player_points_props bp
  ON k.player_lookup = bp.player_lookup
  AND k.game_date = bp.game_date
WHERE k.game_date = CURRENT_DATE()
  AND k.prop_type = 'points'
  AND bp.is_best_line = TRUE
  AND ABS(k.line_value - bp.points_line) <= 0.5"

# Check processor deployment
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Should be: 6f195068
```

## Project Documentation

Full project docs at: `docs/08-projects/current/kalshi-integration/`
- `README.md` - Complete implementation guide
- `DESIGN.md` - Technical architecture
- `API-NOTES.md` - Kalshi API details
- `IMPLEMENTATION-PLAN.md` - Original task breakdown

## Why Kalshi Matters

| Traditional Sportsbook | Kalshi |
|----------------------|--------|
| Limits winning bettors | No limits (profits from fees) |
| 1 line per player | 3-5 lines per player |
| State regulated | CFTC regulated (federal) |
| -110/-110 vig | ~2% transaction fee |

This gives our users an alternative platform where they can bet profitably without getting banned.
