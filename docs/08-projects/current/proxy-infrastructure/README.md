# Proxy Infrastructure Project

**Status:** Active
**Priority:** P1 - High
**Created:** 2026-01-22
**Last Updated:** 2026-01-22

## Overview

This project tracks proxy infrastructure health, monitoring, and provider management for our web scraping operations.

## Current State

### Provider: ProxyFuel (Primary)
- **Plan:** Rotating Pro 1M (1 million requests/month)
- **Endpoint:** `gate2.proxyfuel.com:2000`
- **Status:** ⚠️ DEGRADED - Target sites blocking IPs (as of 2026-01-22)

### Provider: Decodo/Smartproxy (Fallback)
- **Plan:** Residential 25 GB
- **Endpoint:** `us.decodo.com:10001` (US residential IPs) - currently configured
- **Status:** ❌ BLOCKED by BettingPros (as of 2026-01-23)
- **Secret:** `DECODO_PROXY_CREDENTIALS` in Secret Manager

**Alternative Decodo Endpoints:**
| Gateway | Ports | Notes |
|---------|-------|-------|
| `gate.decodo.com` | 10001-10010 | Global gateway, 10 ports available |
| `us.decodo.com` | 10001 | US-specific (currently used) |

Different ports may route through different IP pools - worth trying if one is blocked.

### Scraper Status (2026-01-23 Update)
| Scraper | Target Site | Status | Notes |
|---------|-------------|--------|-------|
| `bp_events` | api.bettingpros.com | ❌ 403 | BOTH proxies blocked |
| `bp_player_props` | api.bettingpros.com | ❌ 403 | BOTH proxies blocked |
| `nbac_team_boxscore` | stats.nba.com | ✅ Working | With Decodo fallback |
| `oddsa_events` | api.the-odds-api.com | ✅ Working | Uses API key, no proxy |
| `oddsa_player_props` | api.the-odds-api.com | ✅ Working | Uses API key, no proxy |

### Working Scrapers (No Proxy)
| Scraper | Target Site | Status |
|---------|-------------|--------|
| `bdl_*` | api.balldontlie.io | ✅ Working |
| `nbac_injury_report` | nba.com (PDF) | ✅ Working |
| `nbac_gamebook_pdf` | nba.com (PDF) | ✅ Working |

## Documents

1. [Monitoring Setup](./MONITORING-SETUP.md) - How proxy health is tracked
2. [Provider Evaluation](./PROVIDER-EVALUATION.md) - Proxy provider comparison
3. [Migration Plan](./MIGRATION-PLAN.md) - Steps to switch providers
4. [Incident Log](./INCIDENT-LOG.md) - Historical proxy issues

## Quick Links

- **BigQuery Table:** `nba_orchestration.proxy_health_metrics`
- **Summary View:** `nba_orchestration.proxy_health_summary`
- **Proxy Config:** `scrapers/utils/proxy_utils.py`
- **Health Logger:** `shared/utils/proxy_health_logger.py`
- **Provider Detection:** `scrapers/scraper_base.py` → `_get_proxy_provider()`

## Validation Query

Check proxy health per provider (should show **both** `proxyfuel` and `decodo`):

```sql
SELECT
  DATE(timestamp) as date,
  proxy_provider,
  target_host,
  COUNTIF(success) as success,
  COUNTIF(NOT success) as failed,
  ROUND(100 * COUNTIF(success) / COUNT(*), 1) as success_pct
FROM nba_orchestration.proxy_health_metrics
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 3, 2
```

**If only `proxyfuel` appears:** The `proxy_provider` field isn't being set correctly.
Check `_get_proxy_provider()` in `scrapers/scraper_base.py` (added 2026-01-23).

## Action Items

- [x] Evaluate Decodo/Smartproxy as replacement
- [x] Set up alerting for proxy failure thresholds
- [x] Add proxy health to daily health check
- [ ] Consider direct access (no proxy) for some endpoints
- [ ] Monitor Decodo usage to right-size plan

## Recent Changes (2026-01-22)

1. **Added Decodo as fallback** - 25GB residential plan, US gateway
2. **Mounted secrets** - `DECODO_PROXY_CREDENTIALS`, `BETTINGPROS_API_KEY`
3. **Proxy health monitoring** - Tracks success/failure in BigQuery
4. **Daily health alerts** - Warns if success rate < 80%, critical if < 50%
