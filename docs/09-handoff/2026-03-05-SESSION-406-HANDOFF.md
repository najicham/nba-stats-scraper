# Session 406 Handoff — Scraper Resurrection, Playwright, Combo Edge Fix

**Date:** 2026-03-05
**Algorithm:** `v406_scraper_fixes_combo_edge3`
**Status:** All 3 broken scrapers fixed and verified. Playwright re-added. Combo signals lowered to edge 3.0. Awaiting first daily pipeline run with new data.

---

## Summary

This session resurrected **3 dead scrapers** (NumberFire, VSiN, NBA Tracking), **re-added Playwright** to the Docker image for JS-rendered pages (FantasyPros, Dimers), and **lowered combo signal edge thresholds** to 3.0 (from 4.0) to match post-ASB edge compression reality. This unblocks the `projection_consensus` and `sharp_money` shadow signals that have been dead since inception.

---

## Scrapers Fixed (3/3 — all verified in production)

### 1. NumberFire/FanDuel GraphQL — Schema Changed

**Root cause:** FanDuel updated the GraphQL schema for `getSlates`. The old query used `input: {sport: NBA}` with `slateId` and `gameCount` fields. The new schema uses direct args `(sport: NBA)` with `id` field and no `gameCount`.

**Fix:** Updated `_get_main_slate_id()` in `numberfire_projections.py`:
- Query: `getSlates(sport: NBA) { id name }` (was `getSlates(input: {sport: NBA}) { slateId name gameCount }`)
- Field: `slate["id"]` (was `slate["slateId"]`)
- Fallback: first slate (was sort by gameCount)
- Added GraphQL error response handling

**Result:** **120 player projections** from FanDuel GraphQL API. Verified in production logs.

### 2. VSiN Betting Splits — Nested HTML Elements

**Root cause:** `row.find_all("td")` returned 150+ nested elements from the freezetable layout instead of 10 direct `<td>` children. The parser saw 150 cells and extracted garbled data from nested elements.

**Fix (two parts):**
1. `vsin_betting_splits.py`: Added `recursive=False` to `find_all("td")` — gets exactly 10 direct children
2. `resolve_team()`: Fixed word-boundary bug where "nets" matched inside "hornets" → Charlotte resolved to BKN. New approach splits name into words and checks each individually, then checks multi-word keys.

**Result:** **14 games** with correct team codes, spreads, totals, handle/ticket percentages. Verified in production logs.

### 3. NBA Tracking Stats — Proxy Already Deployed

**Root cause:** Session 405 added proxy support to the scraper code, but the deployment happened AFTER the scraper's last run. The scraper never got a chance to use the proxy.

**Fix:** Triggered the scraper post-deploy. The `nba_api` library with decodo proxy worked immediately.

**Result:** **546 players** with usage/tracking stats via `nba_api` + decodo residential proxy. Verified in production logs and BQ table.

---

## Combo Signals — MIN_EDGE 4.0 → 3.0

**Root cause (deeper than Session 405 diagnosis):** Even after lowering from 5.0 → 4.0 in Session 405, combo signals still produced zero fires. Analysis showed only **0-1 OVER predictions per day** reach edge 4.0+ post-ASB. The edge compression is structural:

| Date | Max OVER Edge | OVER edge 4+ count |
|------|--------------|---------------------|
| Mar 4 | 4.0 | 1 |
| Mar 3 | 4.4 | 1 |
| Mar 2 | 4.4 | 1 |
| Mar 1 | 6.1 | 5 |
| Feb 28 | 5.7 | 28 |
| Feb 27 | 3.8 | 0 |

**Fix:** Lowered `MIN_EDGE` to 3.0 in both `combo_3way.py` and `combo_he_ms.py`. This matches the aggregator's general edge floor. With ~15 OVER predictions at edge 3.0-3.6 daily, the minutes surge gate (~7% of players) becomes the quality discriminator.

**Expected impact:** ~1 combo signal fire per day (was 0). The minutes surge requirement (>= 3.0) ensures quality even at lower edge.

---

## Playwright Re-added to Dockerfile

**Context:** Playwright was removed in Session ~404 because Debian Trixie broke the install (`ttf-unifont` and `ttf-ubuntu-font-family` packages don't exist on Trixie).

**Fix:** Install Chromium system dependencies manually (Trixie-compatible package names), then run `playwright install chromium` (without `--with-deps`).

**Added deps:** libnss3, libnspr4, libdbus-1-3, libatk1.0-0, libatk-bridge2.0-0, libcups2, libdrm2, libxkbcommon0, libatspi2.0-0, libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libgbm1, libpango-1.0-0, libcairo2, libasound2, fonts-liberation, fonts-unifont

**Playwright scrapers:**
- **FantasyPros:** `daily-overall.php` only serves 10 players in static HTML (rest is JS-loaded). Playwright renders full table. Falls back to HTTP (10 players) if Playwright fails.
- **Dimers:** Static HTML has 20 rows with most PTS values empty. Playwright should populate all values.

**First Playwright deploy:** Build `ee91013f` succeeded. Awaiting first scraper trigger to verify.

---

## RotoWire Investigation — projected_minutes Permanently Absent

**Finding:** The RotoWire lineups page (`nba-lineups.php`) does NOT contain projected minutes anywhere in the HTML. Player items have:
- Position (`lineup__pos`)
- Injury status (`lineup__inj`)
- Play probability (`is-pct-play-0/50/75/100` CSS class)

**No minutes-related elements exist.** The `minutes_surge_over` signal is **permanently blocked** unless we find an alternative minutes projection source.

**Added:** `play_probability` field extraction from CSS class. This data could power a `dnp_risk_filter` signal in the future.

---

## Projection Consensus — Unblocked

With NumberFire now providing 120 projections, the signal has a second source (alongside Dimers' 3-20 players). The `MIN_SOURCES_ABOVE = 2` threshold in `projection_consensus.py` should now be reachable for players covered by both sources.

**Remaining issue:** FantasyPros only gives 10 players via static HTML. Playwright deployment should increase this significantly. Dimers has garbled names in BQ from old runs but the `_clean_concatenated_name` fix is deployed.

---

## Data State After Session 406

| Source | Status | Row Count | Notes |
|--------|--------|-----------|-------|
| NumberFire | **FIXED** | 120 in GCS | GraphQL schema fix. Awaiting Phase 2 → BQ |
| VSiN | **FIXED** | 14 games in GCS | recursive=False + team resolution. Awaiting Phase 2 → BQ |
| NBA Tracking | **FIXED** | 546 in BQ | nba_api + decodo proxy working |
| FantasyPros | Partial | 10 in GCS | Static HTML only. Playwright deployed, untested |
| Dimers | Partial | 20 in GCS | Name fix deployed. Playwright deployed, untested |
| TeamRankings | Working | 450 rows | Daily accumulation |
| Hashtag DvP | Working | Fresh | DVP rank fix deployed |
| RotoWire | Working | Fresh | Lineups + play_probability (no minutes) |
| Covers Referee | Working | Fresh | |
| DFF | Excluded | N/A | DFS FPTS, not NBA points. Intentionally excluded from consensus |

---

## Files Changed

| File | Change |
|------|--------|
| `scrapers/projections/numberfire_projections.py` | Fix `getSlates` GraphQL schema (sport: NBA, id field) |
| `scrapers/external/vsin_betting_splits.py` | `recursive=False` + `resolve_team` word-boundary fix |
| `scrapers/external/nba_tracking_stats.py` | No code change — proxy support already deployed, just triggered |
| `scrapers/external/rotowire_lineups.py` | Added `play_probability` extraction from CSS class |
| `scrapers/projections/fantasypros_projections.py` | Playwright rendering + HTTP fallback + sanity filter (>60 pts) |
| `scrapers/projections/dimers_projections.py` | Playwright rendering + HTTP fallback + `_clean_concatenated_name` |
| `scrapers/Dockerfile` | Re-added Playwright + Chromium with Trixie-compatible system deps |
| `scrapers/requirements-lock.txt` | Added `playwright==1.52.0` |
| `ml/signals/combo_3way.py` | MIN_EDGE 4.0 → 3.0 |
| `ml/signals/combo_he_ms.py` | MIN_EDGE 4.0 → 3.0 |
| `ml/signals/aggregator.py` | Algorithm version → `v406_scraper_fixes_combo_edge3` |

---

## Verification Queries (for next session)

```sql
-- 1. NumberFire data in BQ?
SELECT COUNT(*) FROM nba_raw.numberfire_projections WHERE game_date >= '2026-03-05'

-- 2. VSiN data in BQ?
SELECT COUNT(*) FROM nba_raw.vsin_betting_splits WHERE game_date >= '2026-03-05'

-- 3. Projection consensus firing?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag LIKE 'projection_consensus%' AND game_date >= '2026-03-05'
GROUP BY 1

-- 4. Sharp money signals firing?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag LIKE 'sharp_money%' AND game_date >= '2026-03-05'
GROUP BY 1

-- 5. Combo signals revived?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN ('combo_3way', 'combo_he_ms') AND game_date >= '2026-03-05'
GROUP BY 1

-- 6. Pick volume improved? (was 2/day)
SELECT game_date, COUNT(*) as picks,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-04'
GROUP BY 1 ORDER BY 1 DESC

-- 7. Playwright data volume (FP should have more than 10 if working)
SELECT 'fantasypros' as src, COUNT(*) FROM nba_raw.fantasypros_projections WHERE game_date >= '2026-03-05'
UNION ALL SELECT 'dimers', COUNT(*) FROM nba_raw.dimers_projections WHERE game_date >= '2026-03-05'
```

---

## Known Issues

1. **Phase 2 scraper name routing:** NumberFire publishes as `number_fire_projections_scraper`, VSiN as `v_si_n_betting_splits_scraper`. If Phase 2 doesn't recognize these names, data stays in GCS only. Check Phase 2 logs.
2. **Playwright first run:** Not yet tested in production. FantasyPros timed out at 30s (fixed to 60s with `domcontentloaded`). May need further tuning.
3. **minutes_surge_over permanently blocked:** No minutes projection source available. Signal is dead code.
4. **FantasyPros 10-player limit without Playwright:** If Playwright fails, only 10 players per run.

---

## Strategic Context

This session completed the scraper layer of the Session 405+ plan (Phase 1). The pipeline now has data flowing from:
- **3 projection sources** (NumberFire, FantasyPros, Dimers) — enables projection_consensus
- **1 betting splits source** (VSiN) — enables sharp_money signals
- **1 tracking stats source** (NBA Tracking) — enrichment data

Next priority is **Phase 2-3 of the plan**: accumulate shadow signal data and run first promotion window analysis.

**Full plan:** `docs/09-handoff/session-prompts/SESSION-406-PLAN.md`

---

## Session 406 Verification (Mar 5, ~9 PM ET)

### Build Status
- **14/15 builds SUCCESS.** One scraper build FAILED (Playwright `--with-deps` on Trixie) — fixed by subsequent commit `ee91013f` (manual system deps). Final scraper build `e7f1d8f3` SUCCESS.
- `nba-scrapers` deployed at 01:40 UTC. All other services up to date.

### Scraper Data Freshness (Verified in BQ)
| Source | Status | Count | Latest |
|--------|--------|-------|--------|
| NumberFire | **120 rows** | Valid pts (29.5, 24.3...) | Mar 5 01:22 UTC |
| VSiN | **14 rows** | Correct team codes | Mar 5 01:22 UTC |
| NBA Tracking | **1092 rows** | 2 scrapes | Mar 5 00:57 UTC |
| DVP | **510 rows** | rank=NULL in raw (expected — computed in supplemental query) | Mar 4 18:49 UTC |
| FantasyPros | **4065 rows** | ALL invalid (2418 for SGA = DFS season totals). 0/4065 in 5-60 range. | Mar 4 18:49 UTC |
| Dimers | **320 rows** | Only 3/20 with valid pts (85% NULL). Pre-Playwright data. | Mar 5 01:30 UTC |

### Key Finding: Data scraped BEFORE Playwright fix deployed
- Dimers data at 01:30 UTC was scraped BEFORE the new build deployed at 01:32 UTC
- Next scheduled scrape: 9:30-9:45 AM ET Mar 5 — will be first true Playwright test
- FantasyPros: Even with Playwright, the `daily-overall.php` page shows DFS data. URL needs changing or FP needs excluding.

### Models & Signals
- **New models** (catboost/xgb_train0107_0219): No predictions yet. Worker cache refreshed (`MODEL_CACHE_REFRESH` updated). Will produce predictions on next Phase 5 run.
- **Shadow signals**: Only `predicted_pace_over` (2 fires Mar 4). Others awaiting morning pipeline with new data.
- **Pick volume**: 2/day on Mar 4 (pre-fix). Target 4-8.

### Infrastructure
- **GCS freshness monitor**: Deployed + scheduler (every 6h ET) + tested. 10/10 exports PASS.
- **Deployment drift**: `nba-phase1-scrapers` (legacy service name) flagged as stale. `nba-scrapers` (current) is up to date.
- **Worker model cache**: Refreshed to `$(date +%Y%m%d_%H%M)`.

### Remaining for Next Session
1. **Verify Playwright renders Dimers** (9:45 AM ET scrape)
2. **Fix FantasyPros URL** — `daily-overall.php` is DFS data. Try `overall.php` or exclude permanently.
3. **Verify shadow signals fire** after morning pipeline
4. **Verify combo signals fire** with MIN_EDGE 3.0
5. **Check pick volume** improvement
6. **Optional: Evening CLV scheduler** for closing line data
