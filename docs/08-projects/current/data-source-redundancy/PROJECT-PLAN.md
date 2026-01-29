# Data Source Redundancy & Quality Monitoring System

**Project Start**: 2026-01-28 (Session 8)
**Status**: 🟡 In Progress
**Priority**: P0 - Critical Infrastructure

---

## Executive Summary

This project establishes a comprehensive data redundancy and quality monitoring system to ensure the NBA stats pipeline never fails due to a single data source going down or returning bad data.

### Key Goals

1. **Never lose data** - Multiple backup sources for all critical data
2. **Detect bad data immediately** - Cross-source validation catches discrepancies
3. **Monitor source health** - Track reliability of each source over time
4. **Automatic fallback** - Switch to backup sources when primary fails

---

## 1. Data Source Hierarchy

### 1.1 Player Box Scores (CRITICAL)

| Priority | Source | Storage | Status | Reliability |
|----------|--------|---------|--------|-------------|
| Primary | NBA.com Gamebook PDF | BigQuery | ✅ Active | 99.9% |
| Backup 1 | Basketball Reference | BigQuery | ✅ Active | 99%+ |
| Backup 2 | NBA API BoxScoreV3 | BigQuery | ✅ Active | 95%+ |
| Disabled | BDL API | BigQuery | ⚠️ Monitoring | 57% (bad) |

**Tables:**
- `nba_raw.nbac_gamebook_player_stats` (primary)
- `nba_raw.bref_player_boxscores` (backup)
- `nba_raw.nba_api_player_boxscores` (backup)
- `nba_raw.bdl_player_boxscores` (disabled)

### 1.2 Schedule Data (CRITICAL)

| Priority | Source | Storage | Status |
|----------|--------|---------|--------|
| Primary | NBA.com CDN | BigQuery | ✅ Active |
| Primary | NBA.com API | BigQuery | ✅ Active |
| Backup | Basketball Reference | GCS | 📋 TODO |
| Backup | NBA API | GCS | 📋 TODO |

**Tables:**
- `nba_raw.v_nbac_schedule_latest` (view)
- `nba_raw.nbac_schedule` (table)

### 1.3 Play-by-Play Data (HIGH)

| Priority | Source | Storage | Status |
|----------|--------|---------|--------|
| Primary | BigDataBall | BigQuery | ✅ Active |
| Backup | NBA.com PBP | BigQuery | ✅ Active |
| Backup | Basketball Reference | GCS | 📋 TODO |

**Tables:**
- `nba_raw.bigdataball_play_by_play` (primary - delayed release)
- `nba_raw.nbac_play_by_play` (backup)

### 1.4 Team Rosters (HIGH)

| Priority | Source | Storage | Status |
|----------|--------|---------|--------|
| Primary | ESPN | BigQuery | ✅ Active |
| Backup | NBA.com | BigQuery | ✅ Active |
| Backup | NBA API | GCS | 📋 TODO |

**Tables:**
- `nba_raw.espn_team_rosters`
- `nba_raw.nbac_roster`

### 1.5 Injury Reports (HIGH)

| Priority | Source | Storage | Status |
|----------|--------|---------|--------|
| Primary | NBA.com | BigQuery | ✅ Active |
| Backup | None | - | ❌ Gap |

**Tables:**
- `nba_raw.nbac_injury_report`

**Note**: No good backup source for injuries. ESPN injury data is less reliable.

### 1.6 Betting/Props Data (MEDIUM)

| Priority | Source | Storage | Status |
|----------|--------|---------|--------|
| Primary | OddsAPI | BigQuery | ✅ Active |
| Backup | BettingPros | BigQuery | ✅ Active |

**Tables:**
- `nba_raw.odds_api_player_points_props`
- `nba_raw.bettingpros_player_points_props`

---

## 2. Cross-Source Validation System

### 2.1 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CROSS-SOURCE VALIDATOR                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│   │  NBA.com     │    │  Basketball  │    │   NBA API    │     │
│   │  Gamebook    │    │  Reference   │    │  BoxScoreV3  │     │
│   │  (PRIMARY)   │    │  (BACKUP 1)  │    │  (BACKUP 2)  │     │
│   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘     │
│          │                   │                   │              │
│          └───────────────────┼───────────────────┘              │
│                              │                                   │
│                              ▼                                   │
│                    ┌─────────────────┐                          │
│                    │   COMPARATOR    │                          │
│                    │                 │                          │
│                    │ • Match players │                          │
│                    │ • Compare stats │                          │
│                    │ • Flag diffs    │                          │
│                    └────────┬────────┘                          │
│                             │                                    │
│              ┌──────────────┼──────────────┐                    │
│              ▼              ▼              ▼                    │
│     ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│     │  BigQuery  │  │   Slack    │  │  Metrics   │             │
│     │ Discrepancy│  │   Alert    │  │ Dashboard  │             │
│     │   Table    │  │            │  │            │             │
│     └────────────┘  └────────────┘  └────────────┘             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Comparison Logic

**Fields Compared:**
- `minutes_played` (threshold: ±3 min for major, ±1 for minor)
- `points` (threshold: ±2 pts for major)
- `assists`, `rebounds`, `steals`, `blocks` (threshold: ±1)

**Matching Strategy:**
- Match by `player_lookup` (normalized name)
- Only compare players with `minutes_played > 0` (skip DNP)

### 2.3 Discrepancy Storage

**Table**: `nba_orchestration.source_discrepancies`

```sql
CREATE TABLE source_discrepancies (
    game_date DATE,
    player_lookup STRING,
    player_name STRING,
    backup_source STRING,      -- 'basketball_reference', 'nba_api', 'bdl'
    severity STRING,           -- 'major', 'minor'
    discrepancies_json STRING, -- JSON of field differences
    detected_at TIMESTAMP,
    reviewed BOOL,
    review_notes STRING
);
```

### 2.4 Daily Workflow

```yaml
Schedule: Daily at 11 AM UTC (after games processed)

Steps:
  1. Scrape Basketball Reference (3s delay, respectful)
  2. Scrape NBA API BoxScoreV3 (1s delay)
  3. Run cross-source validator
  4. Store discrepancies to BigQuery
  5. Send Slack alert if major discrepancies found
```

---

## 3. BDL Data Quality Monitoring

### 3.1 Background

BDL (Ball Don't Lie) API was disabled on 2026-01-28 due to severe data quality issues:
- **43% major mismatches** (>5 minute differences)
- **27 players completely missing**
- Max difference of **36 minutes**

### 3.2 Monitoring Strategy

**Daily Check**: Compare BDL data against NBA.com gamebook

**Metrics Tracked:**
- Coverage percentage (% of players with BDL data)
- Exact match rate (minutes match exactly)
- Major mismatch rate (>5 min difference)
- Average/max difference

**Alerting:**
- Alert if quality remains poor (status quo)
- Alert if quality IMPROVES (signal to re-enable)

### 3.3 Re-Enable Criteria

BDL can be re-enabled when:
- Coverage > 95%
- Major mismatch rate < 5%
- Sustained for 7+ consecutive days

**To Re-Enable:**
```python
# In player_game_summary_processor.py
USE_BDL_DATA = True  # Change from False
```

### 3.4 Monitoring Scripts

| Script | Purpose | Schedule |
|--------|---------|----------|
| `check_bdl_data_quality.py` | Manual quality check | On-demand |
| `bdl_quality_alert.py` | Automated alerting | Daily via GitHub workflow |

---

## 4. Missing Data Monitoring

### 4.1 BigDataBall PBP Data (Special Case)

**Problem**: BigDataBall releases play-by-play data at unpredictable times after games complete (sometimes 2-6 hours, sometimes next day).

**Current Gap**: No monitoring for when BDB data becomes available.

**Proposed Solution:**

```
┌─────────────────────────────────────────────────────────────┐
│              BIGDATABALL PBP MONITOR                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. AVAILABILITY CHECK (runs every 30 min)                  │
│     ├── Query BigDataBall for yesterday's games             │
│     ├── Compare against expected games from schedule        │
│     └── Track which games have PBP data                     │
│                                                              │
│  2. GAP DETECTION                                            │
│     ├── Games with no BDB data after 6 hours → WARNING      │
│     ├── Games with no BDB data after 24 hours → ALERT       │
│     └── Track in nba_orchestration.data_gaps                │
│                                                              │
│  3. AUTO-RETRY TRIGGER                                       │
│     ├── When data appears, trigger Phase 3 reprocessing     │
│     └── Update gap status to 'resolved'                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 General Missing Data Detection

**Check all critical sources daily:**

| Source | Expected | Check Method |
|--------|----------|--------------|
| Gamebook | All finished games | Compare vs schedule |
| BRef | All finished games | Compare vs schedule |
| BDB PBP | All finished games | Compare vs schedule |
| Injuries | Daily update | Check freshness |
| Props | All scheduled games | Compare vs schedule |

### 4.3 Data Gaps Table

**Table**: `nba_orchestration.data_gaps`

```sql
CREATE TABLE data_gaps (
    game_date DATE,
    game_id STRING,
    source STRING,           -- 'bigdataball_pbp', 'gamebook', etc.
    expected_at TIMESTAMP,   -- When we expected data
    detected_at TIMESTAMP,   -- When gap was detected
    resolved_at TIMESTAMP,   -- When data appeared
    severity STRING,         -- 'warning', 'critical'
    auto_retry_count INT64,
    status STRING            -- 'open', 'resolved', 'manual_review'
);
```

---

## 5. Alerting Strategy

### 5.1 Alert Channels

| Channel | Purpose | Urgency |
|---------|---------|---------|
| `#app-error-alerts` | Critical failures, data loss | P0 |
| `#nba-alerts` | Warnings, quality issues | P1 |
| `#daily-orchestration` | Daily summaries | P2 |

### 5.2 Alert Types

**Data Quality Alerts:**
- Major discrepancy detected (>3 min or >2 pts difference)
- BDL quality status (poor/improving)
- Source coverage below threshold

**Missing Data Alerts:**
- Game data missing after 6 hours (warning)
- Game data missing after 24 hours (critical)
- BigDataBall PBP not available

**Source Health Alerts:**
- Scraper failed to run
- API returning errors
- Unexpected data format

### 5.3 Alert Format

```
:warning: Data Quality Alert

*Date:* 2026-01-27
*Source:* basketball_reference

*Issues Found:*
• 3 players with major minute discrepancies
• Coverage: 95% (expected 100%)

*Sample Discrepancy:*
Player: LeBron James
Gamebook: 38 min, 28 pts
BRef: 35 min, 26 pts

*Action:* Review discrepancies in BigQuery
```

---

## 6. Implementation Checklist

### Phase 1: Core Infrastructure ✅ COMPLETE

- [x] Disable BDL data source (USE_BDL_DATA = False)
- [x] Create Basketball Reference scraper
- [x] Create NBA API BoxScoreV3 scraper
- [x] Create cross-source validator
- [x] Create BDL quality monitor
- [x] Set up BigQuery tables for discrepancies
- [x] Create daily GitHub workflow

### Phase 2: Enhanced Monitoring 📋 TODO

- [ ] Create BigDataBall PBP availability monitor
- [ ] Create data_gaps table and tracking
- [ ] Add auto-retry trigger for late-arriving data
- [ ] Create morning dashboard with source health
- [ ] Add source reliability metrics to Grafana

### Phase 3: GCS Backups 📋 TODO

- [ ] Create GCS bucket for backup data
- [ ] Implement GCS backup scrapers:
  - [ ] NBA API schedule → GCS
  - [ ] NBA API standings → GCS
  - [ ] NBA API rosters → GCS
  - [ ] BRef season totals → GCS
  - [ ] BRef advanced stats → GCS
- [ ] Create weekly backup job

### Phase 4: Automatic Fallback 📋 FUTURE

- [ ] Implement fallback logic in PlayerGameSummaryProcessor
- [ ] Add source priority configuration
- [ ] Create automatic source switching
- [ ] Add fallback usage tracking

---

## 7. Files & Locations

### Scrapers

```
scrapers/
├── basketball_reference/
│   ├── __init__.py
│   └── bref_boxscore_scraper.py      # Daily box scores
├── nba_api_backup/
│   ├── __init__.py
│   ├── boxscore_traditional_scraper.py  # Daily box scores
│   └── gcs_backup_scrapers.py           # GCS backups
└── nbacom/
    └── (existing scrapers)
```

### Monitoring

```
bin/monitoring/
├── cross_source_validator.py    # Compare all sources
├── check_bdl_data_quality.py    # Manual BDL check
├── bdl_quality_alert.py         # BDL alerting
├── morning_health_check.sh      # Daily dashboard
└── [TODO] bdb_pbp_monitor.py    # BigDataBall monitor
```

### Schemas

```
schemas/bigquery/
├── nba_raw/
│   ├── bref_player_boxscores.sql
│   └── nba_api_player_boxscores.sql
└── nba_orchestration/
    ├── source_discrepancies.sql
    └── [TODO] data_gaps.sql
```

### Workflows

```
.github/workflows/
├── daily-source-validation.yml   # Scrape + validate
├── bdl-quality-monitor.yml       # BDL monitoring
└── [TODO] data-gap-monitor.yml   # Missing data
```

---

## 8. Success Metrics

### Data Quality

| Metric | Target | Current |
|--------|--------|---------|
| Primary source uptime | 99.9% | ✅ |
| Backup source coverage | 95%+ | ✅ 95%+ |
| Major discrepancy rate | <1% | 📊 Tracking |
| Data gap resolution time | <6 hours | 📊 Tracking |

### Source Reliability

| Source | Target Reliability | Current |
|--------|-------------------|---------|
| NBA.com Gamebook | 99.9% | ✅ |
| Basketball Reference | 99%+ | ✅ |
| NBA API | 95%+ | ✅ |
| BigDataBall PBP | 95%+ | 📊 Unknown |
| BDL API | 95%+ | ❌ 57% |

---

## 9. Rollback Plan

If any backup source causes issues:

1. **Disable in processor:**
   ```python
   USE_BDL_DATA = False  # Example
   ```

2. **Stop daily scrape:**
   - Disable GitHub workflow
   - Or remove from Cloud Scheduler

3. **Keep data for analysis:**
   - Don't delete BigQuery tables
   - Review discrepancies to understand issue

---

## 10. Related Documentation

- [Data Quality Prevention](../data-quality-prevention/PROJECT-OVERVIEW.md)
- [Validation Hardening](../validation-hardening/)
- [Session 8 Handoff](../../09-handoff/2026-01-28-SESSION-8-HANDOFF.md)

---

## Appendix A: SQL Queries

### Check Source Coverage

```sql
SELECT
    game_date,
    'gamebook' as source,
    COUNT(DISTINCT player_lookup) as players
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
UNION ALL
SELECT
    game_date,
    'bref' as source,
    COUNT(DISTINCT player_lookup) as players
FROM nba_raw.bref_player_boxscores
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
UNION ALL
SELECT
    game_date,
    'nba_api' as source,
    COUNT(DISTINCT player_lookup) as players
FROM nba_raw.nba_api_player_boxscores
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY game_date DESC, source;
```

### Check Discrepancy Trends

```sql
SELECT
    game_date,
    backup_source,
    severity,
    COUNT(*) as count
FROM nba_orchestration.source_discrepancies
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY 1, 2, 3
ORDER BY game_date DESC;
```

### Find Missing BDB PBP Data

```sql
SELECT
    s.game_date,
    s.game_id,
    s.home_team_abbr,
    s.away_team_abbr,
    CASE WHEN b.game_id IS NULL THEN 'MISSING' ELSE 'OK' END as bdb_status
FROM nba_raw.v_nbac_schedule_latest s
LEFT JOIN (
    SELECT DISTINCT game_id FROM nba_raw.bigdataball_play_by_play
) b ON s.game_id = b.game_id
WHERE s.game_date = CURRENT_DATE() - 1
  AND s.game_status = 'Final';
```

---

*Last Updated: 2026-01-28*
*Author: Claude Opus 4.5 + User*
