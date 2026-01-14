# Processor Run History - Quick Reference
**Last Updated:** 2026-01-13 | **Period:** Last 30 days

---

## 🚨 Critical Issues (P0)

1. **Phase 5 (Predictions): 27% success rate**
   - Average duration: 123 HOURS (clearly broken)
   - Root cause: Processors stuck in "running" state for 4+ hours
   - Action: Implement 30-minute timeout with retry

2. **Phase 2 (Raw): 2.4% success rate**
   - 246,075 failures out of 254,317 runs
   - Root cause: Missing classification of "no data available" vs "scraper error"
   - Action: Add `failure_category` field to distinguish expected vs unexpected failures

3. **Stale Running Cleanup Masking Errors**
   - 35+ processors stuck >4 hours in last 7 days
   - Original errors are lost: `"original_errors": null`
   - Action: Implement 15-minute heartbeat + preserve original errors

---

## 📊 Phase Performance Summary

| Phase | Success Rate | Avg Duration | Status |
|-------|--------------|--------------|--------|
| Phase 2 (Raw) | 2.36% | 100 min | 🔴 Needs classification |
| Phase 3 (Analytics) | 42.04% | 84 min | 🟡 Below target (90%) |
| Phase 4 (Precompute) | 87.67% | 81 min | ✅ Healthy |
| Phase 5 (Predictions) | 27.27% | 123 hours | 🔴 **BROKEN** |

---

## 🔝 Top 10 Failing Processors

| Rank | Processor | Failure Rate | Total Runs | Category |
|------|-----------|--------------|------------|----------|
| 1 | BasketballRefRosterBatchProcessor | 99.91% | 9,772 | Complete failure |
| 2 | NbacGamebookProcessor | 99.77% | 54,683 | PDF unavailable |
| 3 | BdlStandingsProcessor | 98.00% | 1,898 | API failure |
| 4 | BasketballRefRosterProcessor | 97.69% | 147,538 | Scraper issues |
| 5 | NbacScheduleProcessor | 96.87% | 6,542 | Source unavailable |
| 6 | EspnTeamRosterProcessor | 94.57% | 4,624 | Scraper issues |
| 7 | BigDataBallPbpProcessor | 93.08% | 159 | API failure |
| 8 | OddsApiPropsProcessor | 91.53% | 26,816 | Rate limiting |
| 9 | TeamOffenseGameSummaryProcessor | 78.35% | 7,184 | Partition filter bug |
| 10 | BettingPropsProcessor | 23.60% | 161 | Expected (off-days) |

---

## ⏱️ Performance Outliers (High Variance)

| Processor | Avg | Std Dev | Max | CoV | Alert Threshold |
|-----------|-----|---------|-----|-----|-----------------|
| PredictionCoordinator | 43.6s | 99.0s | 607.9s | **2.27** | >250s |
| PlayerGameSummaryProcessor | 32.8s | 69.4s | 1188.6s | **2.11** | >90s |
| UpcomingTeamGameContextProcessor | 40.1s | 76.8s | 1075.3s | **1.92** | >100s |
| PlayerShotZoneAnalysisProcessor | 28.3s | 32.0s | 266.0s | **1.13** | >80s |
| BasketballRefRosterProcessor | 18.2s | 15.4s | 88.8s | **0.85** | >50s |

**CoV = Coefficient of Variation** (stddev/mean). Values >1 indicate high instability.

---

## 📉 Zero-Record Anomalies

| Processor | Total Runs | Zero-Record Rate | Status |
|-----------|------------|------------------|--------|
| UpcomingTeamGameContextProcessor | 190 | 100% | 🔴 Never produces data |
| UpcomingPlayerGameContextProcessor | 139 | 100% | 🔴 Never produces data |
| BdlStandingsProcessor | 38 | 100% | 🔴 Never produces data |
| BigDataBallPbpProcessor | 11 | 100% | 🔴 Never produces data |
| BdlBoxscoresProcessor | 56 | 98.21% | 🟡 Only 1 success |
| BdlActivePlayersProcessor | 43 | 97.67% | 🟡 Only 1 success |
| OddsGameLinesProcessor | 1,376 | 60.76% | ✅ Expected (off-days) |
| BettingPropsProcessor | 123 | 47.97% | ✅ Expected (off-days) |

**Action:** Investigate the 4 processors with 100% zero-record rate. Why are they running?

---

## 🕐 Time-Based Failure Clustering

**Peak Failure Windows:**

| Day | Hour (UTC) | Failures | Top Failing Processors |
|-----|------------|----------|------------------------|
| Monday | 2am | 8,751 | PlayerDailyCacheProcessor, OddsApiPropsProcessor, NbacGamebookProcessor |
| Monday | 3am | 8,186 | PlayerDailyCacheProcessor, MLFeatureStoreProcessor, PlayerCompositeFactorsProcessor |
| Monday | 1am | 6,884 | BasketballRefRosterProcessor, OddsApiPropsProcessor, BdlStandingsProcessor |
| Monday | 12am | 6,758 | OddsGameLinesProcessor, BettingPropsProcessor, NbacScheduleProcessor |
| Friday | 5am | 3,772 | TeamDefenseGameSummaryProcessor, PlayerGameSummaryProcessor |

**Pattern:** Monday midnight-3am UTC shows massive failure spike (30K+ failures in 4 hours)

**Hypothesis:**
- Weekend backfill jobs creating contention
- Retry storms after Friday/Saturday game processing
- Stale data not cleaned up properly

---

## 🔗 Dependency Failure Impact

| Processor | Dep Failures | Missing Dependencies |
|-----------|--------------|----------------------|
| PlayerGameSummaryProcessor | 118 | nbac_gamebook_player_stats, bdl_player_boxscores |
| TeamOffenseGameSummaryProcessor | 16 | (unspecified) |
| PlayerCompositeFactorsProcessor | 7 | upcoming_player_game_context |
| MLFeatureStoreProcessor | 7 | player_daily_cache |
| PlayerDailyCacheProcessor | 1 | player_game_summary |

**Total:** 156 runs failed due to missing dependencies (0.06% of total runs)

**Pattern:** Phase 2 failures cascade through Phase 3 → Phase 4 → Phase 5

---

## 🛠️ Recommended Alerts

### Performance Alerts (Slow Queries)
```yaml
PredictionCoordinator:
  warning: >250s (2x P95)
  timeout: >500s (4x P95)

PlayerGameSummaryProcessor:
  warning: >90s (2x P95)
  timeout: >180s (4x P95)

UpcomingTeamGameContextProcessor:
  warning: >100s (2x P95)
  timeout: >200s (4x P95)
```

### Data Completeness Alerts
```yaml
PlayerGameSummaryProcessor:
  alert_if: records_created == 0
  reason: Should never produce zero records

PlayerCompositeFactorsProcessor:
  alert_if: zero_record_rate_24h > 10%
  reason: Expected <4% zero-record rate

MLFeatureStoreProcessor:
  alert_if: zero_record_rate_24h > 10%
  reason: Expected <4% zero-record rate
```

### Dependency Alerts
```yaml
alert_if:
  - same_missing_dependency_count > 5
  - cascade_depth > 2 (Phase 2 → Phase 3 → Phase 4)

example: |
  "5 processors blocked by missing nba_raw.nbac_gamebook_player_stats"
```

### Stuck Processor Alerts
```yaml
alert_if:
  - status == 'running' AND duration > 15 minutes

action:
  - send_warning_at: 15 min
  - kill_and_retry_at: 30 min
  - escalate_at: 60 min
```

---

## 📈 Day-of-Week Patterns (Expected)

### Record Count by Day
| Processor | Mon | Tue | Wed | Thu | Fri | Sat | Sun | Pattern |
|-----------|-----|-----|-----|-----|-----|-----|-----|---------|
| OddsApiPropsProcessor | 26 | 19 | 26 | 26 | 28 | 27 | 26 | Tue dip (cleanup?) |
| BdlLiveBoxscoresProcessor | 182 | 324 | 223 | 160 | 397 | 103 | 320 | Fri/Tue peaks (games) |
| PlayerCompositeFactorsProcessor | 151 | 181 | 193 | 196 | - | 158 | 96 | Thu peak, Sun drop |
| NbacScheduleProcessor | 1231 | 1231 | 1231 | 1231 | 1231 | 1231 | 1231 | Always 1,231 |

**Insight:** Use these baselines for anomaly detection. Example:
- If BdlLiveBoxscoresProcessor creates <100 records on Friday → Alert
- If OddsApiPropsProcessor creates <15 records on Monday → Alert

---

## 🎯 Top 3 Recommendations

### 1. Fix Phase 5 Timeout (P0)
**Current:** 4-hour timeout → cleanup marks as failed
**Proposed:**
- 15-min heartbeat check
- 30-min timeout with retry
- Preserve original error message

**Impact:** Reduce Phase 5 duration from 123 hours to <10 minutes average

### 2. Classify Phase 2 Failures (P0)
**Add field:** `failure_category`
- `no_data_available` (expected, don't alert)
- `scraper_error` (unexpected, alert)
- `rate_limit` (expected, retry)
- `source_unavailable` (downstream issue, alert)

**Impact:** Reduce alert noise by 90%+ (most Phase 2 failures are expected)

### 3. Implement P95-Based Timeouts (P1)
**Current:** Fixed 4-hour timeout for all processors
**Proposed:** Dynamic timeout per processor
- Warning at 2x P95
- Kill + retry at 4x P95
- Escalate at 6x P95

**Impact:** Catch stuck processors in 15-30 minutes instead of 4 hours

---

## 📝 Implementation Checklist

### Week 1: Critical Fixes
- [ ] Implement 15-minute heartbeat for stuck processor detection
- [ ] Add `failure_category` field to processor_run_history
- [ ] Set Phase 5 timeout to 30 minutes (from 4 hours)
- [ ] Preserve original errors in stale_running_cleanup
- [ ] Basic CloudWatch alert: processors stuck >15 minutes

### Week 2-3: Enhanced Monitoring
- [ ] Backfill `failure_category` for top 10 failing processors
- [ ] Implement P95-based timeout alerts (2x P95 = warning)
- [ ] Create anomaly detection for record counts (>3 stddev)
- [ ] Set up dependency cascade alerts (>5 processors blocked)
- [ ] Daily summary Slack bot

### Week 4: Dashboard & Automation
- [ ] Build Grafana dashboard with 5 key panels
- [ ] Implement ML-based anomaly detection for record counts
- [ ] Add retry tracking (`retry_attempt` field population)
- [ ] Create dependency DAG visualization
- [ ] Load test: simulate Monday 2am peak to identify bottlenecks

---

## 🔍 Quick Investigation Queries

**Find stuck processors:**
```sql
SELECT * FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 15;
```

**Find recent anomalies:**
```sql
WITH stats AS (
  SELECT processor_name, AVG(records_created) as avg, STDDEV(records_created) as stddev
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) AND records_created > 0
  GROUP BY processor_name
)
SELECT h.processor_name, h.records_created, s.avg,
       ABS(h.records_created - s.avg) / s.stddev as z_score
FROM `nba-props-platform.nba_reference.processor_run_history` h
JOIN stats s ON h.processor_name = s.processor_name
WHERE h.started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
  AND ABS(h.records_created - s.avg) > 3 * s.stddev;
```

**Check dependency cascade:**
```sql
SELECT processor_name, dependency_check_passed,
       JSON_VALUE(missing_dependencies, '$[0]') as missing_dep
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND dependency_check_passed = false;
```

---

**For full analysis:** See `/home/naji/code/nba-stats-scraper/docs/analysis/processor_run_history_quality_analysis.md`
