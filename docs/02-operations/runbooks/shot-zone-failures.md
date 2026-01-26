# Shot Zone Data Failure Runbook

**Created:** 2026-01-25
**Purpose:** Diagnose and remediate shot zone data failures
**Severity:** Medium (impacts prediction quality, not critical)

## Quick Reference

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| `shot_zones_source = None` | Both BigDataBall + NBAC failed | Check PBP scrapers |
| `shot_zones_source = 'nbac_play_by_play'` | BigDataBall failed, NBAC fallback | Normal - check BigDataBall health |
| `has_shot_zone_data = 0.0` in features | Shot zones NULL for player | Check player-game data quality |
| Shot zone completeness <70% | Widespread PBP scraper issues | Escalate + backfill |

---

## Overview

Shot zone data flows from play-by-play (PBP) scrapers through analytics to ML features. This runbook covers:

1. How to diagnose shot zone scraper failures
2. How to backfill missing shot zone data
3. Impact on predictions when data missing
4. Monitoring queries for completeness

---

## Data Flow

```
BigDataBall PBP Scraper (Primary)
  ↓
  └─> PlayerGameSummary analytics → ML Feature Store → Predictions
  ↓
NBAC PBP Scraper (Fallback)
  ↓
  └─> PlayerGameSummary analytics → ML Feature Store → Predictions
  ↓
NULL (if both fail)
  ↓
  └─> has_shot_zone_data=0.0 → Model handles missingness
```

---

## Diagnosis

### Step 1: Check Shot Zone Completeness

Query ML Feature Store for today's completeness:

```sql
SELECT
    COUNT(*) as total_players,
    COUNTIF(has_shot_zone_data = 1.0) as with_shot_zones,
    COUNTIF(has_shot_zone_data = 0.0) as missing_shot_zones,
    ROUND(100.0 * COUNTIF(has_shot_zone_data = 1.0) / COUNT(*), 1) as completeness_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
```

**Expected:** ≥80% completeness
**Alert if:** <70% completeness

### Step 2: Check Source Attribution

Identify which source is being used:

```sql
SELECT
    source_shot_zones_source,
    COUNT(*) as player_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE()
GROUP BY source_shot_zones_source
ORDER BY player_count DESC
```

**Expected:**
- `bigdataball_pbp`: 90-95%
- `nbac_play_by_play`: 5-10%
- `NULL`: <1%

**Alert if:**
- `NULL` >10%
- `nbac_play_by_play` >50% (BigDataBall likely down)

### Step 3: Check Raw PBP Data

**BigDataBall:**
```sql
SELECT
    COUNT(DISTINCT game_id) as games_with_pbp,
    COUNT(*) as total_events
FROM `nba_raw.bigdataball_play_by_play`
WHERE game_date = CURRENT_DATE()
    AND event_type = 'shot'
```

**Expected:** 14 games (typical game day), ~2,000 shot events

**NBAC:**
```sql
SELECT
    COUNT(DISTINCT game_id) as games_with_pbp,
    COUNT(*) as total_events
FROM `nba_raw.nbac_play_by_play`
WHERE game_date = CURRENT_DATE()
    AND event_type = 'fieldgoal'
```

**Expected:** 14 games, ~2,000 shot events

### Step 4: Check Scraper Logs

Look for PBP scraper failures in Cloud Logging:

```
resource.type="cloud_run_revision"
resource.labels.service_name=~"bigdataball|nbac"
severity>=ERROR
textPayload=~"play.by.play|pbp|shot"
```

Common errors:
- **Rate limiting:** `429 Too Many Requests`
- **Source unavailable:** `503 Service Unavailable`
- **Parse errors:** `Failed to parse shot events`

---

## Impact on Predictions

### When Shot Zones Missing

**What happens:**
1. Features 18-20 (paint%, mid-range%, three%) = NULL
2. Feature 33 (`has_shot_zone_data`) = 0.0
3. CatBoost model uses missingness signal to adjust prediction
4. Prediction quality slightly degraded but still usable

**MAE Impact:**
- With full shot zones: 3.40 MAE
- With NULL shot zones: ~3.55 MAE (+4% error)
- Still beats baseline (4.80 MAE)

**Recommendation:**
- Predictions still valid, include with lower confidence
- Add note in prediction metadata: `"shot_zone_data_unavailable": true`

---

## Remediation

### Backfill Missing Shot Zone Data

**When to backfill:**
- Completeness <70% for the day
- BigDataBall was down, now recovered
- NBAC fallback provided basic zones, but BigDataBall has superior data

**How to backfill:**

```bash
# 1. Re-run PlayerGameSummary processor with force flag
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
    --start-date 2026-01-25 \
    --end-date 2026-01-25 \
    --skip-downstream-trigger \
    --backfill-mode

# 2. Re-run ML Feature Store processor to update features
python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
    --start-date 2026-01-25 \
    --end-date 2026-01-25 \
    --skip-downstream-trigger \
    --backfill-mode

# 3. Verify completeness improved
bq query --use_legacy_sql=false '
SELECT COUNT(*), COUNTIF(has_shot_zone_data = 1.0) as with_zones
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = "2026-01-25"
'
```

**Note:** Re-running predictions requires manual trigger - predictions are immutable once generated.

---

## Monitoring

### Daily Checks

Add to morning validation script (`scripts/validate_tonight_data.py`):

```python
def check_shot_zone_completeness(game_date: str) -> ValidationResult:
    """Check shot zone data completeness."""
    query = f"""
    SELECT
        COUNT(*) as total_players,
        COUNTIF(has_shot_zone_data = 1.0) as has_zones,
        ROUND(100.0 * COUNTIF(has_shot_zone_data = 1.0) / COUNT(*), 1) as completeness_pct
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
    """

    result = bq_client.query(query).result()
    row = list(result)[0]

    passed = row.completeness_pct >= 80
    message = f"Shot zone completeness: {row.completeness_pct}%"

    return ValidationResult(
        check_name='shot_zone_completeness',
        passed=passed,
        message=message
    )
```

### Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Completeness | <80% | <70% |
| NULL rate | >10% | >20% |
| NBAC fallback rate | >30% | >60% |

### Dashboard Queries

**7-day shot zone trend:**
```sql
SELECT
    game_date,
    COUNT(*) as total_players,
    COUNTIF(has_shot_zone_data = 1.0) as with_zones,
    ROUND(100.0 * COUNTIF(has_shot_zone_data = 1.0) / COUNT(*), 1) as completeness_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

**Source distribution:**
```sql
SELECT
    source_shot_zones_source,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY source_shot_zones_source
```

---

## Escalation

### When to Escalate

- Shot zone completeness <50% for 2+ consecutive days
- BigDataBall scraper down >24 hours
- Both BigDataBall and NBAC failing
- Backfill doesn't improve completeness

### Who to Contact

1. **On-call engineer** (PagerDuty)
2. **Data team** (Slack #data-engineering)
3. **ML team** (Slack #ml-models) - if prediction quality impacted

### What to Include

- Completeness % for affected dates
- Error logs from scrapers
- Source distribution (BigDataBall vs NBAC vs NULL)
- Backfill attempts and results

---

## Common Scenarios

### Scenario 1: BigDataBall Rate Limited

**Symptoms:**
- NBAC fallback rate >50%
- BigDataBall scraper logs: `429 Too Many Requests`

**Fix:**
- Wait for rate limit reset (usually 1 hour)
- Backfill once rate limit lifted
- Consider request throttling in scraper

### Scenario 2: NBAC Schema Change

**Symptoms:**
- NBAC fallback rate 0% (should be 5-10%)
- NBAC scraper logs: Parse errors

**Fix:**
- Check NBAC PBP schema changes
- Update `shot_zone_analyzer.py` extraction logic
- Redeploy PlayerGameSummary processor

### Scenario 3: Both Sources Down

**Symptoms:**
- NULL rate >80%
- Both scrapers failing

**Fix:**
- Immediate escalation to on-call
- Check upstream NBA.com API status
- Consider manual data entry for critical games
- Predictions still usable with reduced confidence

---

## Related Documentation

- [ML Feature Catalog](../../05-ml/features/feature-catalog.md) - Feature definitions
- [Shot Zone Handling Improvements](../../09-handoff/IMPROVE-SHOT-ZONE-HANDLING.md) - Implementation details
- [Player Game Summary Processor](../../../data_processors/analytics/player_game_summary/)
- [Shot Zone Analyzer Source Code](../../../data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py)

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2026-01-25 | Initial runbook created | Claude Sonnet 4.5 |
