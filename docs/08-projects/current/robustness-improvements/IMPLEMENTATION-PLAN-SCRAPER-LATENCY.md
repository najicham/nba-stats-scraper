# Scraper Latency Monitoring - Implementation Plan

**Created:** January 21, 2026
**Status:** Ready to Implement
**Estimated Effort:** 2-3 hours

---

## Executive Summary

Implement comprehensive latency monitoring for all key scrapers with automated alerting via Slack and email.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     NBA Schedule (Source of Truth)                   │
│                     nba_raw.nbac_schedule                           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│              v_scraper_game_availability (BigQuery View)             │
│  Compares schedule against all data sources:                        │
│  - BDL box scores                                                    │
│  - NBAC gamebook                                                     │
│  - OddsAPI lines                                                     │
│  - ESPN scoreboard (when fixed)                                      │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│           scraper_availability_monitor (Cloud Function)              │
│  Runs: 8 AM ET daily (after morning recovery scraper)               │
│  Checks: Yesterday's games for missing data                         │
│  Alerts: Slack (#nba-alerts) + Email (critical)                     │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
            ┌─────────────┐                ┌─────────────┐
            │    Slack    │                │    Email    │
            │ #nba-alerts │                │ AWS SES     │
            └─────────────┘                └─────────────┘
```

---

## Components to Build

### 1. Unified Availability View

**Location:** `nba_orchestration.v_scraper_game_availability`

**Sources to Compare:**
| Source | Table | First-Seen Column |
|--------|-------|-------------------|
| Schedule | `nba_raw.nbac_schedule` | (baseline) |
| BDL | `nba_raw.bdl_player_boxscores` | `created_at` |
| NBAC | `nba_raw.nbac_gamebook_player_stats` | Parse from `source_file_path` |
| OddsAPI | `nba_raw.odds_api_game_lines` | `created_at` |

**Output Fields:**
- `game_date`, `game_id`, `matchup`
- `game_start_time`, `estimated_game_end`
- `bdl_available`, `bdl_latency_hours`
- `nbac_available`, `nbac_latency_hours`
- `odds_available`, `odds_latency_hours`
- `missing_sources` (array of missing source names)
- `availability_status` (OK / WARNING / CRITICAL)

### 2. Cloud Function: Scraper Availability Monitor

**Location:** `orchestration/cloud_functions/scraper_availability_monitor/main.py`

**Schedule:** `0 13 * * *` (8 AM ET = 1 PM UTC)

**Logic:**
1. Query yesterday's games from `v_scraper_game_availability`
2. Filter for games with `availability_status != 'OK'`
3. Group issues by source (BDL missing X games, NBAC missing Y, etc.)
4. Send Slack alert with summary
5. If critical (>50% missing), also send email
6. Log to Firestore for tracking

### 3. Alert Format

**Slack Message:**
```
🔴 Scraper Data Gaps Detected

📅 Date: 2026-01-20
⏰ Checked at: 8:00 AM ET

❌ Missing Data:
• BDL: 3 games missing (MIA@GSW, TOR@GSW, LAL@DEN)
• NBAC: 0 games missing ✅
• OddsAPI: 1 game missing (TOR@GSW)

📊 Coverage:
• BDL: 57% (4/7 games)
• NBAC: 100% (7/7 games)
• OddsAPI: 86% (6/7 games)

🔗 View details: [BigQuery Console Link]
```

---

## Implementation Steps

### Step 1: Create Unified View (30 min)

```sql
CREATE OR REPLACE VIEW nba_orchestration.v_scraper_game_availability AS
WITH schedule AS (...),
bdl_data AS (...),
nbac_data AS (...),
odds_data AS (...)
SELECT ...
```

### Step 2: Create Cloud Function (1 hour)

```python
# orchestration/cloud_functions/scraper_availability_monitor/main.py
@functions_framework.http
def check_scraper_availability(request):
    # Query view for yesterday
    # Build alert message
    # Send to Slack + Email if critical
    # Log to Firestore
```

### Step 3: Deploy & Configure Scheduler (30 min)

```bash
# Deploy Cloud Function
gcloud functions deploy scraper-availability-monitor ...

# Create scheduler job
gcloud scheduler jobs create http scraper-availability-daily \
    --schedule="0 13 * * *" \
    --time-zone="UTC" \
    --uri="https://..." \
    ...
```

### Step 4: Test & Verify (30 min)

1. Manually trigger function
2. Verify Slack message format
3. Verify email for critical alerts
4. Check Firestore logging

---

## Files to Create

| File | Purpose |
|------|---------|
| `schemas/bigquery/monitoring/scraper_game_availability.sql` | View definition |
| `orchestration/cloud_functions/scraper_availability_monitor/main.py` | Cloud Function |
| `orchestration/cloud_functions/scraper_availability_monitor/requirements.txt` | Dependencies |

---

## Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| BDL coverage | < 90% | < 50% |
| NBAC coverage | < 95% | < 80% |
| OddsAPI coverage | < 80% | < 50% |
| Any source completely missing | - | Critical |

---

## Success Criteria

- [ ] View correctly shows availability for all sources
- [ ] Alert fires within 12 hours of game completion
- [ ] Slack message is clear and actionable
- [ ] Email sent for critical issues
- [ ] Historical data tracked in Firestore
- [ ] No false positives (games that haven't finished yet)

---

## Related Documents

- `ERROR-TRACKING-PROPOSAL.md` - Broader error tracking vision
- `SCRAPER-LATENCY-MONITORING-PROPOSAL.md` - Original proposal
- `BDL-AVAILABILITY-INVESTIGATION-JAN-21-2026.md` - Investigation that drove this
