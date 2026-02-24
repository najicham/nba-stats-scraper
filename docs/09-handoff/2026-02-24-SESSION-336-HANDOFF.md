# Session 336 Handoff — Player Profiles Signal Implementation

**Date:** 2026-02-23
**Status:** Complete. 3 commits on main, NOT pushed yet.

---

## What Was Done

### V15 Model Experiment → Signal Pivot

The V15 model experiment added `ft_rate_season` and `starter_rate_season` as CatBoost features. Both had <1% feature importance — the model can't learn tier-specific directional interactions from global features.

Pivoted to a **post-model signal/filter** approach based on the validated finding:
- Bench OVER + High FT rate (>= 0.30): **72.5% HR** (edge 5.2, N=1,548)
- Bench OVER + Low FT rate: **66.9% HR** (edge 5.2)
- 5.6pp gradient at same edge — controlled, not confounded

### Commits (3, unpushed)

| Commit | Description |
|--------|-------------|
| `0a33425` | Signal: `ft_rate_bench_over` — fires for bench OVER + FT rate >= 0.30 |
| `6d4fce2` | Subset: `signal_ft_rate_bench_over` (ID 40) for live tracking |
| `dfe5691` | Docs: project docs + CLAUDE.md (13 active signals) |

### Files Changed

**New:**
- `ml/signals/ft_rate_bench_over.py` — signal class (WATCH, confidence 0.80)
- `docs/08-projects/current/player-profiles/09-SIGNAL-IMPLEMENTATION.md`

**Modified:**
- `ml/signals/supplemental_data.py` — added `ft_rate_season`, `starter_rate_season` to query + dicts
- `ml/signals/registry.py` — registered `FTRateBenchOverSignal`
- `ml/signals/signal_health.py` — added to `ACTIVE_SIGNALS` (now 13)
- `ml/signals/pick_angle_builder.py` — added angle template
- `data_processors/publishing/signal_subset_materializer.py` — added subset config
- `shared/config/subset_public_names.py` — added ID 40
- `CLAUDE.md` — updated signal count and table

---

## Morning Checklist

```bash
# 1. Push (auto-deploys)
git push origin main

# 2. Verify builds
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. Morning steering
/daily-steering

# 5. Validate pipeline
/validate-daily
```

---

## What to Verify After Push

1. **Signal fires:** After today's pipeline run, check that `ft_rate_bench_over` appears in `pick_signal_tags`:
   ```sql
   SELECT signal_tag, COUNT(*)
   FROM `nba-props-platform.nba_predictions.pick_signal_tags`,
     UNNEST(signal_tags) AS signal_tag
   WHERE game_date = CURRENT_DATE()
     AND signal_tag = 'ft_rate_bench_over'
   GROUP BY 1
   ```

2. **Subset materializes:** Check `current_subset_picks` for the new subset:
   ```sql
   SELECT COUNT(*), subset_id
   FROM `nba-props-platform.nba_predictions.current_subset_picks`
   WHERE game_date = CURRENT_DATE()
     AND subset_id = 'signal_ft_rate_bench_over'
   GROUP BY 2
   ```

3. **Signal health:** After grading tomorrow, verify it appears in `signal_health_daily`

---

## Uncommitted Files (Pre-existing, Not From This Session)

These were already dirty before Session 336 — from the V15 experiment work:
- `ml/experiments/quick_retrain.py` — V15 augmentation code + feature-set flag
- `shared/ml/feature_contract.py` — V15 contract definitions
- `docs/08-projects/current/player-profiles/00-08` — earlier project docs
- `.claude/skills/daily-steering/SKILL.md` — unrelated change

**Decision needed:** Commit the V15 experiment code (useful for future experiments) or leave uncommitted. The signal implementation works independently of these.

---

## Signal Design Notes

- **WATCH status** — not PRODUCTION. Does not appear in `validate-daily` expected signals list.
- **Positive signal only** — annotates picks, does NOT block any. Low-FT-rate bench OVER (66.9%) is still profitable.
- **Promotion criteria:** Live HR >= 65% over 50+ graded picks → promote to PRODUCTION.
- **`starter_rate_season`** data is now in the pipeline but unused by any signal yet — available for future work.

---

## Dead Ends Confirmed

- V15 model approach: `ft_rate_season` and `starter_rate_season` as CatBoost features — <1% importance, model can't learn tier-specific interactions. Don't revisit.
