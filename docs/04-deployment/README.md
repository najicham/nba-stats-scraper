# Deployment Documentation

**File:** `docs/deployment/README.md`
**Created:** 2025-11-22
**Last Updated:** 2025-11-25
**Purpose:** All deployment-related documentation for NBA platform
**Status:** Current

> **Note:** This directory is for **deployment milestone documentation** (production changes).
> For **session-to-session handoffs**, see [`handoff/`](../handoff/).
> For **archived documents**, see [`ARCHIVE_INDEX.md`](../ARCHIVE_INDEX.md).

---

## Quick Links

**📊 Current Status:**
- **Quick overview:** [`../SYSTEM_STATUS.md`](../SYSTEM_STATUS.md) - High-level system status
- **Detailed status:** [`00-deployment-status.md`](00-deployment-status.md) - Complete deployment details

**📜 History:**
- **Deployment log:** [`01-deployment-history.md`](01-deployment-history.md) - Changelog of all deployments

**🔄 Operations:**
- **Rollback guide:** [`02-rollback-procedures.md`](02-rollback-procedures.md) - How to rollback deployments

**📖 Guides:**
- **Phase-specific guides:** [`guides/`](guides/) - How to deploy each phase

---

## Directory Structure

```
deployment/
├── README.md (this file)
├── 00-deployment-status.md     ⭐ LIVING DOC - Current deployment status
├── 01-deployment-history.md    📜 APPEND ONLY - Deployment changelog
├── 02-rollback-procedures.md   🔄 REFERENCE - Rollback guide
│
├── guides/                      📁 Permanent how-to guides
│   ├── phase3-monitoring.md
│   └── [Future: phase1-5 deployment guides]
│
└── archive/                     📁 Historical logs and reports
    └── 2025-11/
        ├── 01-phase-3-4-5-deployment-assessment.md
        ├── 02-deployment-status-summary.md
        ├── 04-phase-3-schema-verification.md
        ├── 05-critical-findings-phase-2-3-status.md
        ├── 06-phase-2-fixes-and-deployment.md
        ├── 07-phase-4-precompute-assessment.md
        ├── 08-phase-4-schema-updates-complete.md
        ├── 09-phase-5-predictions-assessment.md
        └── 10-phase-4-5-schema-deployment-complete.md
```

---

## Document Types

### Living Documents (Updated Regularly)

**`00-deployment-status.md`**
- Current deployment status for all phases
- Last deployment dates
- Current versions
- Known issues
- Next planned deployments
- **Update after each deployment**

### Append-Only Documents

**`01-deployment-history.md`**
- Chronological log of all deployments
- What was deployed, when, by whom
- Changes made
- Issues encountered
- **Add new entries, never delete**

### Reference Documents

**`02-rollback-procedures.md`**
- How to rollback each phase
- Rollback decision criteria
- Recovery procedures
- Verification steps
- **Update when procedures change**

**`guides/`**
- Permanent how-to guides
- Phase-specific deployment instructions
- Best practices
- **Update when deployment process changes**

### Archived Documents

**`archive/YYYY-MM/`**
- Point-in-time deployment logs
- Assessment snapshots
- Issue reports
- Verification results
- **Never updated - historical record**

---

## How to Use This Directory

### "What's currently deployed?"

1. **Quick answer:** Check [`../SYSTEM_STATUS.md`](../SYSTEM_STATUS.md)
2. **Detailed answer:** Check [`00-deployment-status.md`](00-deployment-status.md)

### "When was Phase X deployed?"

1. Check [`01-deployment-history.md`](01-deployment-history.md)
2. Search for phase name
3. See deployment date and details

### "How do I deploy Phase X?"

1. Check [`guides/`](guides/) directory
2. Look for phase-specific guide
3. Follow step-by-step instructions

### "How do I rollback a deployment?"

1. Check [`02-rollback-procedures.md`](02-rollback-procedures.md)
2. Find relevant phase
3. Follow rollback steps

### "What happened during deployment on Date X?"

1. Check [`archive/YYYY-MM/`](archive/) directory
2. Look for deployment logs from that date
3. Read detailed reports

---

## Deployment Workflow

### Before Deployment

1. **Check current status:** `00-deployment-status.md`
2. **Review deployment guide:** `guides/phaseX-deployment.md`
3. **Check prerequisites:** Schemas, dependencies, tests
4. **Plan rollback strategy:** `02-rollback-procedures.md`

### During Deployment

1. **Follow deployment guide** step-by-step
2. **Document issues** encountered
3. **Verify deployment** with health checks
4. **Test basic functionality**

### After Deployment

1. **Update status:** `00-deployment-status.md`
2. **Add to history:** `01-deployment-history.md`
3. **Archive deployment logs:** Move to `archive/YYYY-MM/`
4. **Update `../SYSTEM_STATUS.md`** if major change
5. **Notify team** of changes

---

## Archive Organization

**Naming convention for archived docs:**
- `YYYY-MM-DD-phase-X-description.md`
- Example: `2025-11-22-phase4-schema-deployment.md`

**When to archive:**
- Deployment completion reports
- Assessment snapshots
- Issue investigation reports
- Verification results
- Any point-in-time documentation

**What NOT to archive:**
- Permanent guides (keep in `guides/`)
- Living status docs (keep at root)
- Reference procedures (keep at root)

---

## Related Documentation

### Operations
- **[Operations Guides](../operations/)** - Day-to-day operations
- **[Backfill Operations](../operations/01-backfill-operations-guide.md)** - Running backfills
- **[Cloud Run Args](../operations/03-cloud-run-jobs-arguments.md)** - Passing arguments

### Architecture
- **[Phase Integration Plans](../architecture/)** - System architecture
- **[Implementation Plans](../implementation/)** - Implementation roadmap

### Monitoring
- **[Monitoring Guides](../monitoring/)** - System monitoring
- **[Grafana Setup](../monitoring/01-grafana-monitoring-guide.md)** - Monitoring dashboards

### Processors
- **[Processor Cards](../processor-cards/)** - Quick processor references
- **[Processor Operations](../processors/)** - Phase-specific operations

---

## Current Deployment Status (Quick Reference)

**As of Nov 22, 2025:**

| Phase | Schemas | Processors | Hash Columns | Status |
|-------|---------|------------|--------------|--------|
| Phase 1 | ✅ Deployed | ✅ Deployed | N/A | ✅ Production |
| Phase 2 | ✅ Deployed | ✅ Deployed | ✅ Active | ✅ Production |
| Phase 3 | ✅ Deployed | ✅ Deployed | ✅ Ready | ✅ Production |
| Phase 4 | ✅ Deployed | ⏳ Code updates | ✅ Deployed | ⏳ Ready |
| Phase 5 | ⏳ Partial | ❌ Not deployed | ⏳ Partial | ❌ Not deployed |

**See [`00-deployment-status.md`](00-deployment-status.md) for detailed status.**

---

## Maintenance

**Update `00-deployment-status.md`:**
- After every deployment
- When issues are discovered
- When versions change

**Add to `01-deployment-history.md`:**
- After every deployment (append only)
- Include: date, what, why, who, issues

**Archive temporal docs:**
- Move deployment logs to `archive/YYYY-MM/` after completion
- Keep organized by month

**Review quarterly:**
- Check if guides need updates
- Archive old documents (>6 months)
- Verify status docs are current

---

**Last Review:** 2025-11-22
**Maintained By:** NBA Platform Team
**Next Review:** After next major deployment
