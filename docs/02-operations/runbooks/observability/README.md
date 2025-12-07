# Observability Runbooks

**Created:** 2025-12-06
**Last Updated:** 2025-12-06

Operational runbooks for monitoring, tracking, and managing system health and data quality.

---

## Overview

This directory contains runbooks for observability and monitoring tasks:
- Tracking and resolving data quality issues
- Managing failure states and recovery workflows
- Monitoring system health and alerting
- Investigating and resolving operational issues

---

## Available Runbooks

### [Registry Failures](registry-failures.md)
**Status:** Active

Monitor and manage player registry failures during Phase 3 processing:
- Query failure status and trends
- Track resolution lifecycle (failure → resolution → reprocessing)
- Targeted reprocessing after alias creation
- Investigate persistent resolution issues

**Use this when:**
- You see player registry errors in logs
- Players are missing from analytics output
- You need to reprocess games after adding new aliases
- You want to monitor resolution health over time

---

## Quick Links

### Related Documentation

**Design Docs:**
- [Failure Tracking Design](../../../08-projects/current/observability/FAILURE-TRACKING-DESIGN.md) - Technical design for registry failure tracking

**Related Runbooks:**
- [Name Resolution](../backfill/name-resolution.md) - Player name resolution during backfills
- [Backfill Overview](../backfill/README.md) - General backfill procedures

**Tools:**
- `monitoring/resolution_health_check.py` - Automated health checks
- `tools/player_registry/resolve_unresolved_batch.py` - Batch resolution tool
- `tools/player_registry/reprocess_resolved.py` - Reprocessing after resolution

---

## When to Use These Runbooks

### Daily Operations
- **Morning checks:** Review overnight failures and resolution status
- **Pre-deployment:** Verify no outstanding critical failures
- **Post-deployment:** Monitor for new failure patterns

### Issue Investigation
- **Missing player data:** Check registry failures for lookup issues
- **Analytics gaps:** Identify players causing processing failures
- **Data quality alerts:** Investigate source of player name mismatches

### Recovery Operations
- **After alias additions:** Reprocess games with newly resolved players
- **After bulk registry updates:** Validate resolution improvements
- **Backfill validation:** Ensure historical data is complete

---

## Monitoring Best Practices

### Regular Health Checks
1. **Daily:** Check for new failures and resolution trends
2. **Weekly:** Review persistent failures needing manual intervention
3. **Monthly:** Analyze failure patterns and resolution effectiveness

### Alert Thresholds
- **Warning:** > 10 new failures per day
- **Critical:** > 50 failures for single player (indicates systemic issue)
- **Attention:** Failures older than 7 days without resolution

### Resolution Workflow
1. **Detect:** Identify failures via queries or monitoring
2. **Investigate:** Determine root cause (typo, variant, new player)
3. **Resolve:** Add alias or fix data source
4. **Reprocess:** Trigger reprocessing for affected dates
5. **Validate:** Confirm resolution and data completeness

---

## Common Patterns

### New Player Added to League
**Symptom:** Multiple failures for same player starting on specific date
**Solution:** Add player to registry, create initial aliases, reprocess affected dates

### Name Spelling Variant
**Symptom:** Sporadic failures for existing player with slightly different name
**Solution:** Add alias variant to existing player, reprocess failures

### Data Source Inconsistency
**Symptom:** Failures only from specific processor or data source
**Solution:** Investigate source data quality, may need source-specific alias

---

**Last Verified:** 2025-12-06
**Maintained By:** NBA Platform Team
