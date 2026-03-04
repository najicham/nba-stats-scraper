# Session 405+ Plan — Signal Validation, Experiments & System Optimization

**Created:** 2026-03-04 (Session 404)
**Scope:** Mar 5 through end of March
**Goal:** Turn 12 shadow signals into profitable pick volume while maintaining 58%+ HR

---

## Current State (Mar 4)

| Metric | Value |
|--------|-------|
| 14d HR | 58.3% (14/24) |
| OVER HR | 50.0% (6/12) |
| UNDER HR | 66.7% (8/12) |
| Daily picks | 1-6 (avg ~2.5) |
| Rescued picks | 2 total (both OVER) |
| Shadow signals | 12 (1 firing: predicted_pace_over) |
| Fleet | 10+ enabled models, no single champion |
| Top models (edge 3+) | catboost_v12_train0104_0222 85.7% (n=7), catboost_v16_noveg 73.3% (n=15) |

**Key bottleneck:** Signal density. Most predictions die at signal_count >= 3 gate. Only 2 picks/day when shadow signals contribute nothing. Promoting shadow signals increases pick volume.

---

## Phase 1: Scraper Verification + Quick Wins (Session 405)

### 1a. Trigger and verify 3 fixed scrapers

```bash
gcloud scheduler jobs run nba-numberfire-projections --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs run nba-vsin-betting-splits --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs run nba-tracking-stats --location=us-west2 --project=nba-props-platform
```

Verify data:
```sql
SELECT "numberfire" as source, COUNT(*) as row_count FROM nba_raw.numberfire_projections WHERE game_date >= CURRENT_DATE() - 1
UNION ALL SELECT "vsin", COUNT(*) FROM nba_raw.vsin_betting_splits WHERE game_date >= CURRENT_DATE() - 1
UNION ALL SELECT "nba_tracking", COUNT(*) FROM nba_raw.nba_tracking_stats WHERE game_date >= CURRENT_DATE() - 1
```

**If NumberFire fails:** Debug GraphQL API response. The FanDuel research API may have changed endpoints.
**If VSiN fails:** Debug HTML parsing — check if `data.vsin.com` layout changed.
**If NBA Tracking fails:** Check nba_api proxy pool. Cloud IPs may still be blocked.

### 1b. RotoWire projected_minutes investigation

RotoWire `projected_minutes` is null for all 11,520 rows. Either:
- The scraper isn't extracting the field (check HTML parsing)
- RotoWire doesn't display minutes on the page we're scraping
- The field needs a different data source

**Action:** Examine `scrapers/external/rotowire_lineups.py` to see if projected_minutes is being parsed. If not extractable, mark `minutes_surge_over` as BLOCKED and focus on other signals.

### 1c. Grade yesterday's picks

```bash
/yesterdays-grading
```

Check Mar 4 picks (2 OVER rescued picks) — first grading data for rescued picks.

### 1d. Deploy Session 404 changes

The new signal code (sharp_money, minutes_projection, monitoring) needs to be deployed:
```bash
git add ml/signals/sharp_money.py ml/signals/minutes_projection.py
git add ml/signals/supplemental_data.py ml/signals/registry.py
git add ml/signals/signal_health.py ml/signals/pick_angle_builder.py ml/signals/aggregator.py
git add docs/
git commit -m "feat: add VSiN sharp money + RotoWire minutes projection shadow signals"
git push origin main
```

Monitor deploy:
```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

---

## Phase 2: Shadow Signal Data Accumulation (Mar 5-12)

### Daily monitoring checklist

Run every day after predictions:
```sql
-- Which shadow signals fired today?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN ('projection_consensus_over', 'projection_consensus_under',
  'predicted_pace_over', 'dvp_favorable_over',
  'positive_clv_over', 'positive_clv_under',
  'sharp_money_over', 'sharp_money_under', 'minutes_surge_over',
  'public_fade_filter', 'projection_disagreement', 'negative_clv_filter')
  AND game_date = CURRENT_DATE()
GROUP BY 1 ORDER BY fires DESC
```

### Expected fire rates

| Signal | Expected fires/day | N=30 by | Notes |
|--------|-------------------|---------|-------|
| `projection_consensus_over` | 5-15 | ~Mar 10 | Needs NumberFire + 1 other source |
| `projection_consensus_under` | 3-8 | ~Mar 12 | |
| `predicted_pace_over` | 1-3 | ~Mar 18 | Already firing (2x Mar 4) |
| `dvp_favorable_over` | 1-2 | ~Mar 22 | Depends on rank <= 5 threshold |
| `sharp_money_over` | 1-4 | ~Mar 15 | Needs VSiN data |
| `sharp_money_under` | 1-3 | ~Mar 18 | Needs VSiN data |
| `positive_clv_over/under` | 2-6 | ~Mar 14 | Needs closing snapshot data |
| `minutes_surge_over` | 0 | BLOCKED | RotoWire projected_minutes is null |

---

## Phase 3: First Promotion Window (Mar 10-14)

### 3a. Run validation query

```sql
WITH shadow_picks AS (
  SELECT pst.player_lookup, pst.game_date, pst.system_id, signal_tag
  FROM nba_predictions.pick_signal_tags pst
  CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
  WHERE signal_tag IN ('projection_consensus_over', 'projection_consensus_under',
    'predicted_pace_over', 'dvp_favorable_over',
    'positive_clv_over', 'positive_clv_under',
    'sharp_money_over', 'sharp_money_under')
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

### 3b. Promotion decisions

**Promote to production** (add to ACTIVE_SIGNALS, contributes to signal_count):
- Already happens by being registered — shadow signals that fire DO count toward signal_count
- Key question: should any be added to `rescue_tags` in aggregator?

**Promote to rescue** (allow picks below edge floor):
- IF `projection_consensus_over` HR >= 65% at edge 0-5, N >= 15 → add to `rescue_tags`
- IF `sharp_money_over` HR >= 65% at edge 0-5, N >= 15 → add to `rescue_tags`

**Add to UNDER_SIGNAL_WEIGHTS:**
- IF `sharp_money_under` HR >= 60% → add with weight derived from HR
- IF `projection_consensus_under` HR >= 60% → add with weight

**Code changes for promotion** (per signal):
1. `ml/signals/aggregator.py` — add to `rescue_tags` set (~line 316) if rescue-qualified
2. `ml/signals/aggregator.py` — add to `UNDER_SIGNAL_WEIGHTS` dict (~line 66) if UNDER variant
3. Bump `ALGORITHM_VERSION` string
4. Deploy

### 3c. Disable decisions

- IF any shadow signal HR < 50% on N >= 30 → consider disabling
- IF `public_fade_filter` tagged picks HR >= 55% → don't activate as negative filter

---

## Phase 4: Threshold Experiments (Mar 12-20)

All SQL-based retroactive analysis — no code changes until results justify them.

### 4a. Projection consensus threshold sweep

```sql
-- Test MIN_SOURCES = 1 vs 2 vs 3
WITH proj_picks AS (
  SELECT pa.player_lookup, pa.game_date, pa.prediction_correct,
    pa.recommendation,
    p.projection_sources_above_line, p.projection_sources_below_line,
    p.projection_sources_total
  FROM nba_predictions.prediction_accuracy pa
  JOIN nba_predictions.player_prop_predictions p
    ON pa.player_lookup = p.player_lookup AND pa.game_date = p.game_date AND pa.system_id = p.system_id
  WHERE pa.game_date >= '2026-03-05'
    AND pa.prediction_correct IS NOT NULL
    AND p.projection_sources_total >= 1
)
SELECT
  threshold,
  COUNTIF(recommendation = 'OVER' AND sources_above >= threshold AND prediction_correct) as over_wins,
  COUNTIF(recommendation = 'OVER' AND sources_above >= threshold) as over_total,
  COUNTIF(recommendation = 'UNDER' AND sources_below >= threshold AND prediction_correct) as under_wins,
  COUNTIF(recommendation = 'UNDER' AND sources_below >= threshold) as under_total
FROM proj_picks, UNNEST([1, 2, 3]) AS threshold
WHERE (recommendation = 'OVER' AND projection_sources_above_line >= threshold)
   OR (recommendation = 'UNDER' AND projection_sources_below_line >= threshold)
GROUP BY threshold ORDER BY threshold
```

### 4b. Sharp money divergence sweep

```sql
-- Test different handle-ticket divergence thresholds
-- (only possible once VSiN data is flowing)
WITH money_picks AS (
  SELECT pa.player_lookup, pa.game_date, pa.prediction_correct,
    pa.recommendation,
    -- need to get vsin data from somewhere — may need a custom query
    vsin.over_money_pct, vsin.over_ticket_pct,
    vsin.under_money_pct, vsin.under_ticket_pct
  FROM nba_predictions.prediction_accuracy pa
  -- join VSiN data via game teams
  ...
)
-- Sweep: divergence thresholds of 15pp, 20pp, 25pp, 30pp
```

### 4c. Predicted pace threshold sweep

Test `predicted_game_pace` thresholds: 99, 100, 101, 102, 103.

### 4d. DvP rank threshold sweep

Test `opponent_dvp_rank` thresholds: 3, 5, 8, 10.

### 4e. CLV threshold sweep

Test `closing_line_value` thresholds: 0.3, 0.5, 1.0 (OVER); -0.3, -0.5, -1.0 (UNDER).

---

## Phase 5: Signal Combination Discovery (Mar 15-20)

### Test high-value signal pairs

```sql
WITH pick_signals AS (
  SELECT pst.player_lookup, pst.game_date, pst.system_id, signal_tags,
    pa.prediction_correct
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pst.player_lookup = pa.player_lookup AND pst.game_date = pa.game_date AND pst.system_id = pa.system_id
  WHERE pst.game_date >= '2026-03-05'
    AND pa.prediction_correct IS NOT NULL
)
-- Find all pairs
SELECT s1, s2,
  COUNT(*) as co_fires,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM pick_signals,
  UNNEST(signal_tags) as s1,
  UNNEST(signal_tags) as s2
WHERE s1 < s2  -- avoid duplicates
  AND s1 NOT IN ('model_health', 'high_edge', 'edge_spread_optimal')
  AND s2 NOT IN ('model_health', 'high_edge', 'edge_spread_optimal')
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY hr DESC
```

**Expected high-value combos:**
- `projection_consensus_over` + `sharp_book_lean_over` → external agreement
- `sharp_money_over` + `high_edge` → sharp money validates model
- `positive_clv_over` + `high_edge` → market movement confirms model
- `sharp_money_under` + `sharp_book_lean_under` → double sharp confirmation

If any combo HR >= 80% on N >= 15, register in `signal_combo_registry` BQ table.

---

## Phase 6: Model Fleet Cleanup (Mar 20-25)

### 6a. Promotion assessment

Models approaching promotion gates (N >= 20 edge 3+):

| Model | Edge 3+ HR | N | Next step |
|-------|-----------|---|-----------|
| catboost_v16_noveg_train1201_0215 | 73.3% | 15 | **5 more → promotion decision** |
| catboost_v12_noveg_train0108_0215 | 77.8% | 9 | Need ~11 more |
| lgbm_v12_noveg_train1201_0209 | 83.3% | 6 | Need ~14 more |
| lgbm_v12_noveg_train0103_0227 | 72.7% | 11 | Need ~9 more |

### 6b. Disable candidates

Models with poor edge 3+ performance (< 50% on 20+ picks):

| Model | Edge 3+ HR | N | Action |
|-------|-----------|---|--------|
| catboost_v12_noveg_q45_train1102_0125 | 50.8% | 63 | **Review for disable** |
| catboost_v12_noveg_q43_train1102_0125 | 50.7% | 71 | **Review for disable** |
| catboost_v12_q43_train1225_0205 | 33.3% | 12 | **Disable candidate** |
| catboost_v12_train1102_0125 | 37.5% | 8 | **Disable candidate** |
| catboost_v12_vegas_q43_train0104_0215 | 42.9% | 7 | Monitor |
| similarity_balanced_v1 | 46.7% | 15 | **Disable candidate** |

**Process:**
```bash
python bin/deactivate_model.py MODEL_ID --dry-run  # Preview impact
python bin/deactivate_model.py MODEL_ID             # Execute
```

### 6c. UNDER_SIGNAL_WEIGHTS recalibration

Monthly check — run after Mar 15:
```sql
SELECT signal_tag,
  COUNTIF(pa.prediction_correct) as wins,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr_30d
FROM nba_predictions.pick_signal_tags pst
CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
JOIN nba_predictions.prediction_accuracy pa
  ON pst.player_lookup = pa.player_lookup AND pst.game_date = pa.game_date AND pst.system_id = pa.system_id
WHERE pa.recommendation = 'UNDER'
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND pa.prediction_correct IS NOT NULL
  AND signal_tag IN ('sharp_book_lean_under', 'book_disagreement', 'bench_under',
    'home_under', 'extended_rest_under', 'starter_under')
GROUP BY 1
ORDER BY hr_30d DESC
```

Compare live 30d HR to current weights. If ranking order diverges significantly, update `UNDER_SIGNAL_WEIGHTS`.

---

## Phase 7: Pick Volume Optimization (ongoing)

### Current funnel (Mar 4)
```
726 predictions → 36 edge 3+ → 13 unique players → 11 pass signal gate → 2 picks
```

### Levers to increase volume

| Lever | Expected impact | Risk | When |
|-------|----------------|------|------|
| Promote projection_consensus to rescue | +1-3 picks/day | Unknown HR | Mar 12+ |
| Promote sharp_money to rescue | +1-2 picks/day | Unknown HR | Mar 15+ |
| Add new UNDER signals to weights | Better UNDER ranking | Minimal | Mar 12+ |
| Disable poor models (reduce noise) | Cleaner edge selection | May lose some picks | Mar 20+ |
| Lower edge floor from 3.0 | +many picks | HR drops significantly | NOT RECOMMENDED |

### Target state (end of March)
- **4-8 picks/day** (up from 2-3)
- **58%+ HR** (maintain or improve)
- **avg real_sc >= 2.0** (up from ~1.5)
- **6+ shadow signals promoted or disabled** (clear decisions)

---

## Phase 8: Advanced Experiments (Mar 25+, if time permits)

### 8a. Brier-weighted model selection
- Use `model_performance_daily.brier_score_14d` to weight model selection in cross_model_scorer
- Hypothesis: well-calibrated models produce better edges
- Requires 2+ weeks of Brier data (accumulating since Session 399)

### 8b. Signal decay detection automation
- Currently manual: check signal_health_daily for COLD signals
- Automate: if any signal drops to COLD for 3+ consecutive days, disable it
- Implementation: add check to `decay-detection` Cloud Function

### 8c. Dynamic edge floors by signal density
- Currently static: edge >= 3.0 (or rescue)
- Hypothesis: picks with 5+ real signals might be profitable at edge 2.0
- Test retroactively before implementing

### 8d. Regime-aware signal thresholds
- Use calendar_regime to adjust signal thresholds
- E.g., tighten edge floors during toxic window (Jan 30 - Feb 25)
- May not be relevant until next season

---

## Don't Do

- Don't add features to models (77+ dead ends, V12_NOVEG is optimal)
- Don't retrain models (10 in fleet, focus on evaluation and signal work)
- Don't build NBA Tracking signals (redundant with model features)
- Don't build referee signals without referee assignment data
- Don't promote signals with N < 30 graded (statistical noise)
- Don't lower edge floors below 3.0 (25% HR below edge 3 in best bets)
- Don't designate a single production champion (multi-model is working)
- Don't relax zero-tolerance defaults (intentional coverage trade-off)

---

## Success Metrics (End of March)

| Metric | Current | Target |
|--------|---------|--------|
| Daily picks | 1-3 | 4-8 |
| Best bets HR (14d rolling) | 58.3% | >= 58% |
| Average real_sc on picks | ~1.5 | >= 2.0 |
| Shadow signals resolved | 0/12 | >= 8/12 promoted or disabled |
| New signals operational | 0 | 2-4 promoted from shadow |
| Models disabled | 0 | 2-4 underperformers removed |
| Signal combos discovered | 0 | 1-3 new SYNERGISTIC combos |
