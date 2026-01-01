# Data Completeness & Monitoring Architecture
**Date:** 2025-12-31
**Problem:** Missing game data detection and backfill strategy
**Status:** Design Proposal

---

## Problem Statement

### What Happened
- **Dec 30, 2025:** BDL API returned empty data all day (200+ scrapes)
- **Nov 10-12, 2025:** Complete 3-day outage (27 games)
- **Detection:** Discovered 1+ days later via analytics processor failures
- **Current State:** BDL has since backfilled data, but we have permanent gaps

### Root Causes
1. **No real-time validation** - Scraper doesn't check if response matches expectations
2. **No completeness tracking** - Don't compare scraped data vs schedule
3. **No game-level monitoring** - Only table-level freshness (not specific games)
4. **No automatic backfill** - Can't recover when API backfills data later

---

## Core Design Principles

### 1. **Detect at Multiple Levels**
Defense in depth - catch issues at different stages:
- **L1: Scraper execution** (seconds) - Is response empty?
- **L2: Post-processing** (minutes) - Are all expected games present?
- **L3: Daily audit** (hours) - Any gaps in last 7 days?

### 2. **Separation of Concerns**
- **Scraper:** Get data, log results, don't block
- **Validator:** Check completeness, alert
- **Backfiller:** Retry missing data
- **Auditor:** Track trends, patterns

### 3. **Single Source of Truth**
`nba_raw.nbac_schedule` = expected games
→ Compare all scraped data against this

### 4. **Fail Gracefully**
- Don't block pipeline on missing data
- Log and alert, but continue
- Enable manual/automated recovery

---

## Proposed Architecture

## Layer 1: Scrape Execution Logging

### Table: `nba_monitoring.scrape_execution_log`

```sql
CREATE TABLE nba_monitoring.scrape_execution_log (
  -- Identity
  execution_id STRING NOT NULL,
  scraper_name STRING NOT NULL,
  execution_timestamp TIMESTAMP NOT NULL,
  date_scraped DATE NOT NULL,

  -- Expected (from schedule)
  games_expected INT64,
  expected_game_ids ARRAY<STRING>,

  -- Actual (from scrape)
  games_returned INT64,
  games_saved_to_gcs INT64,
  returned_game_ids ARRAY<STRING>,

  -- Results
  status STRING,  -- 'success', 'empty_response', 'partial', 'error'
  is_empty_response BOOL,
  is_partial_data BOOL,
  missing_game_ids ARRAY<STRING>,

  -- Metadata
  file_path STRING,
  api_response_code INT64,
  error_message STRING,
  execution_duration_ms INT64,

  -- Backfill tracking
  is_backfill BOOL,
  backfill_reason STRING
)
PARTITION BY DATE(execution_timestamp)
CLUSTER BY scraper_name, date_scraped, status;
```

### Scraper Integration

```python
class ScraperBase:
    def scrape(self, date):
        execution_id = generate_uuid()
        start_time = time.time()

        # 1. Get expected games from schedule
        expected_games = self._get_expected_games_from_schedule(date)

        # 2. Execute scrape
        try:
            response = self._call_api(date)
            games = response.get('data', [])
            file_path = self._save_to_gcs(response, date)
        except Exception as e:
            self._log_execution(
                execution_id=execution_id,
                status='error',
                error_message=str(e),
                games_expected=len(expected_games)
            )
            raise

        # 3. Determine status
        status = self._determine_status(expected_games, games)

        # 4. Log execution to BigQuery
        self._log_execution(
            execution_id=execution_id,
            scraper_name=self.name,
            date_scraped=date,
            games_expected=len(expected_games),
            expected_game_ids=[g['game_id'] for g in expected_games],
            games_returned=len(games),
            returned_game_ids=[str(g['id']) for g in games],
            status=status,
            is_empty_response=(len(games) == 0 and len(expected_games) > 0),
            is_partial_data=(0 < len(games) < len(expected_games)),
            missing_game_ids=self._find_missing(expected_games, games),
            file_path=file_path,
            execution_duration_ms=int((time.time() - start_time) * 1000)
        )

        # 5. IMMEDIATE ALERT on critical issues
        if status == 'empty_response':
            self._alert_empty_response(date, expected_games, execution_id)
        elif status == 'partial':
            self._alert_partial_data(date, expected_games, games, execution_id)

        # 6. Continue with normal processing
        return self._process_games(games)

    def _determine_status(self, expected, actual):
        if len(actual) == 0 and len(expected) > 0:
            return 'empty_response'
        elif len(actual) < len(expected):
            return 'partial'
        elif len(actual) == len(expected):
            return 'success'
        else:
            return 'success'  # Got more than expected (future games, ok)

    def _get_expected_games_from_schedule(self, date):
        """Query schedule table for expected games on this date."""
        query = f"""
            SELECT game_id, game_code, home_team_tricode, away_team_tricode
            FROM nba_raw.nbac_schedule
            WHERE game_date = '{date}'
              AND game_status_text IN ('Final', 'In Progress', 'Scheduled')
        """
        return execute_bigquery(query)
```

**Benefits:**
- ✅ Detects empty responses within seconds
- ✅ Logs every scrape attempt (audit trail)
- ✅ Alerts immediately on issues
- ✅ Doesn't block pipeline
- ✅ Enables historical analysis

---

## Layer 2: Game-Level Completeness Tracking

### Table: `nba_monitoring.game_data_completeness`

```sql
CREATE TABLE nba_monitoring.game_data_completeness (
  -- Game identity
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  game_code STRING NOT NULL,
  home_team STRING,
  away_team STRING,

  -- Availability by source
  in_schedule BOOL,
  in_bdl_boxscores BOOL,
  in_nbacom_gamebook BOOL,
  in_nbacom_boxscore BOOL,
  in_pbpstats BOOL,
  in_odds_api BOOL,

  -- Quality metrics (per source)
  bdl_player_count INT64,
  nbacom_gamebook_player_count INT64,
  nbacom_boxscore_player_count INT64,

  -- Completeness status
  is_complete BOOL,  -- All critical sources present
  missing_sources ARRAY<STRING>,
  completeness_score FLOAT64,  -- 0-100%

  -- Timestamps
  first_seen_in_schedule TIMESTAMP,
  first_scraped_bdl TIMESTAMP,
  first_scraped_nbacom TIMESTAMP,
  last_updated TIMESTAMP,
  last_checked TIMESTAMP,

  -- Backfill tracking
  backfill_attempts INT64,
  last_backfill_attempt TIMESTAMP,
  backfill_successful BOOL
)
PARTITION BY game_date
CLUSTER BY game_date, is_complete;
```

### Daily Completeness Checker (Cloud Function)

```python
def check_game_completeness(event, context):
    """
    Runs daily at 6 AM ET.
    Checks last 7 days for missing games.
    Updates completeness table.
    Alerts on critical gaps.
    """

    for days_ago in range(7):
        date = today - timedelta(days=days_ago)

        # Get all scheduled games
        scheduled_games = get_scheduled_games(date)

        # Check each source
        bdl_games = get_bdl_games(date)
        nbacom_gamebook_games = get_nbacom_gamebook_games(date)
        nbacom_boxscore_games = get_nbacom_boxscore_games(date)

        # Update completeness table
        for game in scheduled_games:
            completeness = calculate_completeness(
                game, bdl_games, nbacom_gamebook_games, nbacom_boxscore_games
            )
            upsert_game_completeness(game, completeness)

            # Alert if incomplete and recent
            if not completeness['is_complete'] and days_ago < 2:
                alert_incomplete_game(game, completeness, days_ago)
```

**Benefits:**
- ✅ Game-level visibility (not just table-level)
- ✅ Cross-source validation (BDL vs NBA.com)
- ✅ Historical completeness tracking
- ✅ Can identify patterns (which source is unreliable?)
- ✅ Prioritizes recent games for alerts

---

## Layer 3: Intelligent Backfiller

### Cloud Function: `intelligent_backfiller`

```python
class IntelligentBackfiller:
    """
    Runs daily at 7 AM ET (after completeness check).
    Attempts to backfill missing data.
    """

    def run_daily_backfill(self):
        # 1. Get incomplete games from last 30 days
        incomplete_games = self._get_incomplete_games(
            days=30,
            min_completeness_score=90  # Missing >10% of sources
        )

        logger.info(f"Found {len(incomplete_games)} incomplete games")

        for game in incomplete_games:
            # 2. Check which sources are missing
            missing_sources = game['missing_sources']

            for source in missing_sources:
                # 3. Check if data is NOW available in API
                if self._check_api_has_data(source, game):
                    logger.info(f"API now has {source} for {game['game_code']}")

                    # 4. Trigger backfill scrape
                    success = self._trigger_backfill_scrape(
                        source=source,
                        game_date=game['game_date'],
                        game_code=game['game_code']
                    )

                    # 5. Update backfill tracking
                    self._update_backfill_attempt(game, source, success)
                else:
                    logger.debug(f"API still missing {source} for {game['game_code']}")

    def _check_api_has_data(self, source, game):
        """Check if API now has this game."""
        if source == 'bdl_boxscores':
            response = bdl_api.get_games(date=game['game_date'])
            game_ids = [str(g['id']) for g in response.get('data', [])]
            # Map NBA game_id to BDL game_id (use team codes)
            expected_id = f"{game['game_date'].replace('-', '')}_{game['away_team']}_{game['home_team']}"
            return expected_id in game_ids

        elif source == 'nbacom_gamebook':
            # Check if gamebook file exists in NBA.com
            url = f"https://cdn.nba.com/static/json/liveData/gamebook/{game['game_code']}_Book.pdf"
            response = requests.head(url)
            return response.status_code == 200

        return False

    def _trigger_backfill_scrape(self, source, game_date, game_code):
        """Trigger scraper for specific game."""
        scraper_map = {
            'bdl_boxscores': 'bdl_live_box_scores_scraper',
            'nbacom_gamebook': 'nbac_gamebook_pdf'
        }

        scraper_name = scraper_map.get(source)
        if not scraper_name:
            logger.warning(f"No scraper for source: {source}")
            return False

        # Call scraper service
        response = requests.post(
            f"{SCRAPER_SERVICE_URL}/scrape",
            json={
                'scraper': scraper_name,
                'game_code': game_code,
                'date': str(game_date),
                'is_backfill': True,
                'backfill_reason': 'api_data_now_available'
            }
        )

        return response.status_code == 200
```

**Benefits:**
- ✅ Automatic recovery from temporary outages
- ✅ Only retries when data is available (no wasted effort)
- ✅ Tracks backfill attempts
- ✅ Handles BDL's delayed backfill pattern

---

## Alert Strategy

### Severity Levels

```python
def determine_alert_severity(game_date, missing_sources):
    """Determine alert severity based on recency and criticality."""

    days_old = (datetime.now().date() - game_date).days

    # Critical: Recent games missing critical sources
    if days_old <= 2 and any(s in ['bdl_boxscores', 'nbacom_gamebook'] for s in missing_sources):
        return 'critical'

    # Warning: Older games or non-critical sources missing
    elif days_old <= 7:
        return 'warning'

    # Info: Historical gaps
    else:
        return 'info'
```

### Alert Routing

```python
class AlertRouter:
    def route_alert(self, alert):
        if alert.severity == 'critical':
            # Recent games missing - need immediate attention
            self.send_to_slack(alert, channel='#data-critical')
            self.send_email(alert, to='oncall@company.com')
            self.create_pagerduty_incident(alert)

        elif alert.severity == 'warning':
            # Older games or partial issues
            self.send_to_slack(alert, channel='#data-monitoring')
            self.send_email(alert, to='data-team@company.com')

        elif alert.severity == 'info':
            # Just log for historical tracking
            self.log_to_bigquery(alert)
```

**Benefits:**
- ✅ Reduces alert fatigue
- ✅ Prioritizes actionable alerts
- ✅ Appropriate escalation

---

## Implementation Roadmap

### Phase 1: Immediate (Today - 1 hour)

**Goal:** Backfill known gaps, establish baseline

1. **Create backfill script** (15 min)
   ```bash
   # Simple script to manually trigger scrapers
   python scripts/manual_backfill.py --dates 2025-12-30,2025-11-10,2025-11-11,2025-11-12
   ```

2. **Run backfill for Dec 30 & Nov 10-12** (15 min)
   - Trigger BDL scraper for these dates
   - Verify data now in BigQuery
   - Document in monitoring log

3. **Create completeness table** (30 min)
   ```sql
   CREATE TABLE nba_monitoring.game_data_completeness...
   ```

4. **Run initial completeness check** (15 min)
   - Populate table with last 30 days
   - Identify any other gaps

**Deliverables:**
- ✅ Dec 30 & Nov 10-12 backfilled
- ✅ Completeness table created
- ✅ Baseline established

---

### Phase 2: Quick Win (Tomorrow - 3 hours)

**Goal:** Daily completeness monitoring

1. **Build daily completeness checker** (2 hours)
   - Cloud Function
   - Checks last 7 days
   - Updates completeness table
   - Sends alerts on critical gaps

2. **Deploy and test** (1 hour)
   - Deploy to Cloud Functions
   - Schedule for 6 AM ET daily
   - Test with yesterday's data

**Deliverables:**
- ✅ Daily completeness check running
- ✅ Alerts on missing games

---

### Phase 3: Medium Term (This Week - 6 hours)

**Goal:** Real-time scrape validation

1. **Create scrape execution log table** (30 min)
   ```sql
   CREATE TABLE nba_monitoring.scrape_execution_log...
   ```

2. **Modify BDL scraper** (2 hours)
   - Add execution logging
   - Add real-time validation
   - Alert on empty responses

3. **Modify NBA.com scrapers** (2 hours)
   - Same logging/validation pattern

4. **Test and deploy** (1.5 hours)
   - Test with live scrapes
   - Verify alerts work
   - Deploy to production

**Deliverables:**
- ✅ All scrapers log executions
- ✅ Real-time empty response alerts
- ✅ Historical scrape data for analysis

---

### Phase 4: Long Term (Next Week - 8 hours)

**Goal:** Intelligent automatic backfill

1. **Build backfiller service** (4 hours)
   - Check API availability
   - Trigger scrapes for missing games
   - Track backfill attempts

2. **Integrate with completeness checker** (2 hours)
   - Backfiller reads from completeness table
   - Updates status after backfill

3. **Deploy and monitor** (2 hours)
   - Deploy as Cloud Function
   - Schedule for 7 AM ET daily
   - Monitor backfill success rate

**Deliverables:**
- ✅ Automatic backfill of missing data
- ✅ Self-healing pipeline
- ✅ Reduced manual intervention

---

## Success Metrics

### Immediate (Week 1)
- ✅ 100% of games from last 7 days accounted for
- ✅ Missing games detected within 24 hours
- ✅ Manual backfill process < 15 minutes

### Short Term (Month 1)
- ✅ Missing games detected within 1 hour
- ✅ 90% of missing games auto-backfilled
- ✅ Zero critical alerts >48 hours old

### Long Term (Quarter 1)
- ✅ 99.9% completeness across all sources
- ✅ Mean time to detect (MTTD) < 5 minutes
- ✅ Mean time to recovery (MTTR) < 1 hour
- ✅ Zero manual backfill interventions

---

## Key Design Decisions

### 1. Where to Validate?
**Decision:** Both scraper AND separate service
- Scraper: Quick check (is response empty?)
- Validator: Deep check (all expected games present?)

**Rationale:** Speed vs accuracy tradeoff - need both

### 2. When to Alert?
**Decision:** Severity-based (critical/warning/info)
- Critical: Recent (<2 days) + critical sources
- Warning: Older or non-critical
- Info: Historical only

**Rationale:** Reduce alert fatigue, focus on actionable

### 3. When to Backfill?
**Decision:** Hybrid approach
- Alert immediately (human knows)
- Auto-retry after 1 hour (may be transient)
- Daily check (batch backfill older gaps)

**Rationale:** Balance speed vs efficiency

### 4. How to Store Logs?
**Decision:** BigQuery + Cloud Logging
- Cloud Logging: Real-time alerts
- BigQuery: Historical analysis

**Rationale:** Different use cases, both needed

---

## Risk Mitigation

### Risk 1: Alert Fatigue
**Mitigation:**
- Severity-based routing
- Dedup similar alerts (same game, same day)
- Daily summary instead of per-game

### Risk 2: Backfill Loops
**Mitigation:**
- Track backfill attempts per game
- Max 3 attempts before manual intervention
- Exponential backoff (1h, 6h, 24h)

### Risk 3: Cost Increase
**Mitigation:**
- Partition tables by date
- 30-day retention on scrape logs
- Sample validation (not every scrape)

### Risk 4: False Positives
**Mitigation:**
- Grace period (6 hours after game end)
- Cross-validate with multiple sources
- Manual verification for critical alerts

---

## Cost Estimate

### Storage (BigQuery)
- Scrape logs: ~100KB/scrape × 500 scrapes/day = 50MB/day = $0.08/month
- Completeness table: ~1KB/game × 1,500 games/month = 1.5MB/month = $0.003/month
- **Total storage:** ~$0.10/month

### Compute (Cloud Functions)
- Daily completeness check: 1 minute × 30 days = 30 min/month @ $0.40/million = $0.00002
- Daily backfiller: 2 minutes × 30 days = 60 min/month @ $0.40/million = $0.00004
- **Total compute:** ~$0.001/month

### Queries (BigQuery)
- Daily checks: ~100MB scanned/day × 30 days = 3GB/month @ $5/TB = $0.015/month
- **Total queries:** ~$0.02/month

**Total cost increase:** ~$0.15/month (negligible)

---

## Next Steps

1. **Review this design** with team
2. **Approve Phase 1** (backfill + baseline)
3. **Start implementation** (1 hour today)
4. **Schedule Phases 2-4** over next 2 weeks

**Ready to proceed?**
