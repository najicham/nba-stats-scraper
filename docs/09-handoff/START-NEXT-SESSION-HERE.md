# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 430 — BDL retired, system-wide audit complete)
**Status:** BDL retired. 4-agent audit produced prioritized improvement plan. MLB 20 days from opening day.

---

## Prioritized Action Plan (from 4-agent system audit)

### Tier 0 — Do First (< 30 min, highest ROI)

| # | Task | Effort | Why |
|---|------|--------|-----|
| 1 | **Promote `volatile_starter_under` + `downtrend_under`** to active UNDER signal weights | 15 min | Cross-season validated: +11.1pp and +8.1pp lift. N=2291 combined. |
| 2 | **Demote `sharp_book_lean_under`** to observation-only | 5 min | Zero production fires in 2026 — market regime makes negative sharp lean nonexistent. |
| 3 | **Verify Cloud Function concurrency limits** on Phase 3→4 and 4→5 orchestrators | 5 min | `gcloud functions describe phase3-to-phase4-orchestrator --gen2 --region us-west2` — check max-concurrency >= 100 |

**Files to edit for #1-2:** `ml/signals/signal_best_bets_exporter.py` (UNDER_SIGNAL_WEIGHTS dict)

### Tier 1 — This Week (prevent silent failures)

| # | Task | Effort | Why |
|---|------|--------|-----|
| 4 | **Schedule `signal_decay_monitor` + `data_source_health_canary`** as Cloud Scheduler jobs | 30 min | Both have `http_handler()` but no scheduler trigger — SPOF failures go undetected |
| 5 | **Verify `decay-detection` CF is scheduled daily 11 AM ET** | 15 min | AUTO_DISABLE_ENABLED=true set, but may not be triggered |
| 6 | **Add Pub/Sub subscription lag monitoring** | 2 hr | Phase 2→3 uses direct Pub/Sub — if it dies, 3.5h blind spot before backup scheduler at 10:30 AM |
| 7 | **Enhance grading readiness with direct-trigger fallback** | 1.5 hr | If Pub/Sub fails, grading stalls until next scheduled job |

### Tier 2 — MLB Pre-Season (Mar 24-27)

| # | Task | Effort | When |
|---|------|--------|------|
| 8 | Resume MLB scheduler jobs | 5 min | Mar 24 |
| 9 | Retrain CatBoost V1 on freshest data | 30 min | Mar 24 |
| 10 | Health check all MLB Cloud Run services | 15 min | Mar 24 |
| 11 | E2E test with spring training data | 30 min | Mar 26 |
| 12 | Complete batter backfill (108/550 dates) | Background | Ongoing |

**MLB Pre-Season Checklist:** `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md`

### Tier 3 — This Month (strategic improvements)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 13 | Add SPOF fallback scrapers (NumberFire→Dimers, VSiN→Covers, DvP→BigQuery) | 3-8 hr each | Prevents irrecoverable data loss |
| 14 | Cross-phase dependency validator | 3 hr | Catches stale data before Phase 5 |
| 15 | BigQuery DML lock monitor | 1 hr | Detects 90-min lock deadlocks |
| 16 | Fix RotoWire projected_minutes | 2 hr | Unblocks `minutes_surge_over` signal |

### Tier 4 — Next Quarter (structural)

| # | Task | Impact |
|---|------|--------|
| 17 | Train non-CatBoost model (break r≥0.95 fleet redundancy) | All 8 models predict identically |
| 18 | Build UNDER signal discovery framework | Only 6 active UNDER vs 12+ OVER |
| 19 | Clean 450+ BDL references from codebase | Code clarity |

---

## What Was Done (Session 430)

### BDL Retirement — COMPLETE
- Deleted 4 Cloud Scheduler jobs
- Removed BDL from NBA registry (1 entry), both MLB registries (13+13 entries), scraper groups
- Removed BDL IL queries from MLB predictors → return empty set
- Removed BDL injury integration from NBA predictions → NBA.com sole source
- Removed BDL pitcher splits, BDL analytics triggers
- **KEPT** BDL in `batter_game_summary_processor.py` UNION (backfill at 108/550)
- Updated 4 project docs (BDL-RETIREMENT-PLAN, CURRENT-STATUS, DATA-SOURCES, SCRAPER-INVENTORY)

### Proxy Audit — 3 MLB scrapers enabled
`mlb_umpire_stats`, `mlb_ballpark_factors`, `mlb_reddit_discussion` → proxy_enabled = True

### 4-Agent System Audit — Key Findings

**MLB Pre-Season (85% ready):** All core infrastructure deployed. No critical blockers. Resume schedulers Mar 24-25, retrain model, health check services.

**NBA System Health:** HR 57.7% (7d). 2 UNDER signals ready for promotion (+2-3pp expected). `sharp_book_lean_under` has zero fires (demote). Auto-disable infrastructure needs scheduler job.

**Data Resilience:** 5 SPOFs identified with concrete backup solutions. NumberFire (FanDuel GraphQL) is highest risk — no backup projection source. All snapshot data is irrecoverable.

**Pipeline Reliability:** Phase 2→3 Pub/Sub is riskiest link (no lag monitoring). Grading pipeline has 3.5h gap if Pub/Sub fails. Self-healing is reactive (12:45 PM) — needs proactive checks.

---

## System State

| Item | Status |
|------|--------|
| NBA | v430, 8 models, 28 active signals, BB HR 57.7% (7d) |
| MLB Worker | Deployed — catboost_v1, v1_6_rolling, ensemble_v1 all loading |
| MLB Schedulers | 13+ jobs paused. Resume Mar 24-25 (20 days to opening day). |
| BDL | **FULLY RETIRED** — subscription cancelled |
| Batter Backfill | 108/550 dates done. Resume from virtualenv/Cloud Shell. |
| Proxy | 3 MLB web scrapers proxy-enabled |

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/signal_best_bets_exporter.py` | UNDER_SIGNAL_WEIGHTS — edit for Tier 0 signal changes |
| `bin/monitoring/signal_decay_monitor.py` | Has http_handler() — needs Cloud Scheduler job |
| `bin/monitoring/data_source_health_canary.py` | Has http_handler() — needs Cloud Scheduler job |
| `data_processors/analytics/mlb/batter_game_summary_processor.py` | BDL UNION — remove when backfill hits 365+ dates |
| `docs/09-handoff/2026-03-07-SESSION-430-HANDOFF.md` | Full session handoff with agent audit details |
