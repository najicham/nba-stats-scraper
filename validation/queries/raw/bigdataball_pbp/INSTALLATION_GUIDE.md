# BigDataBall Play-by-Play Validation - Installation Guide

**FILE:** `validation/queries/raw/bigdataball_pbp/INSTALLATION_GUIDE.md`

---

Quick setup guide for BigDataBall validation queries and CLI tool.

---

## 📁 File Structure

Create this directory structure in your project:

```
validation/queries/raw/bigdataball_pbp/
├── README.md
├── discovery/
│   ├── discovery_query_1_date_range.sql
│   ├── discovery_query_2_event_volume.sql
│   ├── discovery_query_3_missing_games.sql
│   ├── discovery_query_4_date_gaps.sql
│   └── discovery_query_5_sequence_integrity.sql
├── season_completeness_check.sql
├── find_missing_games.sql
├── daily_check_yesterday.sql
├── weekly_check_last_7_days.sql
├── event_quality_checks.sql
└── realtime_scraper_check.sql

scripts/
└── validate-bigdataball
```

---

## 🚀 Installation Steps

### Step 1: Create Directories

```bash
cd ~/code/nba-stats-scraper

# Create query directories
mkdir -p validation/queries/raw/bigdataball_pbp/discovery

# Create scripts directory if doesn't exist
mkdir -p scripts
```

### Step 2: Copy Query Files

Save all the SQL artifacts to the appropriate directories:

**Discovery Queries** → `validation/queries/raw/bigdataball_pbp/discovery/`
- Discovery Query 1 → `discovery_query_1_date_range.sql`
- Discovery Query 2 → `discovery_query_2_event_volume.sql`
- Discovery Query 3 → `discovery_query_3_missing_games.sql`
- Discovery Query 4 → `discovery_query_4_date_gaps.sql`
- Discovery Query 5 → `discovery_query_5_sequence_integrity.sql`

**Validation Queries** → `validation/queries/raw/bigdataball_pbp/`
- `season_completeness_check.sql`
- `find_missing_games.sql`
- `daily_check_yesterday.sql`
- `weekly_check_last_7_days.sql`
- `event_quality_checks.sql`
- `realtime_scraper_check.sql`

**README** → `validation/queries/raw/bigdataball_pbp/README.md`

### Step 3: Install CLI Tool

```bash
# Copy CLI tool
cp validate-bigdataball scripts/

# Make executable
chmod +x scripts/validate-bigdataball

# Test it works
scripts/validate-bigdataball --help
```

### Step 4: Verify Setup

```bash
# Check all files present
ls -la validation/queries/raw/bigdataball_pbp/
ls -la validation/queries/raw/bigdataball_pbp/discovery/
ls -la scripts/validate-bigdataball

# Expected output:
# - 6 SQL files in bigdataball_pbp/
# - 5 SQL files in bigdataball_pbp/discovery/
# - 1 README in bigdataball_pbp/
# - 1 executable CLI tool in scripts/
```

---

## 🔍 Step-by-Step First Run

### Phase 1: Discovery (MANDATORY)

**Purpose:** Understand what data exists before creating validation expectations.

```bash
# Option 1: Run via CLI (if discovery queries in place)
./scripts/validate-bigdataball discover

# Option 2: Run manually
cd validation/queries/raw/bigdataball_pbp/discovery

# Run each query and document results
bq query --use_legacy_sql=false < discovery_query_1_date_range.sql
bq query --use_legacy_sql=false < discovery_query_2_event_volume.sql
bq query --use_legacy_sql=false < discovery_query_3_missing_games.sql
bq query --use_legacy_sql=false < discovery_query_4_date_gaps.sql
bq query --use_legacy_sql=false < discovery_query_5_sequence_integrity.sql
```

**Document your findings:**

Create `validation/queries/raw/bigdataball_pbp/DISCOVERY_FINDINGS.md`:

```markdown
# BigDataBall Play-by-Play Discovery Findings

**Date Run:** 2025-10-13

## Query 1: Date Range
- Earliest Date: _____________
- Latest Date: _____________
- Total Games: _____________
- Avg Events Per Game: _____________

## Query 2: Event Volume
- Typical games: 400-600 events? _____________
- Any anomalies: _____________

## Query 3: Missing Games
- Total missing dates: _____________
- Pattern: _____________

## Query 4: Date Gaps
- Off-season gaps: Normal? _____________
- Unexpected gaps: _____________

## Query 5: Sequence Integrity
- Sequences start at 0/1? _____________
- Any gaps or duplicates? _____________

## Conclusions
- Data coverage: ___% complete
- Date ranges for validation: _____________
- Known issues: _____________
```

### Phase 2: Update Query Date Ranges

Based on discovery findings, update date ranges in:

1. `season_completeness_check.sql`
   - Lines with `BETWEEN '2021-10-19' AND '2025-06-20'`
   - Update to match YOUR actual data range

2. `find_missing_games.sql`
   - Line: `WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-20'`
   - Update for season you're validating

3. Other queries as needed

### Phase 3: Run Validation Queries

```bash
# Check season completeness
./scripts/validate-bigdataball season

# Find specific missing games
./scripts/validate-bigdataball missing

# Daily monitoring (set up cron later)
./scripts/validate-bigdataball daily

# Weekly trend analysis
./scripts/validate-bigdataball weekly

# Event quality deep dive
./scripts/validate-bigdataball quality

# Realtime scraper status
./scripts/validate-bigdataball realtime

# Run everything at once
./scripts/validate-bigdataball all
```

### Phase 4: Export Results

```bash
# CSV export for sharing
./scripts/validate-bigdataball all --csv > bigdataball_validation_report.csv

# Save to BigQuery for tracking
./scripts/validate-bigdataball season --table nba_processing.bigdataball_validation
```

---

## 📅 Automation Setup

### Daily Monitoring (Recommended)

Add to crontab to run every morning at 9 AM:

```bash
crontab -e

# Add this line:
0 9 * * * cd /path/to/nba-stats-scraper && ./scripts/validate-bigdataball daily >> logs/bigdataball_daily.log 2>&1
```

### Weekly Report

Run every Monday at 8 AM:

```bash
0 8 * * 1 cd /path/to/nba-stats-scraper && ./scripts/validate-bigdataball weekly >> logs/bigdataball_weekly.log 2>&1
```

### Alerting (Optional)

Create a wrapper script that sends Slack/email alerts:

```bash
#!/bin/bash
# scripts/validate-bigdataball-with-alerts

result=$(./scripts/validate-bigdataball daily)

if echo "$result" | grep -q "❌ CRITICAL"; then
    # Send alert
    echo "$result" | mail -s "BigDataBall Validation CRITICAL" team@example.com
fi

echo "$result"
```

---

## ✅ Verification Checklist

After installation, verify:

- [ ] All 6 validation SQL files in `bigdataball_pbp/`
- [ ] All 5 discovery SQL files in `bigdataball_pbp/discovery/`
- [ ] README.md in `bigdataball_pbp/`
- [ ] CLI tool executable at `scripts/validate-bigdataball`
- [ ] CLI tool shows help: `./scripts/validate-bigdataball --help`
- [ ] Discovery queries run successfully
- [ ] Discovery findings documented
- [ ] Date ranges updated in queries
- [ ] Season validation query works
- [ ] Daily check query works
- [ ] Cron job scheduled (if desired)

---

## 🔧 Troubleshooting

### Issue: "Query file not found"

**Solution:**
```bash
# Check QUERIES_DIR in CLI tool
grep QUERIES_DIR scripts/validate-bigdataball

# Update path if needed:
QUERIES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../validation/queries/raw/bigdataball_pbp" && pwd)"
```

### Issue: "Permission denied"

**Solution:**
```bash
chmod +x scripts/validate-bigdataball
```

### Issue: Partition filter error

**Error:** "Cannot query over table without filter on partition field"

**Solution:** All queries MUST include `WHERE game_date BETWEEN ...`

Check your query has partition filter on BOTH tables if joining.

### Issue: No results from discovery

**Check:**
1. Table name correct? `nba-props-platform.nba_raw.bigdataball_play_by_play`
2. Data actually exists? `SELECT COUNT(*) FROM table`
3. Date filter too restrictive? Try `WHERE game_date >= '2020-01-01'`

---

## 📚 Next Steps

1. **Run discovery queries** → Document findings
2. **Update date ranges** → Match your actual data
3. **Run season check** → Verify 4 seasons present
4. **Investigate issues** → Use missing games query
5. **Set up daily automation** → Catch issues early
6. **Weekly trend analysis** → Monitor data quality

---

## 🆘 Support

**Questions?**
- Review `README.md` in queries directory
- Check master validation guide: `validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- Compare to BDL boxscores (Pattern 3): `validation/queries/raw/bdl_boxscores/`

**Found a bug in queries?**
1. Check partition filters present
2. Verify table name
3. Confirm date ranges match your data

---

**Installation Complete!** 🎉

Start with: `./scripts/validate-bigdataball discover`
