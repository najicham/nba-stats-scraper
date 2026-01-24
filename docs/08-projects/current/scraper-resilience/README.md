# Scraper Resilience System

**Status:** Active
**Priority:** P1
**Created:** 2026-01-24
**Last Updated:** 2026-01-24

## Overview

Comprehensive scraper resilience system with automatic failure tracking, recovery, alerting, and intelligent proxy management.

**Phase 1 (Complete):** Automatic gap detection and backfill
**Phase 2 (Complete):** Gap alerting, dashboard, circuit breaker, multi-provider proxy support

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   SCRAPER RESILIENCE SYSTEM                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FAILURE LOGGING (scraper_base.py)                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Scraper fails → _log_scraper_failure_for_backfill()     │   │
│  │              → UPSERT into scraper_failures table       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  DATA STORE (BigQuery)                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ nba_orchestration.scraper_failures                      │   │
│  │ - game_date, scraper_name, error_type, error_message    │   │
│  │ - first_failed_at, last_failed_at, retry_count          │   │
│  │ - backfilled, backfilled_at                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  RECOVERY (Cloud Function - every 4 hours)                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ scraper-gap-backfiller:                                 │   │
│  │ 1. Query unbackfilled failures (last 7 days)            │   │
│  │ 2. For each scraper with gaps:                          │   │
│  │    - Test health (scrape today's date)                  │   │
│  │    - If healthy, backfill oldest gap                    │   │
│  │    - Mark as backfilled on success                      │   │
│  │ 3. Rate limit: 1 gap per scraper per run                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Failure Tracking (scraper_base.py)

When any scraper fails, `_log_scraper_failure_for_backfill()` is called:
- Extracts game_date from scraper opts
- Uses MERGE to upsert into scraper_failures table
- Increments retry_count if already failed for this date
- Never fails the scraper - logging errors are swallowed

### 2. BigQuery Table

```sql
-- nba_orchestration.scraper_failures
game_date DATE,           -- The date that failed to scrape
scraper_name STRING,      -- e.g., "bp_events", "bp_player_props"
error_type STRING,        -- Exception class name
error_message STRING,     -- Error details (truncated to 500 chars)
first_failed_at TIMESTAMP,
last_failed_at TIMESTAMP,
retry_count INT64,        -- How many times we've tried
backfilled BOOL,          -- TRUE when successfully recovered
backfilled_at TIMESTAMP
```

### 3. Recovery Cloud Function

Location: `orchestration/cloud_functions/scraper_gap_backfiller/`

**Schedule:** Every 4 hours (Cloud Scheduler)

**Logic:**
1. Query unbackfilled failures from last 7 days
2. Group by scraper_name
3. For each scraper with gaps:
   - Test health by scraping today's date
   - If healthy, trigger backfill for oldest gap
   - Mark as backfilled on success
4. Rate limit: 1 backfill per scraper per run (prevents overwhelming)

**Endpoints:**
- `GET /?dry_run=true` - Show gaps without backfilling
- `GET /?scraper=bp_events` - Limit to specific scraper
- `GET /` - Run backfill

## Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| LOOKBACK_DAYS | 7 | Only backfill gaps from last 7 days |
| REQUEST_TIMEOUT | 180s | Timeout for scraper requests |
| Schedule | Every 4 hours | How often recovery runs |

## Monitoring

### View Current Gaps
```sql
SELECT scraper_name, game_date, retry_count, first_failed_at
FROM nba_orchestration.scraper_failures
WHERE backfilled = FALSE
ORDER BY game_date
```

### View Recent Backfills
```sql
SELECT scraper_name, game_date, backfilled_at
FROM nba_orchestration.scraper_failures
WHERE backfilled = TRUE
  AND backfilled_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY backfilled_at DESC
```

### Gap Summary by Scraper
```sql
SELECT
  scraper_name,
  COUNTIF(NOT backfilled) as open_gaps,
  COUNTIF(backfilled) as recovered,
  MIN(CASE WHEN NOT backfilled THEN game_date END) as oldest_gap
FROM nba_orchestration.scraper_failures
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY scraper_name
```

## Deployment

### Deploy Cloud Function
```bash
cd orchestration/cloud_functions/scraper_gap_backfiller
gcloud functions deploy scraper-gap-backfiller \
  --gen2 \
  --runtime python311 \
  --trigger-http \
  --entry-point scraper_gap_backfiller \
  --region us-west2 \
  --memory 256Mi \
  --timeout 540s \
  --set-env-vars="SCRAPER_SERVICE_URL=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
```

### Create Scheduler
```bash
gcloud scheduler jobs create http scraper-gap-backfiller-schedule \
  --location us-west2 \
  --schedule "0 */4 * * *" \
  --uri "https://us-west2-nba-props-platform.cloudfunctions.net/scraper-gap-backfiller" \
  --http-method GET \
  --oidc-service-account-email "nba-props-platform@appspot.gserviceaccount.com"
```

## Files

| File | Purpose |
|------|---------|
| `scrapers/scraper_base.py` | Failure logging in `_log_scraper_failure_for_backfill()` |
| `orchestration/cloud_functions/scraper_gap_backfiller/main.py` | Recovery logic |
| `nba_orchestration.scraper_failures` | BigQuery table for tracking |

---

## Phase 2: Enhanced Resilience

### Gap Alerting

Automatic alerts when gaps accumulate beyond threshold (>= 3 days):
- Integrated into gap backfiller Cloud Function
- Sends email via AWS SES
- Includes affected scrapers, gap counts, oldest gaps

### Health Dashboard

Visual dashboard at `/scraper-dashboard`:
- Real-time gap counts per scraper
- Last run times with color-coded status
- Proxy health metrics (24h success rates)
- Recent backfills

**URL:** `https://us-west2-nba-props-platform.cloudfunctions.net/scraper-dashboard`

### Circuit Breaker

Intelligent proxy rotation that skips blocked proxies:

```
CLOSED ──(3 failures)──► OPEN ──(5min cooldown)──► HALF_OPEN
        ◄────────────── SUCCESS ◄─────────────────
```

**States:**
- **CLOSED:** Proxy working, use normally
- **OPEN:** Proxy blocked for target, skip it
- **HALF_OPEN:** Cooldown elapsed, test once

**BigQuery Table:** `nba_orchestration.proxy_circuit_breaker`

### Multi-Provider Proxy Support

Abstract provider interface for easy addition of new proxies:

| Provider | Priority | Type | Status |
|----------|----------|------|--------|
| ProxyFuel | 1 | Datacenter | Active |
| Decodo | 2 | Residential | Active |
| Bright Data | 3 | Premium | Placeholder |

## Phase 2 Files

| File | Purpose |
|------|---------|
| `shared/utils/email_alerting_ses.py` | `send_scraper_gap_alert()` method |
| `orchestration/cloud_functions/scraper_dashboard/main.py` | Health dashboard |
| `scrapers/utils/proxy_utils.py` | Circuit breaker + multi-provider |
| `nba_orchestration.proxy_circuit_breaker` | Circuit state table |

## Phase 2 Deployment

```bash
# Deploy gap backfiller with alerting
cd orchestration/cloud_functions/scraper_gap_backfiller
gcloud functions deploy scraper-gap-backfiller \
  --gen2 --runtime python311 --trigger-http \
  --entry-point scraper_gap_backfiller \
  --region us-west2 --memory 512Mi --timeout 540s

# Deploy dashboard
cd ../scraper_dashboard
gcloud functions deploy scraper-dashboard \
  --gen2 --runtime python311 --trigger-http \
  --entry-point scraper_dashboard \
  --region us-west2 --memory 256Mi --timeout 60s \
  --allow-unauthenticated

# Deploy nba-scrapers with circuit breaker (from repo root)
gcloud run deploy nba-scrapers --source scrapers/
```

---

## Related

- [Phase 2 Enhancements](./PHASE2-ENHANCEMENTS.md) - Detailed design doc
- [Proxy Infrastructure](../proxy-infrastructure/README.md) - Proxy health monitoring
- [Grading Improvements](../grading-improvements/README.md) - Data quality monitoring
