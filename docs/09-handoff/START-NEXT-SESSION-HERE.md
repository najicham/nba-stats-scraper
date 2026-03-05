# Start Your Next Session Here

**Updated:** 2026-03-05 (Session 405 — Critical Signal Bug Fixes)
**Status:** 26 active signals, 12 shadow signals, 10 enabled models. Algorithm `v404_sharp_money_shadow`. 6 critical bugs fixed, deploying now.

---

## Quick Start

```bash
/daily-steering
/validate-daily
./bin/check-deployment-drift.sh --verbose
/best-bets-config
```

---

## What's New (Session 405)

**6 critical bugs fixed:**
1. **player_lookup join mismatch** — Scrapers produce `jalen-brunson`, predictions use `jalenbrunson`. Added `REPLACE('-','')` in SQL. Was preventing ALL projection signals from firing.
2. **combo_3way + combo_he_ms DEAD** — Post-ASB edge compression (max OVER edge 4.0-4.7). Lowered MIN_EDGE 5.0 → 4.0. These are 95%+ HR signals.
3. **FantasyPros scraping season totals** — URL was `tot.php` (values 181-2418). Fixed to `daily-overall.php`.
4. **DFF provides DFS FPTS not real NBA points** — Excluded from consensus. Now 3 sources.
5. **DFF HTML parser garbled** — Player names included position/salary/FPTS. Fixed extraction.
6. **Dimers name duplication** — Full + abbreviated name concatenated. Fixed with `link.string`.

**4 new shadow signals (Session 404):** `sharp_money_over/under`, `public_fade_filter`, `minutes_surge_over`

---

## Immediate: Verify Bug Fixes

After morning prediction run (~6 AM ET), check:

```sql
-- 1. Projection consensus firing?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag LIKE 'projection_consensus%' AND game_date = CURRENT_DATE()
GROUP BY 1

-- 2. Combo signals revived?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN ('combo_3way', 'combo_he_ms') AND game_date = CURRENT_DATE()
GROUP BY 1

-- 3. Pick volume improved? (was 2/day)
SELECT game_date, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC
```

---

## Still Broken (Lower Priority)

| Scraper | Issue | Status |
|---------|-------|--------|
| NumberFire | GraphQL API returning 0 rows | Needs endpoint debug |
| VSiN | Scraper not producing data | Needs HTML parsing debug |
| NBA Tracking | stats.nba.com blocks Cloud IPs | nba_api proxy issue |
| RotoWire minutes | `projected_minutes` null all rows | Scraper extraction issue |

---

## Current Fleet (10 enabled models)

Multi-model architecture — best bets selects highest-edge per player across all enabled models.

**Top performers (edge 3+, since Feb 15):**
- catboost_v12_train0104_0222: 85.7% (n=7)
- lgbm_v12_noveg_train1201_0209: 83.3% (n=6)
- catboost_v16_noveg_train1201_0215: 73.3% (n=15) — **5 more picks → promotion decision**

**Disable candidates (< 50% on 20+ edge 3+):**
- catboost_v12_noveg_q45_train1102_0125: 50.8% (n=63)
- catboost_v12_noveg_q43_train1102_0125: 50.7% (n=71)
- catboost_v12_q43_train1225_0205: 33.3% (n=12)

---

## Strategic Priorities

1. **Verify fixes** — projection consensus + combo signals should fire now
2. **Shadow signal accumulation** — 12 signals, first promotion decision ~Mar 12
3. **Model fleet cleanup** — disable 2-4 underperformers after verification
4. **Signal rescue validation** — rescue HR check at 14 days (~Mar 18)

**Full plan:** `docs/09-handoff/session-prompts/SESSION-405-PLAN.md`
**Detailed handoff:** `docs/09-handoff/2026-03-05-SESSION-405-HANDOFF.md`

---

## Key References

- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **Model dead ends:** `docs/06-reference/model-dead-ends.md`
- **Session learnings:** `docs/02-operations/session-learnings.md`
- **Troubleshooting:** `docs/02-operations/troubleshooting-matrix.md`
