# Session 101 Continued - Handoff for Next Session

**Date:** 2026-02-03
**Time:** 7:50 PM UTC (11:50 AM PT)
**Model:** Claude Opus 4.5

---

## Session Summary

Investigated and fixed Pub/Sub reliability issues causing intermittent prediction delivery failures. Applied infrastructure fixes and discovered the "authentication errors" were actually from Cloud Monitoring Uptime Checks, not Pub/Sub.

---

## Fixes Applied This Session

| Fix | Status | Details |
|-----|--------|---------|
| **Worker minScale=1** | ✅ Applied | `gcloud run services update prediction-worker --min-instances=1` |
| **Pub/Sub retry policy** | ✅ Applied | 15 attempts (was 5), 10s-600s backoff |
| **Rate limiting** | ✅ Committed (Session 102) | 0.1s delay between messages |
| **Documentation** | ✅ Created | Project docs + handoff |

---

## Current System State

### Predictions

| Metric | Value |
|--------|-------|
| Feb 3 total predictions | 149 |
| With feature_quality_score | 47 |
| Unique players | 137 |
| Feature quality value | 87.59 (correct) |

### Services

| Service | Status | Notes |
|---------|--------|-------|
| prediction-worker | Healthy | Rev 00095-g9q, minScale=1 |
| prediction-coordinator | Healthy | Rate limiting deployed |
| Pub/Sub subscription | Updated | 15 retries, 10s-600s backoff |

### Feb 3 Games
- 10 games scheduled
- Games start evening ET (~7 PM ET / midnight UTC)

---

## Key Discoveries

### 1. "Not Authenticated" Errors Are NOT Pub/Sub

The 403 "not authenticated" errors in worker logs are from **Cloud Monitoring Uptime Checks** hitting `/health/deep` without auth tokens - NOT from Pub/Sub delivery.

**Evidence:**
```
User-Agent: GoogleStackdriverMonitoring-UptimeChecks
Path: /health/deep
Status: 403
```

Actual Pub/Sub `/predict` deliveries return 204 (success) or 429 (rate limited).

### 2. Feature Mismatch Root Cause (Resolved)

The Session 100 feature mismatch issue was a **deployment timing issue**:
- Predictions created Feb 2 at 23:12 UTC
- Worker fix deployed Feb 3 at 17:51 UTC
- New predictions have correct feature_quality_score = 87.59

---

## Remaining Tasks for Next Session

### P1: Monitor Feb 3 Hit Rates

After games complete (~11 PM PT / 7 AM UTC Feb 4):

```sql
-- Compare predictions with quality vs without
SELECT
  CASE WHEN p.feature_quality_score IS NOT NULL THEN 'Has Quality' ELSE 'No Quality' END as group,
  COUNT(*) as predictions,
  COUNTIF(a.prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(a.prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy a
  ON p.player_lookup = a.player_lookup
  AND p.game_date = a.game_date
  AND p.system_id = a.system_id
WHERE p.game_date = '2026-02-03' AND p.system_id = 'catboost_v9'
  AND a.recommendation IN ('OVER', 'UNDER')
GROUP BY 1
```

### P2: Fix Uptime Check Auth

Two uptime checks fail because they lack auth:
- `nba-prediction-worker-deep-health-prod` (2 configs)

**Options:**
1. Configure uptime check with service account auth
2. Change path from `/health/deep` to `/health`
3. Allow unauthenticated access to health endpoints

```bash
# List uptime checks
gcloud monitoring uptime list-configs --filter='displayName~prediction'
```

### P3: Verify Pub/Sub Reliability

After next prediction batch, verify:
1. No 403 errors on `/predict` endpoint
2. All predictions complete without DLQ
3. Rate limiting prevents burst overload

```bash
# Check for auth errors on /predict (should be 0)
gcloud logging read 'resource.labels.service_name="prediction-worker" AND httpRequest.requestUrl:"/predict" AND httpRequest.status=403' --limit=5 --freshness=1h
```

---

## Verification Commands

### Check Worker Status
```bash
gcloud run services describe prediction-worker --region=us-west2 \
  --format='value(spec.template.metadata.annotations.[autoscaling.knative.dev/minScale])'
# Should return: 1
```

### Check Retry Policy
```bash
gcloud pubsub subscriptions describe prediction-request-prod \
  --format='yaml(retryPolicy,deadLetterPolicy)'
# Should show: maxDeliveryAttempts: 15, minimumBackoff: 10s
```

### Check Predictions
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*), COUNTIF(feature_quality_score IS NOT NULL)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-03' AND system_id = 'catboost_v9'"
```

### Run Daily Validation
```bash
/validate-daily
```

---

## Files Changed This Session

| File | Change |
|------|--------|
| `predictions/coordinator/coordinator.py` | Rate limiting (committed Session 102) |
| `docs/08-projects/current/pubsub-reliability-fixes/README.md` | Created - fix documentation |
| `docs/08-projects/current/feature-mismatch-investigation/` | Resolution docs |
| `docs/09-handoff/2026-02-03-SESSION-101-HANDOFF.md` | Session handoff |

---

## Related Sessions

| Session | Focus | Outcome |
|---------|-------|---------|
| 97 | Cloud Function fixes | Fixed morning-deployment-check, analytics-quality-check |
| 100 | Feature mismatch investigation | Documented the issue |
| 101 (this) | Pub/Sub reliability | Applied 3 fixes |
| 102 | Edge filter fix | Restored missing predictions |

---

## Quick Start for Next Session

```bash
# 1. Check current state
/validate-daily

# 2. Check Feb 3 game status
bq query --use_legacy_sql=false "
SELECT game_status, COUNT(*) as games
FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-03'
GROUP BY 1"

# 3. If games complete, check hit rates
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN ABS(predicted_points - line_value) >= 3 THEN 'Edge 3+' ELSE 'Edge <3' END as tier,
  COUNT(*) as bets,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-03' AND system_id = 'catboost_v9'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1"
```

---

## Session 101 Part 2: Model Bias Investigation (Added ~2:30 PM PT)

### Critical Finding

CatBoost V9 has **systematic regression-to-mean bias**:
- Stars (25+ pts): under-predicted by **9.3 points**
- Bench (<5 pts): over-predicted by **5.6 points**

This explains:
- 78% UNDER skew (RED daily signal)
- Feb 2 high-edge picks going 0/7
- High-edge picks consistently losing on star players

### Full Investigation Document

**`docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`**

Contains:
- Bias analysis by player tier with queries
- Feb 2 failure breakdown
- Austin Reaves anomaly investigation
- Three fix options (recalibration, retrain, quantile regression)
- Validation queries to verify fixes

### Recommended Next Steps

1. **Review MODEL-BIAS-INVESTIGATION.md** for full context
2. **Decide on fix approach** (quick recalibration vs proper retrain)
3. **Implement fix** before Feb 4 predictions
4. **Monitor Feb 3 results** to confirm pattern

### Quick Validation Query

```sql
-- Check model bias by tier (should see -9 for stars)
SELECT
  CASE WHEN actual_points >= 25 THEN 'Stars' ELSE 'Other' END as tier,
  ROUND(AVG(predicted_points - actual_points), 1) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-20'
GROUP BY 1
```

---

## Session 101 Part 3: Validation & Uptime Fix (~12:30 PM PT)

### Daily Validation Results

**Date:** Feb 3, 2026 (Pre-Game Check)
**Time:** 12:23 PM PT

#### Infrastructure Status

| Check | Status | Details |
|-------|--------|---------|
| Deployment drift | ✅ OK | All 5 services up to date |
| Worker minScale | ✅ OK | minScale=1 |
| Pub/Sub retry policy | ✅ OK | 15 attempts, 10s-600s backoff |
| DLQ | ✅ OK | Only old test messages from Jan 28 |
| /predict errors | ✅ OK | No 403 errors on /predict endpoint |

#### Data Pipeline Status

| Phase | Status | Details |
|-------|--------|---------|
| Phase 3 (today) | ✅ OK | 1/5 expected (only upcoming_* runs pre-game) |
| Phase 4 | ✅ OK | 285 records in player_daily_cache |
| Phase 5 | ✅ OK | 155 predictions for 10 games |
| ML Features | ✅ OK | 339 feature records, avg quality 85.1 |

#### Prediction Quality

| Metric | Value | Status |
|--------|-------|--------|
| Daily Signal | 🔴 RED | UNDER_HEAVY (21.9% pct_over) |
| High-edge picks | 4 (9 total) | Low volume |
| Total predictions | 155 | Normal |

**Signal Warning:** Heavy UNDER skew detected. Historical data shows 54% hit rate vs 82% on balanced days.

#### Edge Filter Status

| Check | Result | Notes |
|-------|--------|-------|
| Low-edge predictions | 105 found | But these have PASS recommendation |
| PASS recommendations | 45 | Correct: low-edge → PASS |
| OVER/UNDER with edge<3 | 60 | ⚠️ These get recommendations despite low edge |

The edge filter is working for PASS recommendations, but OVER/UNDER are still recommended for some low-edge predictions. This may be by design.

#### Orphan Predictions Check

| Date | Players with Active | Orphan Superseded |
|------|---------------------|-------------------|
| 2026-02-03 | 154 | 1 (paulgeorge) |
| 2026-02-02 | 69 | 0 |
| 2026-01-31 | 209 | 0 |

**Note:** Paul George has one orphan superseded prediction (NO_PROP_LINE). Not critical.

### Uptime Check Fix

Created service account and granted invoker permissions:

```bash
# Service account created
gcloud iam service-accounts create uptime-checker --display-name="Uptime Check Service Account"

# Granted invoker permission
gcloud run services add-iam-policy-binding prediction-worker \
  --member="serviceAccount:uptime-checker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**Manual Step Required:** Update uptime checks in Cloud Console to use OIDC auth:
1. Go to Cloud Console > Monitoring > Uptime Checks
2. Edit `nba-prediction-worker-deep-health-prod`
3. Under "Authentication", select "Service Account Token"
4. Select `uptime-checker@nba-props-platform.iam.gserviceaccount.com`
5. Enter audience: `https://prediction-worker-f7p3g7f6ya-wl.a.run.app`

### Weekly Hit Rate Trend

| Week | Predictions | Hit Rate | Status |
|------|-------------|----------|--------|
| 2026-02-01 | 142 | 59.2% | ✅ OK |
| 2026-01-25 | 457 | 51.6% | 🟡 LOW |
| 2026-01-18 | 394 | 56.4% | ✅ OK |
| 2026-01-11 | 453 | 55.6% | ✅ OK |

### High-Edge Performance (Most Recent Week)

| Week | Tier | Bets | Hit Rate |
|------|------|------|----------|
| 2026-02-01 | High (5+) | 10 | 20.0% ⚠️ |
| 2026-02-01 | Medium (3-5) | 17 | 64.7% ✅ |
| 2026-01-25 | High (5+) | 26 | 65.4% ✅ |
| 2026-01-18 | High (5+) | 27 | 85.2% ✅ |

**Concern:** High-edge picks for week of Feb 1 showing 20% hit rate (only 10 bets, small sample).

---

**End of Session 101 Continued**
