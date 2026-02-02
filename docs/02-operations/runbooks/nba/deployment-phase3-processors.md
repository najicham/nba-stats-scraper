# NBA Phase 3 Analytics Processors Deployment Runbook

**Version**: 1.0
**Last Updated**: 2026-02-02
**Owner**: NBA Data Infrastructure Team

---

## Overview

Phase 3 processors transform raw data into analytics tables. Most critical: `PlayerGameSummaryProcessor` which creates comprehensive player game stats used by feature store. Processing runs both morning (6 AM ET) and evening (6 PM, 10 PM, 1 AM ET) to support same-night analytics.

**Service**: `nba-phase3-analytics-processors`
**Region**: `us-west2`
**Repository**: `nba-stats-scraper`
**Dockerfile**: `data_processors/analytics/Dockerfile`

**Critical Processors**:
- `PlayerGameSummaryProcessor` - Player game stats (MOST CRITICAL)
- `TeamGameSummaryProcessor` - Team-level analytics
- `PlayerSeasonAveragesProcessor` - Rolling season averages

---

## Pre-Deployment Checklist

- [ ] Code changes reviewed and approved
- [ ] Tests passing: `pytest tests/data_processors/analytics/ -v`
- [ ] Schema compatibility verified (esp. `player_game_summary`)
- [ ] Shot zone data handling verified (Session 53 fix)
- [ ] Boxscore fallback logic tested (evening processing)
- [ ] Local synced with remote
- [ ] Current Phase 3 completion: Check dashboard
- [ ] Rollback plan documented

---

## Deployment Process

### Step 1: Verify Current State

```bash
# Check current deployment
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(metadata.labels.commit-sha,status.url)"

# Check Phase 3 completion rate (target: 100%)
bq query --use_legacy_sql=false \
  "SELECT game_date,
          COUNT(DISTINCT game_id) as games_scheduled,
          (SELECT COUNT(DISTINCT game_id)
           FROM nba_analytics.player_game_summary pgs
           WHERE pgs.game_date = s.game_date) as games_processed
   FROM nba_reference.nba_schedule s
   WHERE game_date >= CURRENT_DATE() - 3
     AND game_status = 3
   GROUP BY game_date ORDER BY game_date DESC"

# Check recent heartbeats
gcloud logging read \
  'resource.labels.service_name="nba-phase3-analytics-processors"
   AND jsonPayload.message=~"Heartbeat"' \
  --limit=10 --format="value(timestamp,jsonPayload.processor_name)"

# Check for errors
gcloud logging read \
  'resource.labels.service_name="nba-phase3-analytics-processors"
   AND severity>=ERROR' \
  --limit=10
```

**Pre-deployment baseline**:
- Record current Phase 3 completion %
- Note recent error rate
- Check shot zone completeness %

### Step 2: Deploy Using Automated Script

```bash
# From repository root
./bin/deploy-service.sh nba-phase3-analytics-processors
```

**What the script validates**:
1. Service identity
2. Heartbeat code (prevents Firestore proliferation)
3. **Processor heartbeats** (specific to Phase 3)
4. Recent error rate

**Deployment takes**: ~6-8 minutes

### Step 3: Post-Deployment Verification

```bash
# 1. Check service health
SERVICE_URL=$(gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(status.url)")
curl -s $SERVICE_URL/health | jq '.'

# 2. Trigger test processing (recent completed game)
curl -X POST $SERVICE_URL/process \
  -H "Content-Type: application/json" \
  -d '{
    "processor": "PlayerGameSummaryProcessor",
    "data_date": "2026-02-01",
    "force": true
  }'

# 3. Monitor processing
gcloud logging read \
  'resource.labels.service_name="nba-phase3-analytics-processors"
   AND timestamp>="'$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=50 | grep -E "PlayerGameSummaryProcessor|Completed|ERROR"

# 4. Verify data written
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(*) as player_game_records,
          COUNTIF(has_complete_shot_zones) as with_shot_zones,
          ROUND(COUNTIF(has_complete_shot_zones) * 100.0 / COUNT(*), 1) as shot_zone_pct
   FROM nba_analytics.player_game_summary
   WHERE game_date >= CURRENT_DATE() - 2
   GROUP BY game_date ORDER BY game_date DESC"

# Expected:
# - Record count matches expected player-games
# - Shot zone completeness: 50-90% (depends on BDB availability)

# 5. Check heartbeats are updating correctly
gcloud logging read \
  'resource.labels.service_name="nba-phase3-analytics-processors"
   AND jsonPayload.message=~"Heartbeat"
   AND timestamp>="'$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=5
```

---

## Common Issues & Troubleshooting

### Issue 1: Boxscore Fallback Not Working (Evening Processing)

**Symptom**: Evening schedulers (6 PM, 10 PM, 1 AM) process 0 games

**Cause**:
- `USE_NBAC_BOXSCORES_FALLBACK = False` (should be True)
- Boxscores not available yet (games still in progress)
- Query logic error in fallback path

**Diagnosis**:
```bash
# Check if gamebook data available (morning processing source)
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(DISTINCT game_id) as games
   FROM nba_raw.nbac_gamebook_player_stats
   WHERE game_date = CURRENT_DATE()"

# Check if boxscore data available (evening processing fallback)
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(DISTINCT game_id) as games
   FROM nba_raw.nbac_player_boxscores
   WHERE game_date = CURRENT_DATE()
     AND game_status_code = 3"  -- Final games only

# Check processor config
gcloud logging read \
  'resource.labels.service_name="nba-phase3-analytics-processors"
   AND textPayload=~"USE_NBAC_BOXSCORES_FALLBACK"' \
  --limit=5
```

**Fix**:
- Ensure `USE_NBAC_BOXSCORES_FALLBACK = True` in `player_game_summary_processor.py`
- Check boxscore scraper is running (part of nba-scrapers service)

### Issue 2: Shot Zone Data Missing or Incorrect

**Symptom**: `has_complete_shot_zones = FALSE` for most/all records

**Cause** (Session 53 fix should prevent this):
- Mixed data sources (paint/mid from PBP, three_pt from boxscore)
- BDB play-by-play data not available
- Query logic error

**Diagnosis**:
```bash
# Check BDB coverage
bq query --use_legacy_sql=false \
  "SELECT game_date,
          COUNT(DISTINCT game_id) as games_scheduled,
          (SELECT COUNT(DISTINCT game_id)
           FROM nba_raw.bigdataball_play_by_play pbp
           WHERE pbp.game_date = s.game_date) as games_with_pbp
   FROM nba_reference.nba_schedule s
   WHERE game_date >= CURRENT_DATE() - 3
     AND game_status = 3
   GROUP BY game_date ORDER BY game_date DESC"

# Check shot zone data quality
bq query --use_legacy_sql=false \
  "SELECT game_date,
          COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*) as pct_complete,
          ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
            THEN SAFE_DIVIDE(paint_attempts * 100.0,
                             paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_paint_rate
   FROM nba_analytics.player_game_summary
   WHERE game_date >= CURRENT_DATE() - 3 AND minutes_played > 0
   GROUP BY game_date ORDER BY game_date DESC"
```

**Expected**:
- Shot zone completeness: 50-90% (depends on BDB availability)
- Paint rate: 30-50% (typical NBA distribution)

**Fix**: If rates look wrong, check Session 53 fix is deployed

### Issue 3: Heartbeat Document Proliferation

**Symptom**: Firestore `processor_heartbeats` collection has 1000s of documents

**Cause**: Old heartbeat code using `{processor_name}_{data_date}_{run_id}` as doc ID

**Detection**:
```bash
# Check Firestore document count (should be ~30)
gcloud firestore collections list | grep processor_heartbeats

# If >100 docs, proliferation is happening
```

**Fix**:
- Ensure Session 61 heartbeat fix is deployed
- Run cleanup: `python bin/cleanup-heartbeat-docs.py`
- Verify heartbeat code:
```python
# CORRECT (Session 61 fix):
@property
def doc_id(self) -> str:
    return self.processor_name  # ONE doc per processor

# WRONG (old code):
def doc_id(self) -> str:
    return f"{self.processor_name}_{self.data_date}_{self.run_id}"  # Unbounded growth
```

### Issue 4: Silent BigQuery Write Failure

**Symptom**: Processor completes successfully but table has 0 records

**Cause**: Same as Phase 4 (Session 59 root cause)

**Detection/Fix**: See Phase 4 runbook Issue 3

---

## Rollback Procedure

```bash
# 1. List recent revisions
gcloud run revisions list --service=nba-phase3-analytics-processors --region=us-west2 --limit=5

# 2. Route to previous revision
gcloud run services update-traffic nba-phase3-analytics-processors \
  --region=us-west2 \
  --to-revisions=nba-phase3-analytics-processors-00122-xyz=100

# 3. Verify rollback
curl -s $(gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(status.url)")/health | jq '.'

# 4. Reprocess recent dates
for date in $(seq 0 2); do
  curl -X POST $(gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
    --format="value(status.url)")/process \
    -H "Content-Type: application/json" \
    -d "{\"processor\": \"PlayerGameSummaryProcessor\", \"data_date\": \"$(date -d "$date days ago" +%Y-%m-%d)\", \"force\": true}"
  sleep 30
done

# 5. Verify data restored
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(*) FROM nba_analytics.player_game_summary
   WHERE game_date >= CURRENT_DATE() - 2
   GROUP BY game_date ORDER BY game_date DESC"
```

---

## Evening Processing (Session 73)

Phase 3 runs in EVENING mode to support same-night predictions:

| Scheduler Job | Time (ET) | Purpose |
|---------------|-----------|---------|
| `evening-analytics-6pm-et` | 6 PM Sat/Sun | Weekend matinees |
| `evening-analytics-10pm-et` | 10 PM Daily | 7 PM games |
| `evening-analytics-1am-et` | 1 AM Daily | West Coast games |
| `morning-analytics-catchup-9am-et` | 9 AM Daily | Safety net |

**Boxscore Fallback**:
- Morning processing uses `nbac_gamebook_player_stats` (gold standard)
- Evening processing uses `nbac_player_boxscores` (scraped live, available immediately after games)

**Verify which source was used**:
```sql
SELECT game_date,
  COUNTIF(primary_source_used = 'nbac_boxscores') as from_boxscores,
  COUNTIF(primary_source_used = 'nbac_gamebook') as from_gamebook
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date ORDER BY game_date DESC
```

---

## Service Dependencies

| Dependency | Purpose | Impact if Down |
|------------|---------|----------------|
| BigQuery `nbac_gamebook_player_stats` | Gold standard stats | Fall back to boxscores |
| BigQuery `nbac_player_boxscores` | Evening processing fallback | Evening processing fails |
| BigQuery `bigdataball_play_by_play` | Shot zone data | Shot zones incomplete |
| BigQuery `player_game_summary` (output) | Feature store input | Predictions fail |

---

## Success Criteria

Deployment is successful when:

- ✅ Service responds to `/health`
- ✅ No errors in logs (10 min window)
- ✅ Heartbeats updating correctly (one doc per processor)
- ✅ Test processing completes successfully
- ✅ Phase 3 completion >= 90% (check next day)
- ✅ Shot zone completeness in expected range (50-90%)

---

## Related Runbooks

- [Deployment: Phase 4 Processors](./deployment-phase4-processors.md)
- [Shot Zone Failures Troubleshooting](../../shot-zone-failures.md)
- [Evening Analytics Processing (Session 73)](../../../08-projects/current/evening-analytics-processing/)

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-02-02 | 1.0 | Initial runbook | Claude + Session 79 |
