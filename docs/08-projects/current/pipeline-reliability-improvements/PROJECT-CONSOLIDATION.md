# Project Directory Consolidation Plan

**Created:** December 30, 2025
**Status:** Proposed

---

## Current Structure Analysis

The `docs/08-projects/current/` directory has grown organically with 16 directories. Many projects overlap in scope and should be consolidated for better organization.

---

## Proposed Consolidation

### 1. MERGE INTO `pipeline-reliability-improvements/`

These projects are all aspects of pipeline reliability and should be consolidated:

| Project | Reason | Action |
|---------|--------|--------|
| `self-healing-pipeline/` | Self-healing is core reliability | Merge docs |
| `observability/` | Monitoring is part of reliability | Merge docs |
| `same-day-pipeline-fix/` | Pipeline timing is reliability | Merge or archive |
| `email-alerting/` | Alerting is part of reliability | Merge docs |
| `processor-optimization/` | Optimization affects reliability | Merge relevant docs |
| `boxscore-monitoring/` | Monitoring is part of reliability | Merge docs |

### 2. KEEP SEPARATE (Active/Different Scope)

| Project | Reason |
|---------|--------|
| `2025-26-season-backfill/` | Specific backfill work, different scope |
| `prediction-coverage-fix/` | Active work (Dec 29), extensive docs |
| `challenge-system-backend/` | Different feature entirely |
| `live-data-reliability/` | Specific to live data, could merge later |
| `website-ui/` | Frontend work, different scope |
| `four-season-backfill/` | Historical backfill |
| `system-evolution/` | Architecture evolution |

### 3. NEW ORGANIZATIONAL DIRECTORIES

Already created:
- `session-handoffs/` - Session handoff documents by month
- `postmortems/` - Incident postmortems

---

## Proposed Final Structure

```
docs/08-projects/current/
├── pipeline-reliability-improvements/     # MAIN PROJECT - consolidated
│   ├── README.md                         # Project overview
│   ├── MASTER-TODO.md                    # All tasks in one place
│   ├── TODO.md                           # Quick reference
│   ├── PROJECT-CONSOLIDATION.md          # This file
│   ├── FILE-ORGANIZATION.md              # File org plan
│   │
│   ├── plans/                            # Improvement plans
│   │   ├── PIPELINE-ROBUSTNESS-PLAN.md
│   │   ├── ORCHESTRATION-IMPROVEMENTS.md
│   │   ├── ORCHESTRATION-TIMING-IMPROVEMENTS.md
│   │   └── (from other projects)
│   │
│   ├── monitoring/                       # Monitoring-related docs
│   │   ├── (from observability/)
│   │   ├── (from boxscore-monitoring/)
│   │   └── (from email-alerting/)
│   │
│   ├── self-healing/                     # Self-healing docs
│   │   └── (from self-healing-pipeline/)
│   │
│   ├── optimization/                     # Optimization docs
│   │   └── (from processor-optimization/)
│   │
│   └── archive/                          # Historical session docs
│       └── (session-specific analysis)
│
├── live-data-reliability/                # Keep separate for now
│   ├── BOXSCORE-DATA-GAPS-ANALYSIS.md
│   └── LIVE-DATA-PIPELINE-ANALYSIS.md
│
├── prediction-coverage-fix/              # Keep - active work
│   └── (8 detailed docs from Dec 29)
│
├── 2025-26-season-backfill/              # Keep - specific backfill
├── challenge-system-backend/             # Keep - different feature
├── website-ui/                           # Keep - frontend
├── four-season-backfill/                 # Keep - historical
├── system-evolution/                     # Keep - architecture
│
├── postmortems/                          # NEW - incident reports
│   ├── 2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md
│   └── GAMEBOOK-INCIDENT-POSTMORTEM.md
│
└── session-handoffs/                     # NEW - handoff docs
    └── 2025-12/
        └── (handoff files)
```

---

## Implementation Commands

```bash
# Create subdirectories in pipeline-reliability-improvements
mkdir -p docs/08-projects/current/pipeline-reliability-improvements/plans
mkdir -p docs/08-projects/current/pipeline-reliability-improvements/monitoring
mkdir -p docs/08-projects/current/pipeline-reliability-improvements/self-healing
mkdir -p docs/08-projects/current/pipeline-reliability-improvements/optimization

# Move plans (already in root of pipeline-reliability-improvements)
mv docs/08-projects/current/pipeline-reliability-improvements/PIPELINE-ROBUSTNESS-PLAN.md \
   docs/08-projects/current/pipeline-reliability-improvements/plans/
mv docs/08-projects/current/pipeline-reliability-improvements/ORCHESTRATION-IMPROVEMENTS.md \
   docs/08-projects/current/pipeline-reliability-improvements/plans/
mv docs/08-projects/current/pipeline-reliability-improvements/ORCHESTRATION-TIMING-IMPROVEMENTS.md \
   docs/08-projects/current/pipeline-reliability-improvements/plans/

# Copy key docs from self-healing-pipeline
cp docs/08-projects/current/self-healing-pipeline/README.md \
   docs/08-projects/current/pipeline-reliability-improvements/self-healing/

# Copy key docs from observability
cp docs/08-projects/current/observability/*.md \
   docs/08-projects/current/pipeline-reliability-improvements/monitoring/ 2>/dev/null || true

# Copy key docs from processor-optimization
cp docs/08-projects/current/processor-optimization/*.md \
   docs/08-projects/current/pipeline-reliability-improvements/optimization/ 2>/dev/null || true

# Copy key docs from email-alerting
cp docs/08-projects/current/email-alerting/*.md \
   docs/08-projects/current/pipeline-reliability-improvements/monitoring/ 2>/dev/null || true

# Copy key docs from boxscore-monitoring
cp docs/08-projects/current/boxscore-monitoring/*.md \
   docs/08-projects/current/pipeline-reliability-improvements/monitoring/ 2>/dev/null || true
```

---

## After Consolidation

**Benefits:**
1. Single source of truth for pipeline reliability work
2. Easier to find related documentation
3. Clear project boundaries
4. Reduced duplication

**Risks:**
1. Some historical context may be lost
2. Need to update cross-references

---

## Decision

Execute consolidation?
- **Option A:** Full consolidation now (recommended)
- **Option B:** Partial - just create structure, copy key docs
- **Option C:** Defer to future session

---

*Created: December 30, 2025*
