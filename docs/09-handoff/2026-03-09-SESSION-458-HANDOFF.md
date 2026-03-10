# Session 458 Handoff — MLB V3 FINAL Production Deploy + Dynamic Blacklist Experiment

*Date: 2026-03-09*

## What Was Done

### 1. V3 FINAL Wired into Production (COMPLETE)

All V3 FINAL settings from Session 455 replay are now in `ml/signals/mlb/best_bets_exporter.py`:

| Setting | Before | After |
|---------|--------|-------|
| Away edge floor | n/a | 1.25 K (`AWAY_EDGE_FLOOR`) |
| Away rescue | allowed | BLOCKED (`BLOCK_AWAY_RESCUE`) |
| MAX_PICKS_PER_DAY | 3 | 5 |
| `long_rest_over` | active signal | TRACKING_ONLY |
| `k_trending_over` | active signal | TRACKING_ONLY |
| Ultra edge | 1.1 | 0.5 |
| Ultra half-line | required | not required (vacuous — all K lines are x.5) |
| Ultra rescued | allowed | excluded |
| Algorithm version | `mlb_v7_s447` | `mlb_v8_s456_v3final_away_5picks` |

New config constants: `AWAY_EDGE_FLOOR`, `BLOCK_AWAY_RESCUE`, `TRACKING_ONLY_SIGNALS`. All env-var overridable.

Shadow picks path also updated to apply away edge floor + away rescue blocking (code review catch).

**Tests:** 35/35 passing (25 existing updated + 10 new).

### 2. Dynamic Blacklist Experiment (REJECTED)

Built `DynamicBlacklist` class in `season_replay.py`: walk-forward pitcher suppression — if pitcher has HR < threshold at N >= min_n trailing BB picks, auto-suppress OVER picks.

#### Initial Results (CONTAMINATED — do not use)

| Config | 2022 | 2023 | 2024 | 2025 | TOTAL | vs BL |
|--------|------|------|------|------|-------|-------|
| V3 FINAL (no BL) | +15.8u | +42.0u | +98.0u | +217.0u | +372.8u | --- |
| **N>=10 HR<40%** | +46.8u | +55.5u | +115.9u | +216.0u | **+434.2u** | **+61.4u** |
| N>=10 HR<45% | +42.8u | +55.5u | +108.7u | +206.6u | +413.5u | +40.7u |
| N>=8 HR<45% | +42.8u | +55.5u | +98.9u | +201.4u | +398.6u | +25.7u |

Looked great. Three-agent review found two critical issues:

1. **Recovery bug (HIGH):** Suppressed pitchers never got new outcomes recorded → history froze → permanent suppression. Made blacklist look valuable by trapping pitchers who would have recovered.
2. **Data load contamination:** Baseline was from Session 455 (older BQ data). DynBL runs used fresh data. Different data = different models = phantom deltas (2023 showed +13.5u with ZERO picks blocked).

#### Clean Comparison (same data load, recovery bug fixed)

| Season | HR | Baseline P&L | + DynBL N10/HR40 | Delta | Blocked |
|--------|-----|-------------|-----------------|-------|---------|
| 2022 | 59.3% / 59.4% | +45.4u | +46.8u | +1.4u | 16 |
| 2023 | 61.5% / 61.5% | +55.5u | +55.5u | +0.0u | 0 |
| 2024 | 61.1% / 61.1% | +118.3u | +118.3u | +0.0u | 6 |
| 2025 | 65.0% / 65.0% | +225.2u | +225.2u | +0.0u | 2 |
| **TOTAL** | | **+444.4u** | **+445.8u** | **+1.4u** | 24 |

**Verdict: No-op.** With recovery fix, suppressed pitchers quickly accumulate "would-have-won" outcomes and un-suppress within 2-3 games. Blacklist self-corrects before it can add value.

### 3. Clean V3 FINAL Baseline (Latest Data)

| Season | HR | P&L (vig) | ROI | Picks | Picks/Day | Ultra HR (N) | $ at $100/u |
|--------|-----|-----------|-----|-------|-----------|-------------|-------------|
| 2022 | 59.3% | +45.4u | 4.9% | 553 | 4.5 | 59.8% (378) | +$4,540 |
| 2023 | 61.5% | +55.5u | 11.9% | 299 | 1.6 | 65.1% (166) | +$5,550 |
| 2024 | 61.1% | +118.3u | 10.0% | 821 | 4.5 | 63.0% (362) | +$11,830 |
| 2025 | 65.0% | +225.2u | 17.6% | 853 | 4.7 | 67.2% (427) | +$22,520 |
| **TOTAL** | **62.0%** | **+444.4u** | **11.5%** | **2,526** | | **63.3% (1,333)** | **+$44,440** |

Note: Higher than Session 455 (+372.8u) due to BQ data backfills since then.

## V3 FINAL Deploy Config (LOCKED)

```
Training: 120d window, 14d retrains
Edge floor: 0.75 K (home), 1.25 K (away)
Away rescue: BLOCKED
Volume: 5 picks/day
Signals: long_rest_over, k_trending_over → TRACKING_ONLY
Ultra: Home + Projection agrees + edge >= 0.5 + not rescued
Staking: 1u BB, 2u Ultra
Blacklist: OFF (static and dynamic both rejected)
Algorithm: mlb_v8_s456_v3final_away_5picks
```

## Experiment Methodology (CRITICAL — Read Before Experimenting)

### Rule 1: Always Run Baseline + Experiment Back-to-Back

```bash
# CORRECT — same BQ data load, same session
PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay_cross/2025_EXP_baseline/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue

PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay_cross/2025_EXP_variant/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue \
  [YOUR EXPERIMENT FLAGS]

# WRONG — comparing to results from a previous session
```

### Rule 2: BQ Concurrency Limit

Running 4+ BQ queries simultaneously causes timeouts. Run max 2 seasons in parallel, or run all 4 sequentially in a single script (see `/tmp/run_clean_comparison.sh` pattern).

### Rule 3: V3 FINAL Baseline Flags

```
--max-picks 5 --away-edge-floor 1.25 --block-away-rescue
```

### Rule 4: Season Date Ranges

| Season | Start | End |
|--------|-------|-----|
| 2022 | 2022-04-07 | 2022-10-05 |
| 2023 | 2023-03-30 | 2023-10-01 |
| 2024 | 2024-03-28 | 2024-09-29 |
| 2025 | 2025-03-27 | 2025-09-28 |

### Rule 5: Metrics to Report

For EVERY experiment, report per-season AND total:
- **HR%** — hit rate (wins / total)
- **P&L (vig)** — vig-adjusted using actual American odds (`compute_pnl()`)
- **ROI%** — P&L / total_staked (accounts for ultra 2u staking)
- **N picks** — total best bets selected
- **Ultra HR% (N)** — ultra tier hit rate and volume
- **Picks/day** — average daily volume
- **Delta vs baseline** — per-season AND total

### Dynamic Blacklist Flags (if revisiting)

```
--dynamic-blacklist --bl-min-n 10 --bl-max-hr 0.40
```

## Dead Ends Log

| Experiment | Result | Why It Failed |
|-----------|--------|---------------|
| Static blacklist (28 pitchers) | Season-specific | 96% of pitchers only bad in 1 season |
| Dynamic BL N>=10/HR<45% | +1.4u (clean) | Self-corrects too fast, no-op |
| Dynamic BL N>=10/HR<40% | +1.4u (clean) | Same — barely triggers, pitcher recovers |
| Dynamic BL N>=8/HR<45% | Not clean-tested | More aggressive = worse (over-suppresses) |
| "Less aggressive = better" pattern | Artifact | Was actually "doing nothing = best" |

## What's Next

### P0: Before Opening Day (March 25)

1. **Deploy to production** — push to main, verify builds, check drift
2. **Odds-aware ranking** — rank by EV (edge × payout_multiplier) instead of raw edge. Heavy faves (-160+) have 64% HR but only +37u/603 picks. Test across 4 seasons.
3. **Max juice filter** — block -160+ odds? Profit center is -150 to -130 (+117u). Cross-season test needed.

### P1: Post-Launch Experiments (replay-first, measure all metrics)

4. **Edge floor tuning** — edge 0.75-1.00 is weakest bucket (57.1% HR). Test raising home floor to 0.85/1.00.
5. **RSC cap** — rsc=3-4 is 63-64% HR, rsc=6+ loses money. Test capping at rsc<=5.
6. **Lineup K rate feature** — computed in feature store, not in model. Add to training features.
7. **Umpire zone features** — orthogonal signal, could boost ballpark_k_boost.
8. **Rolling window dynamic BL** — last 15-20 picks instead of full season. Different recovery dynamics.

### Production Deploy Checklist

- [x] V3 FINAL config wired into `best_bets_exporter.py`
- [x] Tests passing (35/35)
- [x] Shadow picks path updated for away floor
- [ ] Push to main (auto-deploys)
- [ ] Verify builds: `gcloud builds list --region=us-west2 --limit=5`
- [ ] Check drift: `./bin/check-deployment-drift.sh --verbose`
- [ ] Paper trade April 1-14 at 50% stakes
- [ ] Full stakes from April 15+

## Files Modified

| File | Change |
|------|--------|
| `ml/signals/mlb/best_bets_exporter.py` | V3 FINAL: away floor, rescue block, 5/day, tracking-only, ultra redesign, shadow picks fix |
| `tests/mlb/test_exporter_with_regressor.py` | Updated 3 existing tests, added 10 new |
| `scripts/mlb/training/season_replay.py` | `DynamicBlacklist` class, recovery fix, dead code cleanup |
