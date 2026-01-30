# Data Recovery Strategy

**Created:** Session 39 (2026-01-30)
**Status:** Draft - Needs Review

---

## Problem Statement

The CatBoost V8 model collapsed from 77% to 34% hit rate because:
1. Play-by-play data had gaps (BigDataBall unavailable, NBAC incomplete)
2. System silently continued with corrupted data
3. No alerts triggered despite obvious data quality issues
4. No clear retry/recovery policy

This document defines a comprehensive strategy for handling missing scraped data.

---

## Data Source Hierarchy

Each data type has a fallback chain with quality tiers:

### Play-by-Play (for shot zones)
| Source | Quality | Coverage | Limitations |
|--------|---------|----------|-------------|
| BigDataBall | Gold (100) | ~94% | Requires Google Drive access |
| NBAC (NBA.com) | Silver (85) | ~99% | Missing shot_distance on some records |
| No Data | Bronze (0) | - | Set NULL, skip rate calculations |

### Box Scores (for basic stats)
| Source | Quality | Coverage | Limitations |
|--------|---------|----------|-------------|
| NBA.com Gamebook | Gold (100) | 100% | Primary source |
| BDL API | Silver (90) | ~97% | 3% player discrepancy |
| No Data | - | - | CRITICAL - block predictions |

---

## Failure Scenarios and Policies

### Scenario 1: BigDataBall Unavailable, NBAC Available

**Detection:** `bdb_pbp_monitor.py` detects missing BDB data
**Auto-Retry:** Yes, 3 attempts over 3.5 minutes
**Fallback:** Use NBAC with quality tier Silver (85)
**Validation:** Check zone data completeness (Session 39 fix)

**Policy:**
1. Fall back to NBAC automatically
2. Validate all three zones have data (paint, mid, three)
3. If validation fails, set rates = NULL (not corrupted values)
4. Log warning: "Using NBAC fallback - incomplete zone data"
5. Schedule retry at T+2h, T+6h for full BDB data

### Scenario 2: Both BDB and NBAC Unavailable

**Detection:** Both extraction attempts fail
**Auto-Retry:** Yes, schedule delayed retries
**Fallback:** No fallback - accept degraded quality
**Impact:** Shot zone features unavailable

**Policy:**
1. Set all shot zone fields = NULL in player_game_summary
2. Track gap in `nba_orchestration.data_gaps` table
3. Send WARNING alert to Slack
4. Schedule retries: T+30min, T+2h, T+6h, T+24h
5. If still missing after 24h:
   - Send CRITICAL alert
   - Mark game for manual review
   - Continue with degraded predictions (flag confidence = "low")

### Scenario 3: Data Arrives After Predictions Generated

**Detection:** Gap resolved after Phase 5 complete
**Auto-Retry:** No automatic re-prediction
**Impact:** Predictions remain with degraded quality

**Policy:**
1. Log: "Late data arrival - predictions already generated"
2. Update gap status to "resolved_late"
3. Do NOT automatically regenerate predictions (could confuse users)
4. For next day: system will have correct L10 data

**Exception:** For high-stakes games (playoffs), manual trigger to regenerate

### Scenario 4: Data Source Permanently Down

**Detection:** Multiple consecutive failures (>3 days)
**Auto-Retry:** Suspended after circuit breaker trips
**Impact:** Model degradation for affected features

**Policy:**
1. After 3 consecutive days of failures: CRITICAL alert
2. Circuit breaker: suspend retries for 7 days
3. Model behavior: use longer rolling windows (L20 instead of L10)
4. Manual intervention required to:
   - Investigate root cause
   - Potentially switch to alternative source
   - Trigger backfill when resolved

---

## Retry Policy Matrix

| Phase | Data Type | Initial Retry | Max Retries | Backoff | Final State |
|-------|-----------|---------------|-------------|---------|-------------|
| 2 | BDB PBP | Immediate | 3 | 30s, 60s, 120s | Fall to NBAC |
| 2 | NBAC PBP | Immediate | 3 | 10s, 30s, 60s | NULL + alert |
| 2 | Gamebook | Immediate | 5 | 30s, 60s, 120s, 300s, 600s | CRITICAL block |
| 3 | Analytics | On failure | 3 | 15min, 1h, 6h | Partial + alert |
| 4 | Precompute | On failure | 3 | 15min, 1h, 6h | NULL + degraded |
| 5 | Predictions | Self-heal | 1 | At T-15min | No prediction |

---

## Graceful Degradation Tiers

When data is incomplete, the system should degrade gracefully:

### Tier 1: Full Quality (Gold)
- All data sources available
- All features populated
- Confidence: HIGH
- Prediction: Generate normally

### Tier 2: Reduced Quality (Silver)
- Primary source unavailable, fallback used
- Most features populated, some degraded
- Confidence: MEDIUM
- Prediction: Generate with warning

### Tier 3: Limited Quality (Bronze)
- Both primary and fallback unavailable
- Critical features missing (shot zones)
- Confidence: LOW
- Prediction: Generate but flag as low confidence

### Tier 4: Unacceptable Quality (Block)
- Core data missing (box score, schedule)
- Cannot generate valid prediction
- Confidence: NONE
- Prediction: DO NOT GENERATE, alert operations

---

## Gap Tracking Schema

Use existing `nba_orchestration.data_gaps` table:

```sql
-- Insert on gap detection
INSERT INTO nba_orchestration.data_gaps
  (game_date, game_id, home_team, away_team, source,
   detected_at, severity, status, auto_retry_count)
VALUES
  ('2026-01-30', '0022600123', 'LAL', 'BOS', 'bigdataball_pbp',
   CURRENT_TIMESTAMP(), 'warning', 'open', 0);

-- Update on retry attempt
UPDATE nba_orchestration.data_gaps
SET auto_retry_count = auto_retry_count + 1,
    last_retry_at = CURRENT_TIMESTAMP(),
    next_retry_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
WHERE game_id = '0022600123' AND source = 'bigdataball_pbp';

-- Update on resolution
UPDATE nba_orchestration.data_gaps
SET status = 'resolved',
    resolved_at = CURRENT_TIMESTAMP(),
    resolution_type = 'auto_retry'
WHERE game_id = '0022600123' AND source = 'bigdataball_pbp';
```

---

## Alert Escalation

| Severity | Trigger | Action | Notification |
|----------|---------|--------|--------------|
| INFO | Fallback used | Log only | None |
| WARNING | Gap detected <6h | Schedule retry | Slack #data-ops |
| CRITICAL | Gap >24h or box score missing | Block/degrade | Slack + PagerDuty |
| EMERGENCY | Multiple games affected | Manual intervention | Phone call |

---

## Implementation Checklist

### Phase 1: Detection (Immediate)
- [x] BDB gap detection (`bdb_pbp_monitor.py`)
- [ ] NBAC gap detection
- [ ] Gamebook gap detection
- [ ] Odds API gap detection

### Phase 2: Validation (Session 39)
- [x] Zone completeness validation (shot_zone_analyzer.py)
- [x] Rate calculation validation (player_shot_zone_analysis_processor.py)
- [x] Daily validation check (validate_tonight_data.py)

### Phase 3: Recovery (Future)
- [ ] Automatic delayed retries at processor level
- [ ] Post-prediction reprocessing capability
- [ ] Manual backfill trigger via Slack command

### Phase 4: Alerting (Future)
- [ ] Slack integration for gap alerts
- [ ] Daily gap summary report
- [ ] Weekly data quality metrics

---

## Questions for Decision

1. **Should we regenerate predictions when late data arrives?**
   - Pro: Better accuracy
   - Con: Confusing for users who saw different predictions

2. **What's the acceptable degradation for regular season vs playoffs?**
   - Regular: Accept Silver quality?
   - Playoffs: Require Gold quality?

3. **How long should we retry before giving up?**
   - Current thinking: 24h for non-critical, 6h for critical

4. **Should missing shot zones block predictions entirely?**
   - Current: No - we use model without those features
   - Alternative: Yes - flag as low confidence

---

## Related Documents

- Session 38 Handoff: Investigation findings
- Session 39 Handoff: Fixes implemented
- `bin/monitoring/bdb_pbp_monitor.py`: BDB gap detection
- `shared/processors/patterns/fallback_source_mixin.py`: Fallback framework
