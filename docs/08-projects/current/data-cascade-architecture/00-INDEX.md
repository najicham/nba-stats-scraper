# Data Cascade Architecture Project

**Created:** January 22, 2026
**Status:** Infrastructure Exists - Needs Consistent Usage
**Priority:** HIGH - Architectural Integrity
**Related:** `team-boxscore-data-gap-incident/`
**Updated:** January 23, 2026 - Key finding: infrastructure already implemented!

---

## KEY FINDING (Jan 23, 2026)

**The infrastructure for historical completeness tracking ALREADY EXISTS!**

| Component | Location | Status |
|-----------|----------|--------|
| Validation logic | `shared/validation/historical_completeness.py` | Implemented |
| Feature store integration | `ml_feature_store_processor.py:967-1069` | Implemented |
| BigQuery schema | `ml_feature_store_v2.historical_completeness` | Exists |

**Problem:** Not consistently populated - many records have NULL values.

**Remaining Work:**
1. Fix processor to ALWAYS populate `historical_completeness` struct
2. Add daily completeness audit to health check
3. Filter features where `is_complete=false` in prediction coordinator

See [10-SESSION-FINDINGS-2026-01-23.md](./10-SESSION-FINDINGS-2026-01-23.md) for details.

---

## Project Overview

This project addresses a fundamental architectural gap: **when historical data is missing, downstream calculations silently degrade without detection or tracking.**

The goal is to implement a comprehensive system that:
1. **Detects** when historical data windows are incomplete
2. **Tracks** what data contributed to each calculation (lineage)
3. **Flags** results that were computed with incomplete data
4. **Enables** cascade reprocessing after backfills

---

## Document Index

| Document | Purpose |
|----------|---------|
| [01-PROBLEM-STATEMENT.md](./01-PROBLEM-STATEMENT.md) | What the problem is and why it matters |
| [02-ROOT-CAUSE-ANALYSIS.md](./02-ROOT-CAUSE-ANALYSIS.md) | Deep dive into why this happens architecturally |
| [03-CORNER-CASES.md](./03-CORNER-CASES.md) | All edge cases, scenarios, and gotchas |
| [04-SOLUTION-ARCHITECTURE.md](./04-SOLUTION-ARCHITECTURE.md) | The proposed solution design |
| [05-DATA-MODEL.md](./05-DATA-MODEL.md) | Schema changes and data structures |
| [06-CASCADE-PROTOCOL.md](./06-CASCADE-PROTOCOL.md) | Step-by-step backfill and reprocessing workflow |
| [07-IMPLEMENTATION-PLAN.md](./07-IMPLEMENTATION-PLAN.md) | Phased implementation with tasks and estimates |
| [08-REFINED-COMPLETENESS-LOGIC.md](./08-REFINED-COMPLETENESS-LOGIC.md) | Discussion: Expected vs actual data logic |
| [09-FINAL-DESIGN.md](./09-FINAL-DESIGN.md) | **APPROVED:** Final design with bootstrap distinction |
| [10-SESSION-FINDINGS-2026-01-23.md](./10-SESSION-FINDINGS-2026-01-23.md) | **KEY:** Infrastructure exists, needs consistent usage |
| [11-COMPLETENESS-BACKFILL-PLAN.md](./11-COMPLETENESS-BACKFILL-PLAN.md) | **NEW:** Backfill plan for historical completeness metadata |

---

## Quick Links

**Key Files to Modify:**
- `data_processors/precompute/ml_feature_store/feature_extractor.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `shared/validation/historical_window_validator.py` (NEW)
- `bin/cascade_reprocessor.py` (NEW)

**Key Tables:**
- `nba_predictions.ml_feature_store_v2` - Add `historical_completeness` column
- `nba_precompute.feature_lineage` (NEW) - Optional lineage tracking

---

## Success Criteria

- [x] All feature records include completeness metadata *(schema exists, needs consistent population)*
- [x] Incomplete features are flagged and queryable *(is_complete flag exists)*
- [x] After any backfill, we know exactly what needs re-running *(contributing_game_dates exists)*
- [ ] Re-running cascade is a documented, repeatable process
- [ ] Monitoring shows daily completeness metrics
- [ ] **NEW:** Processor consistently populates historical_completeness (not NULL)
- [ ] **NEW:** Predictions filter unreliable features

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-22 | Target 100% completeness, flag anything less | User requirement: no silent degradation |
| 2026-01-22 | Flag don't block | Allow processing but track issues for later fix |
| 2026-01-22 | Store contributing_game_dates | Enables precise cascade detection |
| 2026-01-22 | 21-day forward impact window | 10 games typically span 2-3 weeks |
| 2026-01-22 | Distinguish bootstrap vs missing | Early season/new player = complete; data gap = incomplete |
| 2026-01-22 | Minimum 5 games threshold | Below 5 games, don't generate feature (too sparse) |
| 2026-01-22 | Use player_game_summary as source of truth | Has team_abbr per game, handles trades automatically |
| 2026-01-22 | Don't store missing_game_dates | Can be derived when needed, keep schema simple |
| 2026-01-23 | Infrastructure already exists | Found during session - focus on consistent usage, not new implementation |

---

**Document Status:** Infrastructure Exists - Needs Consistent Usage
