# Phase 4 Troubleshooting & Recovery

**File:** `docs/processors/07-phase4-troubleshooting.md`
**Created:** 2025-11-15 16:00 PST
**Last Updated:** 2025-11-15 16:00 PST
**Purpose:** Failure scenarios, recovery procedures, and runbooks for Phase 4 processors
**Status:** Draft (awaiting deployment)
**Audience:** On-call engineers troubleshooting Phase 4 issues

**Related Docs:**
- **Operations:** See `05-phase4-operations-guide.md` for processor specifications
- **Scheduling:** See `06-phase4-scheduling-strategy.md` for dependency management
- **ML Feature Store:** See `08-phase4-ml-feature-store-deepdive.md` for P5-specific troubleshooting
- **Phase 3 Troubleshooting:** See `04-phase3-troubleshooting.md` for upstream dependencies

---

## Table of Contents

1. [Quick Diagnosis](#quick-diagnosis)
2. [Failure Scenarios](#failure-scenarios)
3. [Manual Recovery Runbook](#manual-recovery-runbook)
4. [Retry Strategy](#retry-strategy)
5. [Alert Configuration](#alert-configuration)
6. [Early Season Considerations](#early-season-considerations)

---

## Quick Diagnosis

### Is Phase 4 Working?

Run this query to check overall Phase 4 health:

```sql
-- Quick health check for Phase 4
SELECT
  'team_defense' as processor,
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END as status,
  COUNT(*) as rows,
  MAX(processed_at) as last_run,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_since_last_run
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT
  'player_shot_zone',
  CASE WHEN COUNT(*) >= 400 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT
  'player_composite',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT
  'player_daily_cache',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()

UNION ALL

SELECT
  'ml_feature_store',
  CASE WHEN COUNT(*) >= 100 AND AVG(feature_quality_score) >= 70 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(created_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR)
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Expected Output (Healthy):**
```
processor           | status    | rows | last_run            | hours_since_last_run
--------------------|-----------|------|---------------------|---------------------
team_defense        | ✅ OK     | 30   | 2025-11-15 23:02:15 | 10
player_shot_zone    | ✅ OK     | 452  | 2025-11-15 23:08:42 | 10
player_composite    | ✅ OK     | 435  | 2025-11-15 23:45:18 | 9
player_daily_cache  | ✅ OK     | 178  | 2025-11-15 23:40:05 | 9
ml_feature_store    | ✅ OK     | 435  | 2025-11-16 00:02:33 | 9
```

---

### Check Recent Executions

```bash
# Check all Phase 4 job executions in last 24h
for job in phase4-team-defense-zone-analysis phase4-player-shot-zone-analysis phase4-player-composite-factors phase4-player-daily-cache phase4-ml-feature-store-v2; do
  echo "=== $job ==="
  gcloud run jobs executions list \
    --job=$job \
    --region=us-central1 \
    --limit=5 \
    --format="table(name,status,startTime)"
  echo ""
done
```

---

### Check Cloud Scheduler

```bash
# Verify scheduler job is enabled
gcloud scheduler jobs describe phase4-nightly-trigger \
  --location=us-central1 \
  --format="table(name,state,schedule)"
```

**Expected Output:**
```
NAME                    STATE    SCHEDULE
phase4-nightly-trigger  ENABLED  0 23 * * *
```

---

## Failure Scenarios

### Scenario 1: P1 (team_defense) Fails

**Symptoms:**
- Query shows < 20 team records for today
- Cloud Run execution shows FAILED status
- Logs show errors

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| P2 (player_shot_zone) | ✅ Can continue | Independent |
| P3 (player_composite) | ❌ BLOCKED | Depends on P1 |
| P4 (player_daily_cache) | ✅ Can continue | Depends on P2 only |
| P5 (ml_feature_store_v2) | ❌ BLOCKED | Depends on P1 via P3 |

**Diagnosis:**

```bash
# Check execution logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=phase4-team-defense-zone-analysis AND severity>=ERROR" \
  --limit=50 \
  --format=json \
  --project=nba-props-platform
```

**Common Errors:**

**Error:** "Table not found: nba_analytics.team_defense_game_summary"
- **Cause:** Phase 3 team defense processor failed
- **Recovery:** Check Phase 3 processor status, manually trigger if needed

**Error:** "No rows returned for date 2025-11-15"
- **Cause:** No games yesterday OR Phase 3 data missing
- **Recovery:** Verify games scheduled, check Phase 3 data

**Recovery Steps:**

1. **Verify Phase 3 Data Exists:**
```sql
SELECT COUNT(*) as team_defense_rows
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE() - 1;
```

2. **If Phase 3 Missing → Fix Phase 3 First:**
```bash
# See Phase 3 troubleshooting
# docs/processors/04-phase3-troubleshooting.md
```

3. **If Phase 3 Complete → Manually Trigger P1:**
```bash
gcloud run jobs execute phase4-team-defense-zone-analysis \
  --region us-central1 \
  --set-env-vars "ANALYSIS_DATE=$(date +%Y-%m-%d)"
```

4. **Once P1 Completes → Manually Trigger P3:**
```bash
gcloud run jobs execute phase4-player-composite-factors \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

5. **Once P3 Completes → Manually Trigger P5:**
```bash
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

**Timeline:**
- Auto-retry: +10 minutes (5 min × 2 retries)
- Manual intervention: +30-60 minutes
- Total delay: ~40-70 minutes (may miss 12:30 AM target)

---

### Scenario 2: P2 (player_shot_zone) Fails

**Symptoms:**
- Query shows < 400 player records for today
- P2 is the longest-running processor (8 min typical)
- Blocks the most downstream processors

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| P1 (team_defense) | ✅ Unaffected | Already complete |
| P3 (player_composite) | ❌ BLOCKED | Depends on P2 |
| P4 (player_daily_cache) | ❌ BLOCKED | Depends on P2 |
| P5 (ml_feature_store_v2) | ❌ BLOCKED | Depends on P2 via P3 and P4 |

**This is CRITICAL - blocks 3 downstream processors**

**Recovery:**

1. **Check P2 Logs:**
```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=phase4-player-shot-zone-analysis AND severity>=ERROR" \
  --limit=50
```

2. **Common Causes:**
- Phase 3 player_game_summary incomplete
- Timeout (processing >20 min)
- Memory exceeded (>2Gi)

3. **Manually Trigger P2:**
```bash
gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "ANALYSIS_DATE=$(date +%Y-%m-%d)"
```

4. **Once P2 Complete → Trigger P3 + P4 in Parallel:**
```bash
# Trigger both simultaneously
gcloud run jobs execute phase4-player-composite-factors \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)" &

gcloud run jobs execute phase4-player-daily-cache \
  --region us-central1 \
  --set-env-vars "CACHE_DATE=$(date +%Y-%m-%d)" &

wait  # Wait for both to complete
```

5. **Once P3 + P4 Complete → Trigger P5:**
```bash
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

**Timeline:**
- Auto-retry: +30 minutes (15 min × 2 retries)
- Manual intervention: +30-60 minutes
- Total delay: ~60-90 minutes (WILL miss 12:30 AM target, may miss 1 AM deadline)

---

### Scenario 3: P3 (player_composite) Fails

**Symptoms:**
- Query shows < 100 player records for today
- Logs show "Missing dependency" errors

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| P1, P2, P4 | ✅ Unaffected | Already complete or independent |
| P5 (ml_feature_store_v2) | ❌ BLOCKED | Depends on P3 |

**Recovery:**

1. **Verify P1 + P2 Complete:**
```sql
-- P3 needs BOTH P1 + P2
SELECT
  (SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date = CURRENT_DATE()) as p1_rows,
  (SELECT COUNT(*) FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date = CURRENT_DATE()) as p2_rows;
-- Expected: p1_rows >= 20, p2_rows >= 400
```

2. **If P1 or P2 Missing → Fix Those First**

3. **If P1 + P2 Complete → Manually Trigger P3:**
```bash
gcloud run jobs execute phase4-player-composite-factors \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

4. **Once P3 Completes → Trigger P5:**
```bash
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

**Timeline:**
- Auto-retry: +40 minutes (20 min × 2 retries)
- Manual intervention: +15-30 minutes
- Total delay: ~55-70 minutes (may miss 12:30 AM target)

---

### Scenario 4: P4 (player_daily_cache) Fails

**Symptoms:**
- Query shows < 100 player records for today (on game day)
- Logs show missing historical data

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| P1, P2, P3 | ✅ Unaffected | Already complete |
| P5 (ml_feature_store_v2) | ❌ BLOCKED | Depends on P4 |

**Note:** P5 can use Phase 3 fallback if P4 fails (degraded mode)

**Recovery:**

1. **Check P4 Logs:**
```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=phase4-player-daily-cache AND severity>=ERROR" \
  --limit=50
```

2. **Verify P2 Complete (P4's dependency):**
```sql
SELECT COUNT(*) as p2_rows
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
-- Expected: >= 400
```

3. **Manually Trigger P4:**
```bash
gcloud run jobs execute phase4-player-daily-cache \
  --region us-central1 \
  --set-env-vars "CACHE_DATE=$(date +%Y-%m-%d)"
```

4. **Once P4 Complete → Trigger P5:**
```bash
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

**Alternative:** P5 can proceed with Phase 3 fallback (see P5 deep-dive doc)

**Timeline:**
- Auto-retry: +30 minutes (15 min × 2 retries)
- Manual intervention: +15-30 minutes
- Total delay: ~45-60 minutes (likely meets 12:30 AM target)

---

### Scenario 5: P5 (ml_feature_store_v2) Fails

**Symptoms:**
- Query shows 0 rows in ml_feature_store_v2 for today
- Phase 5 predictions not running
- Critical PagerDuty alert

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| P1, P2, P3, P4 | ✅ Unaffected | Already complete |
| Phase 5 predictions | ❌ BLOCKED | No features available |

**This is CRITICAL - blocks ALL Phase 5**

**Recovery:**

See `08-phase4-ml-feature-store-deepdive.md` → Incident Response Playbook for detailed recovery procedures.

**Quick Recovery:**

1. **Check All Dependencies:**
```sql
SELECT
  (SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date = CURRENT_DATE()) as p1,
  (SELECT COUNT(*) FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date = CURRENT_DATE()) as p2,
  (SELECT COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date = CURRENT_DATE()) as p3,
  (SELECT COUNT(*) FROM nba_precompute.player_daily_cache WHERE cache_date = CURRENT_DATE()) as p4;
```

2. **If Any Missing → Fix Those First**

3. **If All Present → Manually Trigger P5:**
```bash
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

4. **Verify Success:**
```sql
SELECT
  COUNT(*) as total_players,
  AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- Expected: 100-450 players, quality 70-100
```

**Timeline:**
- Auto-retry: +10 minutes (5 min × 2 retries)
- Manual intervention: +10-20 minutes
- Total delay: ~20-30 minutes (likely meets 12:30 AM target)

---

### Scenario 6: Phase 3 Incomplete (Upstream Failure)

**Symptoms:**
- All Phase 4 processors fail within 10 seconds
- All logs show "dependency check failed"
- No Phase 3 data for today

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| All Phase 4 | ❌ BLOCKED | No source data |
| Phase 5 | ❌ BLOCKED | No features |

**Detection:**
- Dependency check at start of P1 + P2 fails
- Query returns 0 rows for today's game_date

**Recovery:**

1. **Alert on-call immediately (CRITICAL)**

2. **Check Phase 3 Completion:**
```sql
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as rows
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'team_defense_game_summary', COUNT(*)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'upcoming_player_game_context', COUNT(*)
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
```

3. **Fix Phase 3:**
```bash
# See Phase 3 troubleshooting
# docs/processors/04-phase3-troubleshooting.md
```

4. **Once Phase 3 Complete → Trigger Phase 4:**
```bash
# Trigger phase4-start
gcloud pubsub topics publish phase4-start \
  --message '{"processor":"phase4_start","phase":"4","analysis_date":"'$(date +%Y-%m-%d)'"}'
```

**Timeline:**
- Variable (depends on Phase 3 issue)
- May need to skip day if unrecoverable

---

### Scenario 7: Early Season (Insufficient Data)

**Symptoms:**
- All processors create <50% of expected rows
- Quality scores <50
- early_season_flag = TRUE in outputs

**Impact:**

| Component | Status | Quality |
|-----------|--------|---------|
| P1-P5 | ✅ All create placeholders | Low quality scores (<50), many NULL values |

**This is EXPECTED in Week 1-3, not a failure**

**Detection:**
- early_season_flag = TRUE in outputs
- Quality scores below thresholds
- Row counts below normal but >0

**Response:**

**No action needed** - this is expected behavior

**Monitor for Week 4+** when should resolve

**Timeline:**
- Week 1-2: All placeholders (normal)
- Week 3: Partial data (normal)
- Week 4+: Should be normal operations

---

## Manual Recovery Runbook

### Complete Manual Phase 4 Trigger

**Use this when Phase 4 needs to be run manually for a specific date.**

#### Step 1: Verify Phase 3 Complete

```bash
# Check Phase 3 has data for target date
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as row_count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'team_defense_game_summary', COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'upcoming_player_game_context', COUNT(*)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = CURRENT_DATE()
"
```

**Expected:** All counts > 0

---

#### Step 2: Trigger Parallel Set 1 (P1 + P2)

```bash
# Option A: Via Pub/Sub (triggers both P1 + P2)
gcloud pubsub topics publish phase4-start \
  --message '{
    "processor": "phase4_start",
    "phase": "4",
    "analysis_date": "'$(date +%Y-%m-%d)'"
  }'

# Option B: Via Cloud Run Jobs (trigger each separately)
gcloud run jobs execute phase4-team-defense-zone-analysis \
  --region us-central1 \
  --set-env-vars "ANALYSIS_DATE=$(date +%Y-%m-%d)" &

gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "ANALYSIS_DATE=$(date +%Y-%m-%d)" &

wait  # Wait for both to complete
```

---

#### Step 3: Verify P1 + P2 Complete

```bash
# Check which processors completed
bq query --use_legacy_sql=false "
SELECT
  'team_defense' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as completed_at
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_shot_zone', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()
"
```

**Expected:**
- team_defense: 20-30 rows
- player_shot_zone: 400-500 rows

---

#### Step 4: Trigger Parallel Set 2 (P3 + P4)

```bash
# Trigger both in parallel (after P1 + P2 complete)
gcloud run jobs execute phase4-player-composite-factors \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)" &

gcloud run jobs execute phase4-player-daily-cache \
  --region us-central1 \
  --set-env-vars "CACHE_DATE=$(date +%Y-%m-%d)" &

wait  # Wait for both to complete
```

---

#### Step 5: Verify P3 + P4 Complete

```bash
# Check completion
bq query --use_legacy_sql=false "
SELECT
  'player_composite' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as completed_at
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT 'player_daily_cache', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = CURRENT_DATE()
"
```

**Expected:**
- player_composite: 100-450 rows
- player_daily_cache: 100-300 rows

---

#### Step 6: Trigger P5 (ML Feature Store)

```bash
# Trigger P5 (after ALL 4 complete)
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

---

#### Step 7: Verify Final Output

```bash
# Check ml_feature_store_v2
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_players,
  AVG(feature_quality_score) as avg_quality,
  SUM(CASE WHEN early_season_flag THEN 1 ELSE 0 END) as early_season_count
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date = CURRENT_DATE()
"
```

**Expected:**
- total_players >= 100
- avg_quality >= 70 (after week 3)

---

## Retry Strategy

### Processor-Level Retries

| Attribute | Value | Configuration |
|-----------|-------|---------------|
| **Max Retries** | 2 (3 total attempts) | `--max-retries 2` in Cloud Run job |
| **Backoff** | Exponential (5s, 10s, 20s) | Automatic |
| **Timeout** | Per-processor (see specs) | `--timeout` in Cloud Run job |

**Retry Criteria:**
- ✅ Transient errors (network timeouts, BigQuery rate limits)
- ✅ Dependency delays (source not yet available)
- ✅ Data quality issues (validation warnings, not errors)

**Don't Retry:**
- ❌ Missing critical dependencies (immediate fail with clear error)
- ❌ Configuration errors (missing environment variables)
- ❌ Auth errors (insufficient permissions)
- ❌ Schema errors (table not found)

---

### Pub/Sub Message Retries

| Attribute | Value | Configuration |
|-----------|-------|---------------|
| **Max Delivery Attempts** | 3 | `--max-delivery-attempts 3` in subscription |
| **Backoff** | Exponential (10s, 20s, 40s) | Automatic |
| **DLQ** | Move to dead letter queue after 3 failures | `--dead-letter-topic` in subscription |

**Manual Recovery from DLQ:**

```bash
# List messages in DLQ
gcloud pubsub subscriptions pull phase4-team-defense-dlq \
  --limit=10 \
  --format=json

# After fixing issue, republish message
gcloud pubsub topics publish phase4-start \
  --message '{"processor":"phase4_start","phase":"4","analysis_date":"'$(date +%Y-%m-%d)'"}'
```

---

## Alert Configuration

### Slack Alerts (Non-Critical)

**Trigger:**
- Processing time > threshold
- Low quality scores (<85)
- Graceful degradation used (fallback mode)

**Channel:** `#nba-props-alerts`

**Example:**
```
⚠️ Phase 4 Warning: player_shot_zone_analysis
Duration: 12 minutes (threshold: 15 min)
Rows: 420 players
Status: Success (slow)
Date: 2025-11-15
```

---

### PagerDuty Alerts (Critical)

**Trigger:**
- All retries exhausted
- No data for today
- P2 or P5 failure (blocks everything)
- Overall duration > 90 minutes
- Phase 3 incomplete (blocks all Phase 4)

**Escalation:** Immediate page to on-call

**Example:**
```
🚨 CRITICAL: Phase 4 Failure
Processor: player_shot_zone_analysis
Error: Missing dependency: nba_analytics.player_game_summary
Retries: 3/3 exhausted
Impact: Blocks P3, P4, P5 (ALL Phase 5 predictions)
Action Required: Investigate Phase 3 completion
Date: 2025-11-15 23:45 ET
```

---

### Alert Rules

| Rule | Severity | Action |
|------|----------|--------|
| P1 fails all retries | Medium | Slack (blocks P3 only) |
| P2 fails all retries | **Critical** | PagerDuty (blocks everything) |
| P3 fails all retries | High | Slack + Page if >1 hour |
| P4 fails all retries | Medium | Slack (P5 has fallback) |
| P5 fails all retries | **Critical** | PagerDuty (blocks Phase 5) |
| Any processor > 2x max duration | High | Slack |
| Overall duration > 60 min | High | Slack |
| Overall duration > 90 min | **Critical** | PagerDuty |
| 0 rows on game day | **Critical** | PagerDuty |
| Phase 3 incomplete | **Critical** | PagerDuty (blocks all Phase 4) |

---

## Early Season Considerations

### Timeline

**Week 1 (Days 1-7):**
- P1: ~10 teams have ≥15 games (33%)
- P2: ~50 players have ≥10 games (11%)
- P3: Uses defaults for ~90% of players
- P4: Skips ~80% of players (<5 games)
- P5: Creates placeholders for ~90% of players
- **Alert Adjustments:** Disable row count alerts, Enable early_season_flag monitoring

**Week 2 (Days 8-14):**
- P1: ~20 teams have ≥15 games (67%)
- P2: ~200 players have ≥10 games (44%)
- P3: Uses defaults for ~60% of players
- P4: Skips ~50% of players
- P5: Creates placeholders for ~60% of players
- **Alert Adjustments:** Lower row count thresholds by 50%, Monitor quality scores

**Week 3 (Days 15-21):**
- P1: ~28 teams have ≥15 games (93%)
- P2: ~380 players have ≥10 games (84%)
- P3: Uses defaults for ~30% of players
- P4: Skips ~20% of players
- P5: Creates placeholders for ~30% of players
- **Alert Adjustments:** Lower row count thresholds by 20%, Start enforcing quality thresholds

**Week 4+ (Day 22+):**
- P1: All 30 teams have ≥15 games (100%)
- P2: ~440 players have ≥10 games (98%)
- P3: Normal operations
- P4: Normal operations
- P5: Normal operations (quality scores 85-100)
- **Alert Adjustments:** Enable all normal thresholds

---

### Configuration Changes for Early Season

**Modify Alert Thresholds:**

```python
# Week 1-2: Lower row count requirements
P1_MIN_ROWS = 10  # Instead of 20
P2_MIN_ROWS = 50  # Instead of 400
P3_MIN_ROWS = 50  # Instead of 100
P4_MIN_ROWS = 20  # Instead of 100
P5_MIN_ROWS = 50  # Instead of 100
P5_MIN_QUALITY = 40  # Instead of 70

# Week 3: Partial thresholds
P1_MIN_ROWS = 20
P2_MIN_ROWS = 200
P3_MIN_ROWS = 80
P4_MIN_ROWS = 80
P5_MIN_ROWS = 80
P5_MIN_QUALITY = 50

# Week 4+: Normal thresholds
P1_MIN_ROWS = 20
P2_MIN_ROWS = 400
P3_MIN_ROWS = 100
P4_MIN_ROWS = 100
P5_MIN_ROWS = 100
P5_MIN_QUALITY = 70
```

**Don't Fail on Placeholders:**
- Processors should NOT fail when creating early season placeholders
- early_season_flag = TRUE is expected, not an error
- Alert only on 0 rows (actual failure), not low counts

---

## Related Documentation

**Operations:**
- `05-phase4-operations-guide.md` - Processor specifications and monitoring

**Scheduling:**
- `06-phase4-scheduling-strategy.md` - Dependency management and orchestration

**ML Feature Store:**
- `08-phase4-ml-feature-store-deepdive.md` - P5-specific troubleshooting and recovery

**Phase 3 Troubleshooting:**
- `04-phase3-troubleshooting.md` - Troubleshooting upstream Phase 3 issues

---

**Last Updated:** 2025-11-15 16:00 PST
**Status:** 🚧 Draft (awaiting deployment)
**Next Review:** After Phase 4 deployment
