# Major Refactoring Project - Master Index

**Created:** 2026-01-25
**Total Scope:** 11 files (29,500 LOC) + 6 functions (3,400 LOC)
**Estimated Total Effort:** 13-18 hours across 6 sessions
**Recommended Model:** Sonnet for all sessions

---

## Session Overview

| Session | Scope | Risk | Est. Time | Dependencies |
|---------|-------|------|-----------|--------------|
| **R1** | Admin Dashboard | Low | 2-3 hrs | None |
| **R2** | Scraper Base | Medium | 2-3 hrs | None |
| **R3** | Raw Processor Service | Medium | 1.5-2 hrs | None |
| **R4** | Base Classes | **HIGH** | 3-4 hrs | None |
| **R5** | Analytics Processors | Medium | 2-3 hrs | R4 |
| **R6** | Precompute & Reference | Medium | 2-3 hrs | R4 |

---

## Recommended Execution Order

```
Week 1:
├── R1: Admin Dashboard (standalone, low risk warmup)
├── R2: Scraper Base (standalone, medium risk)
└── R3: Raw Processor Service (standalone, medium risk)

Week 2:
├── R4: Base Classes (CRITICAL - blocks R5/R6)
├── R5: Analytics Processors (depends on R4)
└── R6: Precompute & Reference (depends on R4)
```

**Why this order:**
1. **R1-R3 are independent** - Can be done in any order or parallel
2. **R4 is the foundation** - Must complete before R5/R6
3. **R1 is lowest risk** - Good warmup to establish patterns
4. **R4 is highest risk** - Schedule when you have focus time

---

## Quick Reference: What's Being Refactored

### Large Files (11 files >2000 LOC)

| File | Lines | Session |
|------|-------|---------|
| `services/admin_dashboard/main.py` | 3,098 | R1 |
| `scrapers/scraper_base.py` | 2,985 | R2 |
| `data_processors/analytics/analytics_base.py` | 2,947 | R4 |
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | 2,641 | R5 |
| `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | 2,630 | R6 |
| `data_processors/precompute/precompute_base.py` | 2,596 | R4 |
| `services/admin_dashboard/services/bigquery_service.py` | 2,532 | R1 |
| `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` | 2,288 | R6 |
| `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` | 2,288 | R5 |
| `data_processors/reference/player_reference/roster_registry_processor.py` | 2,231 | R6 |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | 2,054 | R5 |

### Large Functions (6 functions >250 lines)

| Function | File | Lines | Session |
|----------|------|-------|---------|
| `create_app()` | `scrapers/main_scraper_service.py` | 783 | R2 |
| `process_pubsub()` | `data_processors/raw/main_processor_service.py` | 696 | R3 |
| `run()` | `data_processors/analytics/analytics_base.py` | 536 | R4 |
| `main()` | `scripts/verify_database_completeness.py` | 497 | R6 |
| `_build_backfill_mode_query()` | `async_upcoming_player_game_context_processor.py` | 453 | R5 |
| `extract_opts_from_path()` | `data_processors/raw/main_processor_service.py` | 429 | R3 |

---

## Session Handoff Documents

Each session has a detailed handoff document:

1. **[REFACTOR-R1-ADMIN-DASHBOARD.md](./REFACTOR-R1-ADMIN-DASHBOARD.md)**
   - Extract Flask blueprints from main.py
   - Extract query modules from bigquery_service.py

2. **[REFACTOR-R2-SCRAPER-BASE.md](./REFACTOR-R2-SCRAPER-BASE.md)**
   - Extract mixins from ScraperBase
   - Extract route blueprints from create_app()

3. **[REFACTOR-R3-RAW-PROCESSOR-SERVICE.md](./REFACTOR-R3-RAW-PROCESSOR-SERVICE.md)**
   - Extract batch handlers from process_pubsub()
   - Extract path extractors using registry pattern

4. **[REFACTOR-R4-BASE-CLASSES.md](./REFACTOR-R4-BASE-CLASSES.md)**
   - Extract mixins from AnalyticsProcessorBase
   - Extract mixins from PrecomputeProcessorBase
   - Refactor 536-line run() method

5. **[REFACTOR-R5-ANALYTICS-PROCESSORS.md](./REFACTOR-R5-ANALYTICS-PROCESSORS.md)**
   - Extract calculators from 3 large processors
   - Extract query builder from async processor

6. **[REFACTOR-R6-PRECOMPUTE-REFERENCE.md](./REFACTOR-R6-PRECOMPUTE-REFERENCE.md)**
   - Extract factor calculators
   - Extract source handlers from roster registry
   - Refactor verification script

---

## How to Start Each Session

Copy this prompt to start a new chat:

```
Read this handoff document and execute the refactoring plan:
/home/naji/code/nba-stats-scraper/docs/09-handoff/REFACTOR-R[N]-[NAME].md

Key instructions:
1. Follow the target structure exactly
2. Run tests after each extraction
3. Preserve all existing behavior
4. Create a commit when done
```

---

## Success Metrics

After all sessions complete:

| Metric | Before | Target |
|--------|--------|--------|
| Files >2000 LOC | 11 | 0 |
| Functions >250 lines | 6 | 0 |
| Largest file | 3,098 lines | <600 lines |
| Largest function | 783 lines | <150 lines |

---

## Risk Mitigation

### For R4 (Base Classes) - Highest Risk

1. **Run full test suite before starting**
   ```bash
   python -m pytest tests/unit/data_processors/analytics/ -v
   python -m pytest tests/unit/data_processors/precompute/ -v
   ```

2. **Create a backup branch**
   ```bash
   git checkout -b refactor-base-classes-backup
   git checkout main
   ```

3. **Test after EVERY extraction**
   - Don't batch multiple extractions
   - Verify tests pass before moving to next

4. **Verify MRO (Method Resolution Order)**
   ```python
   from data_processors.analytics.analytics_base import AnalyticsProcessorBase
   print(AnalyticsProcessorBase.__mro__)
   ```

---

## Notes

- Each session is designed to be completable in one sitting
- Sessions R1-R3 can run in parallel if you have multiple developers
- R4 should be done by the most experienced person
- All sessions use Sonnet - it's faster and sufficient for mechanical refactoring
- Create commits at logical checkpoints within each session
