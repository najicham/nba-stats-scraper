# Session 533 Handoff — NBA playoffs hold, MLB active, edge 5+ architecture finding

**Date:** 2026-04-15
**Focus:** Daily steering + frontend polish (matchup section, line beaters ledger). NBA in auto-halt for playoffs. MLB is the active betting system.
**Commits:**
- `props-platform-web`: `edfeb3a` — matchup section (key angles + H2H) + line beaters ledger view

---

## TL;DR

NBA is correctly halted — playoffs started April 15, all models BLOCKED, auto-halt active. No action needed on NBA. MLB is running fine (56.6% model HR, 100% BB HR on 3 picks). The most important finding is the edge 5+ architecture insight: 3 models hit **60% HR at edge 5+** despite being BLOCKED overall. This is an off-season architecture priority.

Frontend shipped two things:
1. **Matchup section** on pitcher modal Overview tab — Key Angles (from best-bets JSON) + H2H history (from game_log, zero backend)
2. **Line Beaters Ledger view** — Cards/Ledger toggle on the Line Beaters tab

---

## System State

### NBA

**All models BLOCKED. Auto-halt active. 0 picks in 7+ days. Correct behavior.**

- Last graded pick: April 7 (lost).
- Last 30d BB record: 7-6 (53.8%). Season final: 415-235 (63.8%).
- League macro last updated: 2026-04-12. Data sparse because no BB picks to grade.
- NBA Playoffs: April 15 onward. Games: Apr 15 (3), Apr 17 (2), Apr 18 (4), Apr 19-22 (3-4/day). Series format through mid-June.

**Do NOT retrain during playoffs.** Playoff data would contaminate the regular-season training set for 2026-27. Let the halt stand.

### MLB

**Operational. Monitor daily.**

- Model HR 7d: 56.6% — healthy
- BB HR 7d: 100% (N=3, small sample but positive)
- K/game: 4.8 (slightly low — early season, normal)
- Market regime: NORMAL
- Vegas MAE 7d: NULL — `mlb_predictions.league_macro_daily` not computing Vegas bias yet. Likely needs `oddsa_pitcher_props` to have enough data to compare against actuals. Not a bug yet — early season.
- Model MAE 7d: 1.79 (within normal range for K props)
- Session 524 bias fix (April-trained model) appears to be working.

### Frontend (`props-platform-web`, commit `edfeb3a`)

Shipped:
- **PitcherModal.tsx**: Matchup section between Splits and Track Record
  - Key Angles: fetches `mlb/best-bets/all.json` when `is_best_bet=true`, renders `angles[]` as `›` bullets (ULTRA BET tags filtered)
  - H2H: filters `profile.game_log` by tonight's opponent, last 5 starts, date/K/line/result
- **MlbScoutingPanels.tsx**: `LineBeatersSection` + `MarginBar` + toggle
  - Cards: unchanged grid
  - Ledger: dense table with rank, team badge, GS, avg margin (colored), bidirectional SVG margin bar (±3K scale), footer stat strip
- **pitchers/page.tsx**: wired to `LineBeatersSection`

---

## Key Finding: Edge 5+ Architecture

This is the most important thing from today's steering report. **3 models hit 60% HR at edge 5+ while being BLOCKED overall:**

| Model | Edge 5+ HR | N | Avg Edge | Overall HR | Premium |
|---|---|---|---|---|---|
| catboost_v12_noveg_mq_train0206_0402 | 60.0% | 20 | 7.03 | 26.2% | **+33.8pp** |
| catboost_v12_noveg_train1227_0221 | 60.0% | 10 | 6.18 | 47.2% | +12.8pp |
| catboost_v12_noveg_train0126_0323 | 60.0% | 5 | 6.02 | INSUFFICIENT | — |
| lgbm_v12_noveg_train0206_0402 | 57.1% | 14 | 7.43 | 44.7% | +12.4pp |

The MQ model is the starkest: 60% HR at edge 5+ (N=20) but 26.2% overall. The massive edge5_premium of +33.8pp means the model's **low-edge predictions** are dragging it to BLOCKED — which then silences the high-edge picks that actually work.

**Off-season architecture implication:** Consider raising the minimum prediction threshold so models only output predictions at edge ≥ 3.0 (not edge 1.0+). This would reduce the denominator for HR metrics, potentially keeping strong models out of BLOCKED state during late season. Off-season research item.

---

## One Thing to Check Today

**`usage_surge_over` is showing HOT (83.3% HR, 6 picks in 7d) in signal_health_daily.** But per Session 506 memory, it was reverted to SHADOW (COLD 33.3% HR at the time). If it's now appearing in active picks at HOT status, it may have been accidentally re-promoted. Verify:

```bash
grep -n "usage_surge_over" ml/signals/aggregator.py | head -20
```

Check whether it's in `ACTIVE_SIGNALS`, `SHADOW_SIGNALS`, or `UNDER_SIGNAL_WEIGHTS`. If active and winning, it may be legitimately HOT now (N=6 is tiny but 83.3% is notable). If shadow, the signal_health row is tracking shadow signal appearances — that's fine, no action needed.

---

## Validation Checklist for Next Session

Run these in order:

```bash
# 1. Pipeline health
/validate-daily

# 2. MLB spot check — did today's picks generate?
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) picks, COUNTIF(is_best_bet) best_bets
FROM \`nba-props-platform.mlb_predictions.pitcher_prop_predictions\`
WHERE game_date = CURRENT_DATE()
GROUP BY 1"

# 3. MLB grading — did yesterday grade correctly?
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) picks, COUNTIF(prediction_correct) wins,
  ROUND(100*COUNTIF(prediction_correct)/COUNT(*),1) hr
FROM \`nba-props-platform.mlb_predictions.prediction_accuracy\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC"

# 4. Check auto-halt status (should be active for NBA)
# Look at today's exported JSON: halt_active field
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/signal-best-bets/$(date +%Y-%m-%d).json" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('halt_active:', d.get('halt_active'), 'picks:', len(d.get('picks',[])))"

# 5. usage_surge_over signal status check
grep -n "usage_surge_over" /home/naji/code/nba-stats-scraper/ml/signals/aggregator.py | head -20
```

---

## What to Work on Next

### NBA Off-season (low urgency, high value)

No code changes during playoffs. But good time to:
1. **Document the edge 5+ architecture finding** — plan minimum edge threshold change for 2026-27
2. **Season retrospective** — final 415-235 (63.8%) record analysis

### MLB (active, incremental)

These are the next frontend/backend items already scoped:

**Frontend-only (Project A remaining — ~half day):**
- `best-bets/{date}.json` already has `angles` per pick — the Key Angles section now shows these in the pitcher modal ✓ DONE
- H2H section ✓ DONE
- Still TODO: nothing else frontend-only in Project A

**Backend-dependent (Project B — Strike Zone Heartbeat):**
- Needs `strikeout_locations` on profile JSON — pull K-outcome pitches from `mlb_game_feed_pitches` (710K+ rows), aggregate last 20 K locations per pitcher, add to pitcher exporter
- Effort: ~1 day backend + 1-2 days frontend SVG component

**Backend-dependent (Project A backend):**
- Opponent K% season table — exists in raw data, needs exporter → GCS
- Park K factors — static reference table, one-time ingest
- Umpire tendency — daily scrape, ~1 day

**HTML prototypes for reference (in `/tmp/` on naji's WSL box):**
- `/tmp/mlb-proto-v2-strike-zone.html` — Strike Zone Heartbeat (fully designed)
- `/tmp/mlb-proto-v2-outing-script.html` — Outing Script (matchup chips)
- `/tmp/mlb-proto-v2-ledger.html` — Line Beaters Ledger ✓ SHIPPED

---

## Model Recommendation for Next Session

**Sonnet.** Validation and MLB monitoring queries are routine. If Strike Zone Heartbeat backend comes up, use Opus for the BigQuery view design (non-trivial aggregation across 710K pitches), Sonnet for the React port.

---

## Memory Updates Needed

Worth saving to memory from this session:
- NBA playoffs started April 15, 2026. Auto-halt active. Do not retrain until off-season (likely October 2026).
- Edge 5+ architecture finding: 3 models at 60% edge 5+ HR despite BLOCKED overall. MQ model has +33.8pp edge5 premium. Off-season: raise minimum prediction threshold to edge ≥ 3.0.
- `usage_surge_over` status unclear — showing HOT in signal_health but was supposed to be SHADOW per Session 506. Verify in aggregator.
