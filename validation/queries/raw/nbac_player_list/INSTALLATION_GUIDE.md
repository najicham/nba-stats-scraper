# NBA.com Player List Validation - Installation Guide

**File:** `validation/queries/raw/nbac_player_list/INSTALLATION_GUIDE.md`

Complete setup guide for validating the NBA.com Player List data.

## Prerequisites

- `bq` command-line tool (Google Cloud SDK)
- `jq` for JSON parsing (install: `brew install jq` or `apt-get install jq`)
- Access to `nba-props-platform` BigQuery project
- Run from `nba-stats-scraper` root directory

## Step 1: Create Directory Structure

```bash
# From nba-stats-scraper root directory
cd ~/code/nba-stats-scraper

# Create directories
mkdir -p validation/queries/raw/nbac_player_list
mkdir -p validation/queries/raw/nbac_player_list/discovery
mkdir -p scripts
```

## Step 2: Save Query Files

Save the following queries to `validation/queries/raw/nbac_player_list/`:

1. `data_freshness_check.sql`
2. `team_completeness_check.sql`
3. `data_quality_check.sql`
4. `cross_validate_with_bdl.sql`
5. `daily_check_yesterday.sql`
6. `player_distribution_check.sql`
7. `README.md`

Save discovery queries to `validation/queries/raw/nbac_player_list/discovery/`:

1. `discovery_date_range.sql`
2. `discovery_team_distribution.sql`
3. `discovery_duplicates.sql`

## Step 3: Install CLI Tool

```bash
# Save the CLI script
cat > scripts/validate-player-list << 'EOF'
[PASTE THE CLI TOOL CONTENT HERE]
EOF

# Make it executable
chmod +x scripts/validate-player-list

# Test it's accessible
./scripts/validate-player-list --help
```

## Step 4: Add to PATH (Optional)

```bash
# Add to your shell profile (~/.bashrc or ~/.zshrc)
export PATH="$HOME/code/nba-stats-scraper/scripts:$PATH"

# Reload shell
source ~/.bashrc  # or source ~/.zshrc

# Now you can run from anywhere
validate-player-list --help
```

## Step 5: Test Installation

### Quick Test
```bash
# Test CLI tool exists
./scripts/validate-player-list --help

# Should show usage information with all commands
```

### Test Query Execution
```bash
# Run a simple query to test BigQuery connection
./scripts/validate-player-list daily

# Should show:
# ✓ Connected to BigQuery
# ✓ Query executed successfully
# [Results displayed with colors]
```

## Step 6: Discovery Phase (MANDATORY!)

Run discovery queries to understand what data exists:

```bash
# Option 1: Using individual queries
cd validation/queries/raw/nbac_player_list/discovery

bq query --use_legacy_sql=false < discovery_date_range.sql
bq query --use_legacy_sql=false < discovery_team_distribution.sql
bq query --use_legacy_sql=false < discovery_duplicates.sql

# Option 2: Using CLI tool (if discovery command implemented)
./scripts/validate-player-list discovery
```

### What to Look For

**discovery_date_range.sql:**
- `latest_seen`: Should be within 24 hours
- `unique_players`: ~600
- `unique_teams`: 30
- `active_players`: ~390-550
- `null_teams`: 0

**discovery_team_distribution.sql:**
- All 30 NBA teams listed
- Each team: 13-17 active players (typical)
- Recent `newest_update` dates

**discovery_duplicates.sql:**
- Should return **0 rows** (no duplicates)
- If any rows: CRITICAL - primary key violation!

## Step 7: Run Initial Validation

```bash
# Quick health check
./scripts/validate-player-list daily

# Full validation suite
./scripts/validate-player-list all

# Individual checks
./scripts/validate-player-list freshness
./scripts/validate-player-list teams
./scripts/validate-player-list quality
./scripts/validate-player-list bdl-comparison
./scripts/validate-player-list distribution
```

## Step 8: Set Up Daily Monitoring

### Option 1: Cron Job (Linux/Mac)

```bash
# Edit crontab
crontab -e

# Add line (runs at 9 AM daily)
0 9 * * * cd /path/to/nba-stats-scraper && ./scripts/validate-player-list daily >> /var/log/player_list_validation.log 2>&1
```

### Option 2: Manual Schedule

Add to your daily routine:
```bash
# Every morning at 9 AM
./scripts/validate-player-list daily
```

### Option 3: GitHub Actions (if using CI/CD)

```yaml
name: Daily Player List Validation

on:
  schedule:
    - cron: '0 9 * * *'  # 9 AM UTC
  workflow_dispatch:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run validation
        run: ./scripts/validate-player-list daily
```

## Verification Checklist

After installation, verify:

- [ ] Directory structure created
- [ ] All 6 query files in `validation/queries/raw/nbac_player_list/`
- [ ] All 3 discovery queries in `discovery/` subdirectory
- [ ] CLI tool saved and executable (`chmod +x`)
- [ ] `jq` installed and working (`jq --version`)
- [ ] BigQuery access configured (`bq ls` works)
- [ ] CLI help displays (`validate-player-list --help`)
- [ ] Discovery queries run successfully
- [ ] Initial validation completes without errors
- [ ] Daily monitoring scheduled (optional)

## Troubleshooting

### CLI Tool Not Found
```bash
# Make sure you're in the right directory
cd ~/code/nba-stats-scraper

# Run with explicit path
./scripts/validate-player-list --help
```

### Permission Denied
```bash
# Make executable
chmod +x scripts/validate-player-list
```

### Query Directory Not Found
```bash
# Check you're in the root directory
pwd
# Should show: /Users/yourname/code/nba-stats-scraper

# Check directory exists
ls -la validation/queries/raw/nbac_player_list/
```

### BigQuery Connection Issues
```bash
# Test BigQuery access
bq ls nba-props-platform:nba_raw

# Re-authenticate if needed
gcloud auth login
gcloud config set project nba-props-platform
```

### jq Not Installed
```bash
# Mac
brew install jq

# Linux
sudo apt-get install jq

# Verify
jq --version
```

### Color Output Not Working
```bash
# Try running without color parsing
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_list/daily_check_yesterday.sql
```

## Next Steps

After successful installation:

1. **Run Discovery** - Understand your data
2. **Run Daily Check** - Verify current state
3. **Run Full Validation** - Complete suite
4. **Schedule Daily Monitoring** - Automate checks
5. **Set Up Alerts** - Get notified of issues

## Expected Output Examples

### Successful Daily Check
```
================================
Daily Check - Yesterday
================================
ℹ Quick health check for daily monitoring...

=== DAILY CHECK: PLAYER LIST ===
Check Date                    2025-10-13    Sunday

=== UPDATE STATUS ===
Last Update                   2025-10-13    0 days ago          ✅ Updated
Last Processed                2025-10-13 08:15 UTC  3 hours ago

=== DATA COMPLETENESS ===
Teams                         30 of 30                          ✅ All teams present
Active Players                456           Expected: ~390-550  ✅ Normal range
Unique Players                612           Total in table

=== DATA QUALITY ===
Players Without Teams         0                                 ✅ No issues
Season Year                   2024          2024-25

=== OVERALL STATUS ===
Daily Check Result                                              ✅ All systems operational
```

### Critical Issue Example
```
=== UPDATE STATUS ===
Last Update                   2025-10-11    2 days ago          🔴 CRITICAL: Not updating

=== OVERALL STATUS ===
Daily Check Result                                              🔴 CRITICAL: Immediate action required
```

## Support

- Documentation: `validation/queries/raw/nbac_player_list/README.md`
- Query files: `validation/queries/raw/nbac_player_list/*.sql`
- CLI tool: `scripts/validate-player-list`

Last Updated: October 13, 2025
