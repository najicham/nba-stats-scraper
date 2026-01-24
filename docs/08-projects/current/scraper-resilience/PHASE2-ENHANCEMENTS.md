# Scraper Resilience Phase 2 - Enhancements

**Created:** 2026-01-24
**Status:** IN PROGRESS
**Priority:** P1
**Depends On:** Phase 1 (COMPLETE - scraper-gap-backfiller deployed)

---

## Overview

Phase 2 adds proactive monitoring, intelligent proxy management, and operational visibility to the resilience system.

## Features

### 1. Gap Accumulation Alerts
**Goal:** Get notified when gaps accumulate beyond a threshold (e.g., > 3 days)

- Add `send_scraper_gap_alert()` to email alerting system
- Modify gap backfiller to check for accumulating gaps
- Alert when: any scraper has > 3 unbackfilled days
- Alert includes: scraper name, gap count, oldest gap date, recent errors

### 2. Scraper Health Dashboard
**Goal:** Visual view of scraper health and gap status

- Cloud Function endpoint returning HTML dashboard
- Shows all scrapers with: status, gap count, last success, recent errors
- Color-coded health indicators (green/yellow/red)
- Auto-refresh capability
- Accessible via simple URL

### 3. Circuit Breaker for Proxy Rotation
**Goal:** Skip proxies that are known to be blocked for specific targets

- Track proxy+target success/failure in BigQuery
- Circuit breaker states: CLOSED (working) → OPEN (blocked) → HALF_OPEN (testing)
- Auto-open circuit after N consecutive failures
- Auto-close after cooldown period + successful test
- Skip blocked proxies during scraping

### 4. Multi-Provider Proxy Support
**Goal:** Add backup proxy providers for redundancy

- Abstract proxy provider interface
- Add Bright Data or Oxylabs as secondary providers
- Priority-based rotation: primary → secondary → tertiary
- Provider-specific configuration (credentials, endpoints)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ENHANCED RESILIENCE SYSTEM                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐  │
│  │  Gap Backfiller │───▶│  Gap Alerting   │───▶│  Email + Slack      │  │
│  │  (every 4 hrs)  │    │  (threshold: 3) │    │  Notifications      │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────────┘  │
│           │                                                              │
│           ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    DASHBOARD (Cloud Function)                    │    │
│  │  ┌──────────────┬──────────────┬──────────────┬──────────────┐  │    │
│  │  │ bp_events    │ bp_props     │ bdl_boxscore │ nba_scoreboard │ │    │
│  │  │ ● 0 gaps     │ ⚠ 2 gaps     │ ● 0 gaps     │ ● 0 gaps       │ │    │
│  │  │ Last: 2h ago │ Last: 8h ago │ Last: 1h ago │ Last: 30m ago  │ │    │
│  │  └──────────────┴──────────────┴──────────────┴──────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    CIRCUIT BREAKER                               │    │
│  │                                                                   │    │
│  │  ProxyFuel + bettingpros.com:  🔴 OPEN (blocked)                 │    │
│  │  Decodo + bettingpros.com:     🟢 CLOSED (working)               │    │
│  │  ProxyFuel + nba.com:          🟢 CLOSED (working)               │    │
│  │  Decodo + nba.com:             🟡 HALF_OPEN (testing)            │    │
│  │                                                                   │    │
│  │  State transitions:                                               │    │
│  │  CLOSED ──(3 failures)──▶ OPEN ──(5min cooldown)──▶ HALF_OPEN   │    │
│  │          ◀────────────── SUCCESS ◀─────────────────              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    PROXY PROVIDERS                               │    │
│  │                                                                   │    │
│  │  1. ProxyFuel (datacenter) - $0.01/request - Primary             │    │
│  │  2. Decodo (residential)   - $0.05/request - Fallback            │    │
│  │  3. [Future: Bright Data]  - $X/GB - Premium fallback            │    │
│  │                                                                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Task 1: Gap Alert System
**Files to modify:**
- `shared/utils/email_alerting_ses.py` - Add `send_scraper_gap_alert()`
- `orchestration/cloud_functions/scraper_gap_backfiller/main.py` - Add alert check

**New BigQuery query:**
```sql
SELECT scraper_name, COUNT(*) as gap_count, MIN(game_date) as oldest_gap
FROM nba_orchestration.scraper_failures
WHERE backfilled = FALSE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY scraper_name
HAVING COUNT(*) >= 3
```

### Task 2: Dashboard Cloud Function
**New files:**
- `orchestration/cloud_functions/scraper_dashboard/main.py`
- `orchestration/cloud_functions/scraper_dashboard/requirements.txt`

**Data sources:**
- `nba_orchestration.scraper_failures` - Gaps
- `nba_orchestration.phase1_scraper_runs` - Run history
- `nba_orchestration.proxy_health_metrics` - Proxy health

### Task 3: Circuit Breaker
**Files to modify:**
- `scrapers/utils/proxy_utils.py` - Add circuit breaker logic
- `scrapers/scraper_base.py` - Integrate circuit breaker

**New BigQuery table:**
```sql
CREATE TABLE nba_orchestration.proxy_circuit_breaker (
  proxy_provider STRING,
  target_host STRING,
  circuit_state STRING,  -- CLOSED, OPEN, HALF_OPEN
  failure_count INT64,
  last_failure_at TIMESTAMP,
  last_success_at TIMESTAMP,
  opened_at TIMESTAMP,
  updated_at TIMESTAMP
)
```

### Task 4: Multi-Provider Support
**Files to modify:**
- `scrapers/utils/proxy_utils.py` - Refactor for multiple providers
- Secret Manager - Add new provider credentials

---

## Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| GAP_ALERT_THRESHOLD | 3 | Days of gaps before alerting |
| CIRCUIT_FAILURE_THRESHOLD | 3 | Consecutive failures to open circuit |
| CIRCUIT_COOLDOWN_MINUTES | 5 | Time before testing OPEN circuit |
| DASHBOARD_CACHE_SECONDS | 60 | Dashboard data cache duration |

---

## Success Criteria

- [ ] Alerts sent when any scraper has > 3 days of gaps
- [ ] Dashboard shows real-time scraper health status
- [ ] Circuit breaker skips blocked proxies automatically
- [ ] New proxy provider ready for integration

---

## Testing

```bash
# Test gap alert (manually add test data)
bq query --use_legacy_sql=false "
INSERT INTO nba_orchestration.scraper_failures
(game_date, scraper_name, error_type, error_message, first_failed_at, last_failed_at, retry_count, backfilled)
VALUES
('2026-01-21', 'test_scraper', 'TestError', 'Test gap', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, FALSE),
('2026-01-22', 'test_scraper', 'TestError', 'Test gap', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, FALSE),
('2026-01-23', 'test_scraper', 'TestError', 'Test gap', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, FALSE),
('2026-01-24', 'test_scraper', 'TestError', 'Test gap', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, FALSE)
"

# Test dashboard
curl "https://us-west2-nba-props-platform.cloudfunctions.net/scraper-dashboard"

# Test circuit breaker (view states)
bq query --use_legacy_sql=false "
SELECT * FROM nba_orchestration.proxy_circuit_breaker
ORDER BY updated_at DESC
"
```

---

## Deployment

```bash
# Deploy updated gap backfiller
cd orchestration/cloud_functions/scraper_gap_backfiller
gcloud functions deploy scraper-gap-backfiller \
  --gen2 --runtime python311 --trigger-http \
  --entry-point scraper_gap_backfiller \
  --region us-west2 --memory 256Mi --timeout 540s

# Deploy dashboard
cd ../scraper_dashboard
gcloud functions deploy scraper-dashboard \
  --gen2 --runtime python311 --trigger-http \
  --entry-point scraper_dashboard \
  --region us-west2 --memory 256Mi --timeout 60s \
  --allow-unauthenticated

# Deploy nba-scrapers with circuit breaker
gcloud run deploy nba-scrapers --source .
```
