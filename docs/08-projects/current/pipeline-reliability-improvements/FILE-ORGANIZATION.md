# File Organization Plan for docs/08-projects/current/

**Status:** Proposed
**Date:** December 30, 2025

---

## Current State

The `docs/08-projects/current/` directory has grown disorganized with many loose files mixed with project directories.

### Loose Files (13 total)

| File | Type | Proposed Action |
|------|------|-----------------|
| `2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md` | Postmortem | → `postmortems/` |
| `2025-12-29-PIPELINE-ANALYSIS.md` | Analysis | → `pipeline-reliability-improvements/archive/` |
| `2025-12-30-HANDOFF-EVENING.md` | Handoff | → `session-handoffs/2025-12/` |
| `2025-12-30-HANDOFF-NEXT-SESSION.md` | Handoff | → `session-handoffs/2025-12/` |
| `2025-12-30-MORNING-PIPELINE-FIXES.md` | Session notes | → `session-handoffs/2025-12/` |
| `2025-12-30-PIPELINE-RELIABILITY-SESSION.md` | Session notes | → `pipeline-reliability-improvements/archive/` |
| `BOXSCORE-DATA-GAPS-ANALYSIS.md` | Analysis | → `live-data-reliability/` |
| `GAMEBOOK-INCIDENT-POSTMORTEM.md` | Postmortem | → `postmortems/` |
| `LIVE-DATA-PIPELINE-ANALYSIS.md` | Analysis | → `live-data-reliability/` |
| `ORCHESTRATION-IMPROVEMENTS.md` | Plan | → `pipeline-reliability-improvements/` |
| `ORCHESTRATION-TIMING-IMPROVEMENTS.md` | Plan | → `pipeline-reliability-improvements/` |
| `PIPELINE-ROBUSTNESS-PLAN.md` | Plan | → `pipeline-reliability-improvements/` |
| `SESSION-173-MORNING-STATUS.md` | Session notes | → `session-handoffs/2025-12/` |

### Existing Directories (14 total)

| Directory | Purpose | Status |
|-----------|---------|--------|
| `2025-26-season-backfill/` | Season backfill work | Keep |
| `boxscore-monitoring/` | Boxscore monitoring | Keep |
| `challenge-system-backend/` | Challenge system | Keep |
| `email-alerting/` | Email alerting setup | Keep |
| `four-season-backfill/` | Historical backfill | Keep |
| `live-data-reliability/` | Live data reliability | Keep, add related docs |
| `observability/` | Observability work | Keep |
| `pipeline-reliability-improvements/` | **NEW** | Keep, consolidate here |
| `prediction-coverage-fix/` | Prediction coverage | Keep |
| `processor-optimization/` | Processor optimization | Keep |
| `same-day-pipeline-fix/` | Same-day pipeline | Keep |
| `self-healing-pipeline/` | Self-healing work | Consider merging with pipeline-reliability |
| `system-evolution/` | System evolution | Keep |
| `website-ui/` | Website UI work | Keep |

---

## Proposed New Directories

### 1. `session-handoffs/`
For handoff and session notes organized by month:
```
session-handoffs/
├── 2025-12/
│   ├── 2025-12-30-HANDOFF-EVENING.md
│   ├── 2025-12-30-HANDOFF-NEXT-SESSION.md
│   ├── 2025-12-30-MORNING-PIPELINE-FIXES.md
│   └── SESSION-173-MORNING-STATUS.md
└── README.md
```

### 2. `postmortems/`
For incident postmortems:
```
postmortems/
├── 2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md
├── GAMEBOOK-INCIDENT-POSTMORTEM.md
└── README.md
```

### 3. Consolidate into `pipeline-reliability-improvements/`
Move these planning docs into the new project:
- `ORCHESTRATION-IMPROVEMENTS.md`
- `ORCHESTRATION-TIMING-IMPROVEMENTS.md`
- `PIPELINE-ROBUSTNESS-PLAN.md`

---

## Implementation Commands

```bash
# Create new directories
mkdir -p docs/08-projects/current/session-handoffs/2025-12
mkdir -p docs/08-projects/current/postmortems
mkdir -p docs/08-projects/current/pipeline-reliability-improvements/archive

# Move handoff files
mv docs/08-projects/current/2025-12-30-HANDOFF-*.md docs/08-projects/current/session-handoffs/2025-12/
mv docs/08-projects/current/2025-12-30-MORNING-PIPELINE-FIXES.md docs/08-projects/current/session-handoffs/2025-12/
mv docs/08-projects/current/SESSION-173-MORNING-STATUS.md docs/08-projects/current/session-handoffs/2025-12/

# Move postmortems
mv docs/08-projects/current/2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md docs/08-projects/current/postmortems/
mv docs/08-projects/current/GAMEBOOK-INCIDENT-POSTMORTEM.md docs/08-projects/current/postmortems/

# Move pipeline reliability docs
mv docs/08-projects/current/ORCHESTRATION-IMPROVEMENTS.md docs/08-projects/current/pipeline-reliability-improvements/
mv docs/08-projects/current/ORCHESTRATION-TIMING-IMPROVEMENTS.md docs/08-projects/current/pipeline-reliability-improvements/
mv docs/08-projects/current/PIPELINE-ROBUSTNESS-PLAN.md docs/08-projects/current/pipeline-reliability-improvements/

# Move analysis docs to related projects
mv docs/08-projects/current/BOXSCORE-DATA-GAPS-ANALYSIS.md docs/08-projects/current/live-data-reliability/
mv docs/08-projects/current/LIVE-DATA-PIPELINE-ANALYSIS.md docs/08-projects/current/live-data-reliability/

# Archive session-specific analysis
mv docs/08-projects/current/2025-12-29-PIPELINE-ANALYSIS.md docs/08-projects/current/pipeline-reliability-improvements/archive/
mv docs/08-projects/current/2025-12-30-PIPELINE-RELIABILITY-SESSION.md docs/08-projects/current/pipeline-reliability-improvements/archive/
```

---

## After Organization

```
docs/08-projects/current/
├── 2025-26-season-backfill/
├── boxscore-monitoring/
├── challenge-system-backend/
├── email-alerting/
├── four-season-backfill/
├── live-data-reliability/
│   ├── BOXSCORE-DATA-GAPS-ANALYSIS.md
│   └── LIVE-DATA-PIPELINE-ANALYSIS.md
├── observability/
├── pipeline-reliability-improvements/    # Main project
│   ├── README.md
│   ├── TODO.md
│   ├── FILE-ORGANIZATION.md
│   ├── ORCHESTRATION-IMPROVEMENTS.md
│   ├── ORCHESTRATION-TIMING-IMPROVEMENTS.md
│   ├── PIPELINE-ROBUSTNESS-PLAN.md
│   └── archive/
│       ├── 2025-12-29-PIPELINE-ANALYSIS.md
│       └── 2025-12-30-PIPELINE-RELIABILITY-SESSION.md
├── postmortems/                          # New
│   ├── 2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md
│   └── GAMEBOOK-INCIDENT-POSTMORTEM.md
├── prediction-coverage-fix/
├── processor-optimization/
├── same-day-pipeline-fix/
├── self-healing-pipeline/
├── session-handoffs/                     # New
│   └── 2025-12/
│       ├── 2025-12-30-HANDOFF-EVENING.md
│       ├── 2025-12-30-HANDOFF-NEXT-SESSION.md
│       ├── 2025-12-30-MORNING-PIPELINE-FIXES.md
│       └── SESSION-173-MORNING-STATUS.md
├── system-evolution/
└── website-ui/
```

---

## Decision Needed

Should we execute this organization now or defer to a future session?

**Recommendation:** Execute now to clean up before the new year.
