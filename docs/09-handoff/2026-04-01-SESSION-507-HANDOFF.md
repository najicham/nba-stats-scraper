# Session 507 Handoff — 2026-04-01 (Wednesday evening)

**Context:** Session 507 ran an 8-agent audit (4 Opus + 4 Sonnet) against the Session 506
handoff open items, then executed all actionable fixes. System is fully GREEN heading into
April 2.

---

## What Happened This Session

### 8-Agent Audit Findings

Agents covered all 6 open items from Session 506 handoff:

1. **`bp_mlb_player_props` had a new blocking bug** introduced by the Session 506 super() fix.
   Calling `super().set_additional_opts()` invoked the NBA parent which queries
   `nba_reference.nba_schedule`, finds NBA games on NBA game days, and proceeds to validate
   `"pitcher_strikeouts"` against the NBA `MARKET_ID_BY_KEYWORD` dict → `DownloadDataException`.
   Would have crashed every scheduler call during NBA+MLB overlap (Mar–Jun).

2. **TIGHT cap design gap confirmed as 15 days** (not 7). `train_end` is `today - 15`, so
   TIGHT market days in the eval window were invisible to the lookback query.

3. **`under_low_rsc` auto-demotion concern = false alarm.** Filter is NOT in
   `ELIGIBLE_FOR_AUTO_DEMOTE`. Cannot be auto-demoted regardless of CF HR or N. Handoff note
   about "N≥30 threshold" was also wrong — code uses N≥20.

4. **`home_under` at 41.4% HR (N=29) = variance, not structural.** Signal has zero data
   dependencies to break. Do NOT demote — Session 483 demoting it caused a 12-day drought.
   Health multiplier (0.5x COLD) is already handling it correctly.

5. **All BB Simulator "ready to add" signals/filters = already done.** CLAUDE.md was stale.
   All 3 signals (hot_3pt_under, cold_3pt_over, line_drifted_down_under) promoted Sessions
   466/495. All 3 filters (cold_fg_under, cold_3pt_under, over_line_rose_heavy) implemented
   Sessions 462/469. All 3 "remove" filters removed Session 494.

6. **`scrapers/mlb/registry.py` confirmed dead code.** Nothing imports it. Had drifted —
   `mlb_catcher_framing` was in the dead file but missing from the live registry.

### Fixes Executed (commit `fa227598`)

| Fix | File | Change |
|-----|------|--------|
| `bp_mlb_player_props` super() crash | `scrapers/bettingpros/bp_mlb_player_props.py` | `super()` → `super(BettingProsPlayerProps, self)` to skip NBA parent |
| TIGHT cap blind spot | `orchestration/cloud_functions/weekly_retrain/main.py` | Lookback query upper bound: `train_end` → `date.today()` |
| `mlb_catcher_framing` missing | `scrapers/registry.py` | Added to `MLB_SCRAPER_REGISTRY` |
| Dead code | `scrapers/mlb/registry.py` | Deleted |
| Stale to-dos | `CLAUDE.md` | All simulator signals/filters marked as already done |

### Deploy

- `mlb-phase1-scrapers` manually deployed — **verified live**:
  - 21 scrapers registered including `bp_mlb_player_props` and `mlb_catcher_framing`
  - Health: PASSED
- Push to main auto-deploys `weekly_retrain` CF (TIGHT cap fix)

---

## Current System State

### NBA Fleet
| Model | State | Enabled | Training Window |
|-------|-------|---------|-----------------|
| `lgbm_v12_noveg_train0126_0323` | active | YES | Jan 26 – Mar 23 |
| `catboost_v12_noveg_train0126_0323` | active | YES | Jan 26 – Mar 23 |

Fleet diversity: 1 LGBM + 1 CatBoost. First full day was April 1.

### Season Record (as of 2026-03-31)
- **Season: 108-76 (58.7%)**
- **March: 19-27 (41.3%)** — drought period, now resolved
- **Edge 5+: 82-44 (65.1%)**

---

## Open Items (Priority Order)

### 1. Run BQ Queries — Signal Graduation Candidates

**`book_disagree_over`** — 5-season HR 79.6%, N=211. Already in `OVER_SIGNAL_WEIGHTS` (weight
3.0) but in `SHADOW_SIGNALS` so doesn't count toward `real_sc`. If BB-level N ≥ 30 at HR ≥ 60%,
remove from `SHADOW_SIGNALS` in `aggregator.py` — highest-value signal system improvement.

```sql
SELECT
  signal_name,
  COUNT(*) as bb_picks,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as bb_hr
FROM nba_predictions.signal_best_bets_picks sbp
JOIN nba_predictions.prediction_accuracy pa
  ON sbp.player_lookup = pa.player_lookup
  AND sbp.game_date = pa.game_date
  AND sbp.recommendation = pa.recommendation
  AND sbp.line_value = pa.line_value
  AND pa.has_prop_line = TRUE
  AND pa.prediction_correct IS NOT NULL,
  UNNEST(JSON_VALUE_ARRAY(sbp.signal_tags)) AS signal_name
WHERE signal_name = 'book_disagree_over'
  AND sbp.game_date >= '2025-10-01'
```

**`sharp_consensus_under`** — 5-season HR 69.3%, N=205. Currently shadow. Would give UNDER
picks with only `home_under` a second real signal, unblocking `under_low_rsc` gate.
Fix for UNDER pick drought if N ≥ 30.

```sql
SELECT
  signal_name,
  COUNT(*) as bb_picks,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as bb_hr
FROM nba_predictions.signal_best_bets_picks sbp
JOIN nba_predictions.prediction_accuracy pa
  ON sbp.player_lookup = pa.player_lookup
  AND sbp.game_date = pa.game_date
  AND sbp.recommendation = pa.recommendation
  AND sbp.line_value = pa.line_value
  AND pa.has_prop_line = TRUE
  AND pa.prediction_correct IS NOT NULL,
  UNNEST(JSON_VALUE_ARRAY(sbp.signal_tags)) AS signal_name
WHERE signal_name = 'sharp_consensus_under'
  AND sbp.game_date >= '2025-10-01'
```

Graduation threshold for both: **N ≥ 30 at BB level, HR ≥ 60%**.

### 2. Monitor April 1 Picks

Expected 3-8 picks (mostly UNDER) on April 1 — first full day for fresh models.

```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-04-01' GROUP BY 1,2 ORDER BY 1,2"
```

### 3. `friday_over_block` — Watch April 3

CF HR was 87.5% (N=8) on March 27 — filter blocking winners recently. Auto-demotion requires
7 consecutive Fridays ≥ 55% CF HR (too slow). **Decision rule: if April 3 CF HR ≥ 55%,
manually write a demotion to `filter_overrides`.** Don't wait for auto-demotion.

```sql
SELECT filter_name, game_date, ROUND(cf_hr*100,1) as cf_hr_pct, n_graded
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date = '2026-04-03' AND filter_name = 'friday_over_block'
```

If demoting manually:
```python
# Write to filter_overrides with override_type='demote_to_observation', active=TRUE
# re_eval_date = 2026-04-17 (14 days)
# Aggregator reads this at export time — no redeploy needed
```

### 4. `home_under` Signal — Watch Only, Do NOT Demote

41.4% HR over 29 picks (7d). This is variance — signal has zero structural dependencies.
Do NOT demote to BASE_SIGNALS. Session 483 demoting it caused a 12-day drought.
Health multiplier (0.5x when COLD) is already limiting its ranking weight.

### 5. Verify `weekly_retrain` CF Deploy

TIGHT cap fix was in tonight's push. Confirm auto-deploy succeeded before Monday April 6
retrain fires at 5 AM ET.

```bash
gcloud functions describe weekly-retrain --region=us-west2 --project=nba-props-platform \
  --format="value(updateTime,status)"
```

---

## Key Audit Findings to Remember

| Finding | Implication |
|---------|-------------|
| `under_low_rsc` NOT in `ELIGIBLE_FOR_AUTO_DEMOTE` | Cannot auto-demote — zero risk. CF HR tracking is informational only. |
| N threshold in auto-demotion code is 20, not 30 | Handoff docs have been wrong about this threshold |
| `home_under` has zero structural failure modes | Cold streaks = variance. Never demote based on <50 picks. |
| All CLAUDE.md simulator to-dos were already done | CLAUDE.md was stale since Session 462/494/495 |
| `bp_mlb_player_props` super() crash = regression from Session 506 | Fixed tonight. Scraper was never safe to run during NBA season until now. |
| TIGHT cap blind spot was 15 days, not 7 | `train_end` is today-15, not today-7. Fixed tonight. |

---

## Session 507 Commits

| Commit | Description |
|--------|-------------|
| `fa227598` | fix: 4 post-session-506 audit fixes (super() crash, TIGHT cap, mlb_catcher_framing, CLAUDE.md cleanup) |

---

## Quick Start for Next Session

```bash
# 1. Morning steering
/daily-steering

# 2. Run signal graduation queries (items 1 above)
# book_disagree_over + sharp_consensus_under — potential UNDER drought fix

# 3. Check April 1 picks landed
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 1 GROUP BY 1,2 ORDER BY 1,2"

# 4. April 3: check friday_over_block CF HR — demote if >= 55%
```
