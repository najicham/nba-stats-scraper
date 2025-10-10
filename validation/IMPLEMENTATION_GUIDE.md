<!-- File: validation/IMPLEMENTATION_GUIDE.md -->
<!-- Description: Comprehensive implementation guide for the Universal Validation System -->

# Universal Validation System - Implementation Guide

## Overview

This guide provides a **pragmatic, incremental approach** to implementing a universal data validation system for the NBA Props Platform.

**Key Principles:**
- Start simple, expand incrementally
- Reuse existing patterns (ESP N validator as template)
- Config-driven for most checks, custom code for complex logic
- Schedule-aware validation (knows NBA season calendar)
- Automated with actionable remediation

---

## Directory Structure

```
nba-props-platform/
├── validation/
│   ├── __init__.py
│   ├── base_validator.py              # Core framework
│   │
│   ├── configs/                        # YAML configs per processor
│   │   ├── espn_scoreboard.yaml
│   │   ├── bdl_boxscores.yaml
│   │   ├── odds_api_props.yaml
│   │   ├── nbac_schedule.yaml
│   │   ├── nbac_gamebook.yaml
│   │   └── ...
│   │
│   ├── validators/                     # Custom validators
│   │   ├── __init__.py
│   │   ├── espn_scoreboard_validator.py
│   │   ├── bdl_boxscores_validator.py
│   │   ├── gamebook_validator.py
│   │   └── ...
│   │
│   ├── schedules/                      # Validation schedules
│   │   ├── daily_validation.yaml      # Daily checks
│   │   ├── weekly_validation.yaml     # Weekly deep checks
│   │   └── season_start_validation.yaml
│   │
│   └── utils/
│       ├── schedule_utils.py          # NBA season awareness
│       └── remediation_utils.py       # Command generation
│
├── cloud_run/
│   └── validation_runner/             # Orchestrator service
│       ├── main.py
│       ├── Dockerfile
│       └── requirements.txt
│
└── bigquery/
    └── schemas/
        └── validation_results.sql     # Results table schema
```

---

## Implementation Phases

### Phase 1: Core Framework (Week 1-2)

**Goal:** Get base framework working with 2-3 processors

**Tasks:**
1. ✅ Create `base_validator.py` (DONE - see artifact)
2. ✅ Create config schema (DONE - see artifact)
3. Create BigQuery results table
4. Implement schedule-aware date range detection
5. Test with ESPN Scoreboard (refactor existing validator)
6. Test with BDL Box Scores
7. Test with Odds API Props

**Deliverables:**
- Working base validator
- 3 processor configs
- Validation results stored in BigQuery
- Command-line execution working

**Validation:**
```bash
# Test ESPN Scoreboard
python validation/validators/espn_scoreboard_validator.py --last-days=7

# Test BDL Box Scores
python validation/validators/bdl_boxscores_validator.py --season=2024

# Test Odds API Props
python validation/validators/odds_api_props_validator.py --start-date=2024-11-01 --end-date=2024-11-30
```

---

### Phase 2: Schedule Awareness (Week 2-3)

**Goal:** Make validation understand NBA season calendar

**Key Features:**

#### 1. NBA Season Calendar Integration

```python
# File: validation/utils/schedule_utils.py

from datetime import date, datetime
from typing import Tuple, List
from google.cloud import bigquery

class NBASeasonCalendar:
    """Understands NBA season structure and special dates"""
    
    def __init__(self, bq_client: bigquery.Client):
        self.bq_client = bq_client
        self.project_id = 'nba-props-platform'
    
    def get_current_season_year(self) -> int:
        """Determine current season (2024 for 2024-25 season)"""
        today = date.today()
        if today.month >= 10:  # October or later
            return today.year
        else:
            return today.year - 1
    
    def get_season_date_range(self, season_year: int) -> Tuple[str, str]:
        """Get season boundaries (regular season + playoffs)"""
        start_date = f"{season_year}-10-01"
        end_date = f"{season_year + 1}-06-30"
        return start_date, end_date
    
    def get_game_dates(
        self, 
        start_date: str, 
        end_date: str,
        include_preseason: bool = False
    ) -> List[str]:
        """Get actual game dates from schedule"""
        
        preseason_filter = "" if include_preseason else "AND game_type != 'preseason'"
        
        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          {preseason_filter}
        ORDER BY game_date
        """
        
        result = self.bq_client.query(query).result()
        return [str(row.game_date) for row in result]
    
    def is_season_active(self) -> bool:
        """Check if NBA season is currently active"""
        today = date.today()
        month = today.month
        
        # Season runs October-June
        return month >= 10 or month <= 6
    
    def is_playoff_time(self) -> bool:
        """Check if playoffs are happening"""
        today = date.today()
        # Playoffs typically April-June
        return today.month >= 4 and today.month <= 6
    
    def get_special_dates(self, season_year: int) -> Dict[str, List[str]]:
        """Get special dates (All-Star break, Christmas, etc.)"""
        
        query = f"""
        SELECT 
          game_date,
          CASE 
            WHEN game_id LIKE '003%' THEN 'all_star'
            WHEN EXTRACT(MONTH FROM game_date) = 12 AND EXTRACT(DAY FROM game_date) = 25 THEN 'christmas'
            WHEN EXTRACT(MONTH FROM game_date) = 1 AND EXTRACT(DAY FROM game_date) = 18 THEN 'mlk_day'
            ELSE 'regular'
          END as special_type
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE season_year = {season_year}
        """
        
        result = self.bq_client.query(query).result()
        
        special_dates = {
            'all_star': [],
            'christmas': [],
            'mlk_day': []
        }
        
        for row in result:
            date_str = str(row.game_date)
            if row.special_type in special_dates:
                special_dates[row.special_type].append(date_str)
        
        return special_dates
```

#### 2. Smart Date Range Detection

Update `base_validator.py` to use calendar:

```python
from validation.utils.schedule_utils import NBASeasonCalendar

class BaseValidator:
    def __init__(self, config_path: str):
        # ... existing code ...
        self.calendar = NBASeasonCalendar(self.bq_client)
    
    def _auto_detect_date_range(self, season_year: Optional[int]) -> Tuple[str, str]:
        """Auto-detect date range based on current season state"""
        
        if season_year:
            # Use specific season
            return self.calendar.get_season_date_range(season_year)
        
        if not self.calendar.is_season_active():
            # Off-season: validate most recent complete season
            season_year = self.calendar.get_current_season_year() - 1
            return self.calendar.get_season_date_range(season_year)
        
        # In-season: validate recent games
        today = date.today()
        
        if self.calendar.is_playoff_time():
            # Playoffs: last 14 days
            start_date = (today - timedelta(days=14)).isoformat()
        else:
            # Regular season: last 7 days
            start_date = (today - timedelta(days=7)).isoformat()
        
        end_date = today.isoformat()
        
        return start_date, end_date
```

#### 3. Validation Schedules

Create schedule configs that know when to run:

```yaml
# File: validation/schedules/daily_validation.yaml

name: "Daily Validation - In-Season"
description: "Runs daily during NBA season"
enabled: true

# When to run this schedule
schedule:
  active_months: [10, 11, 12, 1, 2, 3, 4, 5, 6]  # Oct-June
  run_time: "08:00"  # 8 AM PT
  timezone: "America/Los_Angeles"

# Processors to validate
processors:
  # Critical: Check yesterday's games
  - name: espn_scoreboard
    date_range: last_1_day
    severity_threshold: error
  
  - name: bdl_boxscores
    date_range: last_1_day
    severity_threshold: error
  
  - name: nbac_gamebook
    date_range: last_1_day
    severity_threshold: error
  
  # Important: Check recent props
  - name: odds_api_props
    date_range: last_7_days
    severity_threshold: warning
  
  # Schedule validation (weekly)
  - name: nbac_schedule
    date_range: current_season
    severity_threshold: warning
    frequency: weekly
```

```yaml
# File: validation/schedules/season_start_validation.yaml

name: "Season Start Deep Validation"
description: "Comprehensive check when season begins"
enabled: true

# When to run
schedule:
  trigger: manual  # Or specific date
  run_time: "06:00"
  timezone: "America/Los_Angeles"

# Deep validation of all processors
processors:
  - name: nbac_schedule
    date_range: current_season
    severity_threshold: error
    checks:
      - completeness
      - team_presence
      - game_count_validation
  
  - name: nbac_player_list
    date_range: current
    severity_threshold: error
    checks:
      - all_teams_have_rosters
      - no_duplicate_players
  
  - name: br_rosters
    date_range: current_season
    severity_threshold: warning
  
  # ... all other processors ...
```

---

### Phase 3: Expand Coverage (Week 3-4)

**Goal:** Add remaining processors

**Priority Order:**

1. **Critical Revenue Impact (Week 3):**
   - ✅ ESPN Scoreboard
   - ✅ BDL Box Scores
   - ✅ Odds API Props
   - NBA.com Gamebook
   - NBA.com Schedule
   - BDL Injuries

2. **Important Support Data (Week 4):**
   - NBA.com Player List
   - Basketball Reference Rosters
   - BDL Active Players
   - BDL Standings
   - Odds API Game Lines

3. **Enhanced Analytics (Future):**
   - BigDataBall Play-by-Play
   - BettingPros Props
   - ESPN Box Scores
   - All remaining processors

**For Each Processor:**
1. Create config file (30 min)
2. Test with base validator (1 hour)
3. Add custom validations if needed (2-4 hours)
4. Document in processor reference (30 min)

---

### Phase 4: Automation & Orchestration (Week 4-5)

**Goal:** Automated daily validation with smart scheduling

#### 1. Validation Orchestrator Service

```python
# File: cloud_run/validation_runner/main.py

from flask import Flask, request, jsonify
from validation.utils.schedule_utils import NBASeasonCalendar
from validation.validators import *
import yaml

app = Flask(__name__)

@app.route('/validate', methods=['POST'])
def run_validation():
    """
    Run validation based on schedule or manual trigger
    
    POST /validate
    {
        "schedule_name": "daily_validation",  // or null for all
        "processors": ["espn_scoreboard"],    // or null for all in schedule
        "date_range": "auto",                 // or specific dates
        "notify": true
    }
    """
    data = request.json
    
    schedule_name = data.get('schedule_name', 'daily_validation')
    processors = data.get('processors')
    notify = data.get('notify', True)
    
    # Load schedule
    with open(f'validation/schedules/{schedule_name}.yaml', 'r') as f:
        schedule = yaml.safe_load(f)
    
    # Check if schedule should run
    calendar = NBASeasonCalendar()
    if not should_run_schedule(schedule, calendar):
        return jsonify({
            'status': 'skipped',
            'reason': 'Schedule not active'
        })
    
    # Run validations
    results = {}
    for proc_config in schedule['processors']:
        if processors and proc_config['name'] not in processors:
            continue
        
        try:
            report = run_processor_validation(proc_config, notify)
            results[proc_config['name']] = {
                'status': report.overall_status,
                'failed_checks': report.failed_checks,
                'remediation_available': len(report.remediation_commands) > 0
            }
        except Exception as e:
            results[proc_config['name']] = {
                'status': 'error',
                'error': str(e)
            }
    
    return jsonify({
        'status': 'completed',
        'schedule': schedule_name,
        'results': results
    })

def should_run_schedule(schedule: dict, calendar: NBASeasonCalendar) -> bool:
    """Check if schedule should run now"""
    
    if not schedule.get('enabled', True):
        return False
    
    # Check month
    active_months = schedule['schedule'].get('active_months', [])
    if active_months and datetime.now().month not in active_months:
        return False
    
    # Check if season active
    if not calendar.is_season_active():
        return False
    
    return True

def run_processor_validation(proc_config: dict, notify: bool):
    """Run validation for a single processor"""
    
    processor_name = proc_config['name']
    
    # Load validator
    config_path = f'validation/configs/{processor_name}.yaml'
    
    # Check if custom validator exists
    try:
        validator_class = getattr(
            __import__(f'validation.validators.{processor_name}_validator'),
            f'{processor_name.title().replace("_", "")}Validator'
        )
        validator = validator_class(config_path)
    except:
        # Use base validator
        from validation.base_validator import BaseValidator
        validator = BaseValidator(config_path)
    
    # Determine date range
    date_range_spec = proc_config.get('date_range', 'auto')
    
    if date_range_spec == 'auto':
        start_date, end_date = None, None
    elif date_range_spec.startswith('last_'):
        days = int(date_range_spec.split('_')[1].replace('day', '').replace('s', ''))
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=days)).isoformat()
    else:
        start_date, end_date = None, None  # Let validator auto-detect
    
    # Run validation
    report = validator.validate(
        start_date=start_date,
        end_date=end_date,
        notify=notify
    )
    
    return report

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
```

#### 2. Cloud Scheduler Setup

```bash
# Daily validation during season
gcloud scheduler jobs create http daily-validation \
    --location=us-west2 \
    --schedule="0 8 * * *" \
    --time-zone="America/Los_Angeles" \
    --uri="https://validation-runner-HASH.us-west2.run.app/validate" \
    --http-method=POST \
    --message-body='{"schedule_name": "daily_validation", "notify": true}'

# Weekly deep validation
gcloud scheduler jobs create http weekly-validation \
    --location=us-west2 \
    --schedule="0 6 * * 0" \
    --time-zone="America/Los_Angeles" \
    --uri="https://validation-runner-HASH.us-west2.run.app/validate" \
    --http-method=POST \
    --message-body='{"schedule_name": "weekly_validation", "notify": true}'
```

---

## Key Design Decisions

### 1. When to Run Validations

**Daily (During Season):**
- Yesterday's game data (ESPN, BDL, Gamebooks)
- Recent props data (last 7 days)
- Data freshness checks

**Weekly:**
- Schedule completeness
- Team presence across all processors
- Cross-source validation
- Historical trending

**Season Start:**
- Complete roster validation
- Schedule completeness
- All processor health checks

**Off-Season:**
- Reduced frequency (weekly instead of daily)
- Focus on historical data integrity
- Preparation for next season

### 2. Notification Strategy

**Immediate Alerts (Severity: ERROR or CRITICAL):**
- Missing yesterday's games
- Critical processor failures
- Schedule data issues

**Daily Digest (Severity: WARNING):**
- Minor data quality issues
- Team presence warnings
- Cross-validation mismatches

**Weekly Summary (Severity: INFO):**
- Overall system health
- Trending metrics
- Completion rates

### 3. Remediation Approach

**Auto-Remediation (Future Enhancement):**
- Simple backfills (< 3 dates)
- Retries for transient failures
- Requires approval workflow

**Manual Remediation (Current):**
- Generate exact commands
- Slack notification with commands
- Manual execution by operator

**Example Notification:**
```
🚨 Validation Failed: ESPN Scoreboard

Missing Data: 3 dates
- 2024-11-15 (5 games)
- 2024-11-16 (8 games)
- 2024-11-17 (6 games)

Remediation Commands:
1. gcloud run jobs execute espn-scoreboard-processor-backfill \
     --args=--start-date=2024-11-15,--end-date=2024-11-17 \
     --region=us-west2

2. After backfill completes, verify:
   python validation/validators/espn_scoreboard_validator.py --start-date=2024-11-15 --end-date=2024-11-17
```

---

## Adding New Processors

**Step-by-Step Process:**

1. **Create Config** (30 min)
   ```yaml
   # validation/configs/new_processor.yaml
   processor:
     name: "new_processor"
     description: "..."
     layers: [bigquery]
   
   bigquery_validations:
     enabled: true
     completeness:
       target_table: "nba_raw.new_processor_table"
       reference_table: "nba_raw.nbac_schedule"
       match_field: "game_date"
   # ...
   ```

2. **Test with Base Validator** (1 hour)
   ```python
   from validation.base_validator import BaseValidator
   
   validator = BaseValidator('validation/configs/new_processor.yaml')
   report = validator.validate(start_date='2024-11-01', end_date='2024-11-30')
   ```

3. **Add Custom Validations if Needed** (2-4 hours)
   ```python
   # validation/validators/new_processor_validator.py
   class NewProcessorValidator(BaseValidator):
       def _run_custom_validations(self, start_date, end_date, season_year):
           # Processor-specific checks
           pass
   ```

4. **Add to Daily Schedule** (5 min)
   ```yaml
   # validation/schedules/daily_validation.yaml
   processors:
     - name: new_processor
       date_range: last_7_days
       severity_threshold: warning
   ```

5. **Test End-to-End** (30 min)
   ```bash
   # Manual test
   python validation/validators/new_processor_validator.py --last-days=7
   
   # Scheduled test
   curl -X POST http://localhost:8080/validate \
     -H "Content-Type: application/json" \
     -d '{"processors": ["new_processor"], "notify": false}'
   ```

---

## BigQuery Results Schema

```sql
-- File: bigquery/schemas/validation_results.sql

CREATE TABLE IF NOT EXISTS `nba_processing.validation_results` (
  processor_name STRING NOT NULL,
  validation_timestamp TIMESTAMP NOT NULL,
  date_range STRING,
  check_name STRING NOT NULL,
  check_type STRING NOT NULL,
  layer STRING NOT NULL,
  passed BOOLEAN NOT NULL,
  severity STRING NOT NULL,
  message STRING,
  affected_count INT64,
  overall_status STRING NOT NULL,
  
  -- Metadata
  execution_duration_seconds FLOAT64,
  validator_version STRING
)
PARTITION BY DATE(validation_timestamp)
CLUSTER BY processor_name, check_type, passed;

-- View for recent failures
CREATE OR REPLACE VIEW `nba_processing.validation_failures_recent` AS
SELECT *
FROM `nba_processing.validation_results`
WHERE passed = FALSE
  AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY validation_timestamp DESC;

-- View for processor health
CREATE OR REPLACE VIEW `nba_processing.processor_health_summary` AS
SELECT 
  processor_name,
  DATE(validation_timestamp) as validation_date,
  COUNT(*) as total_checks,
  SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_checks,
  SUM(CASE WHEN NOT passed THEN 1 ELSE 0 END) as failed_checks,
  ROUND(SUM(CASE WHEN passed THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as pass_rate
FROM `nba_processing.validation_results`
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY processor_name, DATE(validation_timestamp)
ORDER BY validation_date DESC, processor_name;
```

---

## Testing Strategy

### Unit Tests
```python
# tests/validation/test_base_validator.py
import pytest
from validation.base_validator import BaseValidator

def test_date_range_detection():
    """Test auto date range detection"""
    validator = BaseValidator('validation/configs/test_processor.yaml')
    start, end = validator._auto_detect_date_range(season_year=2024)
    
    assert start == '2024-10-01'
    assert end == '2025-06-30'

def test_consecutive_date_grouping():
    """Test grouping consecutive dates"""
    validator = BaseValidator('validation/configs/test_processor.yaml')
    dates = ['2024-11-01', '2024-11-02', '2024-11-03', '2024-11-05', '2024-11-06']
    
    groups = validator._group_consecutive_dates(dates)
    
    assert len(groups) == 2
    assert groups[0] == ('2024-11-01', '2024-11-03')
    assert groups[1] == ('2024-11-05', '2024-11-06')
```

### Integration Tests
```python
# tests/validation/test_integration.py
def test_espn_scoreboard_validation():
    """End-to-end test for ESPN Scoreboard"""
    from validation.validators.espn_scoreboard_validator import EspnScoreboardValidator
    
    validator = EspnScoreboardValidator('validation/configs/espn_scoreboard.yaml')
    report = validator.validate(
        start_date='2024-11-01',
        end_date='2024-11-07',
        notify=False
    )
    
    assert report.overall_status in ['pass', 'warn', 'fail']
    assert report.total_checks > 0
    assert len(report.results) == report.total_checks
```

### Manual Testing Checklist

Before deploying:
- [ ] Test each validator individually
- [ ] Test with missing data (should fail gracefully)
- [ ] Test with complete data (should pass)
- [ ] Test date range auto-detection
- [ ] Test remediation command generation
- [ ] Test notification system integration
- [ ] Test BigQuery results storage
- [ ] Test schedule orchestrator
- [ ] Test Cloud Run deployment

---

## Monitoring & Alerting

### Key Metrics to Track

1. **Validation Health:**
   - Pass rate by processor
   - Failed check trends
   - Time to remediation

2. **System Performance:**
   - Validation execution time
   - BigQuery query costs
   - API rate limits

3. **Data Quality:**
   - Completeness percentage
   - Cross-source consistency
   - Data freshness

### Dashboard Queries

```sql
-- Daily validation summary
SELECT 
  processor_name,
  overall_status,
  COUNT(*) as validation_runs,
  SUM(CASE WHEN passed THEN 1 ELSE 0 END) as checks_passed,
  SUM(CASE WHEN NOT passed THEN 1 ELSE 0 END) as checks_failed
FROM `nba_processing.validation_results`
WHERE DATE(validation_timestamp) = CURRENT_DATE()
GROUP BY processor_name, overall_status
ORDER BY processor_name;

-- Trending issues
SELECT 
  processor_name,
  check_name,
  COUNT(*) as failure_count,
  MAX(validation_timestamp) as last_failure
FROM `nba_processing.validation_results`
WHERE passed = FALSE
  AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, check_name
HAVING COUNT(*) >= 3  -- Failed 3+ times
ORDER BY failure_count DESC;
```

---

## Success Criteria

### Phase 1 (Weeks 1-2)
- ✅ Base validator working
- ✅ 3 processors validated
- ✅ Results stored in BigQuery
- ✅ Command-line execution

### Phase 2 (Week 3)
- ✅ Schedule-aware validation
- ✅ NBA calendar integration
- ✅ Smart date range detection
- ✅ 10+ processors covered

### Phase 3 (Week 4)
- ✅ All critical processors validated
- ✅ Automated daily runs
- ✅ Notification integration
- ✅ Remediation commands working

### Phase 4 (Week 5+)
- ✅ Complete coverage (20+ processors)
- ✅ Historical trending
- ✅ Dashboard (optional)
- ✅ Documentation complete

---

## Next Steps

1. **Immediate (This Week):**
   - Review and approve this design
   - Set up validation directory structure
   - Create BigQuery results table
   - Refactor ESPN validator to use base class

2. **Week 1-2:**
   - Implement base validator
   - Add schedule utils
   - Test with 3 processors

3. **Week 3-4:**
   - Expand to all processors
   - Set up automation
   - Deploy orchestrator

4. **Week 5+:**
   - Monitor and refine
   - Add dashboard
   - Implement auto-remediation (optional)

---

## Questions & Decisions Needed

1. **Notification Channels:**
   - Slack only, or also email?
   - Separate channels for different severities?

2. **Auto-Remediation:**
   - Should simple backfills run automatically?
   - What approval process?

3. **Historical Validation:**
   - How far back to validate?
   - Quarterly deep validation?

4. **Dashboard:**
   - Build custom or use Looker Studio?
   - Public or internal only?

5. **Costs:**
   - BigQuery validation queries budget?
   - Cloud Run orchestrator pricing tier?