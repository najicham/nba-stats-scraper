# Session 415 Handoff — Rescue Tightening & Filter Re-evaluation

**Date:** 2026-03-05
**Type:** Signal optimization, filter tuning
**Key Insight:** 67% of recent picks are rescued OVERs with ~50% HR — the #1 drag on BB performance. Tightened rescue eligibility, promoted 2 blocking filters, and added a rescue cap.

---

## What This Session Did

### 1. Rescue Tightening (7 Changes)

| Change | Rationale |
|--------|-----------|
| Removed `low_line_over` from rescue tags | 50% HR at edge 3-5. Not a conviction signal. |
| Removed `high_scoring_environment_over` from rescue tags | Only fires in high-scoring environments already captured by other signals |
| Demoted `signal_stack_2plus` to observation-only | 50% HR (N=6). Thinnest quality tier — 2 real signals is not enough. |
| Promoted `high_spread_over` to active block | 44.3% HR (N=61). Blowout games kill OVER. Was observation, now blocks. |
| Promoted `mid_line_over` to active block | 47.9% HR (N=213). Lines 15-25 are hardest to beat OVER. Was observation, now blocks. |
| Demoted `under_star_away` to observation | 73% HR post-ASB recovery. Was actively blocking good UNDER picks. |
| Added rescue cap at 40% of slate | Safety valve: even if new rescue tags are added, can't exceed 40% rescued. |

### 2. Test Fixes (8 Assertions)

Fixed stale test assertions that broke with the aggregator changes:
- `away_noveg` references (removed in Session 401)
- `star_under` signal count expectations (Session 400 changes)
- `sc3_over` signal expectations
- `flat_trend_under` default parameter handling

### 3. Deploy Verification

| Check | Status |
|-------|--------|
| Cloud Build | 5/5 SUCCESS |
| prediction-coordinator | commit 783d5c7 (latest) |
| prediction-worker | Up to date |
| phase6-export | Redeployed |
| Algorithm version in BQ | `v415_rescue_tighten` confirmed |
| Deployment drift | 1 stale (nba-phase1-scrapers — scraper-only, not critical) |

### 4. Re-Export Results (Mar 5)

| Metric | Before (v414) | After (v415) |
|--------|---------------|--------------|
| GCS JSON picks | 6 | 1 |
| Rescue % of slate | 66.7% | 0% |
| New filter blocks | — | signal_stack_2plus_obs (4), regime_rescue_blocked (2), high_spread_over (2) |
| Total filtered picks | 10 | 23 |

**Note:** BQ still has old v414 picks due to scoped DELETE (true pick locking from Session 412). New algorithm only affects freshly-exported picks. Tomorrow's slate will be the first full test.

**Degradation guard triggered:** GCS backed up old 6-pick version to `_backups/` before writing 1-pick version. Working as designed.

---

## Files Changed

| File | Changes |
|------|---------|
| `ml/signals/aggregator.py` | 7 logic changes (rescue tags, filter promotions, rescue cap) |
| `tests/unit/signals/test_aggregator.py` | 8 test assertion fixes + new rescue cap tests |
| `docs/02-operations/MONITORING-CHECKLIST.md` | Added rescue cap and under_star_away review items |
| `docs/.../SIGNAL-INVENTORY.md` | Updated signal statuses |

---

## Monitoring Plan

### Week 1 (Mar 6-12): Rescue Cap Calibration

**Daily via `/daily-steering`:**
- Rescue % of slate (target: < 40%, cap should rarely trigger)
- Rescued vs normal HR
- Pick count (fewer picks is intentional)
- New filter block counts

**Decision at Mar 12:**
- Rescue HR < 55% at N≥15 → further tighten (remove `volatile_scoring_over` or cap at 30%)
- Rescue HR > 60% → loosen cap to 50%
- Cap never triggers → 40% is a good safety net, keep

### Week 2 (Mar 13-19): under_star_away Review

```sql
SELECT filter_reason, COUNT(*) as n,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason = 'under_star_away'
  AND game_date >= '2026-03-06'
  AND prediction_correct IS NOT NULL
GROUP BY 1;
```

**Decision at Mar 19:**
- Counterfactual HR > 60% → keep observation (filter was blocking winners)
- Counterfactual HR < 50% → re-activate the block
- N < 15 → extend observation 2 more weeks

---

## Known Risks

1. **mid_line_over may subsume starter_over_sc_floor** — both target low-line OVERs. If starter_over picks stop appearing, check for overlap. Intentional for now.
2. **Pick count drop is dramatic** — 6→1 for today's slate. This is expected on a rescue-heavy day. Non-rescue-heavy days should see minimal change.
3. **Scoped DELETE means mixed versions in BQ** — old v414 picks coexist with v415. Only fresh exports use new algorithm.

---

## Context for Next Session

- **Market compression still RED** (0.596 ratio, avg max edge 6.4)
- **OVER collapse ongoing** — model overestimates +1.8-2.2pts post-ASB, self-corrects via 56d window
- **Apr 5+ experiment window** — projection_delta and sharp_money data accumulating
- **Fleet:** 4 HEALTHY, 1 WATCH, 2 DEGRADING, 19 BLOCKED (auto-disabled)
