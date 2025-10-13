# BigDataBall Play-by-Play Validation - Complete Summary

**FILE:** `validation/queries/raw/bigdataball_pbp/VALIDATION_SUMMARY.md`

---

Everything you need to validate BigDataBall enhanced play-by-play data.

---

## 🎯 What You're Validating

**Data Source:** BigDataBall Enhanced Play-by-Play  
**Table:** `nba-props-platform.nba_raw.bigdataball_play_by_play`  
**Business Purpose:** Advanced shot analytics, lineup analysis, event-level betting intelligence  
**Expected Coverage:** 2024-25 NBA season (possibly 2021-2025 based on your note)  
**Expected Volume:** ~400-600 events per game, ~1,200 games per season  
**Pattern:** Pattern 3 (Game-Based, Single Event) - Same as BDL Boxscores

---

## 📦 What I Created For You

### 1. Discovery Queries (5 total) - **RUN THESE FIRST!**

| Query | Purpose | What It Tells You |
|-------|---------|-------------------|
| 1. Date Range | Find actual data coverage | Min/max dates, total games, avg events |
| 2. Event Volume | Check for anomalies | Which games have suspiciously low/high events |
| 3. Missing Games | Cross-check vs schedule | Specific dates with no data |
| 4. Date Gaps | Find continuity issues | Off-season vs unexpected gaps |
| 5. Sequence Integrity | Check event ordering | Gaps or duplicates in event_sequence |

### 2. Validation Queries (6 total) - **Production Use**

| Query | When to Run | What It Checks |
|-------|-------------|----------------|
| `season_completeness_check.sql` | After backfills | All games present, reasonable event counts |
| `find_missing_games.sql` | When completeness fails | Specific missing games for backfill |
| `daily_check_yesterday.sql` | Every morning (automated) | Yesterday's games captured correctly |
| `weekly_check_last_7_days.sql` | Weekly (Mondays) | Trend analysis, spot patterns |
| `event_quality_checks.sql` | Monthly or when investigating | Shot coords, lineups, sequences |
| `realtime_scraper_check.sql` | Anytime | Is scraper running now? |

### 3. CLI Tool - **Easy Execution**

```bash
./scripts/validate-bigdataball [command]

Commands:
  discover   - Run all discovery queries
  season     - Season completeness check
  missing    - Find missing games
  daily      - Check yesterday (for cron)
  weekly     - Last 7 days trend
  quality    - Event quality deep dive
  realtime   - Scraper status
  all        - Run everything
```

### 4. Documentation (3 files)

- **README.md** - Query reference and usage guide
- **Installation Guide** - Step-by-step setup
- **This Summary** - Quick reference and action plan

---

## 🚀 Your Action Plan

### Step 1: Install Everything (15 minutes)

```bash
# 1. Create directories
mkdir -p validation/queries/raw/bigdataball_pbp/discovery
mkdir -p scripts

# 2. Save all SQL files to appropriate locations
#    (See Installation Guide for file list)

# 3. Install CLI tool
cp validate-bigdataball scripts/
chmod +x scripts/validate-bigdataball

# 4. Test
./scripts/validate-bigdataball --help
```

### Step 2: Discovery Phase (30 minutes)

**Critical: Do this BEFORE creating validation expectations!**

```bash
# Run all discovery queries
cd validation/queries/raw/bigdataball_pbp/discovery

bq query --use_legacy_sql=false < discovery_query_1_date_range.sql
# ... run all 5 ...

# Document findings in DISCOVERY_FINDINGS.md
```

**Answer these questions:**
- ✅ What dates do you actually have? (Oct 2024 - Jun 2025? or Oct 2021 - Jun 2025?)
- ✅ How many games total?
- ✅ Average events per game? (~400-600 expected)
- ✅ Any missing dates?
- ✅ Event sequences complete?

### Step 3: Update Query Date Ranges (10 minutes)

Based on discovery findings, update these lines:

**`season_completeness_check.sql`:**
```sql
-- Line ~40: Update these dates
WHEN b.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
-- Update all season ranges to match YOUR actual data
```

**`find_missing_games.sql`:**
```sql
-- Line ~15: Update for season you're checking
WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-20'
```

**Other queries:** Use discovery findings to set appropriate date ranges

### Step 4: Run First Validation (20 minutes)

```bash
# Check season completeness
./scripts/validate-bigdataball season

# Find any missing games
./scripts/validate-bigdataball missing

# Check event quality
./scripts/validate-bigdataball quality
```

**Expected results:**
- ✅ DIAGNOSTICS: All null counts = 0
- ✅ Teams: ~41 home games each (82 total)
- ✅ Events: 400-600 per game average
- ✅ Shots: 70%+ with coordinates
- ✅ Lineups: 80%+ complete

**Red flags:**
- ❌ Teams with <82 games → Run `missing` query
- ❌ Events <300 per game → Data quality issue
- ❌ Shots <70% coords → Processor bug
- ❌ Large sequence gaps → Data corruption

### Step 5: Set Up Daily Automation (10 minutes)

```bash
# Add to crontab
crontab -e

# Daily check at 9 AM (after games processed)
0 9 * * * cd /path/to/nba-stats-scraper && ./scripts/validate-bigdataball daily >> logs/bigdataball_daily.log 2>&1

# Weekly report on Mondays at 8 AM
0 8 * * 1 cd /path/to/nba-stats-scraper && ./scripts/validate-bigdataball weekly >> logs/bigdataball_weekly.log 2>&1
```

---

## 🎓 Key Differences from BDL Boxscores

Since you're familiar with BDL Boxscores validation (Pattern 3), here are the key differences:

| Aspect | BDL Boxscores | BigDataBall Play-by-Play |
|--------|---------------|--------------------------|
| **Records per game** | ~26 (players) | ~400-600 (events) |
| **Completeness metric** | Player count (10-18 per team) | Event count (400-600) |
| **Quality checks** | Player stats completeness | Shot coords, lineups, sequences |
| **Unique challenges** | Name resolution | Event sequence integrity |
| **Data timing** | Immediately after game | ~2 hours after game |

**Adapted from BDL:**
- ✅ Same Pattern 3 structure (game-based, variable records)
- ✅ Same join strategy (date + teams, not game_id)
- ✅ Same diagnostics approach (null checks first)
- ✅ Same team-level aggregation logic

**New for Play-by-Play:**
- 🆕 Event sequence integrity checks
- 🆕 Shot coordinate coverage metrics
- 🆕 Lineup completeness validation
- 🆕 Event type distribution analysis

---

## 📊 Data Quality Standards

### Minimum Acceptable (Critical)
- ✅ All scheduled games present
- ✅ >300 events per game
- ✅ Event sequences start at 0 or 1
- ✅ No null team assignments

### Target Quality (High)
- ✅ 400-600 events per game
- ✅ 70%+ shot coordinate coverage
- ✅ 80%+ full lineup coverage
- ✅ <5 sequence gaps per game

### Exceptional Quality (Bonus)
- ✅ 500+ events per game
- ✅ 90%+ coordinate coverage
- ✅ 95%+ lineup coverage
- ✅ 0 sequence gaps

---

## 🔄 Ongoing Maintenance

### Daily (Automated)
```bash
# 9 AM - Check yesterday's games
./scripts/validate-bigdataball daily
```

### Weekly (Manual)
```bash
# Monday mornings - Trend analysis
./scripts/validate-bigdataball weekly

# Investigate any issues
./scripts/validate-bigdataball quality
```

### Monthly
```bash
# Full season check
./scripts/validate-bigdataball season

# Missing games analysis
./scripts/validate-bigdataball missing
```

### After Backfills
```bash
# Re-run discovery
./scripts/validate-bigdataball discover

# Verify completeness
./scripts/validate-bigdataball season

# Check quality
./scripts/validate-bigdataball quality
```

---

## 🐛 Common Issues & Quick Fixes

### "No data found" during discovery
**Fix:** Check table name and date filter
```sql
-- Verify table exists and has data
SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
WHERE game_date >= '2020-01-01';
```

### "Partition filter required" error
**Fix:** Add `WHERE game_date BETWEEN ...` to BOTH tables in joins
```sql
FROM table1 t1
JOIN table2 t2 ON ...
WHERE t1.game_date BETWEEN '...' AND '...'
  AND t2.game_date BETWEEN '...' AND '...'  -- Don't forget this!
```

### Low event counts (<400 per game)
**Causes:**
- Scraper timeout
- CSV parsing error
- Processor filtering events

**Fix:** Check scraper logs, verify raw CSV files

### Missing shot coordinates
**Causes:**
- BigDataBall data format change
- Processor coordinate extraction bug

**Fix:** Compare recent vs historical games, verify processor logic

### Sequence gaps
**Causes:**
- Events filtered during processing
- CSV parsing skipped rows
- Source data corruption

**Fix:** Compare to raw CSV, check processor filtering

---

## 📚 Related Resources

**This Project:**
- Master Validation Guide: `validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- BDL Boxscores (Pattern 3): `validation/queries/raw/bdl_boxscores/`
- Processor Reference: `validation/PROCESSOR_REFERENCE.md`

**Similar Validations You've Done:**
- BDL Boxscores (Pattern 3) - Variable player counts
- NBA Schedule (Pattern 1) - Fixed records per game
- NBA Injury Report (Pattern 2) - Time-series snapshots
- Odds API Props (Pattern 1) - Multiple bookmakers per game

---

## ✅ Success Checklist

**Installation:**
- [ ] All SQL files saved to correct directories
- [ ] CLI tool installed and executable
- [ ] Test run: `./scripts/validate-bigdataball --help`

**Discovery Phase:**
- [ ] All 5 discovery queries run successfully
- [ ] Findings documented in DISCOVERY_FINDINGS.md
- [ ] Date ranges confirmed (1 season or 4?)
- [ ] Average event counts noted (~400-600?)

**Validation Setup:**
- [ ] Query date ranges updated based on discovery
- [ ] Season completeness check runs clean
- [ ] Missing games query shows results (or empty = good!)
- [ ] Daily check works for yesterday
- [ ] Quality checks pass thresholds

**Automation:**
- [ ] Daily cron job scheduled (9 AM)
- [ ] Weekly cron job scheduled (Monday 8 AM)
- [ ] Logs directory created
- [ ] Alerts configured (optional)

**Production Ready:**
- [ ] 4 full seasons validated (if data exists)
- [ ] All games present (or missing list documented)
- [ ] Event quality meets standards (400-600, 70%+ coords)
- [ ] Team monitoring confident in data quality

---

## 🎉 You're Ready!

You now have:
- ✅ Complete discovery phase queries
- ✅ Production validation queries
- ✅ Easy-to-use CLI tool
- ✅ Automated daily monitoring
- ✅ Comprehensive documentation

**Next Steps:**
1. Run `./scripts/validate-bigdataball discover`
2. Document findings
3. Run `./scripts/validate-bigdataball season`
4. Investigate any issues with `missing` and `quality` commands
5. Set up daily automation with cron

**Questions?** 
- Check README.md for query details
- Review Installation Guide for setup issues
- Compare to BDL Boxscores (same Pattern 3 approach)

---

**Created:** 2025-10-13  
**Pattern:** Pattern 3 (Game-Based, Single Event)  
**Data Source:** BigDataBall Enhanced Play-by-Play  
**Status:** Ready for production use
