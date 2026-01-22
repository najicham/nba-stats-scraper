# SCRAPER RETRY & DATA ARRIVAL TRACKING - HANDOFF

**Session Date:** 2026-01-22
**Status:** ✅ IMPLEMENTATION COMPLETE - Needs Deployment
**Next Steps:** Deploy BigQuery tables, scheduler jobs, validate tracking works

---

## PROBLEM SOLVED

**Issue:** BDL API has late/missing data (33 games missing Jan 1-21, 76% West Coast)
- Current retry windows ended at 6 AM ET - no daytime retries
- No visibility into when data actually arrives
- No tracking of which retry attempt succeeded

**Solution Built:**
1. Extended retry windows (10 AM, 2 PM, 6 PM catch-ups)
2. Unified data arrival tracking across all scrapers
3. Generalized configuration system for any scraper

---

## FILES CREATED THIS SESSION

### Core Infrastructure
```
schemas/bigquery/nba_orchestration/scraper_data_arrival.sql    # Unified tracking table + 4 views
shared/utils/scraper_availability_logger.py                     # Generalized logger for all scrapers
shared/utils/bdl_availability_logger.py                         # MODIFIED: Fixed game_status=3 filter
shared/config/scraper_retry_config.yaml                         # Central retry configuration
shared/config/scraper_retry_config.py                           # Python config loader
```

### Scripts
```
bin/scraper_completeness_check.py     # Check ANY scraper for missing data
bin/bdl_completeness_check.py         # BDL-specific completeness checker
bin/bdl_latency_report.py             # Generate reports for contacting BDL support
bin/deploy/deploy_catchup_schedulers.sh  # Deploy Cloud Scheduler jobs
```

### Modified Files
```
scrapers/balldontlie/bdl_box_scores.py  # Added unified logger integration
config/workflows.yaml                    # Added 3 BDL catch-up workflows
```

### Documentation
```
docs/08-projects/current/jan-21-critical-fixes/BDL-LATE-DATA-SOLUTION.md  # Full solution doc
docs/08-projects/current/jan-21-critical-fixes/00-INDEX.md                # Updated index
```

---

## DEPLOYMENT REQUIRED

### Step 1: Deploy BigQuery Tables
```bash
# Unified tracking table (new)
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/scraper_data_arrival.sql

# BDL-specific table (may already exist, but run to ensure)
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql
```

### Step 2: Deploy Updated Code
Deploy these services that have code changes:
- Phase 1 scrapers (bdl_box_scores.py modified)

### Step 3: Deploy Cloud Scheduler Jobs
```bash
./bin/deploy/deploy_catchup_schedulers.sh
```

Creates 8 scheduler jobs:
- bdl-catchup-midday (10 AM ET)
- bdl-catchup-afternoon (2 PM ET)
- bdl-catchup-evening (6 PM ET)
- gamebook-catchup-morning (8 AM ET)
- gamebook-catchup-late-morning (11 AM ET)
- odds-catchup-noon (12 PM ET)
- odds-catchup-afternoon (3 PM ET)
- odds-catchup-evening (7 PM ET)

---

## KEY VIEWS CREATED

After deploying `scraper_data_arrival.sql`:

| View | Purpose |
|------|---------|
| `v_scraper_first_availability` | When each game's data first appeared per scraper |
| `v_game_data_timeline` | All sources for one game side-by-side |
| `v_scraper_latency_daily` | Daily health metrics per scraper |
| `v_scraper_latency_report` | Summary for contacting API providers |

---

## VALIDATION INTEGRATION NEEDED

### Add to Daily Validation Checklist
The following checks should be added to `/docs/02-operations/daily-validation-checklist.md`:

```markdown
### Scraper Data Arrival (NEW)
- [ ] Check BDL coverage: `python bin/scraper_completeness_check.py bdl_box_scores`
- [ ] Check all scrapers: `python bin/scraper_completeness_check.py --all`
- [ ] Review latency: Query `v_scraper_latency_daily` for yesterday
```

### Add Validation Query
Create `/validation/queries/scraper_availability/daily_scraper_health.sql`:
```sql
SELECT
  scraper_name,
  coverage_pct,
  latency_p50_hours,
  latency_p90_hours,
  health_score,
  never_available_count AS missing_games
FROM `nba_orchestration.v_scraper_latency_daily`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY coverage_pct ASC;
```

### Expected Thresholds
| Scraper | Min Coverage | Max P90 Latency |
|---------|--------------|-----------------|
| nbac_gamebook | 100% | 4 hours |
| bdl_box_scores | 90% | 12 hours |
| oddsa_player_props | 80% | 6 hours |

---

## CONFIGURATION SYSTEM

### scraper_retry_config.yaml
Central config at `shared/config/scraper_retry_config.yaml`:

```yaml
scrapers:
  bdl_box_scores:
    enabled: true
    priority: HIGH
    lookback_days: 3
    retry_windows:
      - time: "10:00"
      - time: "14:00"
      - time: "18:00"

  oddsa_player_props:
    enabled: true
    priority: HIGH
    lookback_days: 1
    # ... etc
```

### Python Usage
```python
from shared.config.scraper_retry_config import (
    get_retry_config,
    get_all_enabled_scrapers,
    should_retry_now
)

# Check if now is a retry window
should_retry, window = should_retry_now('bdl_box_scores')
```

---

## TRACKING SCHEMA

### scraper_data_arrival Table
Key fields:
- `attempt_timestamp` - When scrape occurred
- `scraper_name` - Which scraper
- `attempt_number` - 1st, 2nd, 3rd attempt
- `was_available` - Did API return data?
- `record_count` - How many records
- `latency_minutes` - Time from game end
- `workflow` - Which window found data

---

## USAGE EXAMPLES

### Check for Missing Data
```bash
# Check BDL (last 3 days)
python bin/scraper_completeness_check.py bdl_box_scores

# Check all enabled scrapers
python bin/scraper_completeness_check.py --all

# Get dates with gaps (for scripting)
python bin/scraper_completeness_check.py bdl_box_scores --dates-only
```

### Generate Latency Report
```bash
# For contacting BDL support
python bin/bdl_latency_report.py --format markdown > bdl_report.md

# Last 7 days
python bin/bdl_latency_report.py --days 7
```

### Query Tracking Data
```sql
-- Games missing BDL but have NBAC
SELECT game_date, matchup, bdl_status, nbac_status
FROM v_game_data_timeline
WHERE bdl_status = 'NEVER_AVAILABLE'
  AND nbac_status != 'NEVER_AVAILABLE';

-- Scraper health dashboard
SELECT scraper_name, coverage_pct, latency_p50_hours, health_score
FROM v_scraper_latency_daily
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

---

## ROOT CAUSES FIXED

1. **BDL Logger Broken** - Was filtering `game_status=3` (Final only), but games aren't Final at 1-2 AM when we scrape. FIXED: Removed filter.

2. **Retry Windows Too Narrow** - All retries ended at 6 AM. FIXED: Added 10 AM, 2 PM, 6 PM catch-up windows.

3. **No Visibility** - Couldn't track when data arrived or which attempt succeeded. FIXED: Created unified tracking table.

---

## NEXT SESSION PRIORITIES

### Immediate (Deploy)
1. Run BigQuery table deployments
2. Deploy updated scraper code
3. Run scheduler deployment script
4. Verify first data appears in tracking tables

### This Week
1. Update daily validation checklist with scraper health checks
2. Create validation query for scraper availability
3. Monitor catch-up effectiveness
4. Run first latency report

### If Issues Found
1. Check Cloud Logging for scraper_availability_logger errors
2. Verify BigQuery table permissions
3. Check scheduler job execution logs

---

## KEY FILE LOCATIONS

```
# Configuration
shared/config/scraper_retry_config.yaml      # Retry settings
shared/config/scraper_retry_config.py        # Config loader

# Logging
shared/utils/scraper_availability_logger.py  # Generalized logger
shared/utils/bdl_availability_logger.py      # BDL-specific logger

# Scripts
bin/scraper_completeness_check.py            # Check any scraper
bin/bdl_completeness_check.py                # BDL checker
bin/bdl_latency_report.py                    # Generate reports
bin/deploy/deploy_catchup_schedulers.sh      # Deploy schedulers

# Schema
schemas/bigquery/nba_orchestration/scraper_data_arrival.sql

# Documentation
docs/08-projects/current/jan-21-critical-fixes/BDL-LATE-DATA-SOLUTION.md
```

---

## VERIFICATION AFTER DEPLOYMENT

```bash
# 1. Verify tables exist
bq show nba-props-platform:nba_orchestration.scraper_data_arrival

# 2. Verify schedulers exist
gcloud scheduler jobs list --location=us-west2 | grep catchup

# 3. After next BDL scrape, check for data
bq query "SELECT COUNT(*) FROM nba_orchestration.scraper_data_arrival WHERE DATE(attempt_timestamp) = CURRENT_DATE()"

# 4. Run completeness check
python bin/scraper_completeness_check.py --all
```

---

**Session Complete. Ready for deployment.**
