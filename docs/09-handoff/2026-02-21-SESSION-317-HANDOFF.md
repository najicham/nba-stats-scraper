# Session 317 Handoff — Best Bets Research, GCS Endpoints, External System Review

**Date:** 2026-02-21
**Focus:** Fix daily-steering, research down-week filters, build GCS best-bets endpoints, synthesize two external Opus system reviews into prioritized action plan
**Status:** All 5 planned tasks complete. New session should execute the action plan from external reviews.
**Prior sessions:** 316 (backfill fix, true HR=74.2%), 315 (directional cap investigation), 314 (consolidated best bets)

---

## TL;DR

Session completed the Session 316 handoff priorities: fixed daily-steering to query the correct table, researched 5 filter hypotheses (none warranted), verified combo signal integration (24% overlap, healthy), built two new GCS endpoints (`record.json` and `history.json`), and ran what-if retrain assessment (deferred — market too thin post-ASB).

Then synthesized recommendations from two independent external Opus reviews into a prioritized action plan for the next session.

---

## What Was Done

### 1. Fixed Daily-Steering Skill
- **File:** `.claude/skills/daily-steering/SKILL.md`
- Replaced `current_subset_picks WHERE subset_id = 'best_bets'` with `signal_best_bets_picks` in both query blocks (lines 101-122 and 128-179)
- Daily-steering now shows the true 74.2% season HR instead of the wrong ~48%

### 2. Down-Week Research (5 BQ Queries)
No new filters warranted — all hypotheses either above threshold or insufficient N:

| Hypothesis | Result | Decision |
|------------|--------|----------|
| blowout_recovery as negative filter | 65.0% HR (N=20) vs 76.7% without | No filter (above 55% threshold) |
| prop_line_drop_over + low line (<15) | 86.0% HR (N=57) | Excellent, no filter needed |
| Low-line OVER block (line < 15) | Bench <12 = 85.7% (N=70, best tier) | No filter |
| UNDER star 25+ | 37.5% HR (N=8) | Too small for filter (need N>=20) |
| rest_advantage_2d weekly decay | W2-W3=83%, W6=63.6%, W7=40% | Confirmed decay, cap at W5 |

### 3. Combo Signal Integration Check
- 32/134 (24%) best bets have combo_he_ms or combo_3way signals — healthy overlap
- 533 OVER edge 5+ predictions NOT in best bets have lower avg edge (7.3 vs 9.4) — correctly filtered by quality/signal count/blacklist

### 4. GCS Best Bets Endpoints (NEW)
- **New file:** `data_processors/publishing/best_bets_record_exporter.py`
- **Two endpoints live:**
  - `v1/best-bets/record.json` — season/month/week W-L + current streak + best streak
  - `v1/best-bets/history.json` — full graded pick history grouped by week/day (135 picks, 7 weeks)
- Integrated into `daily_export.py` as `best-bets-record` export type
- Verified at: `https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/record.json`

### 5. Retrain Assessment
- What-if with `--train-end 2026-02-19`: MAE 4.39, bias +0.08, but **0 edge 5+ picks**
- Current model (train to Feb 5): also **0 edge 5+ picks** across 9 game days
- Decision: **Defer retrain to Feb 28** — post-ASB market too thin, retraining won't help

---

## External System Review — Synthesized Recommendations

Two independent Opus chats reviewed the full system (models, signals, filters, retraining, performance). Below is the synthesis.

### Consensus (Both Agree — High Confidence)

| Recommendation | Priority | Effort |
|----------------|----------|--------|
| Add edge distribution / market compression early warning to `/daily-steering` | **#1** | 2 hrs |
| Promote `book_disagreement` signal to production (93% HR, track N) | **#2** | 1 hr |
| Remove `minutes_surge` (53.7%, W4 decay) and `cold_snap` (N=0) | **#3** | 30 min |
| Cap `rest_advantage_2d` at week 5 of season | **#4** | 30 min |
| Don't switch to V12 as champion (anti-correlation finding) | Confirmed | N/A |
| Don't add more filters as reaction to February | Confirmed | N/A |
| Edge-first architecture is correct | Confirmed | N/A |
| February was market structure, not model failure | Confirmed | N/A |
| Don't filter blowout_recovery or UNDER star 25+ (N too small) | Confirmed | N/A |

### Best Unique Ideas (Cherry-Picked)

| Source | Idea | Why It's Good | Effort |
|--------|------|---------------|--------|
| Chat 2 | **Direct edge prediction** (predict actual-line, not raw points) | Reframes problem to directly predict what we're betting on | 3 hrs |
| Chat 2 | **Separate OVER/UNDER models** | Directly addresses structural OVER dependency | 3 hrs |
| Chat 2 | **Filter audit** — check each filter's false positive rate | Reduces overfitting risk from 12 accumulated filters | 2 hrs |
| Chat 1 | **Blended V9/V12 ensemble** (65/35 weighted average) | Extracts V12 signal without consensus anti-correlation | 2 hrs |
| Chat 1 | **League-wide scoring pace feature** (`league_avg_ppg_7d`) | Auto-corrects for scoring environment shifts (ASB, tanking) | 2 hrs |
| Chat 2 | **Remove star-level UNDER exception** until N>=25 | N=7 is too small to carve out an exception | 30 min |
| Chat 2 | **Add time decay to player blacklist** (30-day recency) | Players who improve should graduate off | 1 hr |

### Ideas We're Not Doing

| Idea | Why Not |
|------|---------|
| Kelly bet sizing (Chat 2 #2 priority) | Bankroll management, not model improvement |
| Stop V12 shadows entirely (Chat 2) | Shadow cost is minimal, free data |
| LightGBM (Chat 1) | CatBoost is SOTA for our data; switching frameworks unlikely to matter |
| Neural networks | Dataset too small, tabular data |
| Classification instead of regression (Chat 2) | Would lose the edge magnitude signal |

---

## Action Plan for Next Session (Session 318)

### Phase 1: Quick Wins (45 min)

1. **Remove `minutes_surge` and `cold_snap` signals** — delete from registry, remove signal files
   - Files: `ml/signals/minutes_surge.py`, `ml/signals/cold_snap.py`, registry entries
   - Update signal count in CLAUDE.md (18 → 16)

2. **Cap `rest_advantage_2d` at ISO week 5** — add condition to the signal's `evaluate()` method
   - File: `ml/signals/rest_advantage_2d.py`
   - Data: W6=63.6%, W7=40% — clear decay confirmed in Session 317

3. **Remove star-level UNDER exception** (N=7 too small)
   - File: `ml/signals/aggregator.py` line 152-155
   - Revert to unconditional UNDER edge 7+ block
   - Session 317 data: UNDER star 25+ in best bets = 37.5% (N=8)

### Phase 2: Early Warning System (2 hrs)

Add to `/daily-steering` skill (both reviews' #1 priority):

**Metrics to add:**
```
Market Compression:  rolling_7d_avg_max_edge / rolling_30d_avg_max_edge
Edge Distribution:   count of edge 5+ and edge 3+ predictions today
Pick Volume Trend:   7d avg daily picks vs 30d avg
OVER/UNDER HR Split: trailing 14d by direction
Model Residual Bias: avg(predicted - actual) over 7d
```

**Thresholds (from Chat 1):**
| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Market compression | >= 0.85 | 0.65-0.85 | < 0.65 |
| 7d avg max edge | >= 7.0 | 5.0-7.0 | < 5.0 |
| 3d rolling HR | >= 65% | 55-65% | < 55% |
| Daily pick count (7d avg) | >= 3 | 1-3 | < 1 |
| OVER/UNDER HR divergence | <= 15% | 15-25% | > 25% |

**Implementation:** Add a new Step 2.5 to the daily-steering SKILL.md with a BQ query computing these metrics. Present as a "MARKET REGIME" section between Model Health and Signal Health.

### Phase 3: Filter Audit (1 hr)

For each of the 12 negative filters, query:
1. Sample size (N) at discovery
2. Picks blocked in last 30 days
3. HR of blocked picks (what would have happened)
4. Out-of-sample validation (performance after filter was added)

Focus on filters 4 (familiar matchup) and 6 (bench UNDER) — Chat 2 questioned the causal logic of filter 4, and bench UNDER at edge 5+ is actually 85.7% HR which contradicts the filter's premise at our edge floor.

### Phase 4: Model Experiments (3-4 hrs, if time permits)

**Experiment A: Direct Edge Prediction (Chat 2's best idea)**
```bash
/model-experiment with:
- Target: actual_points - prop_line (instead of raw points)
- Same V9 features (33)
- 42-day rolling window
- Compare edge distribution and HR at 5+ vs current approach
```

**Experiment B: V9/V12 Weighted Blend (Chat 1's best idea)**
```bash
/what-if or /model-experiment:
- Prediction = 0.65 * V9_pred + 0.35 * V12_pred
- Grade against Jan-Feb actuals
- Focus: does blending improve HR at edge 5+ without degrading it?
```

---

## Key Files Modified This Session

| File | Change |
|------|--------|
| `.claude/skills/daily-steering/SKILL.md` | Fixed query source: `current_subset_picks` → `signal_best_bets_picks` |
| `data_processors/publishing/best_bets_record_exporter.py` | **NEW** — record.json + history.json GCS endpoints |
| `backfill_jobs/publishing/daily_export.py` | Added import + export block for BestBetsRecordExporter |

## Performance Snapshot

| Period | Record | HR | Avg Edge | OVER HR | UNDER HR |
|--------|--------|-----|----------|---------|----------|
| Season (Jan 1 - Feb 20) | 92-32 | 74.2% | 8.0 | 77.3% | 63.0% |
| January | 74-17 | 81.3% | 8.7 | 84.2% | 66.7% |
| February | 18-15 | 54.5% | 6.6 | 52.4% | 58.3% |
| Last week (Feb 16) | 2-4 | 33.3% | 5.7 | - | - |

**Context:** Feb decline is 33 picks on thin post-ASB market. Both external reviews confirmed this is market structure, not model failure. System correctly throttled to minimal picks.

## Commit

```
c7a44394 feat: best bets GCS endpoints + fix daily-steering query source
```
