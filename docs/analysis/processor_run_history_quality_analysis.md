# Processor Run History - Data Quality Analysis
**Analysis Period:** Last 30 days (2025-12-14 to 2026-01-13)
**Total Runs Analyzed:** 269,971 runs
**Project:** nba-props-platform
**Dataset:** nba_reference
**Table:** processor_run_history

---

## Executive Summary

### Critical Findings
1. **Phase 2 (Raw Data) has 97.64% failure rate** - 246,075 failures out of 254,317 runs
2. **Basketball Reference scrapers are primary failure source** - 144,126 failures (BasketballRefRosterProcessor alone)
3. **Stale running cleanup is masking real errors** - Many processors stuck in "running" state for 4+ hours
4. **Dependency cascades create false negatives** - 156 runs failed due to missing upstream dependencies
5. **Zero-record patterns suggest monitoring opportunities** - Several processors have 60-100% zero-record rates

---

## 1. Failure Pattern Analysis

### 1.1 Highest Failure Processors (Last 30 Days)

| Processor | Total Runs | Failures | Successes | Failure Rate | Common Pattern |
|-----------|------------|----------|-----------|--------------|----------------|
| BasketballRefRosterProcessor | 147,538 | 144,126 | 1,207 | 97.69% | Scraper failures |
| NbacGamebookProcessor | 54,683 | 54,559 | 124 | 99.77% | PDF availability |
| OddsApiPropsProcessor | 26,816 | 24,544 | 2,266 | 91.53% | API rate limits |
| BasketballRefRosterBatchProcessor | 9,772 | 9,763 | 0 | 99.91% | Complete failure |
| NbacScheduleProcessor | 6,542 | 6,337 | 205 | 96.87% | Source unavailable |
| TeamOffenseGameSummaryProcessor | 7,184 | 5,629 | 1,520 | 78.35% | Partition filter issues |
| EspnTeamRosterProcessor | 4,624 | 4,373 | 251 | 94.57% | Scraper failures |
| BdlStandingsProcessor | 1,898 | 1,860 | 38 | 98.00% | API failures |

**Key Insight:** Phase 2 raw data scrapers dominate failures. These are expected failures (e.g., no games on certain days), but the sheer volume suggests we need better handling of "no data available" vs actual errors.

### 1.2 Time-Based Failure Clustering

**Peak Failure Hours (Top 5):**
1. **Monday 2am UTC** - 8,751 failures (PlayerDailyCacheProcessor, OddsApiPropsProcessor, NbacGamebookProcessor)
2. **Monday 3am UTC** - 8,186 failures (PlayerDailyCacheProcessor, MLFeatureStoreProcessor, PlayerCompositeFactorsProcessor)
3. **Monday 1am UTC** - 6,884 failures (BasketballRefRosterProcessor, OddsApiPropsProcessor, BdlStandingsProcessor)
4. **Monday 12am UTC** - 6,758 failures (OddsGameLinesProcessor, BettingPropsProcessor, NbacScheduleProcessor)
5. **Friday 5am UTC** - 3,772 failures (TeamDefenseGameSummaryProcessor, PlayerGameSummaryProcessor, TeamOffenseGameSummaryProcessor)

**Pattern Analysis:**
- **Monday midnight-3am UTC**: Massive cleanup/retry spike suggests weekend data processing backlog
- **Friday 5am UTC**: Game-day processing failures when games occur Thursday night
- **Day of week matters**: Friday (day_of_week=5) shows clustering around game processing

**Actionable Insight:** Monday early morning failures suggest either:
1. Weekend backfill jobs creating contention
2. Stale data from Friday/Saturday not being cleaned up
3. Retry storms after timeout failures

### 1.3 Common Error Messages

**Recent Error Patterns (Last 7 Days):**

| Error Type | Count | Processors Affected | Pattern |
|------------|-------|---------------------|---------|
| Stale running cleanup | 35+ | All phases | Processors stuck >4 hours in "running" state |
| Partition filter missing | 2 | TeamOffenseGameSummaryProcessor | "Cannot query without partition filter" |
| Missing critical dependencies | 5+ | PlayerGameSummaryProcessor | Missing nbac_gamebook_player_stats, bdl_player_boxscores |
| No data extracted | 10+ | PlayerCompositeFactorsProcessor, PlayerDailyCacheProcessor, MLFeatureStoreProcessor | Legitimate "no upcoming games" scenarios |
| Schema mismatch | 1 | TeamDefenseGameSummaryProcessor | "Name team_abbr not found" |

**Critical Discovery:** The "stale_running_cleanup" errors indicate processors are getting stuck and timing out. This happens when:
- Processor starts, makes some progress, then hangs
- After 4 hours, cleanup job marks it as failed
- Original error is lost (see `"original_errors": null`)

**Recommendation:** Implement heartbeat mechanism to detect stuck processors earlier (e.g., 15-30 minutes instead of 4 hours).

---

## 2. Processing Time Analysis

### 2.1 Slowest Processors (Average Duration)

| Processor | Runs | Avg Duration | Std Dev | Min | Max | P95 | Coefficient of Variation |
|-----------|------|--------------|---------|-----|-----|-----|--------------------------|
| UpcomingPlayerGameContextProcessor | 139 | 64.21s | 40.10s | 16.17s | 235.53s | 147.36s | 0.62 |
| PlayerDailyCacheProcessor | 902 | 51.72s | 18.55s | 2.26s | 215.51s | 77.81s | 0.36 |
| PredictionCoordinator | 36 | 43.56s | 98.97s | - | 607.98s | 124.92s | **2.27** |
| MLFeatureStoreProcessor | 1,011 | 42.45s | 15.83s | 12.74s | 353.09s | 60.70s | 0.37 |
| UpcomingTeamGameContextProcessor | 190 | 40.05s | 76.81s | 14.42s | 1075.28s | 45.86s | **1.92** |
| PlayerCompositeFactorsProcessor | 903 | 33.59s | 10.64s | 2.21s | 158.20s | 44.04s | 0.32 |
| PlayerGameSummaryProcessor | 2,675 | 32.80s | 69.35s | 11.08s | 1188.64s | 41.95s | **2.11** |
| PlayerShotZoneAnalysisProcessor | 543 | 28.27s | 31.95s | 2.31s | 266.02s | 39.90s | **1.13** |

### 2.2 High Variance Processors (Performance Outliers)

**Top 5 by Coefficient of Variation:**

1. **PredictionCoordinator** (CoV = 2.27)
   - Avg: 43.56s, Std Dev: 98.97s, Max: 607.98s
   - **Issue:** 10x+ variance suggests prediction complexity varies wildly by game day
   - **Alert Threshold:** >120s (2x P95)

2. **PlayerGameSummaryProcessor** (CoV = 2.11)
   - Avg: 32.80s, Std Dev: 69.35s, Max: 1188.64s (19+ minutes!)
   - **Issue:** Outlier runs taking 20-40x average time
   - **Alert Threshold:** >90s (2x P95)

3. **UpcomingTeamGameContextProcessor** (CoV = 1.92)
   - Avg: 40.05s, Std Dev: 76.81s, Max: 1075.28s (17+ minutes!)
   - **Issue:** Extreme outliers suggest query timeouts or large game slates
   - **Alert Threshold:** >100s (2x P95)

4. **PlayerShotZoneAnalysisProcessor** (CoV = 1.13)
   - Avg: 28.27s, Std Dev: 31.95s, Max: 266.02s
   - **Issue:** Variable player count per game day
   - **Alert Threshold:** >80s (2x P95)

**Actionable Insight:** These processors need:
1. Query optimization for large data days
2. Timeout alerts at 2x P95 instead of waiting 4 hours
3. Investigation of max duration outliers

---

## 3. Data Completeness Patterns

### 3.1 Expected Record Counts by Processor

| Processor | Runs | Avg Records | Std Dev | Median | Zero-Record Rate | Pattern |
|-----------|------|-------------|---------|--------|------------------|---------|
| BettingPropsProcessor | 123 | 1,638.72 | 1,866.18 | 818 | 47.97% | High on game days, zero on off-days |
| NbacScheduleProcessor | 205 | 780.63 | 594.39 | 1231 | 36.59% | 1,231 when runs, 0 otherwise |
| PlayerShotZoneAnalysisProcessor | 543 | 344.09 | 168.88 | 414 | 13.26% | 400+ players on game days |
| BdlLiveBoxscoresProcessor | 209 | 178.20 | 147.58 | 210 | 29.19% | Varies by game count |
| PlayerGameSummaryProcessor | 2,675 | 159.91 | 281.59 | 139 | 0.00% | Always produces data |
| PlayerCompositeFactorsProcessor | 903 | 150.98 | 119.12 | 125 | 3.77% | Stable player count |
| MLFeatureStoreProcessor | 1,011 | 147.09 | 250.91 | 137 | 3.56% | Stable prediction targets |
| PlayerDailyCacheProcessor | 902 | 116.37 | 82.07 | 112 | 4.43% | Stable player cache |

### 3.2 Anomaly Detection Candidates

**Processors with Suspicious Zero-Record Patterns:**

| Processor | Total Runs | Zero Records | Zero Rate | Avg When Non-Zero | Recommendation |
|-----------|------------|--------------|-----------|-------------------|----------------|
| UpcomingTeamGameContextProcessor | 190 | 190 | 100.00% | - | Investigate: Never produces data |
| UpcomingPlayerGameContextProcessor | 139 | 139 | 100.00% | - | Investigate: Never produces data |
| BdlStandingsProcessor | 38 | 38 | 100.00% | - | Investigate: Never produces data |
| BigDataBallPbpProcessor | 11 | 11 | 100.00% | - | Investigate: Never produces data |
| BdlBoxscoresProcessor | 56 | 55 | 98.21% | 140 (1 run) | Alert: Only 1 successful run |
| BdlActivePlayersProcessor | 43 | 42 | 97.67% | 523 (1 run) | Alert: Only 1 successful run |
| OddsGameLinesProcessor | 1,376 | 836 | 60.76% | 8 | Expected: 8 lines when available |
| BettingPropsProcessor | 123 | 59 | 47.97% | 3,149.41 | Expected: Game day variance |

**Critical Issues:**
1. **4 processors NEVER produce data** (100% zero-record rate) - Are these disabled? Why are they running?
2. **BdlBoxscoresProcessor/BdlActivePlayersProcessor** - Only 1 successful run suggests API/access issues
3. **OddsGameLinesProcessor** - 60.76% zero-rate expected (no lines on off-days) but should be monitored

### 3.3 Day-of-Week Patterns

**Notable Patterns:**

1. **OddsApiPropsProcessor:**
   - Monday: 26.38 records (906 runs)
   - Tuesday: 18.50 records (557 runs) - **30% drop suggests Monday cleanup**
   - Wed-Sun: 25-28 records

2. **BdlLiveBoxscoresProcessor:**
   - Friday: 396.55 records (11 runs) - **Peak game day**
   - Sunday: 320.34 records (41 runs)
   - Monday: 181.82 records (17 runs)
   - Saturday: 102.77 records (22 runs) - **Off-day pattern**

3. **PlayerCompositeFactorsProcessor:**
   - Thursday: 196.12 records (186 runs) - **Peak processing day**
   - Wednesday: 192.55 records (255 runs)
   - Sunday: 96.26 records (213 runs) - **50% drop**

**Insight:** These patterns are expected (games cluster on certain days), but deviations can signal:
- Missing game data
- Scraper failures during peak times
- Downstream dependency issues

---

## 4. Dependency Failure Analysis

### 4.1 Dependency Check Failures

| Processor | Total Runs | Failures | Missing Dependencies |
|-----------|------------|----------|----------------------|
| PlayerGameSummaryProcessor | 118 | 118 | nbac_gamebook_player_stats, bdl_player_boxscores |
| TeamOffenseGameSummaryProcessor | 16 | 16 | (not specified) |
| PlayerCompositeFactorsProcessor | 7 | 7 | upcoming_player_game_context |
| MLFeatureStoreProcessor | 7 | 7 | player_daily_cache |
| UpcomingTeamGameContextProcessor | 4 | 4 | (not specified) |
| TeamDefenseGameSummaryProcessor | 2 | 2 | (not specified) |
| PlayerDailyCacheProcessor | 1 | 1 | player_game_summary |
| UpcomingPlayerGameContextProcessor | 1 | 1 | (not specified) |

**Total Impact:** 156 runs failed due to missing dependencies (0.06% of total runs)

**Key Insight:**
- Dependency failures are rare but cascade through phases
- PlayerGameSummaryProcessor is most affected (118 failures)
- Missing raw data (Phase 2) cascades to analytics (Phase 3) and precompute (Phase 4)

**Recommendation:** Implement dependency DAG visualization to show:
- Which processors are blocked
- Expected data availability time
- Critical path for predictions

---

## 5. Phase-Level Analysis

### 5.1 Success Rates by Phase

| Phase | Total Runs | Successes | Failures | Success Rate | Avg Duration | Avg Records |
|-------|------------|-----------|----------|--------------|--------------|-------------|
| phase_2_raw | 254,317 | 6,013 | 246,075 | **2.36%** | 6,006s | 3.02 |
| phase_3 (analytics) | 10,660 | 4,481 | 6,110 | **42.04%** | 5,040s | 58.78 |
| phase_4_precompute | 4,454 | 3,905 | 495 | **87.67%** | 4,848s | 141.54 |
| phase_3_analytics | 408 | 329 | 61 | **80.64%** | 21,675s | 0.0 |
| phase_5_predictions | 132 | 36 | 34 | **27.27%** | 446,153s | - |

**Critical Findings:**

1. **Phase 2 (Raw Data): 2.36% success rate**
   - This is NOT necessarily bad - most failures are "no data available today"
   - But we need better classification: `no_data_available` vs `scraper_error`
   - Average duration of 6,006s (100 minutes) is concerning for failed runs

2. **Phase 3 (Analytics): 42.04% success rate**
   - Dependency cascades from Phase 2 failures
   - Should be >90% when Phase 2 data is available
   - Need to investigate why 58% fail even when dependencies pass

3. **Phase 4 (Precompute): 87.67% success rate - GOOD**
   - Best performing phase
   - Low variance in duration (4,848s)
   - Clear success criteria

4. **Phase 5 (Predictions): 27.27% success rate - CRITICAL**
   - 446,153s average duration = **123 hours** = **5+ days**
   - This is clearly broken
   - Likely stale/stuck runs being cleaned up

---

## 6. Actionable Monitoring & Alerting Recommendations

### 6.1 Immediate Actions (P0)

1. **Fix Phase 5 (Predictions) timeout handling**
   - Current: 4 hour timeout before cleanup
   - Recommend: 30-minute timeout with retry
   - Alert on any run >60 minutes

2. **Classify Phase 2 failures properly**
   - Add field: `failure_reason` with values:
     - `no_data_available` (expected)
     - `scraper_error` (unexpected)
     - `rate_limit` (retry)
     - `source_unavailable` (downstream issue)
   - Only alert on `scraper_error`

3. **Fix "stale running cleanup" masking errors**
   - Implement 15-minute heartbeat check
   - Log last activity before timeout
   - Preserve original error in cleanup

### 6.2 Performance Alerts (P1)

**Slow Query Alerts:**
| Processor | P95 Baseline | Alert Threshold (2x P95) | Timeout (4x P95) |
|-----------|--------------|---------------------------|------------------|
| PredictionCoordinator | 124.92s | 250s | 500s |
| UpcomingPlayerGameContextProcessor | 147.36s | 300s | 600s |
| PlayerGameSummaryProcessor | 41.95s | 90s | 180s |
| PlayerDailyCacheProcessor | 77.81s | 160s | 320s |
| MLFeatureStoreProcessor | 60.70s | 120s | 240s |
| UpcomingTeamGameContextProcessor | 45.86s | 100s | 200s |

**Alert Logic:**
```python
if duration_seconds > 2 * p95_baseline:
    send_warning_alert()
if duration_seconds > 4 * p95_baseline:
    kill_and_retry()
```

### 6.3 Data Completeness Alerts (P1)

**Zero-Record Alerts:**
| Processor | Expected Non-Zero Rate | Alert Condition |
|-----------|------------------------|-----------------|
| PlayerGameSummaryProcessor | 100% | Any zero-record run |
| PlayerCompositeFactorsProcessor | 96.23% | >10% zero-record rate in 24h window |
| MLFeatureStoreProcessor | 96.44% | >10% zero-record rate in 24h window |
| PlayerDailyCacheProcessor | 95.57% | >10% zero-record rate in 24h window |
| UpcomingPlayerGameContextProcessor | 0% (always zero) | If ever produces records (logic changed?) |

**Record Count Anomaly Detection:**
```python
# For processors with stable record counts
if abs(records_created - median_records) > 3 * stddev:
    send_alert(f"Anomalous record count: {records_created} (expected {median_records} ± {3*stddev})")
```

### 6.4 Dependency Chain Alerts (P1)

**Missing Dependency Alerts:**
- Alert when >5 processors in same phase fail with same missing dependency
- Track cascade depth: if Phase 3 fails → alert on expected Phase 4 failures
- Daily summary: "X processors blocked by missing Y table"

**Example Alert:**
```
DEPENDENCY FAILURE: PlayerGameSummaryProcessor
├─ Missing: nba_raw.nbac_gamebook_player_stats (last updated: 2026-01-12)
├─ Missing: nba_raw.bdl_player_boxscores (last updated: 2026-01-12)
├─ Downstream blocked: PlayerDailyCacheProcessor, PlayerCompositeFactorsProcessor
└─ Expected resolution: When NbacGamebookProcessor succeeds
```

### 6.5 Time-Based Pattern Alerts (P2)

**Cluster Alerts:**
- Alert if >100 failures in same hour (vs 7-day baseline)
- Alert on Monday 12am-3am UTC if failures >2x average
- Alert on Friday 5am UTC (game day) if >50 failures

### 6.6 Retry Pattern Analysis (P2)

**No retry data found** in the last 30 days, suggesting:
1. Retries not implemented
2. Retries not tracked (likely)
3. Retry field not populated

**Recommendation:** Implement retry tracking to understand:
- Which processors benefit from retry
- Optimal retry delay (immediate vs exponential backoff)
- Success rate by retry attempt

---

## 7. Monitoring Dashboard Recommendations

### 7.1 Real-Time Dashboard (CloudWatch/Grafana)

**Panel 1: Phase Health Overview**
```
phase_2_raw:     [████████░░] 42% success (last hour)
phase_3:         [██████████] 87% success
phase_4:         [██████████] 95% success
phase_5:         [█████░░░░░] 27% success ⚠️
```

**Panel 2: Top 10 Failing Processors (Last Hour)**
- Bar chart: Failure count by processor
- Color: Red if >90% failure rate, Yellow if >50%, Green if <10%

**Panel 3: Processing Time P95 (Last 24h)**
- Line chart: P95 duration by processor
- Reference line: Alert threshold (2x baseline P95)

**Panel 4: Record Count Anomalies (Last 24h)**
- Scatter plot: Actual vs Expected record counts
- Highlight points >3 std deviations from mean

**Panel 5: Dependency Chain Status**
- Tree map: Processors color-coded by status
  - Green: Running on schedule
  - Yellow: Delayed but no failures
  - Red: Failed or blocked by dependencies

### 7.2 Daily Summary Report (Email/Slack)

**Subject: NBA Data Pipeline - Daily Health Report (2026-01-13)**

```
Overall Health: 🟡 DEGRADED
─────────────────────────────────────────
Phase Success Rates:
  Phase 2 (Raw):        2.4% (expected <10% on off-days)
  Phase 3 (Analytics):  42.0% ⚠️ (target: >90%)
  Phase 4 (Precompute): 87.7% ✓ (target: >85%)
  Phase 5 (Predictions): 27.3% 🔴 (target: >95%)

Top Issues:
  1. BasketballRefRosterProcessor: 97.7% failure rate (5,342 runs)
  2. Phase 5 stuck processors: 34 runs >4 hours
  3. PlayerGameSummaryProcessor: 118 dependency failures

Anomalies Detected:
  - PlayerDailyCacheProcessor: Zero records on 40 runs (expected <5%)
  - PredictionCoordinator: Max duration 607s (5x average)

Action Required:
  ⚠️ Investigate Phase 5 timeout issues (P0)
  ⚠️ Review Basketball Reference scraper quota (P1)
  ℹ️  Backfill nbac_gamebook_player_stats for 2026-01-12 (P2)
```

---

## 8. Technical Implementation Notes

### 8.1 Schema Enhancements

**Add to `processor_run_history` table:**

```sql
-- New fields for better classification
ALTER TABLE nba_reference.processor_run_history ADD COLUMN IF NOT EXISTS
  failure_category STRING OPTIONS(description="no_data_available, scraper_error, rate_limit, dependency_failure, timeout, unknown");

ALTER TABLE nba_reference.processor_run_history ADD COLUMN IF NOT EXISTS
  expected_record_count_min INT64 OPTIONS(description="Minimum expected records (for anomaly detection)");

ALTER TABLE nba_reference.processor_run_history ADD COLUMN IF NOT EXISTS
  expected_record_count_max INT64 OPTIONS(description="Maximum expected records (for anomaly detection)");

ALTER TABLE nba_reference.processor_run_history ADD COLUMN IF NOT EXISTS
  heartbeat_last_activity TIMESTAMP OPTIONS(description="Last activity timestamp before failure");

ALTER TABLE nba_reference.processor_run_history ADD COLUMN IF NOT EXISTS
  killed_by_timeout BOOLEAN OPTIONS(description="Was this run killed by timeout?");
```

### 8.2 Query Examples for Alerts

**Alert: Processors stuck >15 minutes**
```sql
SELECT processor_name, run_id, started_at,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 15
ORDER BY minutes_running DESC;
```

**Alert: Anomalous record counts**
```sql
WITH stats AS (
  SELECT processor_name,
         AVG(records_created) as avg_records,
         STDDEV(records_created) as stddev_records
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'success'
    AND records_created > 0
  GROUP BY processor_name
)
SELECT h.processor_name, h.run_id, h.records_created,
       s.avg_records, s.stddev_records,
       ABS(h.records_created - s.avg_records) / NULLIF(s.stddev_records, 0) as z_score
FROM `nba-props-platform.nba_reference.processor_run_history` h
JOIN stats s ON h.processor_name = s.processor_name
WHERE h.started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
  AND h.status = 'success'
  AND ABS(h.records_created - s.avg_records) > 3 * s.stddev_records
ORDER BY z_score DESC;
```

**Alert: Dependency cascade detection**
```sql
SELECT
  parent_processor,
  COUNT(DISTINCT processor_name) as blocked_processors,
  ARRAY_AGG(DISTINCT processor_name LIMIT 10) as blocked_list
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND dependency_check_passed = false
GROUP BY parent_processor
HAVING COUNT(DISTINCT processor_name) > 3
ORDER BY blocked_processors DESC;
```

---

## 9. Next Steps

### Phase 1: Immediate (This Week)
1. ✅ Complete this analysis
2. Implement Phase 5 timeout fix (P0)
3. Add `failure_category` classification to top 5 failing processors
4. Set up basic CloudWatch alerts for:
   - Processors stuck >15 minutes
   - Phase success rate <50%

### Phase 2: Short-term (Next 2 Weeks)
1. Implement heartbeat mechanism for stuck processor detection
2. Create anomaly detection alerts for record counts
3. Build dependency chain visualization
4. Backfill missing `failure_category` for historical data

### Phase 3: Medium-term (Next Month)
1. Build full monitoring dashboard (Grafana or CloudWatch)
2. Implement daily summary email/Slack bot
3. Add retry tracking and optimization
4. Create ML-based anomaly detection for record counts

---

## Appendix A: Raw Query Results

### A.1 Full Failure Breakdown by Processor
See `/tmp/failure_patterns.json` for complete list of all 27 failing processors

### A.2 Complete Processing Time Statistics
See `/tmp/processing_times.json` for full duration stats on 30 processors

### A.3 Complete Record Count Patterns
See `/tmp/record_counts.json` for record count distributions

### A.4 Day-of-Week Patterns (Full)
See `/tmp/day_patterns.json` for 100+ processor/day combinations

---

## Appendix B: Glossary

- **Coefficient of Variation (CoV):** Standard deviation / mean. Values >1 indicate high variance.
- **P95:** 95th percentile - 95% of runs complete faster than this time.
- **Zero-record rate:** Percentage of successful runs that inserted 0 records.
- **Dependency check passed:** Whether all upstream tables were available before processing.
- **Phase:** Processing stage (phase_2_raw, phase_3_analytics, phase_4_precompute, phase_5_predictions).
- **Stale running cleanup:** Automated process that marks processors as failed if stuck in "running" status for >4 hours.

---

**Analysis Generated:** 2026-01-13
**Analyst:** NBA Stats Pipeline Analysis
**Contact:** naji@nba-props-platform.com
