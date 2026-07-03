# Session Handoff — 2026-07-02 (Session 2)

**Branch:** main (clean, all pushed)
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Prior handoff:** `2026-07-02-SESSION-HANDOFF.md`

---

## What was done this session

### VSiN Diagnostic (open item from prior handoff)

Root cause of VSiN data gap since 2026-03-28: **Piano paywall**, not a scraper bug.

`data.vsin.com/nba/betting-splits/` now 302-redirects to a Piano-gated page. The data table (`txt-color-vsinred`, `freezetable`) is completely absent from the HTML response.

**Bugs fixed along the way:**
- `scrapers/external/vsin_betting_splits.py` `__main__` was passing `groups=` to `run()` which only accepts `opts` — caused `TypeError` on local invocation. Fixed: moved `group` inside `opts` dict.

**Commits:** `2306ed75`, `a511ba4e`

---

### VSiN Replacement Research (5-agent sweep)

Ran 4 parallel agents + direct curl checks across 10+ sources.

**Findings:**
- **DRF.com**: Horse racing only — no NBA content. Dead end.
- **ActionNetwork**: Has game-level splits, Next.js SPA. Free tier shows basic data; full features behind $20/mo PRO. Needs Playwright to intercept API endpoint.
- **Covers.com**: JS-heavy shell, bot-blocked from direct fetch. `contests.covers.com/consensus` endpoint returns empty body.
- **BetQL, Pregame, SBR**: Bot-blocked (429/403) or paid-only.
- **DraftKings Network** (`dknetwork.draftkings.com`): PWA — one agent claims free player-prop splits, unverifiable from WSL/curl. **Check in real browser at 2026-27 open.**
- **Outlier.bet**: Only confirmed player-prop splits source, $20-30/mo.
- **Player-prop splits for free**: Does not exist as a public resource.

**Data requirements audit (parallel agent):** Only 4 fields needed (over/under ticket_pct + money_pct), game-level. `sharp_money_over` is REMOVED, `sharp_money_under` and `public_fade_filter` are SHADOW with zero pick impact. **Zero production impact from VSiN being paywalled.**

**Decision: skip for now.** Document in scraper inventory; revisit at 2026-27 open.

**Commits:** `d8e337b5` (research outcome in scraper inventory)

---

### External Scraper Health Audit

Confirmed all other external scrapers are healthy — they stopped naturally at season end (April 20-26):

| Scraper | Last Date | Status |
|---------|-----------|--------|
| hashtagbasketball_dvp | 2026-04-26 | ✅ Season end |
| teamrankings_team_stats | 2026-07-02 | ✅ Running through off-season |
| rotowire_lineups | 2026-04-26 | ✅ Season end |
| covers_referee_stats | 2026-04-20 | ✅ Season end |
| nba_tracking_stats | 2026-04-26 | ✅ Season end (bug fixed 2026-07-01) |
| vsin_betting_splits | 2026-03-28 | ❌ Paywalled mid-season |

VSiN scheduler: already PAUSED in GCP — no action needed.

**VSiN is the only external scraper that went dark mid-season.**

---

### Stale table name fixed

`teamrankings_pace` was a stale name everywhere — actual BQ table is `teamrankings_team_stats`, file is `teamrankings_stats.py`. Fixed in CLAUDE.md and scraper inventory.

**Commits:** (in final commit this session)

---

## Files changed this session

| File | Change |
|------|--------|
| `scrapers/external/vsin_betting_splits.py` | Fix `__main__` stale API; update STATUS to PAYWALLED |
| `docs/06-reference/scrapers/00-SCRAPER-INVENTORY.md` | VSiN: PAYWALLED + replacement research; teamrankings: correct table name |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | Mark sharp_money signals as no-data-source |
| `CLAUDE.md` | Fix `teamrankings_pace` → `teamrankings_team_stats` |

---

## DraftKings Network scraper — BUILT (2026-07-02)

Replaced the paywalled VSiN source with a free DraftKings Network scraper. Fully built, registered, and validated end-to-end (commit `17173267`).

**What was built:**
- **Phase 1 scraper** `scrapers/external/dknetwork_betting_splits.py` — parses `div.tb-se` game blocks → over/under ticket% (bets) + money% (handle), VSiN-compatible output + dk_event_id/odds. `proxy_enabled=False` (verified working from plain IP, 1.5s fetch). Registered in `scrapers/registry.py`.
- **Phase 2 processor** `data_processors/raw/external/dknetwork_betting_splits_processor.py` → `nba_raw.dknetwork_betting_splits` (BQ table created, VSiN-compatible schema). Path extractor + processor routing wired.
- **Validated** live fetch → parse → BQ write (3 rows, 0 failed) using in-season MLB as structural proxy (NBA is off-season, 0 games — expected).

**Widget URL params (reverse-engineered):** `tb_eg=42648` (NBA), `tb_edate=today|tomorrow|n7days|n30days`, `tb_emt=Total|Spread|Moneyline`. Fully server-rendered HTML, no auth, no bot protection.

**Remaining (season-open, needs sign-off):**
1. **Scheduler** — create Cloud Scheduler job daily ~2 PM ET → nba-scrapers with `{"scraper":"dknetwork_betting_splits","date":"TODAY"}`.
2. **First-game-day smoke test** — verify non-zero games + NBA tricodes parse correctly. NBA matchup format is *assumed* "LAL Lakers @ BOS Celtics" (validated MLB format "DET Tigers @ TEX Rangers"). If tricodes are wrong, adjust `resolve_team()`.
3. **Proxy fallback** — if smoke test returns 0 games / HTTP errors, GCP egress IPs may be blocked → flip `proxy_enabled=True`.
4. **Signal wiring** — point `sharp_money_over/under` + `public_fade_filter` in `supplemental_data.py` at `dknetwork_betting_splits` (or UNION with vsin). All shadow, zero pick impact until promoted.

## ⚠️ Side-discovery: nba-scrapers deploy was broken (FIXED)

While deploying the DK Network scraper, found that **`deploy-nba-scrapers` had been failing on every push** — `requirements-lock.txt` pinned 7 phantom atproto submodules (`atproto_client`, `atproto_core`, `_crypto`, `_firehose`, `_identity`, `_lexicon`, `_server` `==0.0.69`) that are NOT separate PyPI distributions (they're bundled inside the single `atproto` wheel). pip errored with "No matching distribution found for atproto_client==0.0.69".

**Impact:** any scraper code change pushed while these pins were present never actually deployed to nba-scrapers. Fixed in commit removing the phantom lines (verified `atproto==0.0.69` alone provides all submodules). Both `deploy-nba-scrapers` and `deploy-nba-phase2-raw-processors` now build SUCCESS. **Worth auditing whether other recent scraper changes silently failed to deploy during the broken window.**

## Other candidates (not pursued)
- **PlayerProps.ai** (`playerprops.ai/trends`) — possibly the only free *player-prop-level* ticket%/handle% source. JS-rendered, needs Playwright + DevTools XHR inspection. Worth exploring if we ever want prop-level (not game-level) splits.
- **SportsDataIO** — paid API, documented `BetPercentage`/`MoneyPercentage` for prop markets. Free trial.
- **ActionNetwork** — NOT viable (DataDome blocks cloud IPs, game-level only, $30/mo). **DRF.com** — horse racing only.

---

## System state

- **All off-season tasks complete.** No open items that can be done now.
- **Research converged.** See MEMORY.md and `docs/09-handoff/2026-07-02-SESSION-HANDOFF.md` for full signal fleet state.
- **Branch main is clean and pushed.**
