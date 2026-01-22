# Multi-Scraper Visibility & Latency Improvement Plan
**Date:** January 21, 2026
**Status:** Ready for Implementation
**Priority:** P0 - Critical Pipeline Health Initiative

---

## Executive Summary

**Vision:** Transform our scraper infrastructure from "hope it works" to "know it works" with comprehensive visibility, automated validation, and intelligent retry logic across all 33 NBA scrapers.

**Current State:**
- ✅ Multi-scraper monitoring views deployed (BDL, NBAC, OddsAPI)
- ✅ Daily alerting Cloud Function built (not deployed yet)
- ❌ No per-game availability tracking
- ❌ No automated completeness validation
- ❌ No intelligent retry queues
- ❌ Missing data discovered days later via manual audit

**Target State:**
- ✅ Real-time visibility into every scraper's availability and latency
- ✅ Automated completeness validation after every scrape
- ✅ Intelligent retry queues that auto-heal missing data
- ✅ < 10 minute detection time for missing games
- ✅ Daily Slack reports showing pipeline health across all scrapers

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    NBA Schedule (Source of Truth)            │
│                    nba_raw.nbac_schedule                     │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Per-Scraper Availability Logging                │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │ BDL Attempts │ NBAC Attempts│ Odds Attempts│ + more...   │
│  │ (per game)   │ (per game)   │ (per game)   │             │
│  └──────────────┴──────────────┴──────────────┘             │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              v_scraper_game_availability (DEPLOYED)          │
│  Compares all sources, calculates latency, flags issues     │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
        ┌───────────────────┐  ┌──────────────────┐
        │ Daily Summary     │  │ Missing Game     │
        │ View (DEPLOYED)   │  │ Retry Queue      │
        └─────────┬─────────┘  └────────┬─────────┘
                  │                     │
        8 AM ET Daily          Every 2 hours
                  │                     │
                  ▼                     ▼
        ┌──────────────────┐  ┌─────────────────┐
        │ Availability     │  │ Retry Worker    │
        │ Monitor CF       │  │ Cloud Function  │
        │ (BUILT)          │  │ (TO BUILD)      │
        └─────────┬────────┘  └────────┬────────┘
                  │                    │
            Slack + Email          Auto-heals gaps
```

---

## What We Already Have (Foundation)

### 1. Multi-Scraper Monitoring Views ✅ DEPLOYED
**Location:** BigQuery `nba_orchestration` dataset

**Views:**
- `v_scraper_game_availability` - Per-game availability across BDL, NBAC, OddsAPI
- `v_scraper_availability_daily_summary` - Daily aggregates with alert levels
- `v_bdl_game_availability` - BDL-specific historical view

**Capabilities:**
- Compare schedule vs actual data loaded
- Calculate latency from game end
- Flag missing games
- Daily coverage percentages

**Example Query:**
```sql
SELECT * FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
```

### 2. Alerting Cloud Function ✅ BUILT, NOT DEPLOYED
**Location:** `orchestration/cloud_functions/scraper_availability_monitor/`

**Capabilities:**
- Checks yesterday's games at 8 AM ET daily
- Sends Slack alerts if coverage < 90%
- Logs to Firestore for historical tracking
- Includes missing game list, West Coast analysis, latency stats

**Deployment:** `./deploy.sh --scheduler`

### 3. BDL Game-Level Logger ✅ BUILT, NOT DEPLOYED
**Location:** `shared/utils/bdl_availability_logger.py`

**Capabilities:**
- Tracks which specific games BDL returned on each scrape attempt
- Creates timeline: "Checked at 1 AM - not there. Checked at 2 AM - there."
- Enables precise per-game latency measurement

**Schema:** `schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql`

---

## What We're Building (The Plan)

### Phase 1: Foundation - Per-Scraper Visibility (Week 1)

**Goal:** Get game-level visibility into BDL, NBAC, and OddsAPI scrapers

#### 1.1 Deploy BDL Game-Level Logging ⏰ 30 mins

**Actions:**
1. Create BigQuery table:
   ```bash
   bq query --nouse_legacy_sql --location=us-west2 < \
     schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql
   ```

2. Integrate into `scrapers/balldontlie/bdl_box_scores.py`:
   ```python
   # Add import
   from shared.utils.bdl_availability_logger import log_bdl_game_availability

   # Add in transform_data() after self.data is set
   log_bdl_game_availability(
       game_date=self.opts["date"],
       execution_id=self.run_id,
       box_scores=self.data["boxScores"],
       workflow=self.opts.get("workflow")
   )
   ```

3. Test locally and deploy

**Benefits:**
- See exactly when each game becomes available in BDL
- Measure true latency per game
- Identify consistently late games

#### 1.2 Create NBAC Game-Level Logging ⏰ 1 hour

**New Files:**
- `shared/utils/nbac_availability_logger.py` (copy pattern from BDL)
- `schemas/bigquery/nba_orchestration/nbac_game_scrape_attempts.sql`

**Table Schema:**
```sql
CREATE TABLE nba_orchestration.nbac_game_scrape_attempts (
  scrape_timestamp TIMESTAMP NOT NULL,
  execution_id STRING,
  workflow STRING,

  game_date DATE NOT NULL,
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,

  was_available BOOL NOT NULL,
  gamebook_present BOOL,
  play_by_play_present BOOL,

  latency_hours FLOAT64,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY was_available, home_team;
```

**Integration Points:**
- `scrapers/nbac/nbac_gamebook.py`
- `scrapers/nbac/nbac_play_by_play.py`

**Why:** NBAC is our fallback - need to know its reliability too

#### 1.3 Create OddsAPI Game-Level Logging ⏰ 1 hour

**New Files:**
- `shared/utils/oddsapi_availability_logger.py`
- `schemas/bigquery/nba_orchestration/oddsapi_game_scrape_attempts.sql`

**Table Schema:**
```sql
CREATE TABLE nba_orchestration.oddsapi_game_scrape_attempts (
  scrape_timestamp TIMESTAMP NOT NULL,
  execution_id STRING,
  workflow STRING,

  game_date DATE NOT NULL,
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,

  was_available BOOL NOT NULL,
  odds_count INT64,  -- How many bookmakers had lines
  props_available BOOL,

  latency_hours FLOAT64,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY was_available, home_team;
```

**Integration Points:**
- `scrapers/oddsapi/odds_events.py`
- `scrapers/oddsapi/odds_game_lines.py`

#### 1.4 Deploy Daily Monitoring Alert ⏰ 15 mins

**Action:**
```bash
cd orchestration/cloud_functions/scraper_availability_monitor
./deploy.sh --scheduler
```

**Immediate Benefits:**
- Daily 8 AM ET Slack alerts showing coverage
- Early detection of missing data (within 12 hours vs days)
- Historical tracking in Firestore
- Clear BDL vs NBAC vs OddsAPI comparison

---

### Phase 2: Validation - Automated Completeness Checks (Week 2)

**Goal:** Detect missing games within minutes, not days

#### 2.1 BDL Completeness Validator ⏰ 1 hour

**Option A: Inline Check (Simple)**

Edit `scrapers/balldontlie/bdl_box_scores.py`:
```python
def transform_data(self):
    # ... existing code ...

    # Check completeness
    expected = get_expected_game_count(self.opts["date"])
    games_returned = len(set(
        (r["game"]["home_team"]["abbreviation"],
         r["game"]["visitor_team"]["abbreviation"])
        for r in self.data["boxScores"]
    ))

    if games_returned < expected:
        notify_warning(
            title="BDL Box Scores - Incomplete Data",
            message=f"Missing {expected - games_returned} games for {self.opts['date']}",
            details={
                'expected': expected,
                'returned': games_returned,
                'missing': expected - games_returned
            }
        )
```

**Option B: Separate Cloud Function (Better)**

Create `orchestration/cloud_functions/bdl_completeness_checker/`:
- Triggered via Pub/Sub after BDL scraper completes
- Queries schedule vs loaded data
- Sends alert + adds to retry queue if incomplete
- Logs validation results to BigQuery

**Recommendation:** Start with Option A, migrate to Option B in Phase 3

#### 2.2 NBAC Completeness Validator ⏰ 45 mins

**Similar pattern:**
- Check `nba_raw.nbac_gamebook` count vs schedule
- Alert if mismatch
- NBAC is more reliable, but still need validation

#### 2.3 OddsAPI Completeness Validator ⏰ 45 mins

**Different validation:**
- Not all games have odds immediately
- Check: "Did we get lines for games that started 2+ hours ago?"
- More nuanced than BDL/NBAC

#### 2.4 Create Unified Completeness Dashboard ⏰ 2 hours

**New BigQuery View:**
```sql
CREATE OR REPLACE VIEW nba_orchestration.v_completeness_status AS
WITH expected_games AS (
  SELECT game_date, COUNT(*) as expected_count
  FROM nba_raw.nbac_schedule
  WHERE season_year = 2025
    AND game_status = 3
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
bdl_games AS (
  SELECT game_date, COUNT(DISTINCT game_id) as bdl_count
  FROM nba_raw.bdl_player_boxscores
  GROUP BY game_date
),
nbac_games AS (
  SELECT game_date, COUNT(DISTINCT game_id) as nbac_count
  FROM nba_raw.nbac_gamebook
  GROUP BY game_date
),
odds_games AS (
  SELECT game_date, COUNT(DISTINCT game_id) as odds_count
  FROM nba_raw.oddsapi_events
  GROUP BY game_date
)
SELECT
  e.game_date,
  e.expected_count,

  COALESCE(b.bdl_count, 0) as bdl_count,
  ROUND(SAFE_DIVIDE(b.bdl_count, e.expected_count) * 100, 1) as bdl_coverage_pct,
  CASE
    WHEN COALESCE(b.bdl_count, 0) < e.expected_count THEN 'INCOMPLETE'
    ELSE 'COMPLETE'
  END as bdl_status,

  COALESCE(n.nbac_count, 0) as nbac_count,
  ROUND(SAFE_DIVIDE(n.nbac_count, e.expected_count) * 100, 1) as nbac_coverage_pct,
  CASE
    WHEN COALESCE(n.nbac_count, 0) < e.expected_count THEN 'INCOMPLETE'
    ELSE 'COMPLETE'
  END as nbac_status,

  COALESCE(o.odds_count, 0) as odds_count,
  ROUND(SAFE_DIVIDE(o.odds_count, e.expected_count) * 100, 1) as odds_coverage_pct,

  CASE
    WHEN COALESCE(n.nbac_count, 0) >= e.expected_count THEN 'HEALTHY'
    WHEN COALESCE(b.bdl_count, 0) >= e.expected_count THEN 'HEALTHY_VIA_BDL'
    WHEN COALESCE(b.bdl_count, 0) + COALESCE(n.nbac_count, 0) >= e.expected_count THEN 'NEEDS_ATTENTION'
    ELSE 'CRITICAL'
  END as overall_status

FROM expected_games e
LEFT JOIN bdl_games b USING (game_date)
LEFT JOIN nbac_games n USING (game_date)
LEFT JOIN odds_games o USING (game_date)
ORDER BY game_date DESC;
```

**Use Case:** Single query shows entire pipeline health at a glance

---

### Phase 3: Recovery - Intelligent Retry Queues (Week 3-4)

**Goal:** Auto-heal missing data without manual intervention

#### 3.1 Missing Game Retry Queue ⏰ 2 hours

**BigQuery Table:**
```sql
CREATE TABLE nba_orchestration.missing_game_retry_queue (
  game_date DATE NOT NULL,
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,

  -- Which source is missing
  source STRING NOT NULL,  -- 'BDL', 'NBAC', 'ODDSAPI'

  -- Detection
  detected_at TIMESTAMP NOT NULL,
  detection_source STRING,  -- 'completeness_check', 'manual', 'daily_monitor'

  -- Retry logic
  retry_count INT64 DEFAULT 0,
  last_retry_at TIMESTAMP,
  next_retry_at TIMESTAMP,

  -- Resolution
  resolved_at TIMESTAMP,
  resolved_by STRING,  -- 'auto_retry', 'manual_backfill', 'data_unavailable'

  -- Priority
  priority STRING DEFAULT 'NORMAL',  -- 'HIGH', 'NORMAL', 'LOW'

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY source, resolved_at, priority;
```

**Key Design:**
- Separate entry per source (can have BDL missing but NBAC present)
- Exponential backoff (retry at 2h, 4h, 8h, 16h...)
- Auto-resolve when data appears
- Priority escalation after multiple failures

#### 3.2 Retry Worker Cloud Function ⏰ 3 hours

**Location:** `orchestration/cloud_functions/missing_game_retry_worker/`

**Trigger:** Cloud Scheduler - every 2 hours

**Logic:**
```python
def retry_missing_games(event, context):
    """
    1. Query retry_queue for unresolved entries where next_retry_at <= NOW
    2. For each missing game:
       - Invoke appropriate scraper for that specific date
       - Wait for completion
       - Check if game now exists in target table
       - If yes: mark resolved_at
       - If no: increment retry_count, calculate next_retry_at with exponential backoff
    3. After 10 retries (48 hours): escalate to CRITICAL alert, mark as 'data_unavailable'
    """
```

**Benefits:**
- Automatic recovery from transient API issues
- Intelligent backoff reduces API spam
- Clear visibility into retry history
- Auto-escalation for persistent failures

#### 3.3 Integration with Completeness Validators ⏰ 1 hour

**Update validators to:**
1. Detect missing games
2. Add to retry queue automatically
3. Send immediate alert (don't wait for daily summary)
4. Log detection event

**Flow:**
```
BDL Scraper completes → Completeness Validator runs
  → Detects 3 games missing
  → Adds 3 entries to retry_queue with priority=HIGH
  → Sends Slack alert: "3 games missing from BDL, added to retry queue"
  → Retry worker picks up in 2 hours
```

---

### Phase 4: Expansion - Additional Scrapers (Week 5-6)

**Goal:** Extend monitoring to ESPN, BettingPros, BigDataBall

#### 4.1 ESPN Scraper Monitoring ⏰ 2 hours

**Challenge:** ESPN scraper hasn't run since June 2025 (stale)

**Steps:**
1. Fix ESPN scraper first (separate task)
2. Add game-level logging: `espn_game_scrape_attempts`
3. Add to `v_scraper_game_availability` view
4. Include in daily alerts

**Priority:** Medium (not critical since BDL/NBAC cover this)

#### 4.2 Props Scrapers Monitoring ⏰ 3 hours

**Scrapers:**
- `oddsapi/player_props.py`
- `bettingpros/player_props.py`

**Different validation:**
- Not all players have props every game
- Check: "Did we get props for the stars?"
- More complex than game-level validation

**Approach:**
- Track player-prop coverage (not just game coverage)
- Alert if coverage drops below historical baseline

#### 4.3 Historical Reconciliation Job ⏰ 4 hours

**Weekly Cloud Run Job:** Runs every Monday at 9 AM ET

**Purpose:** Safety net - validate last 7 days, auto-backfill any gaps

**Logic:**
```python
def weekly_reconciliation():
    report = []

    for date in last_7_days:
        expected = get_expected_games(date)

        for source in ['BDL', 'NBAC', 'ODDSAPI']:
            actual = get_actual_games(source, date)

            if actual < expected:
                gap = expected - actual
                trigger_backfill(source, date)
                report.append({
                    'date': date,
                    'source': source,
                    'gap': gap,
                    'action': 'BACKFILLED'
                })

    send_weekly_report(report)  # Email summary
```

**Benefits:**
- Catches anything the daily monitor missed
- Auto-heals gaps before they become problems
- Weekly health report to stakeholders

---

## Implementation Priorities

### P0 - Critical (Deploy This Week)

1. **Deploy existing monitoring** (15 mins)
   - Scraper availability monitor Cloud Function
   - Start getting daily alerts immediately

2. **BDL game-level logging** (30 mins)
   - Immediate visibility into BDL latency issues

3. **BDL completeness check** (1 hour)
   - Detect missing games in real-time

4. **Investigate workflow execution** (2 hours)
   - Fix why recovery windows (2 AM, 4 AM, 6 AM) didn't run

**Total: ~4 hours** → Immediate ROI

### P1 - High (Week 2)

5. **NBAC game-level logging** (1 hour)
6. **OddsAPI game-level logging** (1 hour)
7. **NBAC/OddsAPI completeness checks** (1.5 hours)
8. **Completeness dashboard view** (2 hours)
9. **Missing game retry queue** (2 hours)
10. **Retry worker function** (3 hours)

**Total: ~10.5 hours** → Full automated recovery

### P2 - Medium (Week 3-4)

11. **Real-time completeness monitor** (4 hours)
    - Pub/Sub triggered after each scraper
12. **Weekly reconciliation job** (4 hours)
13. **ESPN scraper fixes + monitoring** (6 hours)

**Total: ~14 hours** → Complete coverage

### P3 - Future Enhancements

14. **Props scraper monitoring** (3 hours)
15. **Historical data quality dashboard** (4 hours)
16. **MLOps model input validation** (see ERROR-TRACKING-PROPOSAL.md)

---

## Success Metrics

### Before Implementation

| Metric | Current State |
|--------|---------------|
| Missing game detection time | **Days** (manual audit) |
| Missing game rate (Jan 1-21) | **17%** (31 of 180 games) |
| Recovery mechanism | **Manual backfill** |
| Latency visibility | **None** (aggregate only) |
| Alert coverage | **None** (manual checks) |
| Time to resolve issues | **Days** |

### After Phase 1 (Week 1)

| Metric | Target |
|--------|--------|
| Missing game detection time | **< 12 hours** (next morning alert) |
| Missing game visibility | **100%** (daily summary) |
| Latency visibility | **Per-game** (BDL, NBAC, OddsAPI) |
| Alert coverage | **Daily Slack** |

### After Phase 2 (Week 2)

| Metric | Target |
|--------|--------|
| Missing game detection time | **< 10 minutes** (post-scrape validation) |
| Real-time alerts | **Immediate** (Slack on incompleteness) |
| Validation coverage | **BDL, NBAC, OddsAPI** |

### After Phase 3 (Week 4)

| Metric | Target |
|--------|--------|
| Missing game rate | **< 1%** (with retry queue) |
| Recovery mechanism | **Automatic** (80%+ auto-healed) |
| Time to resolve issues | **< 4 hours** (retry queue) |
| Manual intervention needed | **< 20%** of issues |

---

## Reusable Patterns

### Pattern 1: Game-Level Availability Logger

**Template:** `shared/utils/availability_logger_base.py`

```python
class AvailabilityLogger:
    """Base class for logging game availability across scrapers"""

    def __init__(self, source_name: str, table_name: str):
        self.source = source_name
        self.table = table_name
        self.bq_client = bigquery.Client()

    def log_availability(self, game_date: str, execution_id: str,
                        games_found: List[Dict], workflow: str = None):
        """
        Logs which games were found in this scrape attempt.

        Args:
            game_date: Date being scraped
            execution_id: Unique ID for this scrape run
            games_found: List of games returned by API
            workflow: Which workflow triggered this (post_game_window_2, etc.)
        """
        # Implementation...
```

**Usage:**
```python
# In any scraper
from shared.utils.availability_logger_base import AvailabilityLogger

logger = AvailabilityLogger(source_name="BDL", table_name="bdl_game_scrape_attempts")
logger.log_availability(
    game_date=self.opts["date"],
    execution_id=self.run_id,
    games_found=self.data["boxScores"],
    workflow=self.opts.get("workflow")
)
```

### Pattern 2: Completeness Validator

**Template:** `shared/validation/completeness_validator.py`

```python
class CompletenessValidator:
    """Validates scraper completeness against schedule"""

    def validate(self, source: str, game_date: str,
                 games_returned: int) -> ValidationResult:
        """
        Compare games returned vs expected from schedule.

        Returns:
            ValidationResult with status, expected, actual, missing list
        """
        expected = self._get_expected_count(game_date)

        if games_returned < expected:
            missing_games = self._identify_missing_games(source, game_date)
            self._add_to_retry_queue(missing_games, source)
            self._send_alert(source, game_date, expected, games_returned)

            return ValidationResult(
                status="INCOMPLETE",
                expected=expected,
                actual=games_returned,
                missing=missing_games
            )

        return ValidationResult(status="COMPLETE", expected=expected, actual=games_returned)
```

### Pattern 3: Retry Queue Entry

**Template:** `shared/utils/retry_queue.py`

```python
class RetryQueue:
    """Manages retry queue for missing games"""

    def add_missing_game(self, game_date: str, home_team: str,
                        away_team: str, source: str,
                        priority: str = "NORMAL"):
        """Add game to retry queue"""

        entry = {
            'game_date': game_date,
            'home_team': home_team,
            'away_team': away_team,
            'source': source,
            'detected_at': datetime.now(timezone.utc),
            'detection_source': 'completeness_check',
            'retry_count': 0,
            'next_retry_at': datetime.now(timezone.utc) + timedelta(hours=2),
            'priority': priority
        }

        self._insert_to_bigquery(entry)
```

---

## Related Documentation

### Existing Docs
- **BDL Root Cause:** `BDL-MISSING-GAMES-ROOT-CAUSE-AND-FIXES.md`
- **Quick Start:** `QUICK-START-BDL-FIXES.md`
- **Error Tracking Vision:** `ERROR-TRACKING-PROPOSAL.md`
- **Previous Session:** `../../09-handoff/2026-01-21-SCRAPER-MONITORING-HANDOFF.md`
- **Data Validation:** `../historical-backfill-audit/2026-01-21-DATA-VALIDATION-REPORT.md`

### Schema Files
- `schemas/bigquery/monitoring/scraper_game_availability.sql` (deployed)
- `schemas/bigquery/monitoring/bdl_game_availability_tracking.sql` (deployed)
- `schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql` (ready to deploy)

### Code Files
- `shared/utils/bdl_availability_logger.py` (ready to deploy)
- `orchestration/cloud_functions/scraper_availability_monitor/` (ready to deploy)

---

## Quick Start Commands

### Deploy Existing Monitoring (Do First)
```bash
# Deploy daily alert function
cd orchestration/cloud_functions/scraper_availability_monitor
./deploy.sh --scheduler

# Verify tomorrow at 8 AM ET
```

### Add BDL Game-Level Logging
```bash
# Create table
bq query --nouse_legacy_sql --location=us-west2 < \
  schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql

# Edit scraper (see QUICK-START-BDL-FIXES.md for details)
# Test
python scrapers/balldontlie/bdl_box_scores.py --date 2026-01-20 --debug

# Deploy
# (your deployment process here)
```

### Check Current Status
```sql
-- Daily summary (last 7 days)
SELECT * FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;

-- Completeness dashboard
SELECT * FROM nba_orchestration.v_completeness_status
ORDER BY game_date DESC
LIMIT 7;
```

---

## Risks & Mitigations

### Risk 1: Increased API Usage
**Concern:** Retry queue might spam APIs with duplicate requests

**Mitigation:**
- Exponential backoff (2h → 4h → 8h → 16h)
- Max 10 retries per game
- Rate limiting in retry worker
- Only retry games genuinely missing (not all games)

### Risk 2: False Positives
**Concern:** Alerting on games that are legitimately unavailable

**Mitigation:**
- Grace period: Don't alert for games < 2 hours after end
- Context in alerts: "Expected 5 games (4 completed, 1 in progress)"
- Track historical patterns: "BDL is usually available 2.1h after game end"

### Risk 3: Alert Fatigue
**Concern:** Too many Slack messages

**Mitigation:**
- Daily summary (not per-game alerts)
- Severity levels: Only WARNING/CRITICAL to #nba-alerts
- Deduplication: Same issue within 15 minutes = 1 alert
- Rate limiting: Max 5 alerts/hour

### Risk 4: Backfill Load
**Concern:** Retry queue triggers too many backfills

**Mitigation:**
- Batch retries: Process up to 10 games at once
- Timing: Run during low-traffic hours
- Priority queue: HIGH priority goes first
- Circuit breaker: Stop if consecutive failures

---

## Next Steps

1. **Review this plan** - Discuss priorities with team
2. **Deploy Phase 0** - Enable existing monitoring (15 mins)
3. **Start Phase 1** - BDL game-level logging (30 mins)
4. **Track progress** - Use todo list for implementation
5. **Iterate** - Adjust based on what we learn from Phase 1

---

**Document Created:** January 21, 2026
**Last Updated:** January 21, 2026
**Owner:** Data Engineering Team
**Next Review:** After Phase 1 implementation
