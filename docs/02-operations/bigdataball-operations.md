# BigDataBall Operations Guide

**Purpose:** BigDataBall (BDB) provides shot zone coordinates essential for accurate predictions. This guide covers monitoring, alerting, and recovery procedures.

---

## Why BigDataBall Matters

BDB provides the **only** reliable source for shot zone data (paint, mid-range, three-point). Without it:
- `paint_attempts` = NULL
- Shot zone rates become corrupted (e.g., 100% three_pt_rate instead of 35%)
- Model predictions degrade significantly (V8 dropped from 77% → 34% hit rate)

---

## Data Flow

```
BDB Scraper          BigQuery Table              Phase 3
    │                     │                        │
    ▼                     ▼                        ▼
Google Drive  →  bigdataball_play_by_play  →  player_game_summary
                                                    │
                                                    ▼
                                             paint_attempts
                                             mid_range_attempts
                                             shot zone features
```

---

## Monitoring

### 1. Critical Monitor (Every 30 Minutes)

```bash
# Check BDB status and send alerts
python bin/monitoring/bdb_critical_monitor.py

# Dry run (no alerts)
python bin/monitoring/bdb_critical_monitor.py --dry-run

# Check specific date
python bin/monitoring/bdb_critical_monitor.py --date 2026-01-29
```

**Alert Levels:**
| Level | Condition | Action |
|-------|-----------|--------|
| WARNING | >2h after game, BDB missing | Retry triggered, Slack alert |
| CRITICAL | >6h after game, BDB missing | Escalation, multiple retries |
| EMERGENCY | >24h after game, BDB missing | Manual intervention required |

### 2. Pending Games Monitor

```bash
# Check games awaiting BDB data
python bin/monitoring/bdb_pending_monitor.py --dry-run

# Trigger re-runs for games with BDB now available
python bin/monitoring/bdb_pending_monitor.py
```

### 3. Quick Health Check

```sql
-- Check BDB coverage for recent games
SELECT
  game_date,
  COUNT(DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0')) as games_with_bdb,
  (SELECT COUNT(*) FROM nba_raw.nbac_schedule s
   WHERE s.game_date = b.game_date AND s.game_status = 3) as total_games
FROM nba_raw.bigdataball_play_by_play b
WHERE game_date >= CURRENT_DATE() - 3
  AND bdb_game_id IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Recovery Procedures

### Scenario 1: BDB Data Missing for Tonight's Games

**Detection:** Monitor shows games with 0 BDB shots

**Steps:**
1. Check if BDB scraper ran:
   ```bash
   gcloud logging read 'resource.labels.service_name="nba-bdb-scraper"' --limit=20
   ```

2. Manually trigger scraper:
   ```bash
   gcloud pubsub topics publish nba-phase2-trigger \
     --message='{"processor": "bigdataball_pbp", "game_date": "2026-01-30"}'
   ```

3. After data arrives, re-run Phase 3:
   ```bash
   gcloud pubsub topics publish nba-phase3-trigger \
     --message='{"game_date": "2026-01-30", "trigger_reason": "bdb_recovery"}'
   ```

### Scenario 2: BDB Data Arrives After Predictions Made

**Detection:** `pending_bdb_games` shows games with `status='blocked'`

**Policy:** If >1 hour before game start, auto re-run. Otherwise, prediction is locked.

**Check blocked games:**
```sql
SELECT game_date, game_id, resolution_notes
FROM nba_orchestration.pending_bdb_games
WHERE status = 'blocked'
ORDER BY game_date DESC;
```

### Scenario 3: Historical Data Missing (Backfill Needed)

**Detection:** Query shows dates with low paint_pct

```sql
SELECT game_date,
  ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 1) as paint_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01' AND minutes_played > 0
GROUP BY 1
HAVING paint_pct < 50
ORDER BY 1;
```

**Backfill:**
```bash
# Dry run first
python bin/backfill/backfill_shot_zones.py --dry-run

# Process all affected dates
python bin/backfill/backfill_shot_zones.py --all --delay 30

# Or specific date
python bin/backfill/backfill_shot_zones.py --date 2026-01-23
```

---

## Quality Tracking

### Prediction Quality Tiers

| Tier | Condition | Confidence Impact |
|------|-----------|-------------------|
| Gold | BDB data available, all features populated | Full confidence |
| Silver | NBAC fallback used (BDB unavailable) | Reduced confidence |
| Bronze | Shot zone features unavailable | Significantly reduced |

### Check Quality Distribution

```sql
SELECT
  game_date,
  data_quality_tier,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### Audit Log

Every prediction is logged with full data availability context:

```sql
SELECT
  game_date,
  player_lookup,
  data_quality_tier,
  shot_zones_source,
  missing_features,
  is_rerun,
  rerun_reason
FROM nba_predictions.prediction_audit_log
WHERE game_date = CURRENT_DATE()
  AND data_quality_tier != 'gold';
```

---

## Alerting Configuration

### Slack Webhook

Set environment variable:
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

### Alert Channels

| Alert Type | Channel | Frequency |
|------------|---------|-----------|
| BDB missing (warning) | #data-ops | When >3 games affected |
| BDB missing (critical) | #data-ops + @oncall | Immediately |
| Quality degraded | #predictions | Daily summary |

---

## Re-run Policy

### Automatic Re-runs

| Condition | Action |
|-----------|--------|
| BDB arrives >1h before game | Auto re-run Phase 3, 4, 5 |
| BDB arrives <1h before game | Log "blocked", keep original prediction |
| BDB arrives after game | Log "late_arrival", no re-run |

### Manual Re-runs

Only trigger manual re-runs if:
1. Clear data quality issue identified
2. >2 hours before game start
3. Approved by operations

```bash
# Manual Phase 3 re-run
gcloud pubsub topics publish nba-phase3-trigger \
  --message='{"game_date": "2026-01-30", "game_id": "0022500686", "trigger_reason": "manual_recovery"}'
```

---

## Scheduled Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| `bdb_critical_monitor` | */30 * * * * | Check BDB availability, send alerts |
| `bdb_arrival_trigger` | On BDB data arrival | Trigger re-runs when data available |
| `bdb_pending_monitor` | 0 */2 * * * | Check pending games, trigger re-runs |

### Set Up Cloud Scheduler

```bash
# BDB monitor every 30 minutes
gcloud scheduler jobs create pubsub bdb-monitor \
  --schedule="*/30 * * * *" \
  --topic=nba-bdb-monitor \
  --message-body='{"source": "scheduler"}'

# Pending games check every 2 hours
gcloud scheduler jobs create pubsub bdb-pending-check \
  --schedule="0 */2 * * *" \
  --topic=nba-bdb-arrival \
  --message-body='{"source": "scheduler"}'
```

---

## Troubleshooting

### "No BDB data for game X"

1. Check if game is in schedule:
   ```sql
   SELECT * FROM nba_raw.nbac_schedule WHERE game_id = 'X';
   ```

2. Check BDB table:
   ```sql
   SELECT COUNT(*) FROM nba_raw.bigdataball_play_by_play
   WHERE game_date = '2026-01-30' AND bdb_game_id = 22500686;
   ```

3. Check scraper logs for errors

### "Paint rate is 0% despite BDB available"

1. Verify BDB has shot_distance:
   ```sql
   SELECT COUNTIF(shot_distance IS NOT NULL) / COUNT(*) as pct
   FROM nba_raw.bigdataball_play_by_play
   WHERE game_date = '2026-01-30' AND event_type = 'shot';
   ```

2. Check player_lookup format matches

3. Re-run Phase 3 for that date

### "Predictions show quality=bronze"

1. Check when prediction was made:
   ```sql
   SELECT processed_at, bdb_pbp_available
   FROM nba_predictions.prediction_audit_log
   WHERE game_date = '2026-01-30' AND player_lookup = 'X';
   ```

2. If BDB now available, check if re-run is possible (>1h before game)

---

## Key Files

| File | Purpose |
|------|---------|
| `bin/monitoring/bdb_critical_monitor.py` | Main BDB monitor |
| `bin/monitoring/bdb_pending_monitor.py` | Pending games monitor |
| `bin/backfill/backfill_shot_zones.py` | Backfill script |
| `predictions/worker/quality_tracker.py` | Quality assessment |
| `orchestration/cloud_functions/bdb_arrival_trigger/` | Auto re-run trigger |

---

## Contacts

- **BDB Data Issues:** Check #data-ops Slack channel
- **Prediction Quality:** Check #predictions Slack channel
- **Escalation:** @oncall in Slack
