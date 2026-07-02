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

## Season-open checklist additions

Add to the 2026-27 opening checklist:
1. **DraftKings Network** (`dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/`) — confirmed FREE, server-rendered HTML, game-level splits. Easy BS4 scrape — same pattern as original VSiN. Build this first if we want a game-level replacement.
2. **PlayerProps.ai** (`playerprops.ai/trends`) — inspect in browser DevTools (Network tab → XHR), look for unauthenticated JSON endpoint for ticket%/handle% per player prop. If the endpoint is clean, this is the only free player-prop-level splits source.
3. **SportsDataIO free trial** — validate NBA player prop splits coverage before committing to paid. Has documented `BetPercentage`/`MoneyPercentage` fields in their REST API schema.
4. **Do NOT build ActionNetwork scraper** — DataDome blocks cloud IPs, game-level only, $29.99/mo PRO. Not worth it.

---

## System state

- **All off-season tasks complete.** No open items that can be done now.
- **Research converged.** See MEMORY.md and `docs/09-handoff/2026-07-02-SESSION-HANDOFF.md` for full signal fleet state.
- **Branch main is clean and pushed.**
