# Welcome Back - AI Session Quick Start

**Last Updated:** 2025-12-27

---

## Current System State

**All 6 pipeline phases are operational in production.**

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | Production | Scrapers (15+ data sources) |
| Phase 2 | Production | Raw Processors (21 processors) |
| Phase 3 | Production | Analytics (5 processors) |
| Phase 4 | Production | Precompute/ML Features (5 processors) |
| Phase 5 | Production | Predictions (coordinator + workers) |
| Phase 6 | Production | Publishing (21 exporters, live scoring) |

---

## Start Here

| Need | Document |
|------|----------|
| **Current operational status** | [SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md) |
| **Find any documentation** | [NAVIGATION_GUIDE.md](../00-start-here/NAVIGATION_GUIDE.md) |
| **Recent session context** | Latest file in this folder (sort by date) |
| **Daily health checks** | [daily-monitoring.md](../02-operations/daily-monitoring.md) |
| **Active projects** | [08-projects/current/](../08-projects/current/) |

---

## Quick Context (December 2025)

### What's Working
- **Same-day predictions**: Morning schedulers (10:30/11:00/11:30 AM ET) generate predictions for today's games
- **Live scoring**: Every 3 minutes during games (7 PM - 1 AM ET)
- **Automated exports**: Results, trends, player profiles to GCS for website
- **End-to-end automation**: Scrapers → Predictions → Exports runs daily without intervention

### Recent Sessions (Last Week)
- **Session 173-174**: Documentation cleanup, navigation fixes
- **Session 169-172**: Same-day prediction schedulers, backfill Dec 21-25
- **Session 165-168**: Parameter resolver fix, Christmas monitoring

### Known Issues
See [SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md) for current issues.

---

## Key Commands

```bash
# Check today's predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY game_date"

# Check for errors
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=10 --format="table(timestamp,resource.labels.service_name,textPayload)" --freshness=2h

# Health check all services
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  echo -n "$svc: "
  curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" | jq -r '.status' 2>/dev/null || echo "failed"
done
```

---

## Documentation Structure

```
docs/
├── 00-start-here/     → SYSTEM_STATUS.md (start here!)
├── 01-architecture/   → Pipeline design, patterns
├── 02-operations/     → Troubleshooting, monitoring, backfills
├── 03-phases/         → Per-phase deep dives
├── 06-reference/      → Processor cards (quick lookups)
├── 08-projects/       → Active (8) and completed (20) projects
└── 09-handoff/        → Session handoffs (you are here)
```

---

## Don't Duplicate - Reference

This file intentionally stays minimal. For detailed status:
- **Schedulers, services, URLs**: See SYSTEM_STATUS.md
- **Daily checks**: See daily-monitoring.md
- **Troubleshooting**: See troubleshooting.md

---

*This document updated automatically when system state changes significantly.*
