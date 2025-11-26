# NBA Gamebook Data Validation Strategy

## 📋 Overview

This document outlines the comprehensive data validation strategy for NBA gamebook data used in our prop betting analytics platform. The approach uses a **two-layered validation system** to ensure data quality while maintaining scraping performance.

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   NBA.com       │    │    Scraper       │    │   GCS Storage   │
│   Source Data   │───▶│  + Light         │───▶│   JSON Files    │
│                 │    │    Validation    │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Alerts &      │◀───│  Comprehensive   │◀───│   Validation    │
│   Monitoring    │    │   Validation     │    │   Triggers      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🎯 Validation Layers

### Layer 1: Scraper Validation (Light & Fast)
**Purpose**: Prevent obviously broken data from being stored  
**When**: During scraping, before storing to GCS  
**Performance**: Must be fast (<100ms per game)

### Layer 2: Post-Scraping Validation (Comprehensive)
**Purpose**: Thorough data quality analysis and monitoring  
**When**: After scraping completes, via triggers or scheduled runs  
**Performance**: Can take seconds per file for thorough analysis

---

## 🚀 Layer 1: Scraper Validation Implementation

### Integration Points

Add validation to your existing scrapers at these points:

#### 1. In Main Scraper Service (`scrapers/main_scraper_service.py`)
```python
from .validation import GamebookLightValidator

class ScraperService:
    def __init__(self):
        self.validator = GamebookLightValidator()
    
    def scrape_game(self, game_code: str) -> bool:
        try:
            # Existing scraping logic
            raw_data = self.fetch_gamebook_data(game_code)
            
            # Light validation before storage
            validation_result = self.validator.validate_scraped_data(raw_data)
            if not validation_result.is_valid:
                logger.warning(f"Validation failed for {game_code}: {validation_result.errors}")
                return False  # Trigger retry
            
            # Store if validation passes
            self.store_gamebook_data(game_code, raw_data)
            return True
            
        except Exception as e:
            logger.error(f"Scraping failed for {game_code}: {e}")
            return False
```

#### 2. In NBA.com Scraper (`scrapers/nbacom/gamebook_scraper.py`)
```python
def process_gamebook_response(self, response_data: dict, game_code: str) -> dict:
    # Existing parsing logic
    parsed_data = self.parse_gamebook_data(response_data)
    
    # Quick validation checks
    validation_errors = []
    
    # Required fields check
    required_fields = ['game_code', 'date', 'away_team', 'home_team', 'active_players']
    for field in required_fields:
        if field not in parsed_data or not parsed_data[field]:
            validation_errors.append(f"Missing required field: {field}")
    
    # Basic format validation
    if 'game_code' in parsed_data:
        if not re.match(r'\d{8}/[A-Z]{6}', parsed_data['game_code']):
            validation_errors.append(f"Invalid game_code format: {parsed_data['game_code']}")
    
    # Team code validation
    valid_teams = {'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                   'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                   'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'}
    
    if parsed_data.get('away_team') not in valid_teams:
        # Check if this might be a special game
        if not self._is_likely_special_game(parsed_data):
            validation_errors.append(f"Invalid away_team: {parsed_data.get('away_team')}")
    
    if validation_errors:
        raise ScrapingValidationError(f"Validation failed: {validation_errors}")
    
    return parsed_data

def _is_likely_special_game(self, data: dict) -> bool:
    """Quick check for special games to avoid false positives"""
    if 'date' in data:
        try:
            game_date = datetime.strptime(data['date'], '%Y-%m-%d')
            # All-Star weekend or preseason
            if (game_date.month == 2 and 10 <= game_date.day <= 20) or \
               (game_date.month in [9, 10] and game_date.day < 15):
                return True
        except ValueError:
            pass
    return False
```

### 3. Create Light Validator Class (`scrapers/validation.py`)
```python
from dataclasses import dataclass
from typing import List, Dict, Any
import re
from datetime import datetime

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]

class GamebookLightValidator:
    """Fast validation for scraped data before storage"""
    
    REQUIRED_FIELDS = ['game_code', 'date', 'away_team', 'home_team', 'active_players']
    VALID_TEAMS = {'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                   'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                   'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'}
    
    def validate_scraped_data(self, data: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
        
        # Validate game_code format
        if 'game_code' in data:
            if not re.match(r'\d{8}/[A-Z]{6}', data['game_code']):
                errors.append(f"Invalid game_code format: {data['game_code']}")
        
        # Validate date format
        if 'date' in data:
            try:
                datetime.strptime(data['date'], '%Y-%m-%d')
            except ValueError:
                errors.append(f"Invalid date format: {data['date']}")
        
        # Quick team validation (with special game allowance)
        is_special = self._is_special_game(data)
        
        if 'away_team' in data and data['away_team'] not in self.VALID_TEAMS:
            if is_special:
                warnings.append(f"Non-standard away team in special game: {data['away_team']}")
            else:
                errors.append(f"Invalid away team: {data['away_team']}")
        
        if 'home_team' in data and data['home_team'] not in self.VALID_TEAMS:
            if is_special:
                warnings.append(f"Non-standard home team in special game: {data['home_team']}")
            else:
                errors.append(f"Invalid home team: {data['home_team']}")
        
        # Validate minimum player count
        if 'active_players' in data:
            if len(data['active_players']) < 10:
                warnings.append(f"Low player count: {len(data['active_players'])}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _is_special_game(self, data: Dict[str, Any]) -> bool:
        """Quick special game detection"""
        if 'date' in data:
            try:
                game_date = datetime.strptime(data['date'], '%Y-%m-%d')
                # All-Star or preseason
                return (game_date.month == 2 and 10 <= game_date.day <= 20) or \
                       (game_date.month in [9, 10] and game_date.day < 15)
            except ValueError:
                pass
        return False
```

---

## 🔍 Layer 2: Comprehensive Validation

### Using the Existing Validation Script

The comprehensive validation script (`scripts/validate_gamebook_data.py`) provides thorough analysis including:

- **Schema validation**: Complete structure verification
- **Business logic validation**: Cross-field consistency
- **Statistical validation**: Player stat reasonableness
- **Special game detection**: All-Star, preseason identification
- **Data quality metrics**: Success rates, error categorization

### Integration with Data Pipeline

#### 1. Pub/Sub Triggered Validation
```yaml
# Cloud Function trigger after scraping completes
name: comprehensive-validation
trigger: 
  pubsub_topic: gamebook-scraping-complete
runtime: python39

# Function code
def validate_scraped_data(cloud_event):
    """Triggered when scraping job completes"""
    
    # Get scraping job details from message
    job_data = json.loads(base64.b64decode(cloud_event.data['message']['data']))
    date_range = job_data.get('date_range', 'today')
    
    # Run appropriate validation
    if date_range == 'today':
        cmd = ['python', 'scripts/validate_gamebook_data.py', '--today', '--sample-size', '50']
    elif date_range == 'season':
        cmd = ['python', 'scripts/validate_gamebook_data.py', '--this-week', '--sample-size', '200']
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Parse results and send alerts if needed
    if result.returncode != 0:
        send_validation_alert(result.stdout, result.stderr)
```

#### 2. Scheduled Validation Jobs
```yaml
# workflows/validation/daily_validation.yaml
name: daily-validation
schedule: "0 1 * * *"  # 1 AM daily

steps:
  - name: validate-yesterday
    image: gcr.io/your-project/nba-validator
    command: ["python", "scripts/validate_gamebook_data.py"]
    args: ["--yesterday", "--sample-size", "100"]
    
  - name: validate-this-week
    image: gcr.io/your-project/nba-validator  
    command: ["python", "scripts/validate_gamebook_data.py"]
    args: ["--this-week", "--sample-size", "200"]
    
  - name: alert-on-failure
    if: failure()
    command: ["python", "scripts/send_alert.py"]
    args: ["--type", "validation-failure"]
```

---

## ⏰ Operational Schedule

### Daily Operations (During Season)

| Time | Validation Type | Purpose | Sample Size |
|------|----------------|---------|-------------|
| **Real-time** | Scraper validation | Prevent bad data storage | All scraped games |
| **30 min after scraping** | Today's games | Quick quality check | 20-50 games |
| **1:00 AM** | Yesterday's games | Complete daily validation | All yesterday's games |
| **1:30 AM** | This week's games | Trending analysis | 100-200 games |

### Weekly Operations

| Day | Validation Type | Purpose |
|-----|----------------|---------|
| **Monday** | Previous week comprehensive | Weekly data quality report |
| **Friday** | Current season sample | Season-wide quality trends |

### Monthly Operations

| Schedule | Validation Type | Purpose |
|----------|----------------|---------|
| **1st of month** | Full season scan | Comprehensive quality audit |
| **Mid-month** | Special games review | All-Star, playoff validation |

---

## 🚨 Alert Strategy

### Alert Levels

#### 🟢 **INFO**: Normal operations
- Successful validation runs
- Expected special games detected
- Minor warnings (high minutes, unusual stats)

#### 🟡 **WARNING**: Attention needed
- 5-10% validation failure rate
- Multiple games with missing optional fields
- Unusual team codes in non-special games

#### 🔴 **ERROR**: Immediate action required
- >10% validation failure rate
- Schema errors (missing required fields)
- Complete scraping failures

### Alert Channels

#### Slack Integration
```python
def send_slack_alert(validation_stats, level="WARNING"):
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    
    color = {"INFO": "good", "WARNING": "warning", "ERROR": "danger"}[level]
    
    message = {
        "attachments": [{
            "color": color,
            "title": f"NBA Data Validation Alert - {level}",
            "fields": [
                {"title": "Success Rate", "value": f"{validation_stats.success_rate:.1f}%", "short": True},
                {"title": "Files Processed", "value": str(validation_stats.total_files), "short": True},
                {"title": "Errors", "value": str(validation_stats.invalid_files), "short": True},
                {"title": "Special Games", "value": str(len(validation_stats.special_games)), "short": True}
            ],
            "text": f"Validation completed for {validation_stats.date_range}"
        }]
    }
    
    requests.post(webhook_url, json=message)
```

#### Email Alerts (for critical failures)
```python
def send_email_alert(validation_stats):
    if validation_stats.success_rate < 90:  # Critical threshold
        send_email(
            to="data-team@company.com",
            subject="CRITICAL: NBA Data Validation Failure",
            body=f"""
            Validation failed with {validation_stats.success_rate:.1f}% success rate.
            
            Errors found:
            {chr(10).join(validation_stats.errors[:10])}
            
            Immediate investigation required.
            """
        )
```

### Alert Configuration
```python
# scripts/validation_alerting.py
ALERT_THRESHOLDS = {
    'critical_success_rate': 90.0,    # Below this = email alert
    'warning_success_rate': 95.0,     # Below this = slack warning
    'max_schema_errors': 3,           # Above this = immediate alert
    'max_special_games': 15           # Above this = review needed
}

def determine_alert_level(stats):
    if stats.success_rate < ALERT_THRESHOLDS['critical_success_rate']:
        return "ERROR"
    elif stats.success_rate < ALERT_THRESHOLDS['warning_success_rate']:
        return "WARNING" 
    elif stats.schema_errors > ALERT_THRESHOLDS['max_schema_errors']:
        return "ERROR"
    else:
        return "INFO"
```

---

## 🛠️ Implementation Guide

### Phase 1: Add Scraper Validation (Week 1)
1. Create `scrapers/validation.py` with light validator
2. Integrate validation into existing scrapers
3. Add validation error handling and retry logic
4. Test with current scraping workflows

### Phase 2: Enhanced Monitoring (Week 2)
1. Deploy comprehensive validation script to Cloud Run
2. Set up Pub/Sub triggers after scraping jobs
3. Implement basic Slack alerting
4. Create daily validation scheduled jobs

### Phase 3: Advanced Alerting (Week 3)
1. Implement email alerts for critical failures
2. Create validation dashboards
3. Add trend analysis and reporting
4. Fine-tune alert thresholds based on observed patterns

### Phase 4: Operational Integration (Week 4)
1. Document runbooks for validation failures
2. Create automated remediation for common issues
3. Implement validation metrics in monitoring dashboards
4. Train team on validation alert responses

---

## 📊 Usage Examples

### During Development
```bash
# Test individual game validation
python scripts/validate_gamebook_data.py --file "gs://nba-scraped-data/nba-com/gamebooks-data/2025-10-15/20251015-LAKLAL/timestamp.json"

# Validate small sample for testing
python scripts/validate_gamebook_data.py --sample-size 10
```

### Daily Operations
```bash
# Morning validation of yesterday's games
python scripts/validate_gamebook_data.py --yesterday

# Quick check of today's games after scraping
python scripts/validate_gamebook_data.py --today --sample-size 20

# Weekly quality review
python scripts/validate_gamebook_data.py --this-week --sample-size 100
```

### Season Management
```bash
# Validate entire current season
python scripts/validate_gamebook_data.py --season "2025-26" --sample-size 500

# End-of-season comprehensive audit
python scripts/validate_gamebook_data.py --season "2025-26" --full-scan
```

### Troubleshooting
```bash
# Investigate specific date range issues
python scripts/validate_gamebook_data.py --start-date "2025-10-15" --end-date "2025-10-22" --full-scan

# Check for special game handling
python scripts/validate_gamebook_data.py --season "2025-26" --show-special-games
```

---

## 🎯 Benefits for Prop Betting Analytics

### Data Reliability
- **Confidence**: 95%+ success rates ensure reliable prop betting data
- **Early Detection**: Catch data issues before they affect betting models
- **Consistency**: Standardized validation across all data sources

### Operational Efficiency  
- **Automated Monitoring**: Reduce manual data quality checks
- **Quick Recovery**: Fast identification and remediation of data issues
- **Scalability**: Handle increasing data volumes with consistent quality

### Business Impact
- **Risk Reduction**: Prevent prop betting decisions based on bad data
- **Competitive Edge**: Higher data quality than competitors
- **Compliance**: Maintain audit trails for regulatory requirements

---

## 📚 Related Documentation

- [NBA Data Pipeline Architecture](../architecture.md)
- [Scraper Testing Guide](../scraper-testing-guide.md)
- [Monitoring Guide](../monitoring-guide.md)
- [Troubleshooting Guide](../troubleshooting.md)

---

## 🔄 Maintenance and Updates

### Monthly Reviews
- Analyze validation patterns and adjust thresholds
- Review special game detection accuracy
- Update team codes for trades/relocations
- Assess alert effectiveness and adjust channels

### Seasonal Updates
- Update season date ranges for new NBA seasons
- Review and update statistical validation ranges
- Assess new game types or format changes
- Update documentation with lessons learned

### Continuous Improvement
- Monitor false positive/negative rates
- Gather feedback from data consumers
- Optimize validation performance
- Enhance alert messaging and actionability
