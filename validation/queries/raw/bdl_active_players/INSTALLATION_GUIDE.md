# BDL Active Players Validation - Installation Guide

**File:** `validation/queries/raw/bdl_active_players/INSTALLATION_GUIDE.md`

Complete setup instructions for BDL Active Players validation system.

## Prerequisites

- Google Cloud SDK (`gcloud`) installed
- BigQuery command-line tool (`bq`) configured
- Access to `nba-props-platform` project
- Bash shell (Linux, macOS, or WSL on Windows)

## Installation Steps

### 1. Verify Directory Structure

```bash
cd ~/code/nba-stats-scraper  # Or your project root

# Check if validation queries directory exists
ls -la validation/queries/raw/bdl_active_players/
```

Expected output:
```
player_count_check.sql
validation_status_summary.sql
data_quality_check.sql
daily_freshness_check.sql
cross_validate_with_nba_com.sql
team_mismatch_analysis.sql
missing_players_analysis.sql
README.md
INSTALLATION_GUIDE.md
DAILY_MONITORING_GUIDE.md
```

### 2. Install CLI Tool

```bash
# Copy CLI tool to scripts directory
cp validation/queries/raw/bdl_active_players/validate-bdl-active-players scripts/

# Make executable
chmod +x scripts/validate-bdl-active-players

# Add to PATH (optional but recommended)
# Add this line to your ~/.bashrc or ~/.zshrc:
export PATH="$PATH:$HOME/code/nba-stats-scraper/scripts"

# OR create a symlink (alternative)
sudo ln -s ~/code/nba-stats-scraper/scripts/validate-bdl-active-players /usr/local/bin/validate-bdl-active-players
```

### 3. Test Installation

```bash
# Test CLI tool
validate-bdl-active-players --help

# Should show usage information
```

### 4. Verify BigQuery Access

```bash
# Test BigQuery connectivity
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total_players
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
"
```

Expected: Should return a count around 550-600

### 5. Run Initial Validation

```bash
# Run complete validation suite to verify setup
validate-bdl-active-players all
```

Expected: Should run all queries successfully and display results

## CLI Tool Commands

### Basic Commands

```bash
# Daily quick check (recommended for morning monitoring)
validate-bdl-active-players daily

# Player count verification
validate-bdl-active-players count

# Validation status distribution (unique to BDL)
validate-bdl-active-players validation-status

# Data quality check
validate-bdl-active-players quality

# Cross-validation with NBA.com
validate-bdl-active-players cross-validate

# Team mismatch deep dive
validate-bdl-active-players team-mismatches

# Missing players analysis
validate-bdl-active-players missing-players

# Run complete validation suite
validate-bdl-active-players all
```

### Output Format Options

```bash
# Terminal output (default, color-coded)
validate-bdl-active-players count

# CSV output
validate-bdl-active-players count --csv > results.csv

# Save to BigQuery table
validate-bdl-active-players quality --table nba_processing.bdl_quality_check_$(date +%Y%m%d)
```

## Running Queries Manually (Without CLI)

If you prefer to run queries directly:

```bash
cd validation/queries/raw/bdl_active_players/

# Run any query
bq query --use_legacy_sql=false < player_count_check.sql

# Save to CSV
bq query --use_legacy_sql=false --format=csv < player_count_check.sql > results.csv

# Save to BigQuery table
bq query --use_legacy_sql=false \
  --destination_table=nba-props-platform:nba_processing.bdl_player_count_check \
  --replace \
  < player_count_check.sql
```

## Setting Up Automated Daily Monitoring

### Option 1: Cron Job (Linux/macOS)

```bash
# Edit crontab
crontab -e

# Add this line (runs every day at 9 AM)
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-bdl-active-players daily >> ~/logs/bdl_validation.log 2>&1
```

### Option 2: Cloud Scheduler (GCP)

Create a Cloud Scheduler job that runs the validation:

```bash
gcloud scheduler jobs create http bdl-active-players-validation \
  --schedule="0 9 * * *" \
  --uri="https://your-cloud-function-url.com/validate-bdl" \
  --http-method=POST \
  --time-zone="America/Los_Angeles"
```

### Option 3: Manual Daily Check

```bash
# Add this to your morning routine
cd ~/code/nba-stats-scraper
./scripts/validate-bdl-active-players daily

# If issues, run detailed checks:
./scripts/validate-bdl-active-players validation-status
./scripts/validate-bdl-active-players quality
```

## Monitoring Dashboard Setup (Optional)

### Create BigQuery Views for Monitoring

```sql
-- Create a view for daily monitoring
CREATE OR REPLACE VIEW `nba-props-platform.nba_processing.bdl_daily_status` AS
WITH last_update AS (
  SELECT
    CURRENT_DATE() as check_date,
    MAX(last_seen_date) as last_update_date,
    DATE_DIFF(CURRENT_DATE(), MAX(last_seen_date), DAY) as days_since_update,
    COUNT(DISTINCT player_lookup) as total_players,
    COUNT(DISTINCT team_abbr) as total_teams,
    ROUND(100.0 * COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) / COUNT(*), 1) as pct_validated
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
)
SELECT
  *,
  CASE
    WHEN days_since_update <= 2 AND total_teams = 30 AND total_players BETWEEN 550 AND 600
    THEN 'HEALTHY'
    WHEN days_since_update <= 4 OR total_players BETWEEN 500 AND 650
    THEN 'WARNING'
    ELSE 'CRITICAL'
  END as overall_status
FROM last_update;
```

### Query the View

```bash
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_processing.bdl_daily_status\`
"
```

## Alerting Setup

### Option 1: Email Alerts with bq query

```bash
#!/bin/bash
# File: scripts/check_bdl_and_alert.sh

RESULT=$(bq query --use_legacy_sql=false --format=csv "
SELECT overall_status 
FROM \`nba-props-platform.nba_processing.bdl_daily_status\`
")

if echo "$RESULT" | grep -q "CRITICAL"; then
    echo "BDL Active Players validation CRITICAL!" | mail -s "CRITICAL: BDL Validation" your-email@example.com
fi
```

### Option 2: Slack Webhook

```bash
#!/bin/bash
# Add to your validation script

STATUS=$(validate-bdl-active-players daily | grep "CRITICAL")

if [ -n "$STATUS" ]; then
    curl -X POST -H 'Content-type: application/json' \
    --data "{\"text\":\"🔴 BDL Active Players Validation CRITICAL: $STATUS\"}" \
    YOUR_SLACK_WEBHOOK_URL
fi
```

## Troubleshooting Installation

### CLI Tool Not Found

```bash
# Check if script is in PATH
which validate-bdl-active-players

# If not found, use full path or create symlink:
ln -s ~/code/nba-stats-scraper/scripts/validate-bdl-active-players /usr/local/bin/
```

### BigQuery Permission Denied

```bash
# Authenticate with gcloud
gcloud auth login

# Set project
gcloud config set project nba-props-platform

# Test access
bq ls nba-props-platform:nba_raw
```

### Query Execution Fails

```bash
# Verify table exists
bq show nba-props-platform:nba_raw.bdl_active_players_current

# Check if table has data
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_active_players_current\` LIMIT 1
"
```

### Color Output Not Working

The CLI uses ANSI color codes. If colors don't display:

```bash
# Force color output
export TERM=xterm-256color

# Or use plain output:
validate-bdl-active-players daily | cat
```

## Verification Checklist

After installation, verify:

- [ ] CLI tool runs: `validate-bdl-active-players --help`
- [ ] Daily check works: `validate-bdl-active-players daily`
- [ ] BigQuery access confirmed
- [ ] All queries return results
- [ ] Expected player count (~550-600)
- [ ] Expected teams (30)
- [ ] Expected validation rate (55-65%)
- [ ] CSV output works: `--csv` flag
- [ ] BigQuery table output works: `--table` flag

## Next Steps

1. Review `README.md` for query details
2. Read `DAILY_MONITORING_GUIDE.md` for monitoring workflows
3. Set up automated daily monitoring (cron or Cloud Scheduler)
4. Configure alerting (email or Slack)
5. Add to your morning routine

## Support

For issues or questions:
- Check `README.md` for troubleshooting
- Review query comments for expected results
- Check BigQuery logs for errors
- Verify table schema hasn't changed

## Last Updated
October 13, 2025
