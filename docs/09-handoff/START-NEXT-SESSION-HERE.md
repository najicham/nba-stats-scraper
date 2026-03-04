# Start Your Next Session Here

**Updated:** 2026-03-04 (Session 404 — Shadow Signal Expansion)
**Status:** 26 active signals, 12 shadow signals accumulating, 10 enabled models (no single champion). Algorithm `v404_sharp_money_shadow`.

---

## Quick Start

```bash
# 1. Morning steering report
/daily-steering

# 2. Check pipeline health
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. Review best bets config
/best-bets-config
```

---

## What's New (Sessions 401-404)

1. **10 new scrapers deployed** — Projections (NumberFire, FantasyPros, DFF, Dimers), External Analytics (TeamRankings pace, Hashtag DvP, RotoWire lineups, Covers referee, VSiN betting splits, NBA tracking). 7 of 10 producing data.
2. **12 shadow signals** — 8 from Session 401 (projection consensus, CLV, pace, DvP) + 4 from Session 404 (VSiN sharp money, RotoWire minutes). All firing but NOT affecting picks.
3. **VSiN sharp money signals** (Session 404) — `sharp_money_over/under` + `public_fade_filter`. Handle vs ticket divergence — classic sharp indicator.
4. **Away_noveg filter REMOVED** (Session 401) — was blocking winning picks. Newer models have no AWAY penalty.
5. **Star_under filter REMOVED** (Session 400b) — Feb collapse was model staleness, not structural.
6. **CLAUDE.md trimmed** 455 → 385 lines — dead ends and signal details moved to dedicated docs.

---

## Immediate: Trigger 3 Fixed Scrapers

Sessions 403-404 fixed NumberFire (GraphQL), VSiN (server HTML), NBA Tracking (nba_api). Deploy succeeded but scrapers haven't been triggered yet:

```bash
# Trigger each scraper manually via Cloud Scheduler
gcloud scheduler jobs run nba-numberfire-projections --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs run nba-vsin-betting-splits --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs run nba-tracking-stats --location=us-west2 --project=nba-props-platform
```

Then verify data appears:
```sql
SELECT "numberfire" as source, COUNT(*) as row_count FROM nba_raw.numberfire_projections WHERE game_date >= CURRENT_DATE() - 1
UNION ALL SELECT "vsin", COUNT(*) FROM nba_raw.vsin_betting_splits WHERE game_date >= CURRENT_DATE() - 1
UNION ALL SELECT "nba_tracking", COUNT(*) FROM nba_raw.nba_tracking_stats WHERE game_date >= CURRENT_DATE() - 1
```

---

## Shadow Signal Validation (run every 2-3 days)

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

**Promotion criteria:** HR >= 60% + N >= 30 → production. HR >= 65% at edge 0-5 + N >= 15 → rescue. HR < 50% + N >= 30 → disable.

---

## Current Fleet (10 enabled models, no single champion)

Multi-model architecture — best bets pipeline selects highest-edge per player across all enabled models.

| Model | Framework | Status | Notes |
|-------|-----------|--------|-------|
| Multiple CatBoost v12_noveg | CatBoost | ENABLED | Various training windows |
| 2× XGBoost (s42, s999) | XGBoost | ENABLED | 65.9% mean HR, seed-validated |
| 2× LightGBM | LightGBM | ENABLED | vw015 66.7% HR |
| Legacy catboost_v12 | CatBoost | LEAK FIXED | No picks since Feb 24 |

**Promotion gates:** N >= 20 graded edge 3+, HR >= 65%, balanced OVER/UNDER, Brier below fleet avg.
**Disable threshold:** < 45% HR on 20+ graded best bets picks → `python bin/deactivate_model.py MODEL_ID`

---

## Strategic Priorities

### Priority 1: Shadow Signal Validation (~Mar 5-20)
- 12 shadow signals accumulating data. First promotion decision ~Mar 12 (projection_consensus).
- `predicted_pace_over` first to fire (2x on Mar 4). Others awaiting scraper data.
- Run validation query every 2-3 days.

### Priority 2: Signal Rescue Performance (14d check ~Mar 18)
- Signal rescue live since Mar 4. Need 14+ days of data.
- Any rescue tag < 52.4% on 15+ picks → remove from aggregator rescue_tags.
- Overall rescued pick HR < 55% on 30+ picks → tighten criteria.

### Priority 3: Threshold Experiments (~Mar 12+, when N >= 20)
- Sweep thresholds for shadow signals (projection_consensus MIN_SOURCES, predicted_pace MIN_PACE, etc.)
- Test signal combinations for combo registry candidates.

### Priority 4: Model Fleet Cleanup (~Mar 22+)
- Promote models passing gates to production status.
- Disable models with < 45% HR on 20+ graded best bets.

---

## Key References

- **Session 404 handoff:** `docs/09-handoff/2026-03-04-SESSION-404-HANDOFF.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **Model dead ends:** `docs/06-reference/model-dead-ends.md`
- **Calendar regime:** `docs/08-projects/current/calendar-regime-analysis/00-FINDINGS.md`
- **Session learnings:** `docs/02-operations/session-learnings.md`
- **Troubleshooting:** `docs/02-operations/troubleshooting-matrix.md`
