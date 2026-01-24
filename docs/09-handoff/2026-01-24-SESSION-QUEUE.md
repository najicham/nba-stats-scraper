# Session Queue - January 2026

**Created:** 2026-01-24
**Purpose:** Prioritized queue of improvement sessions with handoff docs

---

## Session Priority Order

| Priority | Session | Handoff Doc | Effort | Status |
|----------|---------|-------------|--------|--------|
| **P0** | Cloud Function Consolidation | *(this session)* | 8-12h | 🔄 In Progress |
| **P1** | Test Infrastructure & Fixes | `SESSION-HANDOFF-TEST-INFRASTRUCTURE.md` | 4-6h | 📋 Ready |
| **P1** | Client Pool Migration | `SESSION-HANDOFF-CLIENT-POOL-MIGRATION.md` | 4-6h | 📋 Ready |
| **P1** | Base Class Integration | `SESSION-HANDOFF-BASE-CLASS-INTEGRATION.md` | 6-8h | 📋 Ready |

---

## Session A: Cloud Function Consolidation (P0)

**Why do this first:**
- Highest impact: eliminates ~15MB / 30K+ lines of duplicate code
- Reduces ongoing maintenance burden
- Prevents future sync drift issues
- Relatively low risk (can be done incrementally per CF)

**Scope:**
- 7 cloud functions have local `shared/` directories (~1.9-2.0M each)
- Central `orchestration/shared/` only has 312KB (13 files)
- Need to expand central location and update CF imports

**Key Files:**
- `orchestration/shared/utils/` - Current central location (expand this)
- `orchestration/cloud_functions/*/shared/` - Local copies (delete after migration)
- `bin/maintenance/sync_shared_utils.py` - Sync script (covers only 18 files currently)

**Cloud Functions to Migrate:**
1. `phase2_to_phase3` (2.0M shared/)
2. `phase3_to_phase4` (1.9M shared/)
3. `phase4_to_phase5` (1.9M shared/)
4. `phase5_to_phase6` (1.9M shared/)
5. `daily_health_summary` (1.9M shared/)
6. `self_heal` (1.9M shared/)
7. `auto_backfill_orchestrator` (2.0M shared/)

---

## Session B: Test Infrastructure & Fixes (P1)

**Handoff:** `docs/09-handoff/SESSION-HANDOFF-TEST-INFRASTRUCTURE.md`

**Goal:** Fix 37 remaining test failures, improve test infrastructure

**Key Areas:**
- Fix mock fixture issues (Mock returning Mock instead of proper types)
- Create shared test fixtures package
- Add test isolation for Google Cloud mocking

---

## Session C: Client Pool Migration (P1)

**Handoff:** `docs/09-handoff/SESSION-HANDOFF-CLIENT-POOL-MIGRATION.md`

**Goal:** Migrate from direct client instantiation to pooled clients

**Key Stats:**
- BigQuery: 667 direct → should use pool
- Firestore: 116 direct → should use pool
- Storage: 170 direct → should use pool

---

## Session D: Base Class Integration (P1 - High Risk)

**Handoff:** `docs/09-handoff/SESSION-HANDOFF-BASE-CLASS-INTEGRATION.md`

**Goal:** Integrate TransformProcessorBase into hierarchy

**Impact:**
- Reduce 5,727 lines to ~500 lines
- Affects 50+ processors
- Requires careful testing

---

## Lower Priority (Future)

| Item | Priority | Notes |
|------|----------|-------|
| Add Sentry to processors | P2 | Error visibility |
| Complete exporter migration | P2 | 6 remaining exporters |
| CI/CD improvements | P2 | PR test automation |
| Structured logging | P3 | JSON logs |
| Documentation updates | P3 | API docs, runbooks |

---

## Source Documents

These handoff docs were synthesized from:
- `docs/09-handoff/2026-01-24-SESSION15-IMPROVEMENTS.md`
- `docs/09-handoff/2026-01-24-FUTURE-WORK-ROADMAP.md`
- `docs/08-projects/current/session-122-morning-checkup/FUTURE-IMPROVEMENTS.md`
- `docs/09-handoff/2026-01-24-SESSION16-REFACTORING-HANDOFF.md`
- `docs/09-handoff/2026-01-24-SESSION7-FINAL-REPORT.md`

---

## Quick Reference: Starting a Session

```bash
# Before starting any session:
git status
git log --oneline -5

# Run quick health check
python -m pytest tests/unit/shared/ -q --tb=no
```

---

**Last Updated:** 2026-01-24
