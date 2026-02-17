# Session 282 Handoff — Experiment Filters + Cross-Season Dimension Analysis

**Date:** 2026-02-17
**Focus:** Build and test 7 experiment filters on the season replay engine, run cross-season validation, discover player blacklist as the top improvement
**Result:** Player blacklist (+$10,450 combined P&L improvement), 4 new dimension analyses, definitive rejection of 5 experiment ideas

---

## What Was Done

### Continued from Session 281 (hit context limit)

Session 281 built adaptive mode + rolling training into the replay engine and discovered rolling 56-day training is +$9,550 vs expanding. Session 282 picked up where 281 left off:

1. **Built 7 experiment filters** into `season_replay_full.py` (~250 lines):
   - A: `--eval-months` — Only evaluate picks in specific months
   - B: `--skip-days 1,4` — Skip Tuesday + Friday picks
   - C: `--min-pts-std 5 --max-pts-std 10` — Player volatility filter
   - D: `--tier-direction-rules` — Star=UNDER only, Bench=OVER only
   - E: `--player-blacklist-hr 40` — Blacklist players below 40% HR after 8+ picks
   - F: `--warmup-days 42` — Skip first 42 days of evaluation
   - G: `--tier-models` — Train separate models per player tier

2. **Added 4 new dimensions** to `compute_dimensions()`:
   - Day of Week (Mon-Sun)
   - Volatility Bucket (Low/Med/High/VHigh by points std dev)
   - Direction x Tier (Star/Starter/Bench x OVER/UNDER)
   - Monthly (Nov-Apr)

3. **Ran 14 experiments** (7 filters x 2 seasons where possible, 6 succeeded for both seasons)

4. **Updated findings doc** with complete cross-season analysis

### Key Results

**Player Blacklist is the biggest discovery:**

| Variant | Combined P&L | Delta vs Base | Cross-Season? |
|---------|-------------|---------------|---------------|
| Rolling56 (base) | +$59,520 | — | YES |
| **E: Blacklist40** | **+$69,970** | **+$10,450 (+17.6%)** | **YES** |
| B: SkipTueFri | +$53,150 | -$6,370 | No (DOW inverts) |
| D: TierDir | +$48,970 | -$10,550 | No (hurts 2424-25) |
| COMBO | +$50,990 | -$8,530 | No (too much volume loss) |

**Definitive rejections:** Day-of-week filters, tier-direction rules, tier-specific models, volatility filters (no effect), warmup period (broken implementation).

**New dimension findings:**
- Day of Week: **Completely inverts between seasons** — Sunday best in 2025-26 (68.5%), worst in 2024-25 (51.6%). Do NOT filter.
- Direction x Tier: Only **Starter UNDER** (55.9%/57.8%) and **Star UNDER** (55.6%/54.3%) are stable. ALL OVER combos are season-specific.
- Month: **January is the sweet spot** both seasons (59.3%/58.8%). December is consistently weakest (56.0%/51.4%).

---

## Files Modified

| File | Changes |
|------|---------|
| `ml/experiments/season_replay_full.py` | +250 lines: 7 experiment filters, 4 new dimensions, player blacklist tracking, tier model training |
| `ml/experiments/analyze_replay_results.py` | No changes this session (cross-season comparison added in S281) |
| `docs/08-projects/current/season-replay-analysis/00-FINDINGS.md` | Updated with Session 282 results |

## Files Created

| File | Description |
|------|-------------|
| `docs/09-handoff/2026-02-17-SESSION-282-HANDOFF.md` | This handoff |

## Result Files (gitignored)

- `replay_2526_blacklist40.json` + `replay_2425_blacklist40.json` — WINNER
- `replay_2526_skipTueFri.json` + `replay_2425_skipTueFri.json` — rejected
- `replay_2526_tierdir.json` + `replay_2425_tierdir.json` — rejected
- `replay_2526_combo.json` + `replay_2425_combo.json` — rejected
- `replay_2526_rolling56_v2.json` + `replay_2425_rolling56_v2.json` — baseline with new dimensions
- `replay_2526_tiermodels.json` — rejected (2526 only)
- `replay_2526_vol5to10.json` — no effect (2526 only)

---

## Immediate Next Steps (Before Feb 19)

### Priority 0: Implement Blacklist in Production
The player blacklist requires a production-side implementation:
1. Track per-player rolling HR in `prediction_accuracy` (already exists — just query it)
2. Add a blacklist check in the signal aggregator or enrichment trigger
3. Blacklist threshold: <40% HR with 8+ graded picks
4. Implementation options:
   - **Option A (simple):** Add to `enrichment_trigger` — query prediction_accuracy for per-player HR, set `is_active=FALSE` for blacklisted players
   - **Option B (full):** Add to signal aggregator as a pre-filter before composite scoring
   - **Option C (lightweight):** Add to `tonight_player_exporter` — filter blacklisted players from JSON export

### Priority 1: Rolling Training Window
Modify `retrain.sh` and `quick_retrain.py` to use `--train-start` based on `(current_date - 56 days)` instead of fixed dates. +$9,550 improvement.

### Priority 2: Feb 19 Validation (Day-of)
- [ ] Run `/validate-daily`
- [ ] Verify all 6 models generate predictions
- [ ] Check `xm_*` cross-model subsets fire
- [ ] Monitor first day's results for blacklist-eligible players

---

## Dead Ends (Do NOT Revisit)

| Idea | Why It Failed |
|------|--------------|
| Day-of-week filtering | Patterns completely invert between seasons |
| Tier-direction rules (Star=UNDER, Bench=OVER) | Only works in 2025-26, -$8,500 regression in 2024-25 |
| Per-tier models (Star/Starter/Bench) | 56.6% HR vs 57.3% standard. Lower HR despite 3x training cost |
| Volatility filter | feature_3 values mostly <5 in 2025-26. Need to investigate data before filtering on it |
| COMBO (all filters) | Highest HR (62.1%) but -$8,530 vs baseline due to volume loss |
| Warmup period | Implementation breaks when warmup + min_training_days creates empty eval windows |
