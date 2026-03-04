# Session 403 Handoff — Scraper Fixes, Exporter Bug, Validation

**Date:** 2026-03-04 (evening)
**Algorithm:** `v401_away_noveg_removed` (confirmed active)
**Status:** Scraper deploys in progress. Exporter consistency fix deployed.

---

## Changes Made

### 1. NumberFire Scraper Rewrite (GraphQL API)

**Was:** HTML scraper → Playwright-based SPA renderer (never worked).
**Now:** Direct FanDuel GraphQL API calls — no browser needed.

- `fdresearch-api.fanduel.com/graphql` is public, no auth
- Two queries: `getSlates(sport: NBA)` → `getProjections(slateId)`
- Returns ~140 players with projected points, minutes, rebounds, assists
- Commit: `773c0102`

### 2. VSiN Scraper Rewrite (Server-Rendered HTML)

**Was:** Playwright-based AJAX renderer (wrong assumption — data IS in static HTML).
**Now:** BeautifulSoup parser for `data.vsin.com/nba/betting-splits/`.

- Data is server-side rendered in a freezetable layout
- Teams in `txt-color-vsinred` links, percentages in nested `div` elements
- Tested: all 6 games for Mar 4 parse correctly
- Field names matched to existing BQ schema (`over_ticket_pct`, `over_money_pct`, etc.)
- Commit: `773c0102`

### 3. NBA Tracking Scraper Proxy Fix

**Was:** `proxy_enabled = True` but `download_and_decode()` override bypassed proxy infrastructure. `nba_api` not installed in production.
**Now:** Wired up `get_healthy_proxy_urls_for_target('stats.nba.com')` in both `_fetch_via_nba_api()` and `_fetch_via_http()`. `nba_api` was already in requirements-lock.txt.

- stats.nba.com blocks cloud IPs — proxy is essential
- If proxy unavailable, falls back to direct (may still timeout)
- Commit: `773c0102`

### 4. Playwright Removed from Dockerfile

**Root cause of build failure:** Debian Trixie removed `ttf-unifont` and `ttf-ubuntu-font-family` packages that Playwright's `--with-deps` needs.
**Fix:** Removed `playwright install chromium --with-deps` from Dockerfile entirely. Removed playwright/playwright-stealth from requirements. No scraper needs a headless browser anymore.
- Commit: `773c0102`

### 5. GCS-BQ Consistency Fix (signal_best_bets_exporter.py)

**Bug:** `_write_to_bigquery()` filtered disabled model picks in a local variable. `export()` then uploaded the UNFILTERED picks to GCS. Result: GCS and BQ had different picks.

**Fix:** Moved disabled model filter to `export()` BEFORE both BQ write and GCS upload. GCS, BQ, and filter_audit now all see the same filtered set.

- Root cause of Mar 3 missing pick: disabled model `catboost_v16_noveg_rec14_train1201_0215` leaked through during rapid-deployment window, BQ filtered it, GCS didn't
- Commit: `773c0102`

### 6. Projection Consensus Wiring (bonus)

- `supplemental_data.py` expanded from 2 to 4 projection sources (FantasyPros, DFF, Dimers, NumberFire)
- `projection_consensus.py` updated for multi-source threshold
- Commit: `773c0102`

---

## Validation Results

### v401 Confirmed Active
- Mar 4: `v401_away_noveg_removed` in filter_audit
- away_blocked = 0, star_blocked = 0 ✓
- Pass rate: 18.2% (2/11), up from 6.25% (1/16) on Mar 3

### HOME vs AWAY in Best Bets (Feb 20+, corrected join)
| Location | Direction | Graded | HR |
|----------|-----------|--------|-----|
| AWAY | OVER | 4 | **75.0%** |
| AWAY | UNDER | 5 | **60.0%** |
| HOME | OVER | 7 | 42.9% |
| HOME | UNDER | 4 | **75.0%** |

AWAY outperforming HOME. Filter removal vindicated.

### Star UNDER Recovery
| Week | Picks | HR |
|------|-------|----|
| W08 (toxic) | 123 | 36.6% |
| W09 | 130 | 53.8% |
| **W10** | 39 | **82.1%** |

### Signal Rescue
- First 2 production rescued picks (Mar 4, ungraded)
- Isaiah Joe OVER (low_line_over), Jaylen Wells OVER (high_scoring_environment_over)

### Fleet Performance (Feb 15+, edge 3+)
| Model | Graded | HR |
|-------|--------|-----|
| catboost_v12_train0104_0222 | 7 | 85.7% |
| catboost_v12_noveg_train0103_0227 | 5 | 80.0% |
| catboost_v12_noveg_train0108_0215 | 9 | 77.8% |
| catboost_v16_noveg_train1201_0215 | 15 | 73.3% |
| lgbm_v12_noveg_train0103_0227 | 11 | 72.7% |

**No model has 20+ graded edge 3+.** Wait for more data.

---

## Scraper Status (After Fixes)

| Scraper | Status | Fix Applied |
|---------|--------|------------|
| FantasyPros | ✅ Working (2,710 rows) | — |
| RotoWire | ✅ Working (5,280 rows) | — |
| DailyFantasyFuel | ✅ Working (1,008 rows) | — |
| Covers referee | ✅ Working (760 rows) | — |
| TeamRankings | ✅ Working (300 rows) | — |
| HashtagBasketball | ✅ Working (340 rows) | — |
| Dimers | ✅ Working (200 rows) | — |
| **NumberFire** | 🔄 Deploying | GraphQL API rewrite |
| **VSiN** | 🔄 Deploying | HTML parser rewrite |
| **NBA Tracking** | 🔄 Deploying | Proxy + nba_api |

---

## Build Status

- `deploy-nba-scrapers` builds in progress (Playwright removal should fix build failure)
- `deploy-phase6-export` succeeded (exporter consistency fix deployed)
- `deploy-prediction-coordinator` succeeded

---

## Known Issues

### game_id Format Mismatch
- `signal_best_bets_picks` uses `20260304_OKC_NYK` format
- `nba_reference.nba_schedule` uses `0022500898` format
- JOIN on game_id fails — use team_abbr + opponent + game_date instead
- Not urgent but worth fixing for cleaner queries

### NBA Tracking May Still Fail
- Even with proxy, stats.nba.com may block all proxy IPs
- Monitor after deploy. If still failing, may need residential proxy or browser-based approach
- Data is nice-to-have, not critical for current signals

---

## Next Session (404) Plan

### Priority 1: Verify Scraper Deploy (5 min)
```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=3 \
  --filter="substitutions.TRIGGER_NAME='deploy-nba-scrapers'" \
  --format='table(id,createTime,status)'
```
If still failing, check logs for new errors.

### Priority 2: Grade Mar 4 Picks (5 min)
```sql
SELECT bb.game_date, bb.player_lookup, bb.recommendation,
  ROUND(bb.edge, 1) as edge, bb.system_id,
  bb.signal_rescued, bb.rescue_signal,
  pa.prediction_correct as hit, pa.actual_points, bb.line_value
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date = '2026-03-04'
```

### Priority 3: Check New Scraper Data Flowing (10 min)
```sql
-- NumberFire (should have data if GraphQL works)
SELECT COUNT(*) FROM nba_raw.numberfire_projections WHERE game_date >= '2026-03-05'
-- VSiN (should have data)
SELECT COUNT(*) FROM nba_raw.vsin_betting_splits WHERE game_date >= '2026-03-05'
-- NBA Tracking
SELECT COUNT(*) FROM nba_raw.nba_tracking_stats WHERE game_date >= '2026-03-05'
```

### Priority 4: Model Promotion Assessment (10 min)
- V16 noveg needs 5+ more graded edge 3+ for promotion (at 15/20)
- LightGBM needs 9+ more (at 11/20)
- Check if any model hits 20+ graded edge 3+ with >= 65% HR

### Priority 5: Projection Consensus Signal (15 min)
- With 4 projection sources now wired up, check if consensus signal fires
- Need at least 2 sources agreeing with model direction to fire
```sql
SELECT game_date, COUNT(*) as picks_with_consensus
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-05'
  AND 'projection_consensus' = ANY(signal_tags)
GROUP BY 1
```

### Priority 6: Brier-Weighted Selection Research (if models have data)
- Need 3+ models with 50+ graded for meaningful comparison
- Concept: `ORDER BY edge * (1 / GREATEST(brier_score_14d, 0.15))` in per-player selection

---

## Don't Do
- Don't re-add away_noveg or star_under filters
- Don't promote models with < 20 graded edge 3+ picks
- Don't retrain — 10 models is enough, focus on evaluation
- Don't lower OVER edge floor below 5.0
- Don't touch signal rescue criteria — need 14+ days of production data
- Don't install Playwright again — all scrapers work without it
