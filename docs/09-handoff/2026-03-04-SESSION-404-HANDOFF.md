# Session 404 Handoff — Documentation Trim, Projection Consensus, CLV Fix

**Date:** 2026-03-04 (late evening, continuation of 403)
**Algorithm:** `v401_away_noveg_removed` (unchanged)
**Status:** All changes committed. Awaiting verification tomorrow.

---

## Changes Made

### 1. CLAUDE.md Trimmed (455 → 385 lines, 31KB → 21KB)

Moved detailed reference material out of CLAUDE.md into dedicated docs:
- **ML Model section**: Cut ~85 lines. Dead ends → `docs/06-reference/model-dead-ends.md`. Fleet details, cross-model monitoring condensed.
- **Signal System section**: Cut ~50 lines. Full signal table + negative filters → updated `SIGNAL-INVENTORY.md`.
- **Common Issues section**: Cut ~25 lines. Kept recurring patterns, removed session-specific historical fixes (already in troubleshooting-matrix.md).

### 2. Signal Inventory Updated

**File:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- Complete rewrite from Session 275 (18 signals) → Session 404 (26 active + 8 shadow + 17 negative filters)
- Added architecture section (SC, signal rescue, UNDER ranking)
- Added shadow signals section (projection consensus, CLV, pace, DvP)
- Added negative filters table with all 17 filters

### 3. Model Dead Ends Document Created

**File:** `docs/06-reference/model-dead-ends.md`
- Organized 80+ dead ends by category (training approaches, feature engineering, signals, etc.)
- Previously was a single massive paragraph in CLAUDE.md

---

## Carried Forward from Session 403

These items were deployed in Session 403 and need verification tomorrow:

### Projection Consensus (Priority #1)
- Expanded from 2 → 4 sources (FantasyPros, DFF, Dimers, NumberFire)
- MIN_SOURCES_ABOVE = 2 threshold now achievable with 3 working sources
- **Verify:** Check if `projection_consensus_over`/`under` signals fire tomorrow
- **Query:** `SELECT signal_name, COUNT(*) FROM signal_best_bets_picks WHERE game_date = CURRENT_DATE() AND signal_name LIKE 'projection_consensus%' GROUP BY 1`

### CLV Pipeline (Priority #2)
- `snapshot_type` now flows from scheduler → orchestration → scraper
- Evening scheduler timeout updated 180s → 900s
- **Verify tonight:** Check if closing snapshot data appears after 10 PM UTC
- **Query:** `SELECT snapshot_type, COUNT(*) FROM nba_raw.odds_api_player_props WHERE game_date = CURRENT_DATE() GROUP BY 1`

### Scraper Rewrites (from Session 403)
- NumberFire → FanDuel GraphQL API (no Playwright)
- VSiN → server-rendered HTML (no Playwright)
- NBA Tracking → nba_api + proxy pool
- Playwright removed from Docker entirely (Debian Trixie broke install)
- **Verify:** Force-trigger each scheduler and check BQ for rows

### Pick Volume Diagnosis
- Funnel: 726 preds → 36 edge 3+ → 13 unique players → 11 pass signal gate → 2 picks
- Signal count ≥ 3 gate is primary bottleneck — projection consensus will help
- Pick volume expected to increase as more signals become available

---

## What to Check Next Session

1. **Scraper build status** — verify deploy-nba-scrapers succeeded (Playwright removal)
2. **NumberFire GraphQL data** — trigger `nba-numberfire-projections` scheduler, check BQ
3. **Projection consensus signals** — after prediction run, check if signals fire
4. **CLV closing data** — after 10 PM UTC, check for snapshot_type=closing in BQ
5. **Pick volume** — compare picks/day with projection consensus active vs baseline

---

## Commits This Session

| Hash | Description |
|------|-------------|
| (pending) | docs: CLAUDE.md trim + signal inventory update + model dead ends doc |

---

## Key Decisions

- **Reddit/social scraping is a dead end** for player props (Session 403 research confirmed)
- **CLAUDE.md strategy:** Keep operational essentials in-file, move detailed reference to docs/ with pointers
- **Signal inventory is the source of truth** for all signal details — CLAUDE.md has summary only
