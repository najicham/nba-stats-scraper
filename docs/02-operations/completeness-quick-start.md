# Completeness Checking - Quick Start Guide

**For:** Operations Team
**Purpose:** Get started monitoring and managing completeness checking
**Time to Read:** 5 minutes

---

## What is Completeness Checking?

Completeness checking ensures that processors only run when they have sufficient upstream data. This prevents:
- Low-quality predictions from incomplete data
- Infinite reprocessing loops
- Wasted compute resources

**Key Threshold:** 90% completeness required for production-ready processing

---

## Daily Operations (5 Minutes)

### 1. Check Circuit Breaker Status

```bash
cd /home/naji/code/nba-stats-scraper
./scripts/check-circuit-breaker-status --active-only
```

**What to Look For:**
- **0 active circuit breakers:** ✅ All good
- **1-5 active circuit breakers:** ⚠️  Normal - investigate if persistent
- **>10 active circuit breakers:** 🚨 Alert - systematic issue

### 2. If You See Active Circuit Breakers

**Step 1: Identify the Entity**
```bash
./scripts/check-completeness --entity lebron_james --date 2024-12-15
```

**Step 2: Decide Action**

| Completeness % | Upstream Data | Action |
|----------------|---------------|--------|
| <90% | Missing | ⏳ Wait for scraper fix |
| <90% | Present | 🔧 Investigate (possible bug) |
| >=90% | Present | ✅ Override circuit breaker |

**Step 3: Override if Needed**
```bash
./scripts/override-circuit-breaker \
  --processor player_daily_cache \
  --entity lebron_james \
  --date 2024-12-15 \
  --reason "False positive - data now complete"
```

---

## Common Scenarios

### Scenario 1: Scraper Outage Resolved

**What Happened:** Scraper was down for 2 days, now fixed and backfilled.

**Action:**
```bash
# Bulk override circuit breakers for affected dates
./scripts/bulk-override-circuit-breaker \
  --date-from 2024-12-10 \
  --date-to 2024-12-12 \
  --reason "Scraper outage resolved, data backfilled"
```

### Scenario 2: Early Season (Bootstrap Mode)

**What Happened:** It's early in the season, completeness is low but expected.

**Action:** Nothing! Bootstrap mode should activate automatically for first 30 days.

**Verify Bootstrap Active:**
```sql
bq query --use_legacy_sql=false "
SELECT
  analysis_date,
  COUNT(*) as total,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_count
FROM \`nba_precompute.player_daily_cache\`
WHERE analysis_date >= '2024-10-01' AND analysis_date < '2024-10-31'
GROUP BY analysis_date
ORDER BY analysis_date
"
```

If bootstrap not activating, contact engineering team.

### Scenario 3: Postponed Game

**What Happened:** Game was postponed, causing lower completeness.

**Action:** Verify in schedule table:
```sql
bq query --use_legacy_sql=false "
SELECT game_date, home_team_abbr, away_team_abbr, game_status
FROM \`nba_raw.nbac_schedule\`
WHERE game_date = '2024-12-15' AND game_status = 'POSTPONED'
"
```

If legitimately postponed, no action needed (circuit breaker is correct).

---

## Monitoring Dashboard

**BigQuery:** See `docs/monitoring/completeness-monitoring-dashboard.sql`

**Key Queries to Run Daily:**

### 1. Overall Health
```sql
SELECT
  processor_name,
  COUNT(*) as total_entities,
  AVG(completeness_percentage) as avg_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM (
  SELECT 'player_daily_cache' as processor_name, completeness_percentage, is_production_ready
  FROM \`nba_precompute.player_daily_cache\`
  WHERE analysis_date = CURRENT_DATE() - 1
  -- Add other processors...
)
GROUP BY processor_name;
```

**Target:** 95%+ production_ready_pct

### 2. Active Circuit Breakers
```sql
SELECT
  processor_name,
  entity_id,
  analysis_date,
  completeness_pct,
  skip_reason,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining
FROM \`nba_orchestration.reprocess_attempts\`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY days_remaining DESC;
```

**Alert if:** More than 10 active circuit breakers

---

## Helper Scripts Reference

| Script | Purpose | Example |
|--------|---------|---------|
| `check-circuit-breaker-status` | View circuit breaker status | `./scripts/check-circuit-breaker-status --active-only` |
| `check-completeness` | Check entity completeness | `./scripts/check-completeness --entity lebron_james` |
| `override-circuit-breaker` | Override single entity | See Scenario 1 above |
| `bulk-override-circuit-breaker` | Override date range | See Scenario 2 above |
| `reset-circuit-breaker` | **DESTRUCTIVE** - Requires approval | Contact team lead first |

**Full Documentation:** `scripts/README-COMPLETENESS-SCRIPTS.md`

---

## When to Escalate

### Self-Service (Use Scripts)
- 1-5 circuit breakers tripped
- False positive (data now available)
- Scraper outage resolved

### Team Lead Approval Required
- Bulk override for >7 days
- Threshold tuning
- Reset circuit breaker (destructive)

### Engineering Team (Create Ticket)
- >10 circuit breakers active
- Completeness always <80%
- Bootstrap mode not working
- Circuit breaker bugs

### Emergency (On-Call)
- All processors failing
- Data loss
- Production system down

---

## Production Readiness Checklist

Before going live with a new processor:

- [ ] Schema deployed with 14+ completeness columns
- [ ] Processor code integrated with CompletenessChecker
- [ ] Circuit breaker tracking enabled
- [ ] Bootstrap mode configured (if applicable)
- [ ] Integration tests passing
- [ ] Manual test run successful
- [ ] Monitoring dashboard updated
- [ ] Team trained on helper scripts

---

## Key Files to Bookmark

1. **This Quick Start:** `docs/operations/COMPLETENESS_QUICK_START.md`
2. **Full Runbook:** `docs/operations/completeness-checking-runbook.md` ⭐
3. **Helper Scripts:** `scripts/README-COMPLETENESS-SCRIPTS.md`
4. **Monitoring Queries:** `docs/monitoring/completeness-monitoring-dashboard.sql`

---

## SLAs (Suggested)

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Production Ready % | >95% | <90% |
| Active Circuit Breakers | <5 | >10 |
| Avg Completeness % | >92% | <85% |
| Circuit Breaker Response Time | <4 hours | <24 hours |

---

## Questions?

1. Check the full runbook: `docs/operations/completeness-checking-runbook.md`
2. Review helper scripts: `scripts/README-COMPLETENESS-SCRIPTS.md`
3. Contact engineering team

---

**Status:** ✅ Production Ready
**Last Updated:** 2025-11-22
**Processors:** 7/7 complete (100%)
