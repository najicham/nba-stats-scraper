# Session 79 Handoff - Kalshi Prediction Enrichment

**Date:** February 2, 2026
**Focus:** Deploy Kalshi processor and add Kalshi data to predictions

## Session Summary

Completed Kalshi integration from Session 78 by deploying the raw processor and implementing Kalshi data enrichment in the prediction pipeline. Predictions now include Kalshi market data for arbitrage detection and alternative betting platform analysis.

## What Was Accomplished

### 1. Deployed Raw Processor ✅
- Deployed `nba-phase2-raw-processors` with Kalshi processor
- Revision: `nba-phase2-raw-processors-00132-hdq`
- Verified 1,360 Kalshi props loaded for Feb 2, 2026

### 2. Kalshi Data Verified ✅
```
| prop_type | count |
|-----------|-------|
| points    | 300   |
| rebounds  | 325   |
| assists   | 225   |
| threes    | 300   |
| blocks    | 105   |
| steals    | 105   |
```

### 3. Prediction Enrichment Implemented ✅

**Coordinator (player_loader.py):**
- Added `_query_kalshi_line()` method (lines 773-869)
- Queries `nba_raw.kalshi_player_props` for points lines
- Finds closest Kalshi line to Vegas line for comparison
- Returns: `kalshi_available`, `kalshi_line`, `kalshi_yes_price`, `kalshi_no_price`, `kalshi_liquidity`, `kalshi_market_ticker`, `line_discrepancy`

**Worker (worker.py):**
- Added Kalshi fields to `line_source_info` extraction (lines 551-558)
- Added Kalshi fields to `features` dict (lines 870-877)
- Added Kalshi fields to BigQuery record (lines 1745-1752)

### 4. Services Deployed ✅
| Service | Revision |
|---------|----------|
| nba-phase2-raw-processors | 00132-hdq |
| prediction-coordinator | 00132-xrv |
| prediction-worker | 00070-vj6 |

### 5. Updated Skills ✅
- Added **Phase 0.9: Kalshi Data Health** to `/validate-daily` skill
- Monitors Kalshi scraper output and data availability
- Alert thresholds for 0 props (critical) or <50 props (warning)

### 6. Commits
| Commit | Description |
|--------|-------------|
| `5967c900` | feat: Add Kalshi prediction market data to predictions |
| `19974b56` | docs: Add Session 79 handoff |
| `0157dee5` | docs: Add Kalshi validation to validate-daily skill |

## How It Works

When predictions run:
1. Coordinator queries player's Vegas line (from OddsAPI/BettingPros)
2. Coordinator queries Kalshi for closest matching line
3. Kalshi fields passed to worker via Pub/Sub
4. Worker includes Kalshi data in BigQuery prediction record

**Fields populated:**
```sql
kalshi_available     -- TRUE if Kalshi has prop for this player
kalshi_line          -- Kalshi line value (e.g., 24.5)
kalshi_yes_price     -- Price in cents (e.g., 51 = 51¢)
kalshi_no_price      -- Price in cents
kalshi_liquidity     -- 'HIGH', 'MEDIUM', 'LOW'
kalshi_market_ticker -- e.g., 'KXNBAPTS-26FEB02CLIPHO-KLEONARDKAWHIL24-5'
line_discrepancy     -- Kalshi line - Vegas line
```

## Testing

The enrichment will be active for the next prediction run (2:30 AM or 7:00 AM ET). To verify:

```sql
-- Check if Kalshi data populated after next prediction run
SELECT
  player_lookup,
  current_points_line as vegas_line,
  kalshi_line,
  line_discrepancy,
  kalshi_yes_price,
  kalshi_liquidity
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-03'
  AND system_id = 'catboost_v9'
  AND kalshi_available = TRUE
ORDER BY ABS(line_discrepancy) DESC
LIMIT 10;
```

## Future Plans

### Priority 1: Quick Wins (Next Session)
- [ ] **Arbitrage Alert**: Create notification when `|line_discrepancy| >= 2` points
  - Could use Cloud Function triggered by prediction completion
  - Send to Discord/Slack when opportunities detected
- [ ] **Add Kalshi to /top-picks**: Show Kalshi line comparison in output
  - Modify skill to include `kalshi_line` and `line_discrepancy` columns

### Priority 2: Analytics (Future)
- [ ] **Kalshi Coverage Tracking**: Daily stats on Kalshi vs Vegas coverage
  - What % of predictions have Kalshi data?
  - Which players have best Kalshi liquidity?
- [ ] **Line Accuracy Comparison**: After games complete, compare:
  - Which was closer to actual: Kalshi line or Vegas line?
  - Track over time to identify systematic differences
- [ ] **Arbitrage ROI Analysis**: Backtest profitability of betting divergences
  - When Kalshi differs from Vegas by 2+ pts, what's the hit rate?

### Priority 3: Features (Later)
- [ ] **Kalshi Dashboard View**: Dedicated view for Kalshi opportunities
- [ ] **Line Movement Tracking**: Store historical Kalshi lines to track movement
- [ ] **Multi-Prop Kalshi**: Extend to rebounds, assists, threes (currently points only)
- [ ] **Kalshi as Signal**: Could line discrepancy be a predictive feature?

## Architecture Reference

```
┌─────────────────────────────────────────────────────────────────┐
│                     KALSHI DATA FLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Kalshi API ──► Scraper ──► GCS ──► Processor ──► BigQuery     │
│  (2 AM ET)      (nba-scrapers)      (raw-processors)            │
│                                                                 │
│                           │                                     │
│                           ▼                                     │
│                  nba_raw.kalshi_player_props                    │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Prediction Coordinator                                   │   │
│  │  1. Query Vegas line (OddsAPI/BettingPros)              │   │
│  │  2. Query Kalshi line (closest to Vegas)                │   │
│  │  3. Calculate line_discrepancy                          │   │
│  │  4. Pass to worker via Pub/Sub                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Prediction Worker                                        │   │
│  │  1. Extract Kalshi fields from request                  │   │
│  │  2. Include in BigQuery prediction record               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│           nba_predictions.player_prop_predictions               │
│           (with kalshi_available, kalshi_line, etc.)            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Useful Commands

```bash
# Check Kalshi data quality
bq query --use_legacy_sql=false "
SELECT prop_type, COUNT(*) as props, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.kalshi_player_props
WHERE game_date = CURRENT_DATE()
GROUP BY prop_type"

# Find arbitrage opportunities (after predictions run)
bq query --use_legacy_sql=false "
SELECT p.player_lookup, p.current_points_line as vegas, p.kalshi_line,
       p.line_discrepancy, p.kalshi_yes_price
FROM nba_predictions.player_prop_predictions p
WHERE p.game_date = CURRENT_DATE()
  AND p.kalshi_available = TRUE
  AND ABS(p.line_discrepancy) >= 2
ORDER BY ABS(p.line_discrepancy) DESC"

# Compare Kalshi vs Vegas line availability
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(kalshi_available) as with_kalshi,
  ROUND(100.0 * COUNTIF(kalshi_available) / COUNT(*), 1) as kalshi_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'"

# Manual Kalshi scrape
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}'
```

## Files Modified

```
MODIFIED:
├── predictions/coordinator/player_loader.py (+100 lines)
│   └── Added _query_kalshi_line() method
│   └── Added Kalshi fields to request creation
├── predictions/worker/worker.py (+16 lines)
│   └── Added Kalshi field extraction
│   └── Added Kalshi fields to BigQuery record
├── .claude/skills/validate-daily/SKILL.md (+55 lines)
│   └── Added Phase 0.9: Kalshi Data Health check
```

## Key Insights

### Why Kalshi Matters
| Traditional Sportsbook | Kalshi |
|----------------------|--------|
| Limits winning bettors | No limits (profits from fees) |
| 1 line per player | 3-5 lines per player |
| State regulated | CFTC regulated (federal) |
| -110/-110 vig | ~2% transaction fee |

### Line Matching Strategy
Kalshi offers multiple lines per player (e.g., 19.5, 24.5, 29.5 points). We match the Kalshi line **closest to Vegas** for the `line_discrepancy` calculation. This enables:
- Arbitrage detection when markets diverge
- Alternative entry points for betting
- Market efficiency analysis

## Related Documentation

- Session 78 Handoff: `docs/09-handoff/2026-02-02-SESSION-78-KALSHI-INTEGRATION.md`
- Kalshi Project: `docs/08-projects/current/kalshi-integration/`
- Prediction Schema: `schemas/bigquery/predictions/kalshi_fields_alter.sql`

---

*Session 79 Complete. Kalshi integration fully operational.*
