# Handoff Documentation Index

Session-by-session development and deployment notes for the NBA Props Platform.

**Purpose:** Historical record of development decisions, session accomplishments, and task continuity.
**Last Updated:** 2025-12-31

---

## Quick Navigation

| What You Need | Document |
|---------------|----------|
| **Current System Status** | [SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md) |
| **AI Session Start** | [WELCOME_BACK.md](./WELCOME_BACK.md) |
| **Active Projects** | [../08-projects/current/](../08-projects/current/) |
| **November 2025 Archive** | [archive/2025-11/](./archive/2025-11/) |

---

## December 2025 (Current - Last 7 Days)

**68 active handoff documents** (Dec 24-31) tracking:
- Pipeline reliability improvements
- Phase 4 & Phase 5 deployment fixes
- Self-healing orchestration design
- Analytics and precompute processor improvements
- Security fixes and IAM policy updates

### Recent Sessions (Last 7 Days)

| Date | Session | Summary |
|------|---------|---------|
| 2025-12-31 | Multiple | Pipeline reliability improvements, orchestration fixes |
| 2025-12-30 | Multiple | Morning pipeline fixes, deployment testing |
| 2025-12-29 | 183-184 | Game ID format fix, pipeline robustness improvements |
| 2025-12-28 | 184 | Same-day pipeline fixes, evening handoff |
| 2025-12-27 | 173 | Documentation deep dive, navigation fixes |
| 2025-12-26 | 169-172 | Same-day predictions, backfill Dec 21-25 |
| 2025-12-25 | 165-168 | Parameter resolver fix, Christmas monitoring |
| 2025-12-24 | 163-164 | Schedule processor fix, deployment verification |

### Key Recent Handoffs

| Document | Description |
|----------|-------------|
| [2025-12-31-MORNING-SESSION-RESULTS.md](./2025-12-31-MORNING-SESSION-RESULTS.md) | Phase 4 deployment and testing results |
| [2025-12-31-OVERNIGHT-SESSION-HANDOFF.md](./2025-12-31-OVERNIGHT-SESSION-HANDOFF.md) | Comprehensive overnight session summary |
| [2025-12-30-NIGHT-SESSION-HANDOFF.md](./2025-12-30-NIGHT-SESSION-HANDOFF.md) | Night session deployment work |
| [2025-12-29-SESSION184-PIPELINE-ROBUSTNESS.md](./2025-12-29-SESSION184-PIPELINE-ROBUSTNESS.md) | Pipeline robustness improvements |

---

## Archives

### December 2025 (Dec 1-23)

**166 handoff documents archived** covering:
- Phase 6 publishing deployment (15 exporters)
- Phase 4 & Phase 5 parallelization (5-10x speedup)
- Comprehensive backfills (all phases)
- 315K+ predictions generated
- Smart reprocessing and AI resolution

See: [archive/2025-12/CONSOLIDATED-DECEMBER-SUMMARY.md](./archive/2025-12/CONSOLIDATED-DECEMBER-SUMMARY.md)

### November 2025 (v1.0 Deployment)

**76 handoff documents archived** covering:
- v1.0 event-driven pipeline deployment
- Bootstrap period implementation
- Fallback system design
- Backfill preparation

See: [archive/2025-11/CONSOLIDATED-NOVEMBER-SUMMARY.md](./archive/2025-11/CONSOLIDATED-NOVEMBER-SUMMARY.md)

### Earlier Sessions

See: [archive/](./archive/) for historical handoffs organized by month.

---

## Standing Documents

These files are not date-specific and persist across sessions:

| Document | Purpose |
|----------|---------|
| [WELCOME_BACK.md](./WELCOME_BACK.md) | Context refresh for AI sessions |
| [NEXT_SESSION.md](./NEXT_SESSION.md) | Immediate next priorities |
| [session-prompt.md](./session-prompt.md) | Standard session start prompt |
| [maintenance-playbook.md](./maintenance-playbook.md) | Routine maintenance procedures |
| [known-data-gaps.md](./known-data-gaps.md) | Known data quality issues |

---

## Document Naming Convention

```
YYYY-MM-DD-description.md    # Date-specific handoffs
YYYY-MM-DD-SESSIONnnn-*.md   # Session-numbered handoffs
NEXT-SESSION-*.md            # Next session guides (no date prefix)
archive/YYYY-MM/             # Archived by month
```

---

## Statistics

| Category | Count |
|----------|-------|
| Active handoffs (last 7 days) | 68 |
| December 2025 (archived Dec 1-23) | 166 |
| November 2025 (archived) | 76 |
| Total handoff documents | 310+ |
| Archived documents | 242 |

---

## Maintenance

**Archival Policy (Updated 2025-12-31):**
- **Active Period:** Handoffs remain in root for 7 days for easy access
- **Archival:** Handoffs older than 7 days → moved to `archive/YYYY-MM/`
- **Monthly Summary:** Create consolidated summary when archiving each month's files
- **Benefits:** Reduced root directory clutter, easier navigation, better organization

**Keep at Root:**
- Last 7 days of handoffs (active development context)
- Standing documents (WELCOME_BACK, NEXT_SESSION, PHASE4-DEPLOYMENT-ISSUE, REPLAY-AUTH-LIMITATION, etc.)
- This README

**Archive Structure:**
```
archive/
├── 2025-11/
│   ├── CONSOLIDATED-NOVEMBER-SUMMARY.md
│   └── [76 handoff files]
├── 2025-12/
│   ├── CONSOLIDATED-DECEMBER-SUMMARY.md
│   └── [166 handoff files]
```
