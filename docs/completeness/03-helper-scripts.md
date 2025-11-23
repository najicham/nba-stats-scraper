# Completeness Checking - Helper Scripts

This directory contains helper scripts for managing completeness checking circuit breakers and troubleshooting data quality issues.

---

## Quick Reference

| Script | Purpose | Use When |
|--------|---------|----------|
| `check-circuit-breaker-status` | View circuit breaker status | Daily monitoring, investigating issues |
| `check-completeness` | Check completeness for specific entity | Diagnosing data quality issues |
| `override-circuit-breaker` | Override circuit breaker for single entity | False positive, data now available |
| `bulk-override-circuit-breaker` | Bulk override for date range | Scraper outage resolved, systematic issue |
| `reset-circuit-breaker` | **DESTRUCTIVE** - Delete all attempts | Circuit breaker bug fixed (requires approval) |

---

## 1. check-circuit-breaker-status

**Purpose:** Monitor circuit breaker status across processors.

**Usage:**
```bash
# Check all circuit breakers
./scripts/completeness/check-circuit-breaker-status

# Check active circuit breakers only
./scripts/completeness/check-circuit-breaker-status --active-only

# Check specific processor
./scripts/completeness/check-circuit-breaker-status --processor player_daily_cache

# Check specific entity
./scripts/completeness/check-circuit-breaker-status --entity lebron_james

# Combine filters
./scripts/completeness/check-circuit-breaker-status --processor player_daily_cache --active-only
```

**Output:**
- Detailed circuit breaker attempts
- Summary by processor
- Active circuit breaker count

**When to Use:**
- Daily health checks
- Before bulk processing
- Investigating why entities aren't processing

---

## 2. check-completeness

**Purpose:** Check completeness metadata for a specific entity across all processors.

**Usage:**
```bash
# Check latest completeness for LeBron James
./scripts/completeness/check-completeness --entity lebron_james

# Check specific date
./scripts/completeness/check-completeness --entity lebron_james --date 2024-12-15

# Check specific processor only
./scripts/completeness/check-completeness --entity lebron_james --processor player_daily_cache

# Check team
./scripts/completeness/check-completeness --entity LAL
```

**Output:**
- Completeness percentage by processor
- Production readiness status
- Multi-window breakdown (for multi-window processors)
- Upstream data availability
- Processing decision reasons

**When to Use:**
- Diagnosing why entity is being skipped
- Investigating data quality issues
- Understanding completeness patterns

---

## 3. override-circuit-breaker

**Purpose:** Override circuit breaker for a single entity (non-destructive).

**Usage:**
```bash
# Override circuit breaker
./scripts/completeness/override-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "Upstream data now available after scraper fix"

# Dry run (preview changes without applying)
./scripts/completeness/override-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "Test reason" \
  --dry-run
```

**What It Does:**
1. Shows current circuit breaker status
2. Asks for confirmation
3. Sets `manual_override_applied = TRUE`
4. Logs reason and user in `notes` field
5. Verifies override applied

**Important:**
- Does NOT automatically reprocess entity (you must trigger processor manually)
- Does NOT delete circuit breaker attempts (only flags as overridden)
- Logs who applied override and why

**When to Use:**
- False positive circuit breaker trip
- Upstream data now available (was temporarily missing)
- Bootstrap mode should have applied but didn't

---

## 4. bulk-override-circuit-breaker

**Purpose:** Bulk override circuit breakers for a date range (non-destructive).

**Usage:**
```bash
# Override all circuit breakers for date range
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-12-10 \
  --date-to 2024-12-15 \
  --reason "Scraper outage resolved, data backfilled"

# Override specific processor only
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-12-10 \
  --date-to 2024-12-15 \
  --processor player_daily_cache \
  --reason "Player data backfilled after scraper fix"

# Dry run (preview impact)
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-12-10 \
  --date-to 2024-12-15 \
  --reason "Test" \
  --dry-run
```

**What It Does:**
1. Shows impact analysis (how many entities affected)
2. Shows sample records
3. Asks for confirmation (requires typing "yes")
4. Bulk updates `manual_override_applied = TRUE`
5. Logs reason and user
6. Verifies bulk override

**When to Use:**
- Scraper outage affecting many entities
- Season boundary affecting all players/teams
- Bootstrap mode detection failed systematically

---

## 5. reset-circuit-breaker

**Purpose:** **DESTRUCTIVE** - Completely delete circuit breaker attempts for an entity.

**⚠️  WARNING:** This is destructive and removes historical tracking data.

**Usage:**
```bash
# Reset circuit breaker (requires multiple confirmations)
./scripts/completeness/reset-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "Circuit breaker bug fixed, reset required. Approved by Team Lead"

# Dry run
./scripts/completeness/reset-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "Test" \
  --dry-run

# Skip confirmation prompts (for automation - use with extreme caution)
./scripts/completeness/reset-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "Approved reason" \
  --i-understand-this-is-destructive
```

**What It Does:**
1. Shows records to be deleted
2. Requires MULTIPLE confirmations:
   - Type entity ID
   - Type "DELETE"
   - Type "yes"
3. Logs reset action (before deleting)
4. Deletes all circuit breaker attempts
5. Resets attempt counter to 0

**When to Use (RARE):**
- Circuit breaker logic had bugs (now fixed)
- Need to completely reset attempt counter
- Approved by team lead

**DO NOT Use For:**
- Normal overrides (use `override-circuit-breaker` instead)
- Routine operations
- Without team lead approval

---

## Common Workflows

### Workflow 1: Daily Health Check

```bash
# 1. Check for active circuit breakers
./scripts/completeness/check-circuit-breaker-status --active-only

# 2. If any found, investigate specific entities
./scripts/completeness/check-completeness --entity lebron_james --date 2024-12-15

# 3. Check upstream data (included in check-completeness output)

# 4. Override if false positive
./scripts/completeness/override-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "Investigated - false positive due to timezone issue"
```

### Workflow 2: After Scraper Outage

```bash
# 1. Fix scraper and backfill missing data
# (scraper team handles this)

# 2. Verify data restored
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba_analytics.player_game_summary\`
WHERE game_date >= '2024-12-10' AND game_date <= '2024-12-15'
GROUP BY game_date
ORDER BY game_date
"

# 3. Bulk override circuit breakers for affected dates
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-12-10 \
  --date-to 2024-12-15 \
  --reason "Scraper outage resolved, data backfilled on 2024-12-16"

# 4. Manually trigger processors for affected dates
# (use processor deployment scripts)
```

### Workflow 3: Investigating Incomplete Data

```bash
# 1. Check entity completeness
./scripts/completeness/check-completeness --entity lebron_james --date 2024-12-15

# 2. Review output to identify:
#    - Which processor(s) incomplete
#    - Expected vs actual counts
#    - Upstream data availability

# 3. Check circuit breaker history
./scripts/completeness/check-circuit-breaker-status --entity lebron_james

# 4. Decide action:
#    - If upstream data missing: Wait for scraper fix
#    - If false positive: Override circuit breaker
#    - If legitimate: No action needed (circuit breaker working correctly)
```

### Workflow 4: New Season Start (Bootstrap Mode Check)

```bash
# 1. Verify bootstrap mode activating
bq query --use_legacy_sql=false "
SELECT
  analysis_date,
  COUNT(*) as total_records,
  AVG(completeness_percentage) as avg_completeness,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_count
FROM \`nba_precompute.player_daily_cache\`
WHERE analysis_date >= '2024-10-01'
  AND analysis_date < '2024-10-31'
GROUP BY analysis_date
ORDER BY analysis_date
"

# 2. If bootstrap mode not activating, check processor code
#    (ensure season_start_date = '2024-10-01')

# 3. If needed, bulk override early season circuit breakers
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-10-01 \
  --date-to 2024-10-30 \
  --reason "Early season bootstrap override - approved by Team Lead"
```

---

## Best Practices

### Do's ✅

- **Always use `--dry-run` first** to preview changes
- **Document reason thoroughly** - include approval if required
- **Check upstream data** before overriding
- **Verify override applied** after running script
- **Monitor after bulk overrides** to ensure no unintended consequences

### Don'ts ❌

- **Don't override without investigating** - Circuit breaker might be correct
- **Don't use reset-circuit-breaker routinely** - It's destructive
- **Don't bulk override without team lead approval** for large date ranges
- **Don't forget to trigger reprocessing** after override
- **Don't override if upstream data genuinely missing** - Wait for scraper fix

---

## Troubleshooting

### "No records found" when checking circuit breaker

**Cause:** Entity has never failed completeness check.

**Action:** No action needed - this is good! Entity is processing successfully.

### "Dry run shows 0 records"

**Cause:** WHERE clause filters don't match any records.

**Action:** Verify:
- Processor name is correct (e.g., `player_daily_cache`, not `player-daily-cache`)
- Entity ID is correct (e.g., `lebron_james`, not `LeBron James`)
- Date format is YYYY-MM-DD

### Override applied but entity still not processing

**Cause:** Override does NOT automatically reprocess.

**Action:**
1. Verify override applied: `./scripts/completeness/check-circuit-breaker-status --entity <entity>`
2. Manually trigger processor for the date
3. Check processor logs for other issues

### Bulk override affecting too many records

**Cause:** Date range too broad or missing processor filter.

**Action:**
1. Use `--dry-run` to preview impact
2. Narrow date range with `--date-from` and `--date-to`
3. Add `--processor` filter to limit scope
4. Run in smaller batches if needed

---

## Related Documentation

- **Quick Start Guide:** [01-quick-start.md](01-quick-start.md)
- **Operational Runbook:** [02-operational-runbook.md](02-operational-runbook.md)
- **Monitoring Guide:** [05-monitoring.md](05-monitoring.md)
- **Implementation Guide:** [04-implementation-guide.md](04-implementation-guide.md)
- **Reference Docs:** [reference/](reference/)

---

## Support

For questions or issues:
1. Check the operational runbook first
2. Review monitoring dashboard queries
3. Check circuit breaker status and entity completeness
4. Escalate to team lead if needed

---

**Safety First:** When in doubt, use `--dry-run` and ask for review before applying overrides.
