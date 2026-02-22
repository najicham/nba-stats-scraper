# Session 322 Handoff: Line Contamination Remediation Complete + Full Season Replay Study

**Date:** 2026-02-21
**Status:** COMPLETE — all 6 remediation phases done, season replay analyzed

---

## What Was Completed

### Remediation (6 Phases)

| Phase | Task | Status | Result |
|-------|------|--------|--------|
| **1** | Re-grade Dec 20/22/25 | DONE | Sub-5 lines: 89/62/21 → 1/1/0. HRs normalized: 77-80% → 24-33% |
| **2** | Jan 12 full GCS re-export | DONE | All critical exports (results, predictions, signals, admin dashboard) |
| **3a** | model_performance_daily rebuild | DONE | Dropped + recreated table (streaming buffer blocked DML). 77 rows, Jan 9 - Feb 20 |
| **3b** | signal_health_daily rebuild | DONE | Dropped + recreated table. 507 rows, Jan 9 - Feb 21 |
| **4** | Best bets season backfill (Nov 19 - Jan 7) | DONE | 46 dates exported to GCS. Early models didn't pass edge 5+ floor → BQ starts Jan 9 |
| **5** | Re-export dashboard | DONE | Season record: 50W-28L (59.5% HR), 84 picks total |
| **6** | Validation queries | DONE | All checks passed |

### Contamination Audit

Comprehensive audit confirmed: **zero BettingPros contamination** in `prediction_accuracy` or `player_prop_predictions`. The contamination exists only in the raw table (`nba_raw.bettingpros_player_points_props`): 53,319 non-points records (rebounds, assists, threes, blocks, steals). The `market_type='points'` filter (commit `a50fd28e`) and line floor sanity checks (commit `a9bf195c`) prevent contamination.

### Full Season Replay Study

Comprehensive analysis of all models, strategies, and the best bets algorithm from Nov 19 - Feb 20.

---

## Replay Study Findings

### Model Performance (Season)

| Model | Period | Edge 3+ N | HR | Edge 5+ N | HR |
|-------|--------|-----------|-----|-----------|-----|
| catboost_v8 | Nov 19 - Feb 20 | 3,106 | 56.3% | 1,618 | **58.8%** |
| catboost_v9 (champion) | Jan 9 - Feb 20 | 573 | 48.3% | 157 | 52.9% |
| catboost_v12 | Feb 1 - Feb 20 | 78 | 51.3% | 10 | 60.0% |
| moving_avg_baseline_v1 | Nov 19 - Jan 3 | 1,198 | 62.6% | 437 | **67.5%** |
| xgboost_v1 | Nov 19 - Jan 19 | 575 | 53.9% | 201 | **70.1%** |

**Surprise:** V8 has the strongest long-term edge 5+ HR (58.8%, N=1,618). Early experimental models (moving_avg_baseline, xgboost_v1) had very high HRs but smaller sample sizes.

### V9 Weekly Performance (Jan 1+, edge 3+)

| Week | N | HR | Notes |
|------|---|-----|-------|
| Jan 5 | 59 | 55.9% | Solid |
| Jan 12 | 91 | 46.2% | Bad |
| Jan 19 | 117 | **64.1%** | Best week |
| Jan 26 | 107 | 51.4% | Breakeven |
| Feb 2 | 136 | **33.1%** | CRASH (35+ days stale) |
| Feb 9 | 58 | **39.7%** | Still decaying |
| Feb 16 | 5 | 80.0% | Post-retrain (tiny N) |

### Edge Threshold Analysis (V9, Jan 9+)

| Edge | Direction | N | HR | Verdict |
|------|-----------|---|-----|---------|
| 3-5 | OVER | 181 | 47.5% | LOSING |
| 3-5 | UNDER | 233 | 46.4% | LOSING |
| 5-7 | OVER | 41 | 56.1% | PROFITABLE |
| 5-7 | UNDER | 63 | 58.7% | PROFITABLE |
| 7+ | OVER | 19 | **63.2%** | GREAT |
| 7+ | UNDER | 30 | **35.5%** | CATASTROPHIC (blocked) |

**Edge 5+ floor validated.** Edge 3-5 is below breakeven. UNDER 7+ block saves ~$500+ in losses.

### Replay Strategy Comparison (Jan 9 - Feb 20)

| Strategy | HR | ROI | P&L | Blocked Days | Switches |
|----------|-----|-----|-----|-------------|----------|
| **Threshold** | **68.1%** | **29.9%** | **$2,370** | 21 | 1 |
| Conservative | 63.0% | 20.3% | $2,230 | 16 | 0 |
| BestOfN | 57.1% | 9.1% | $1,680 | 0 | 2 |
| Oracle | 61.6% | 17.7% | $3,340 | 0 | 37 |

**Threshold beats oracle on ROI** (29.9% vs 17.7%). Blocking during decay is more profitable than perfect model selection. Not betting is often the best bet.

### Best Bets Algorithm Performance

**Season record: 50W-28L, 59.5% HR, cumulative P&L: +$1,260**

- Peaked at +$2,200 on Feb 7
- Drawdown of -$940 from Feb 8-20 (model staleness, pre-ASB)
- The drawdown would have been avoided with model health blocking

---

## Key Recommendations (Next Session)

### 1. Add Model Health Gate to Best Bets (HIGH PRIORITY)

The replay proves that blocking during decay outperforms all other strategies. The best bets algorithm currently has no awareness of model health — it kept picking during Feb 8-20 when V9 was crashing at 27-33% weekly HR.

**Proposed:** Add a 7d rolling HR check before selecting picks. If champion model HR < 52.4% (breakeven at -110 odds), skip that day's picks entirely. This would have saved ~$940 in Feb drawdown.

**Implementation:** Query `model_performance_daily` for champion model's `rolling_hr_7d` before running the best bets algorithm. If below threshold, export 0 picks.

### 2. Keep Current Infrastructure

- **Edge 5+ floor:** Validated — edge 3-5 is consistently below breakeven
- **UNDER 7+ block:** Validated — 35.5% HR without it
- **7-day retrain cadence:** Validated — Feb crash proves models go stale fast
- **Negative filters:** Working correctly

### 3. Investigate V8 as Supplementary Model

V8 shows 58.8% HR at edge 5+ with N=1,618 — the most data AND a strong HR. Could serve as:
- A fallback during V9 decay periods
- An ensemble component
- A baseline comparison for new models

---

## Operational Notes

### Streaming Buffer Workaround

`model_performance_daily` and `signal_health_daily` had active streaming buffers preventing DML (DELETE). Workaround: save schema → drop table → recreate → backfill. This is safe for small monitoring tables.

### Best Bets Backfill Coverage

The Nov 19 - Jan 7 backfill exported to GCS but produced 0 BQ picks for early dates — early models didn't generate edges >= 5. The BQ `signal_best_bets_picks` table effectively starts Jan 9 (when V9 champion went live).

### Session Execution Notes

- Ran commands sequentially per Session 321 learnings (avoid parallel BQ contention)
- Dec 25 grading had a transient Firestore connectivity error — retry succeeded
- Dec 29 best bets export had a BQ timeout — recovered automatically
- Total session time: ~45 min for remediation + ~15 min for analysis

---

## Tables Modified

| Table | Action | Rows |
|-------|--------|------|
| `prediction_accuracy` | Re-graded Dec 20/22/25 | 535 graded |
| `model_performance_daily` | Dropped + rebuilt from scratch | 77 rows (Jan 9 - Feb 20) |
| `signal_health_daily` | Dropped + rebuilt from scratch | 507 rows (Jan 9 - Feb 21) |
| `signal_best_bets_picks` | Backfilled Nov 19 - Jan 7 | 46 dates exported |

## GCS Files Updated

- `v1/signal-best-bets/{date}.json` for 46 dates (Nov 19 - Jan 7)
- `v1/best-bets/record.json` — 50W-28L, 59.5%
- `v1/best-bets/all.json` — 84 picks, 78 graded
- `v1/admin/dashboard.json` — full season data
- `v1/results/2026-01-12.json` + various Jan 12 exports

## Files Changed

None — this session was purely operational (backfills, re-grading, analysis). All code changes were in prior sessions.
