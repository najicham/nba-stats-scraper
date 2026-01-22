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
- **Endpoint:** `us.decodo.com:10001` (US residential IPs)
- **Status:** ✅ ACTIVE - Added 2026-01-22
- **Secret:** `DECODO_PROXY_CREDENTIALS` in Secret Manager

### Scraper Status (After Decodo Fallback)
| Scraper | Target Site | Status | Notes |
|---------|-------------|--------|-------|
| `bp_events` | api.bettingpros.com | ✅ Working | With API key + Decodo |
| `bp_player_props` | api.bettingpros.com | ✅ Working | With API key + Decodo |
| `nbac_team_boxscore` | stats.nba.com | ✅ Working | With Decodo fallback |
| `oddsa_events` | api.the-odds-api.com | ⚠️ Untested | May need testing |
| `oddsa_player_props` | api.the-odds-api.com | ⚠️ Untested | May need testing |

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
