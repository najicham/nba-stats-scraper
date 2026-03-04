# Session 400 Handoff — Signal-First UNDER + Star UNDER Removal + Model Retrain

**Date:** 2026-03-04
**Algorithm:** `v400b_star_under_removed`
**Status:** All changes deployed, zero drift, research complete.

---

## Changes Made

### 1. Signal-First UNDER Architecture (aggregator.py)

UNDER edge is flat at 52-53% across all buckets — edge is NOT a quality discriminator for UNDER. UNDER picks now ranked by weighted signal quality score:

| Signal | Weight | HR |
|--------|--------|-----|
| `sharp_book_lean_under` | 3.0 | 84.7% |
| `book_disagreement` | 2.5 | 93.0% |
| `bench_under` | 2.0 | 76.9% |
| `home_under` | 1.5 | 63.9% |
| `extended_rest_under` | 1.5 | 61.8% |
| `starter_under` | 1.0 | 54.8-68.1% |
| Default (unweighted signals) | 1.0 | — |

Formula: `composite_score = signal_quality + edge * 0.1` (UNDER) vs `composite_score = edge` (OVER, unchanged).

### 2. Star UNDER Filter Removed (aggregator.py)

**Was:** Block UNDER + season_avg >= 25 (unless star_teammates_out >= 1).
**Now:** Removed entirely. `under_star_away` (AWAY + line >= 23) still active.

**Evidence:**
- Feb 50.0% HR was model staleness, not structural (last season Feb was 64.1%)
- Mar 72.1% raw, 71.4% signal-supported
- Today: blocked Maxey (edge 8.5), SGA (6.6), Giannis (4.9), Brown (4.0) — all multi-model
- Star UNDER = non-star UNDER (both 58.5%) — no tier penalty
- Best bets already filtered to 55.6% even in Feb — stack handles it

### 3. signal_health_daily Dedup (signal_health.py)

`write_health_rows()` now uses DELETE-before-INSERT pattern. Cleaned 989 duplicate rows.

### 4. New Model: `catboost_v12_noveg_train0104_0215`

- Training: Jan 4 → Feb 15 (43 days), V12_NOVEG, vegas weight 0.15x
- **ALL 6 governance gates passed**: 67.57% HR edge 3+ (n=37), OVER 90.0%, UNDER 59.3%
- Registered, enabled, producing 79 predictions today
- Worker cache refreshed — model is live

### 5. Signal Rescue Validation

Zero live data — no picks below edge 3.0 with rescue signals in recent days. Code verified working via simulation (13 rescued). Jaylen Wells OVER was the first live rescue today (edge 3.5, rescued by signal).

---

## Patterns to Watch

### A. Star UNDER Performance (Now Unblocked)

**Monitor weekly.** The research showed:

| Period | This Season HR | Last Season HR |
|--------|---------------|----------------|
| Normal (non-toxic) | 65.8% | 66.1% |
| Toxic window (Jan 25 - Feb 25) | 52.5% | 63.7% |
| March | 72.1% (82.1% latest week) | 71.9% |

**Action:** If star UNDER drops below 50% on 30+ graded picks for 2 consecutive weeks, re-evaluate. But DON'T add a permanent filter — the Feb collapse was model-specific.

```sql
-- Weekly star UNDER monitor
SELECT FORMAT_DATE("%Y-W%V", pa.game_date) as week,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy pa
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
  AND pa.has_prop_line = TRUE AND pa.recommendation = 'UNDER'
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND pa.line_value >= 25
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
```

### B. Signal-First UNDER Ranking Impact

Compare UNDER pick quality before/after v400. Look for composite_score values — UNDER should be 1-10 (signal quality), OVER should be 3-8 (edge).

```sql
-- Compare UNDER composite scores by algorithm version
SELECT algorithm_version, recommendation,
  COUNT(*) as picks,
  ROUND(AVG(composite_score), 2) as avg_composite,
  ROUND(AVG(edge), 2) as avg_edge,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-02-20'
GROUP BY 1, 2 ORDER BY 1, 2
```

### C. New Model Live Performance

`catboost_v12_noveg_train0104_0215` just started producing today. Compare to fleet:

```sql
-- New model vs fleet
SELECT system_id,
  COUNT(*) as graded,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-03-04'
  AND has_prop_line = TRUE
  AND ABS(predicted_points - line_value) >= 3
  AND prediction_correct IS NOT NULL
GROUP BY 1 HAVING graded >= 5
ORDER BY hr DESC
```

**Promote to production** after 2+ days of shadow if live HR >= 60% on edge 3+.

### D. Volume Recovery

Recent daily volume: 1-6 picks per day. With star_under removed, expect +2-4 more UNDER picks on star-heavy slates. Monitor:

```sql
SELECT game_date, total_candidates, passed_filters,
  JSON_VALUE(rejected_json, '$.star_under') as star_under_blocked
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-04'
ORDER BY game_date DESC
```

star_under should be 0 from v400b onward. If total volume stays < 3 on 6+ game slates, investigate `away_noveg` (blocked 3-6 picks recently, may need fresh validation).

### E. away_noveg Filter (Potential Next Removal)

Second-biggest blocker at 3-6 rejections per day. Current logic: v12_noveg/v9 family + AWAY game = blocked. March noveg HR is 67.9% (N=81) — recovering like everything else post-toxic-window. Watch for 2 weeks, then evaluate relaxing.

### F. Signal Rescue Accumulation

First live rescue happened today (Jaylen Wells OVER, edge 3.5). After 14 days:
- If rescued pick HR >= 55% on 10+ picks → rescue is working
- If < 52.4% on 15+ picks → tighten rescue tags
- Track per-tag HR to identify weak rescue signals

---

## Recent Best Bets Record

| Date | Picks | Graded | W-L | HR |
|------|-------|--------|-----|-----|
| Mar 4 | 2 | 0 | — | — |
| Mar 1 | 2 | 2 | 2-0 | 100% |
| Feb 28 | 6 | 5 | 2-3 | 40% |
| Feb 27 | 1 | 1 | 0-1 | 0% |
| Feb 26 | 5 | 4 | 2-2 | 50% |
| Feb 24 | 2 | 2 | 1-1 | 50% |
| Feb 22 | 4 | 4 | 4-0 | 100% |

Graded total: 10-7 (58.8%). Low volume hurts per-day variance.

---

## Research Findings: Star UNDER Cross-Season Analysis

Full analysis from research agent (key conclusions):

1. **No seasonal filter needed** — Feb toxic window doesn't replicate across seasons (64.1% last Feb vs 50.0% this Feb)
2. **DOW patterns rotate** — Sunday was catastrophic this season (41.3%) but excellent last season (69.9%). Not stable.
3. **Signal count doesn't discriminate** — too few signal-tagged star UNDER picks for statistical power
4. **Best bets already protects** — 55.6% in Feb even without the filter. The full filter stack (edge floor, signal gates, away block) handles quality
5. **Root cause was model staleness** — not a structural star-UNDER problem. Fresh models fix it.

**Dead ends confirmed:** star_under permanent filter, seasonal star_under activation, DOW-specific star_under, signal-count-gated star_under.

---

## Files Modified

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Signal-first UNDER scoring, star_under removal, version v400b |
| `ml/signals/signal_health.py` | DELETE-before-INSERT dedup |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Updated |

---

## Strategic Priorities (Next Session)

1. **Monitor tonight's results** — first night with star_under removed + signal-first UNDER
2. **New model promotion** — 2+ days of `catboost_v12_noveg_train0104_0215` shadow data
3. **away_noveg evaluation** — is it still justified post-toxic-window?
4. **Signal rescue validation** — accumulate 14 days of data
5. **Brier-weighted model selection** — use calibration scores for selection
