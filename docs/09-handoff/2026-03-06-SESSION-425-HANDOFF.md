# Session 425 Handoff — UNDER Signal Development

**Date:** 2026-03-06
**Algorithm:** `v425_signal_health_gap`
**Status:** Deployed to production via auto-deploy

---

## What Was Done

### Problem
98.4% of model-level UNDER predictions had ZERO real signals. Only 8 UNDER BB picks published in March — a 95.3% rejection rate from 172 qualifying predictions. Almost all production signals were OVER-only.

### Changes

#### New Signals (5 shadow UNDER signals)
| Signal | Criteria | HR | N | Status |
|--------|----------|-----|---|--------|
| `volatile_starter_under` | line 18-25, std>8, edge 5+ | 65.5% | 637 | Shadow |
| `downtrend_under` | trend_slope -1.5 to -0.5 | 63.9% | 1,654 | Shadow |
| `star_favorite_under` | line 25+, spread 3+ | ~73% | 88 | Shadow |
| `starter_away_overtrend_under` | line 18-25, AWAY, over_rate>50% | 68.1% | 213 | Shadow |
| `blowout_risk_under_block_obs` | blowout_risk>=0.40, line>=15 | 16.7% | 12 | Obs filter |

#### Weight Changes
| Signal | Old Weight | New Weight | Reason |
|--------|-----------|-----------|--------|
| `sharp_book_lean_under` | 3.0 | 1.0 | Zero production fires — market regime |
| `sharp_line_drop_under` | (unweighted) | 2.5 | 87.5% HR, was firing but not weighted |
| `home_under` | 1.5 | 2.0 | 60.6% HR (N=4,253) model-level |

#### New Filter
- `b2b_under_block`: UNDER + rest_days <= 1 = 30.8% HR (N=52). Active block.

#### UNDER_SIGNAL_WEIGHTS: 11 entries (was 6)
```
sharp_book_lean_under: 1.0, mean_reversion_under: 2.5, sharp_line_drop_under: 2.5,
book_disagreement: 2.5, bench_under: 2.0, home_under: 2.0,
starter_away_overtrend_under: 1.5, extended_rest_under: 1.5,
volatile_starter_under: 1.5, downtrend_under: 1.5, star_favorite_under: 1.5
```

### Investigation Results

| Item | Finding | Action |
|------|---------|--------|
| `sharp_book_lean_under` zero fires | Market regime: FD/DK consistently set higher lines than soft books. Not a bug. | Weight demoted 3.0→1.0 |
| `mean_reversion_under` low fires | Fields correctly populated. Upstream filters kill candidates before BB. | No fix — new signals increase the UNDER candidate pool |
| Good defense UNDER filter | Feature 13 not extracted, -5.1pp vs baseline | Not worth pursuing |

---

## Files Changed

| File | Changes |
|------|---------|
| `ml/signals/aggregator.py` | b2b_under_block filter, UNDER_SIGNAL_WEIGHTS (11 entries), sharp_book_lean demotion, blowout_risk_under_block_obs |
| `ml/signals/volatile_starter_under.py` | New signal |
| `ml/signals/downtrend_under.py` | New signal |
| `ml/signals/star_favorite_under.py` | New signal |
| `ml/signals/starter_away_overtrend_under.py` | New signal |
| `ml/signals/registry.py` | 4 new signals registered (55 total) |
| `tests/unit/signals/test_aggregator.py` | b2b filter tests, expected keys |
| `CLAUDE.md` | Signal counts, top signals |
| `SIGNAL-INVENTORY.md` | Full update: new signals, filters, shadow validation query |

---

## Monitoring Schedule

| Date | Check | Action |
|------|-------|--------|
| Mar 7 | First day with new signals deployed | Verify shadow signals appear in `pick_signal_tags` |
| Mar 13 | Shadow signal fire rates | If any fire 0 times in 7 days, investigate data availability |
| Mar 20 | Shadow signal HR at N>=15 | Promote best performer to active if HR >= 65% |
| Apr 5 | projection_delta + sharp_money | 30 days of data accumulated, create signals |

### Validation Query (run after Mar 13)
```sql
SELECT signal_tag, COUNT(*) fires,
  COUNTIF(pa.prediction_correct IS NOT NULL) graded,
  COUNTIF(pa.prediction_correct) wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) /
    NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) hr
FROM nba_predictions.pick_signal_tags pst
CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON pst.player_lookup = pa.player_lookup
  AND pst.game_date = pa.game_date AND pst.system_id = pa.system_id
WHERE signal_tag IN ('volatile_starter_under', 'downtrend_under',
  'star_favorite_under', 'starter_away_overtrend_under')
  AND pst.game_date >= '2026-03-07'
GROUP BY 1 ORDER BY fires DESC
```

---

## Deployment Drift (at session end)

| Service | Status |
|---------|--------|
| nba-phase1-scrapers | STALE (5 commits behind) |
| pipeline-health-summary | STALE (~15h) |
| All others | Up to date |

---

## Key Decisions

1. **Shadow mode for all new signals** — no signals promoted to active without 7+ days of production data
2. **sharp_book_lean_under kept registered** — if market regime changes (soft > sharp), it will auto-fire
3. **No rescue logic change for UNDER** — the gap (UNDER at edge 3-5 skips rescue) is by design; new signals address the root cause (no UNDER signals firing)
4. **Good defense filter rejected** — feature not extracted and research shows negative value
