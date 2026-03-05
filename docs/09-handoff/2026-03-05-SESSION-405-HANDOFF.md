# Session 405 Handoff — Critical Signal Bug Fixes + Shadow Signal Expansion

**Date:** 2026-03-04 / 2026-03-05 (late evening)
**Algorithm:** `v404_sharp_money_shadow`
**Status:** All fixes deployed. Builds queued. Verify tomorrow morning.

---

## Summary

This session discovered and fixed **6 critical bugs** that were preventing shadow signals from firing, and revived 2 dead combo signals. Also built 4 new shadow signals (VSiN sharp money + RotoWire minutes).

---

## Critical Bugs Fixed

### 1. player_lookup Join Mismatch (FATAL for all projection signals)

**Root cause:** Scrapers produce hyphenated `player_lookup` (e.g., `jalen-brunson`) but prediction tables use no-hyphen format (`jalenbrunson`). Result: zero joins across all projection sources — projection_consensus could never fire.

**Fix:** Added `REPLACE(player_lookup, '-', '')` in all projection SQL CTEs in `supplemental_data.py`. Also applied to RotoWire minutes query.

### 2. combo_3way + combo_he_ms DEAD (95%+ HR signals offline)

**Root cause:** Post-ASB edge compression — no enabled model produces OVER edge >= 5.0. Max OVER edge is 4.0-4.7. The `MIN_EDGE = 5.0` threshold was unreachable.

**Fix:** Lowered `MIN_EDGE` from 5.0 to 4.0 in both `combo_3way.py` and `combo_he_ms.py`. The minutes surge requirement (>= 3.0) is the real quality discriminator. OVER edge 4-5 has 57.5% HR (N=563) — well above breakeven even without the combo.

### 3. FantasyPros Scraping Season Totals (wrong URL)

**Root cause:** URL was `/nba/projections/tot.php` (season totals, values 181-2418). Jalen Brunson = 1954 projected_points. Comparing against a ~25 prop line makes every player "above line."

**Fix:** Changed URL to `daily-overall.php` for per-game projections (~15-35 range).

### 4. DFF Provides DFS Fantasy Points, Not Real NBA Points

**Root cause:** DailyFantasyFuel only provides DraftKings FPTS (formula: PTS×1 + REB×1.25 + AST×1.5 + ...). FPTS is always higher than real points, creating systematic OVER bias when compared against prop lines.

**Fix:** Excluded DFF from consensus signal entirely. `dailyfantasyfuel: None` in projection_map. Now 3 sources (NumberFire, FantasyPros, Dimers).

### 5. DFF HTML Parser Garbled (name + position + salary concatenated)

**Root cause:** `get_text(strip=True)` on the player cell grabbed everything including position, salary, FPTS, value multiplier. Output: `J. BrunsonPG. $9100FPTS38.7VALUE4.3x`.

**Fix:** Added `_extract_clean_player_name()` with 3-strategy approach + `_clean_garbled_name()` regex cleaner.

### 6. Dimers Name Duplication

**Root cause:** `link.get_text(strip=True)` concatenated full + abbreviated name child elements. Output: `Jalen BrunsonJ. Brunson`.

**Fix:** Use `link.string` (returns direct text only, None if child elements exist) with fallback to longest text node via `stripped_strings`.

---

## New Features Built (Session 404 portion)

### Shadow Signals (4 new, 12 total)

| Signal | Source | Direction | Threshold |
|--------|--------|-----------|-----------|
| `sharp_money_over` | VSiN | OVER | Handle >= 65% + tickets <= 45% |
| `sharp_money_under` | VSiN | UNDER | Handle >= 65% + tickets <= 45% |
| `public_fade_filter` | VSiN | OVER (neg) | 80%+ public tickets on OVER |
| `minutes_surge_over` | RotoWire | OVER | Projected minutes >= avg + 3 |

All in shadow mode — fire and record but don't affect aggregator rescue/ranking.

### Monitoring Expansion

9 shadow signals added to `ACTIVE_SIGNALS` in `signal_health.py`:
- projection_consensus_over/under, predicted_pace_over, dvp_favorable_over
- positive_clv_over/under, sharp_money_over/under, minutes_surge_over

Signal firing canary (Session 405 early) wired into daily-health-check CF.

---

## Data State

| Source | Status | Latest Data | Notes |
|--------|--------|-------------|-------|
| FantasyPros | URL FIXED | Mar 4 (stale) | Will get daily data on next trigger |
| DailyFantasyFuel | EXCLUDED | Mar 4 | DFS FPTS only, not real points |
| Dimers | Parser FIXED | Mar 4 | 85% null projected_points |
| TeamRankings | WORKING | Mar 4 | Pace data for predicted_pace signal |
| Hashtag Basketball | WORKING | Mar 4 | DvP data for dvp_favorable signal |
| RotoWire | WORKING | Mar 4 | projected_minutes is null (all rows) |
| Covers | WORKING | Mar 4 | Referee stats (no signal yet) |
| NumberFire | BROKEN | Never | GraphQL returning 0 rows |
| VSiN | BROKEN | Never | Scraper not producing data |
| NBA Tracking | BROKEN | Never | stats.nba.com blocks Cloud IPs |

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/supplemental_data.py` | REPLACE('-','') in projection CTEs, DFF excluded, VSiN+RotoWire queries |
| `ml/signals/combo_3way.py` | MIN_EDGE 5.0 → 4.0 |
| `ml/signals/combo_he_ms.py` | MIN_EDGE 5.0 → 4.0 |
| `ml/signals/sharp_money.py` | **NEW** — 3 signal classes |
| `ml/signals/minutes_projection.py` | **NEW** — 1 signal class |
| `ml/signals/registry.py` | Registered 4 new signals |
| `ml/signals/signal_health.py` | 9 shadow signals in ACTIVE_SIGNALS |
| `ml/signals/pick_angle_builder.py` | 9 pick angle templates |
| `ml/signals/aggregator.py` | Algorithm v404_sharp_money_shadow |
| `ml/signals/projection_consensus.py` | Docstring updated (DFF excluded) |
| `scrapers/projections/fantasypros_projections.py` | URL tot.php → daily-overall.php |
| `scrapers/projections/dailyfantasyfuel_projections.py` | Clean name extraction, FPTS field |
| `scrapers/projections/dimers_projections.py` | link.string for name extraction |
| `data_processors/raw/projections/dailyfantasyfuel_processor.py` | projected_fantasy_points field |
| `orchestration/cloud_functions/daily_health_check/main.py` | Signal firing canary (CHECK 10) |
| `bin/monitoring/signal_firing_canary.py` | **NEW** — CLI canary tool |

---

## What to Verify Next Session

### Immediate (after morning prediction run)

```sql
-- 1. Check if projection_consensus fires (join fix + FP daily URL)
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag LIKE 'projection_consensus%'
  AND game_date = CURRENT_DATE()
GROUP BY 1

-- 2. Check if combo signals revived (edge 4.0+ threshold)
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN ('combo_3way', 'combo_he_ms')
  AND game_date = CURRENT_DATE()
GROUP BY 1

-- 3. Check pick volume (was 2/day, expect improvement)
SELECT game_date, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC

-- 4. Verify algorithm version
SELECT DISTINCT algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date = CURRENT_DATE()
```

### Shadow signal validation (run every 2-3 days)

```sql
WITH shadow_picks AS (
  SELECT pst.player_lookup, pst.game_date, pst.system_id, signal_tag
  FROM nba_predictions.pick_signal_tags pst
  CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
  WHERE signal_tag IN ('projection_consensus_over', 'projection_consensus_under',
    'predicted_pace_over', 'dvp_favorable_over',
    'positive_clv_over', 'positive_clv_under',
    'sharp_money_over', 'sharp_money_under', 'minutes_surge_over')
    AND game_date >= '2026-03-05'
)
SELECT sp.signal_tag,
  COUNT(*) as fires, COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM shadow_picks sp
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON sp.player_lookup = pa.player_lookup AND sp.game_date = pa.game_date AND sp.system_id = pa.system_id
GROUP BY 1 ORDER BY fires DESC
```

### Still broken (lower priority)

- **NumberFire** — GraphQL API returning 0 rows. May need endpoint update.
- **VSiN** — Scraper deployed but not producing data. Debug HTML parsing.
- **NBA Tracking** — stats.nba.com blocks Cloud IPs. nba_api proxy may need different pool.
- **RotoWire projected_minutes** — null for all rows. Investigate scraper HTML extraction.

---

## Strategic Context

**Full plan:** `docs/09-handoff/session-prompts/SESSION-405-PLAN.md`

**Key priorities:**
1. Verify fixes work → pick volume increases
2. Shadow signal data accumulation (12 signals, first promotion ~Mar 12)
3. Signal promotion when N >= 30 graded (projection_consensus first)
4. Model fleet cleanup — 4-5 disable candidates at < 50% edge 3+ HR
5. Threshold experiments once data accumulates

**14d best bets HR:** 58.3% (14/24). OVER 50.0%, UNDER 66.7%. Pick volume is the bottleneck, not accuracy.
