# Backfill Documentation

**Created:** 2025-11-21 18:23:00 PST
**Last Updated:** 2025-11-21 18:23:00 PST

Reference guides for backfilling historical NBA data across all phases.

---

## Overview

This directory contains processor-specific backfill documentation that details:
- Historical data backfill status
- Commands used for backfill operations
- Date ranges covered
- Records processed
- Issues encountered and resolved

---

## Available Backfill Guides

### Cross-Phase Guides

#### [Player Name Resolution](name-resolution.md)
**Status:** Active

How the name resolution system works during backfills:
- Two-pass backfill to avoid timing issues
- AI-powered resolution for edge cases
- Alias management and validation

**Use this when:** Running any backfill that involves player data.

---

### Phase 2: Raw Data Backfills

#### 1. [NBA.com Team Boxscore Backfill](01-nbac-team-boxscore-backfill.md)
**Status:** ✅ Complete (2021-2025 seasons)

Complete backfill of NBA.com team boxscore data covering:
- 2021-22 season: 1,312 games
- 2022-23 season: 1,312 games
- 2023-24 season: 1,312 games
- 2024-25 season: In progress

**Use this when:** You need details on team boxscore historical data availability.

---

## General Backfill Operations

For general backfill procedures and strategies, see:

### [Backfill Deployment Guide](../guides/03-backfill-deployment-guide.md)
Complete guide for deploying NBA data processors for backfill operations:
- Setting up backfill jobs
- Creating deployment scripts
- Validation strategies
- Recovery procedures
- Cross-phase dependencies

### [Schema Change Process](../guides/04-schema-change-process.md)
Safe schema change management that includes backfill procedures:
- When backfills are needed after schema changes
- Testing on sample data first
- Executing full backfills safely
- Validation queries

---

## Backfill Status Overview

### Phase 2: Raw Data (GCS → BigQuery)

| Processor | Status | Date Range | Records | Notes |
|-----------|--------|------------|---------|-------|
| **NBA.com Team Boxscore** | ✅ Complete | 2021-2025 | ~4,000 games | See [01-nbac-team-boxscore-backfill.md](01-nbac-team-boxscore-backfill.md) |
| **NBA.com Player Boxscore** | ⏳ Pending | - | - | Not yet backfilled |
| **ESPN Boxscore** | ⏳ Pending | - | - | Not yet backfilled |
| **BallDontLie Active Players** | ✅ Live only | Current | ~500 players | Real-time only, no historical |
| **Odds API Game Lines** | ✅ Live only | Current | Daily | Real-time only, no historical |

### Phase 3: Analytics (BigQuery → BigQuery)

| Processor | Status | Depends On | Notes |
|-----------|--------|------------|-------|
| **Player Game Summary** | ⏳ Ready | Team Boxscore, Player Boxscore | Ready for backfill after Phase 2 complete |
| **Team Offense Summary** | ⏳ Ready | Team Boxscore | Ready for backfill |
| **Team Defense Summary** | ⏳ Ready | Team Boxscore | Ready for backfill |
| **Upcoming Player Context** | 🚧 N/A | Real-time data | No backfill needed |
| **Upcoming Team Context** | 🚧 N/A | Real-time data | No backfill needed |

### Automated Backfill Detection

**Phase 3 Backfill Detection Tool:** `bin/maintenance/phase3_backfill_check.py`
- Finds games with Phase 2 data but missing Phase 3 analytics
- Triggers processing for missing games
- Can be scheduled as daily cron job

**Usage:**
```bash
# Dry run (see what would be processed)
python bin/maintenance/phase3_backfill_check.py --dry-run

# Execute backfill
python bin/maintenance/phase3_backfill_check.py

# Schedule daily at 2 AM
0 2 * * * cd /path && python bin/maintenance/phase3_backfill_check.py >> logs/backfill.log 2>&1
```

---

## Creating New Backfill Documentation

When documenting a new backfill operation, create a new guide following this structure:

**File naming:** `{NN}-{processor-name}-backfill.md`

**Required sections:**
1. **Overview** - What was backfilled and why
2. **Execution** - Commands used, date ranges, parameters
3. **Validation** - Queries to verify completeness
4. **Results** - Records processed, issues encountered
5. **Status** - Current state and next steps

**Template:**
```markdown
# {Processor Name} Backfill

**Created:** YYYY-MM-DD HH:MM:SS PST
**Last Updated:** YYYY-MM-DD HH:MM:SS PST
**Status:** {Status Icon} {Description}

## Overview
- Processor: {name}
- Date Range: {start} to {end}
- Records: {count}
- Purpose: {why}

## Execution
{Commands used}

## Validation
{SQL queries to verify}

## Results
{Outcomes and issues}

## Status
{Current state}
```

---

## Related Documentation

### Operations
- **[Operations Guides](../operations/)** - Day-to-day operations
- **[Deployment Docs](../deployment/)** - Deployment procedures
- **[Monitoring](../monitoring/)** - Health checks and alerts

### Development
- **[Processor Development Guide](../guides/01-processor-development-guide.md)** - Building processors
- **[Processor Patterns](../guides/processor-patterns/)** - Implementation patterns
- **[Schema Change Process](../guides/04-schema-change-process.md)** - Safe schema changes

### Reference
- **[Processor Cards](../processor-cards/README.md)** - Quick 1-2 page processor references
- **[Reference Docs](../reference/README.md)** - System component references

---

## Backfill Best Practices

### Planning
1. **Check dependencies** - Ensure upstream data is complete
2. **Estimate size** - Calculate expected records and cost
3. **Test on sample** - Validate with single day/week first
4. **Schedule wisely** - Run during low-traffic periods

### Execution
1. **Use batch processing** - Process in chunks (days, weeks)
2. **Monitor progress** - Track records processed and errors
3. **Handle failures gracefully** - Implement retry logic
4. **Log everything** - Detailed logs for troubleshooting

### Validation
1. **Count records** - Verify expected vs actual counts
2. **Check completeness** - Ensure no gaps in date ranges
3. **Validate data quality** - Spot check sample records
4. **Compare with source** - Cross-check against raw data

### Documentation
1. **Document immediately** - Create backfill doc during or right after
2. **Include all commands** - Exact commands with parameters
3. **Note all issues** - Document problems and solutions
4. **Update status** - Mark complete with verification date

---

## Common Issues

### "No data found for date range"
**Cause:** Raw data might not exist for that period
**Solution:** Check Phase 2 tables first, verify scraper ran for those dates

### "Partition filter required"
**Cause:** BigQuery partitioned tables need partition filter
**Solution:** Always include `WHERE game_date = ...` or `WHERE game_date BETWEEN ...`

### "Exceeded rate limit"
**Cause:** Too many API calls in short period
**Solution:** Add delays between batches, process smaller chunks

### "Duplicate key violations"
**Cause:** Data already exists in target table
**Solution:** Use MERGE instead of INSERT, or check for existing records first

---

**Last Verified:** 2025-11-21
**Maintained By:** NBA Platform Team
