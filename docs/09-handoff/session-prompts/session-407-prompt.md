# Session 407 Plan — Verify Scraper Fixes, Fix FantasyPros, Signal Promotion Tracking

## Context

Session 406 deployed 3 commits fixing scraper data quality (NumberFire GraphQL, VSiN HTML parsing, NBA Tracking proxy, Playwright re-add, DVP rank, combo MIN_EDGE 3.0). All builds succeeded. The `nba-scrapers` service is deployed with Playwright.

**Current state (as of Mar 5 02:30 UTC / 9:30 PM ET Mar 4):**
- NumberFire: 120 rows in BQ, valid per-game points
- VSiN: 14 rows in BQ, correct team codes
- NBA Tracking: 1092 rows
- DVP: rank=NULL in raw table (expected — computed in supplemental query)
- FantasyPros: ALL rows are DFS season-total fantasy points (SGA=2418). 0 valid. **Needs URL fix or exclusion.**
- Dimers: 3/20 valid projected_points (pre-Playwright data). Next scrape at 9:45 AM ET will test Playwright.
- Shadow signals: Only `predicted_pace_over` fired (2x on Mar 4). Others await morning pipeline.
- Pick volume: 2/day (critically low, edge compression)
- New models (catboost/xgb_train0107_0219): Worker cache refreshed. Awaiting first Phase 5 run.
- GCS freshness monitor: Deployed + scheduler (every 6h ET) + tested. 10/10 PASS.

**Important clarification:** The deployment drift checker flags `nba-phase1-scrapers` (LEGACY service name) as stale. The ACTIVE service `nba-scrapers` was deployed successfully at 01:40 UTC. Ignore the legacy service drift.

---

## Phase 1: Morning Verification (P0)

Run these immediately. The morning pipeline (~6 AM ET) and projection scrapers (~9:30-9:45 AM ET) should have run by the time this session starts.

### 1.1 Check Playwright scraper results
```sql
-- Did Dimers Playwright produce more valid data?
SELECT COUNT(*) as total, COUNTIF(projected_points BETWEEN 5 AND 60) as valid_pts,
  COUNTIF(projected_points IS NULL) as null_pts, MAX(scraped_at) as latest
FROM nba_raw.dimers_projections WHERE DATE(scraped_at) = CURRENT_DATE()

-- Did FantasyPros produce any valid per-game data?
SELECT COUNT(*) as total, COUNTIF(projected_points BETWEEN 5 AND 60) as valid_pts,
  MAX(projected_points) as max_pts, MIN(projected_points) as min_pts
FROM nba_raw.fantasypros_projections WHERE DATE(scraped_at) = CURRENT_DATE()
```

**Expected:** Dimers should have 50+ valid rows with Playwright. FantasyPros will likely still be DFS data.

### 1.2 Check Playwright logs
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND (textPayload:"Playwright" OR textPayload:"playwright") AND timestamp>="2026-03-05T14:00:00Z"' --project=nba-props-platform --limit=20
```

### 1.3 Check shadow signals
```sql
SELECT t as signal_tag, COUNT(*) as fires
FROM nba_predictions.signal_best_bets_picks, UNNEST(signal_tags) t
WHERE t IN ('projection_consensus_over','projection_consensus_under',
  'dvp_favorable_over','sharp_money_over','sharp_money_under',
  'combo_3way','combo_he_ms','predicted_pace_over')
  AND game_date = CURRENT_DATE()
GROUP BY 1 ORDER BY 2 DESC
```

### 1.4 Check new model predictions + pick volume
```sql
-- New models producing?
SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE system_id IN ('catboost_v12_noveg_train0107_0219', 'xgb_v12_noveg_train0107_0219')
  AND game_date = CURRENT_DATE() GROUP BY 1

-- Pick volume
SELECT game_date, COUNT(*) as picks,
  COUNTIF(recommendation='OVER') as over_picks,
  COUNTIF(recommendation='UNDER') as under_picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1 DESC
```

### 1.5 Run standard checks
```bash
PYTHONPATH=. python bin/monitoring/signal_firing_canary.py
./bin/check-deployment-drift.sh --verbose
```

---

## Phase 2: Fix FantasyPros (P1)

FantasyPros `daily-overall.php` shows DFS season-total fantasy points, not per-game NBA points. Even with Playwright rendering fully, the data is wrong type.

### Options (pick one):
1. **Try `overall.php`** — May show per-game season averages. Test with `WebFetch` or Playwright.
2. **Try `/nba/stats/avg-pts.php`** — Might have actual NBA stats.
3. **Exclude FantasyPros permanently** — Only 2 sources needed for consensus (NumberFire + Dimers). FantasyPros aggregates from other sources (including NumberFire), so it would double-count anyway.

**Recommendation:** Option 3 (exclude). With NumberFire providing 120 valid rows and Dimers improving with Playwright, 2-source consensus is viable. FantasyPros is a meta-aggregator and adds no unique signal. Remove FP from the consensus query in `supplemental_data.py` and remove the FP scraper scheduler.

If excluding, update:
- `ml/signals/supplemental_data.py` — remove `fp` CTE from projection_query
- `docs/06-reference/scrapers/00-SCRAPER-INVENTORY.md` — mark as excluded
- MEMORY.md — update scraper status

### If Dimers still has mostly NULLs with Playwright
The Dimers page may require specific interaction (clicking tabs, scrolling, waiting for Angular hydration). Check:
1. Does the Playwright `download_and_decode()` wait long enough for Angular to hydrate?
2. Does the table require clicking a "Points" tab?
3. Is there an API endpoint behind the Angular app (check Network tab)?

If Dimers can't be fixed, consensus falls back to NumberFire-only (1 source), which doesn't meet MIN_SOURCES=2. In that case, lower MIN_SOURCES to 1 (single-source mode) with lower weight, or find a replacement source.

---

## Phase 3: Evaluate Signal Data Accumulation (P2)

After the morning pipeline, check how much shadow signal data has accumulated:

```sql
-- Shadow signal accumulation summary
SELECT t as signal_tag,
  MIN(game_date) as first_fire, MAX(game_date) as last_fire,
  COUNT(*) as total_fires,
  COUNTIF(p.prediction_correct IS NOT NULL) as graded,
  COUNTIF(p.prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(p.prediction_correct = TRUE), COUNTIF(p.prediction_correct IS NOT NULL)) * 100, 1) as hr
FROM nba_predictions.signal_best_bets_picks sbp, UNNEST(signal_tags) t
LEFT JOIN nba_predictions.prediction_accuracy p
  ON sbp.player_lookup = p.player_lookup AND sbp.game_date = p.game_date
  AND sbp.system_id = p.system_id AND p.has_prop_line = TRUE
WHERE t IN ('projection_consensus_over','projection_consensus_under',
  'dvp_favorable_over','sharp_money_over','sharp_money_under',
  'combo_3way','combo_he_ms','predicted_pace_over',
  'public_fade_filter','sharp_book_lean_over','sharp_book_lean_under')
GROUP BY 1 ORDER BY total_fires DESC
```

**Promotion criteria reminder:**
- HR >= 60% + N >= 30 → promote to production
- HR >= 65% at edge 0-5 + N >= 15 → add to signal rescue
- HR < 50% + N >= 30 → disable

Most shadow signals have near-zero data. Expected timeline: ~2-4 weeks to reach N=30 for evaluation.

---

## Phase 4: Strategic Priorities (P3, if time)

### 4.1 Fleet Diversity Problem
ALL 145 model pairs have r >= 0.95 (REDUNDANT). The fleet offers zero prediction diversity. Options:
- **Different feature sets**: V12_noveg works best, but other feature sets give different predictions
- **Different algorithms**: XGBoost/LightGBM are already in fleet but converge to same predictions
- **Different training windows**: Current fleet uses similar windows (56-day)
- **Ensemble disagreement**: Use model disagreement as a signal (currently ANTI-correlated with winning)

This is a hard problem. The models are all trained on the same data with similar features, so convergence is expected. May not be solvable without fundamentally different data sources.

### 4.2 Edge Compression Recovery
Post-ASB edge compression continues (2/day picks). Monitor whether edges expand as regular season settles. If still compressed after 2 weeks:
- Consider relaxing edge floor from 3.0 to 2.5 (risky — edge 2-3 historically ~52% HR)
- Focus on signal quality over edge magnitude
- The signal rescue mechanism should help surface good picks below edge 3

### 4.3 Evening CLV Scheduler
The `nba-props-evening-closing` scheduler already exists at 22:00 UTC. Verify it's producing `snapshot_type='closing'` data:
```sql
SELECT snapshot_type, COUNT(*), MAX(scraped_at) as latest
FROM nba_raw.odds_api_player_props
WHERE DATE(scraped_at) >= CURRENT_DATE() - 3
GROUP BY 1
```

If closing data is flowing, the `positive_clv_over/under` shadow signals can be wired.

---

## Files Likely to Change

| File | Change | Phase |
|------|--------|-------|
| `ml/signals/supplemental_data.py` | Remove FP CTE from projection_query (if excluding) | Phase 2 |
| `scrapers/projections/dimers_projections.py` | Fix Playwright rendering if still NULL | Phase 2 |
| MEMORY.md | Update scraper/signal status | Phase 3 |

---

## Success Criteria

- [ ] Dimers Playwright produces 30+ valid projected_points
- [ ] FantasyPros resolved (URL fix or excluded)
- [ ] Projection consensus signal fires (2+ sources)
- [ ] Sharp money signals fire (VSiN data in supplemental)
- [ ] DVP favorable signal fires (rank computed in supplemental)
- [ ] New models producing predictions
- [ ] Pick volume >= 4/day
- [ ] Combo signals fire at least once (MIN_EDGE 3.0)
- [ ] No deployment drift (ignore legacy nba-phase1-scrapers)
