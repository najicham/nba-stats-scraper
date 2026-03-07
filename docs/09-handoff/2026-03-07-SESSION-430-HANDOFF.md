# Session 430 Handoff — BDL Retirement + System-Wide Audit

**Date:** 2026-03-07
**Focus:** BDL subscription retirement, data source/proxy/pipeline audits, system improvement planning

---

## Changes Made

### 1. BDL Fully Retired (8 files, 310 lines removed)

**Scheduler jobs deleted (4):**
- `bdl-catchup-afternoon`, `bdl-catchup-evening`, `bdl-catchup-midday`, `bdl-injuries-hourly`

**Code changes:**

| File | Change |
|------|--------|
| `scrapers/registry.py` | Removed `bdl_injuries` (NBA), 13 BDL MLB entries, `ball_dont_lie` group |
| `scrapers/mlb/registry.py` | Removed 13 BDL entries + `balldontlie` source mapping |
| `data_processors/analytics/mlb/main_mlb_analytics_service.py` | Removed `bdl_pitcher_stats`/`bdl_batter_stats` triggers |
| `predictions/mlb/base_predictor.py` | IL method → returns empty set (prop lines already filter IL) |
| `predictions/mlb/pitcher_strikeouts_predictor.py` | IL method → returns empty set |
| `predictions/shared/injury_integration.py` | Removed `_load_bdl_injuries()` + BDL merge logic |
| `predictions/shared/injury_filter.py` | Removed BDL docstring reference |
| `data_processors/precompute/mlb/pitcher_features_processor.py` | Splits method → returns empty dict |

**Preserved:** `batter_game_summary_processor.py` BDL UNION (backfill at 108/550 dates)

### 2. Proxy Enabled on 3 MLB Scrapers

| Scraper | Type | File |
|---------|------|------|
| `mlb_umpire_stats` | UmpScorecards web scrape | `scrapers/mlb/external/mlb_umpire_stats.py` |
| `mlb_ballpark_factors` | Web scrape | `scrapers/mlb/external/mlb_ballpark_factors.py` |
| `mlb_reddit_discussion` | Reddit | `scrapers/mlb/external/mlb_reddit_discussion.py` |

### 3. Session 429 Leftovers Committed

- `combo_he_ms` HR 94.9% → 70.8%, `combo_3way` HR 78.1% → 63.9% in pick_angle_builder.py
- Signal weight report: added combo_3way, combo_he_ms, book_disagreement, scoring_cold_streak_over, low_line_over to known_active set

### 4. Project Docs Updated

| Doc | Changes |
|-----|---------|
| `BDL-RETIREMENT-PLAN.md` | Marked COMPLETE with execution log |
| `CURRENT-STATUS.md` | BDL migration done, injury replacement done |
| `DATA-SOURCES.md` | BDL marked CANCELLED |
| `00-SCRAPER-INVENTORY.md` | BDL RETIRED, projection statuses corrected, SPOF warnings added |

---

## 4-Agent Audit Results

### Agent 1: MLB Pre-Season Readiness (85% ready)

**Ready:** Data pipeline, prediction systems (CatBoost V1 + V1.6 + Ensemble), signal system (8+6+4), orchestration CFs, config/env.

**Before Mar 27:**
1. Resume scheduler jobs (5 min, Mar 24)
2. Retrain CatBoost V1 (30 min, Mar 24-25)
3. Health check services (15 min)
4. E2E test (30 min, Mar 26)

**Risk:** Scheduler job URLs may need verification. Statcast Jul-Sep 2025 backfill not done (optional).

### Agent 2: NBA System Health

**Healthy:** 57.7% BB HR (7d), 8 models, 28 active signals. Zero-tolerance defaults enforced.

**Quick wins:**
- Promote `volatile_starter_under` (+11.1pp lift) + `downtrend_under` (+8.1pp lift) — cross-season validated
- Demote `sharp_book_lean_under` — zero fires in 2026
- Schedule `signal_decay_monitor` + `data_source_health_canary` as Cloud Scheduler jobs

**Structural:** Fleet has r≥0.95 correlation (zero diversity). Only 6 UNDER signals vs 12+ OVER.

### Agent 3: Data Source Resilience

**5 SPOFs with concrete backup solutions:**

| SPOF | Backup Approach | Effort |
|------|----------------|--------|
| NumberFire (CRITICAL) | Dimers API fallback + enhanced monitoring | 5-8 hr |
| RotoWire lineups | Rotoguru1 HTML parser fallback | 4-6 hr |
| VSiN betting splits | Covers.com betting splits scraper | 3-4 hr |
| Covers referee stats | BigQuery crew O/U reconstruction | 2-3 hr |
| Hashtag DvP | BigQuery position defense reconstruction | 3-4 hr |

All snapshot data (projections, lineups, splits) is irrecoverable if scraper goes down for a day.

### Agent 4: Pipeline Reliability

**5 uncovered failure scenarios:**
1. Phase 2→3 Pub/Sub dies silently (3.5h blind spot)
2. Phase 3→4 orchestrator timeout without identifying which processor is blocking
3. No cross-phase dependency validation (stale data goes undetected)
4. Model cache staleness in prediction worker (no auto-refresh)
5. Grading pipeline stall if Pub/Sub fails (3.5h gap)

**Top fixes:** Pub/Sub lag monitoring (2h), grading trigger fallback (1.5h), BQ lock monitor (1h)

---

## Commits

| Commit | Message |
|--------|---------|
| `4b8fd2c4` | feat: retire BDL data source + enable proxies on MLB web scrapers |
| `08fd52b5` | fix: update combo signal HRs + signal weight report known-active list |
| `0ebbd73c` | docs: Session 430 handoff — BDL retired, audits complete, backfill resuming |
| `7fb91540` | docs: mark BDL retired across project docs + fix scraper inventory |

---

## Batter Backfill Status

- **Progress:** 108 dates / 25,669 records (through 2024-07-13)
- **Target:** ~550 dates / ~150K records (through 2025-09-28)
- **Requires GCP deps** — run from virtualenv or Cloud Shell:
  ```bash
  pip install google-cloud-bigquery
  PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py --start 2024-07-14 --end 2025-09-28 --sleep 0.3 --skip-existing
  ```
- **When complete:** Remove BDL from UNION in `batter_game_summary_processor.py` + circuit breaker check

---

## Build Status

- Auto-deploy triggered (4b8fd2c4 + 7fb91540)
- `signal-weight-report` CF failed (pre-existing: untracked directory from Session 429, needs proper commit or deletion)
- All other services building successfully
