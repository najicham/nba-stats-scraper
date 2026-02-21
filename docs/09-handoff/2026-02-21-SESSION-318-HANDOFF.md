# Session 318 Handoff — Signal Cleanup, Filter Tightening, Market Regime, System Audit

**Date:** 2026-02-21
**Focus:** Execute action plan from Session 317 external reviews — signal removal, filter tightening, market regime early warning, skills audit, architecture audit, prediction_accuracy gap analysis, frontend GCS format design
**Status:** Phase 1-3 complete, Phase 4 deferred. Comprehensive action plan for next session.
**Prior sessions:** 317 (research + GCS endpoints), 316 (backfill fix, true HR=74.2%), 314 (consolidated best bets)

---

## TL;DR

Executed the Session 317 external review action plan: removed 2 underperforming signals, tightened the UNDER edge 7+ filter, capped rest_advantage_2d at mid-season, added market regime early warning to daily-steering, ran a filter audit confirming all filters are correctly blocking bad picks, audited all 31 skills (fixed 3 outdated), updated architecture doc, discovered `feature_quality_score` is 0% populated in `prediction_accuracy` (critical gap), and designed the frontend GCS format for end-user vs admin views.

---

## What Was Done

### 1. Signal Cleanup (Phase 1)

**Removed `minutes_surge` (53.7% HR, W4 decay) and `cold_snap` (N=0 all windows).**

Files deleted:
- `ml/signals/minutes_surge.py`
- `ml/signals/cold_snap.py`

Files updated:
- `ml/signals/registry.py` — removed imports and registrations
- `ml/signals/combo_registry.py` — removed 3 orphaned fallback entries (edge_spread_optimal+high_edge+minutes_surge, high_edge+minutes_surge, cold_snap)
- `ml/signals/pick_angle_builder.py` — removed SIGNAL_ANGLE_MAP entries
- `ml/signals/aggregator.py` — removed contradictory signals check (minutes_surge + blowout_recovery)

**IMPORTANT:** `combo_he_ms` and `combo_3way` still work. They check `supplemental['minutes_stats']` directly — they don't depend on the standalone MinutesSurgeSignal. The supplemental data pipeline still computes `minutes_stats` and `streak_stats`.

**Signal count:** 18 → 16 active signals.

### 2. UNDER Edge 7+ Star Exception Removed

**File:** `ml/signals/aggregator.py`

Session 316 had added a star-level exception allowing UNDER edge 7+ picks when line >= 25. Data showed only N=7 picks at 37.5% HR in best bets — too small to justify a carve-out. Reverted to unconditional block.

Before:
```python
if (pred.get('recommendation') == 'UNDER'
        and pred_edge >= 7.0
        and line_for_under7 < 25):
```

After:
```python
if (pred.get('recommendation') == 'UNDER'
        and pred_edge >= 7.0):
```

### 3. rest_advantage_2d Capped at Season Week 15

**File:** `ml/signals/rest_advantage_2d.py`

Added `MAX_SEASON_WEEKS = 15` check. The signal now computes weeks since the NBA season start (using `get_season_start_date` from shared config) and returns `_no_qualify()` after week 15 (~early February). Data: W2-W3=83% HR, W6=63.6%, W7=40%.

### 4. Market Regime Early Warning in Daily Steering

**File:** `.claude/skills/daily-steering/SKILL.md`

Added Step 2.5 "MARKET REGIME" between Signal Health and Best Bets Performance. Single BQ query computing:

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Market compression (7d/30d avg max edge) | >= 0.85 | 0.65-0.85 | < 0.65 |
| 7d avg max edge | >= 7.0 | 5.0-7.0 | < 5.0 |
| 3d rolling HR | >= 65% | 55-65% | < 55% |
| Daily pick count (7d avg) | >= 3 | 1-3 | < 1 |
| OVER/UNDER HR divergence | <= 15pp | 15-25pp | > 25pp |

Also shows: residual bias (avg predicted - actual over 7d), OVER/UNDER HR split 14d.

### 5. Filter Audit Results

Queried `prediction_accuracy` for all edge 5+ catboost_v9 picks, Jan 1 - Feb 20:

| Segment | N | HR | Verdict |
|---------|---|-----|---------|
| ALL edge 5+ | 194 | 66.5% | Baseline |
| OVER edge 5-7 | 49 | **69.4%** | Good |
| OVER edge 7+ | 58 | **84.5%** | Excellent |
| UNDER edge 5-7 | 60 | **58.3%** | Marginal |
| UNDER edge 7+ (blocked) | 27 | **40.7%** | Correctly blocked |
| Bench UNDER <12 (blocked) | 7 | **0.0%** | Correctly blocked |

All negative filters validated. No filters should be removed.

### 6. Skills Audit

Audited all 31 skills. Fixed 3:

| Skill | Issue | Fix |
|-------|-------|-----|
| `backfill-subsets` | 5 references to `v314_consolidated` | → `v318_signal_cleanup_filter_tightening` |
| `best-bets-config` | Listed ANTI_PATTERN combo as filter #11 | Removed (was removed Session 314) |
| `best-bets-config` | UNDER 7+ filter description | Updated to reflect Session 318 (unconditional) |

Other 28 skills are current. No references to removed signals found.

### 7. Architecture Doc Updated

**File:** `docs/01-architecture/best-bets-and-subsets.md`

- Algorithm version: v314_consolidated → v318_signal_cleanup_filter_tightening
- Added Session 318 changes section
- UNDER 7+ block: noted star exception reverted
- ANTI_PATTERN: marked as removed
- Combo registry: 11 → 8 entries

### 8. prediction_accuracy Table Audit (Critical Finding)

**`feature_quality_score` is 0% populated in `prediction_accuracy`** despite the column existing in the schema. The grading pipeline never copies it from `player_prop_predictions` (where it's 98.5% populated).

| Column | In PA Schema? | Populated | In predictions? | Impact |
|--------|:---:|:---:|:---:|-------|
| `feature_quality_score` | Yes | **0%** | 98.5% | Can't audit quality filter |
| `data_quality_tier` | Yes | **0%** | Yes | Can't audit quality tiers |
| `prop_line_delta` | **No** | — | **No** | Computed at runtime only |
| `games_vs_opponent` | **No** | — | **No** | Computed at runtime only |
| `neg_pm_streak` | **No** | — | **No** | Computed at runtime only |

This means **we cannot do retrospective filter audits** on the quality, line delta, familiar matchup, or neg PM streak filters. Priority fix for next session.

### 9. Frontend GCS Format Design

Proposed structure for two audiences:

**End User (playerprops.io):**
- `v1/best-bets/today.json` — NEW: clean picks (player, team, opponent, direction, line, edge, angles, season record)
- `v1/best-bets/record.json` — EXISTS (Session 317): season/month/week W-L + streaks
- `v1/best-bets/history.json` — EXISTS (Session 317): graded pick history by week

**Admin (your analysis view):**
- `v1/admin/picks/{date}.json` — NEW: full metadata (filter_summary, model provenance, subset membership)
- `v1/admin/subsets/performance.json` — NEW: all subsets with rolling 7d/14d/season HR

### 10. CLAUDE.md Updated

- Signal count: 18 → 16
- `minutes_surge` and `cold_snap` moved to Removed Signals section
- `rest_advantage_2d` notes updated (capped at season week 15)
- Removed signals list updated with Session 318 deletions

---

## Open Question: Signal Observatory

**User concern:** Should we still monitor removed signals? `minutes_surge` could be effective late-season when players are tired or resting for playoffs.

**Key insight:** The supplemental data (`minutes_stats`, `streak_stats`) is still computed because `combo_he_ms` and `combo_3way` need it. The signals were removed from the *registry* (don't fire, don't count toward signal count), but the underlying data pipeline is intact.

**Recommended approach:** Create "observatory" subsets that track the same patterns without being registered signals. These get graded automatically by SubsetGradingProcessor, so we'd see HR trends. If a pattern starts hitting 60%+ in March-April, we re-register it.

---

## Action Plan for Next Session (Session 319)

### Priority 1: Fix `feature_quality_score` in prediction_accuracy (~30 min)
- Find the grading code that writes to `prediction_accuracy`
- Add `feature_quality_score` to the column mapping (copy from `player_prop_predictions`)
- Test with a recent game date
- This unblocks all future filter auditing

### Priority 2: Create `v1/best-bets/today.json` endpoint (~1 hr)
- New `TodayBestBetsExporter` class in `data_processors/publishing/`
- Strips internal fields from signal-best-bets output
- Format: player, team, opponent, direction, line, edge, angles, season_record
- Integrate into `daily_export.py`
- Test with current data

### Priority 3: Signal Observatory (~1 hr)
- Add 2-3 observatory subset definitions to `dynamic_subset_definitions` BQ table:
  - `obs_minutes_surge_over`: minutes_avg_last_3 - minutes_avg_season >= 3, OVER, edge >= 5
  - `obs_cold_snap_home`: prev 2 games UNDER hit, home game, OVER
- These are observation-only (graded, not used for selection)
- Add monthly review prompt to daily-steering

### Priority 4: Admin endpoints (~1.5 hrs)
- `v1/admin/picks/{date}.json` — full pick metadata + filter_summary
- `v1/admin/subsets/performance.json` — all subsets with rolling 7d/14d/season HR
- New exporter classes, integrate into daily_export.py

### Priority 5: Store filter_summary in BQ (~30 min)
- Add `filter_summary` JSON column to `signal_best_bets_picks` schema
- Update SignalBestBetsExporter to write it
- Enables tracking which filters block the most picks over time

### Priority 6: Model experiments (3-4 hrs, if time permits)
- **Experiment A:** Direct edge prediction (predict actual-line instead of raw points)
- **Experiment B:** V9/V12 weighted blend (65/35)
- Deferred until post-ASB market normalizes (currently 0 edge 5+ picks across 9 game days)

### Review Checklist for New Session
- [ ] Read this handoff
- [ ] Verify commit `0d0b5060` deployed successfully: `./bin/check-deployment-drift.sh --verbose`
- [ ] Run `/daily-steering` to verify market regime section works
- [ ] Confirm combo_he_ms and combo_3way still fire (check pick_signal_tags)
- [ ] Confirm `minutes_stats` supplemental data still computed
- [ ] Review the signal observatory approach — does it address the concern about losing signal intelligence?
- [ ] Begin Priority 1 (feature_quality_score propagation)

---

## Key Files Modified This Session

| File | Change |
|------|--------|
| `ml/signals/minutes_surge.py` | **DELETED** |
| `ml/signals/cold_snap.py` | **DELETED** |
| `ml/signals/registry.py` | Removed imports/registrations for both signals |
| `ml/signals/combo_registry.py` | Removed 3 orphaned fallback entries |
| `ml/signals/aggregator.py` | v318 version, removed star exception, removed contradictory check |
| `ml/signals/pick_angle_builder.py` | Removed signal angle map entries |
| `ml/signals/rest_advantage_2d.py` | Added MAX_SEASON_WEEKS=15 cap |
| `.claude/skills/daily-steering/SKILL.md` | Added Market Regime section (Step 2.5) |
| `.claude/skills/backfill-subsets/SKILL.md` | v314→v318 algorithm version |
| `.claude/skills/best-bets-config/SKILL.md` | Removed ANTI_PATTERN filter, updated UNDER 7+ |
| `docs/01-architecture/best-bets-and-subsets.md` | Updated to v318 |
| `CLAUDE.md` | Signal count 18→16, removed signals, rest_advantage notes |

## Performance Snapshot

| Period | Record | HR | Avg Edge | OVER HR | UNDER HR |
|--------|--------|-----|----------|---------|----------|
| Season (Jan 1 - Feb 20) | 92-32 | 74.2% | 8.0 | 77.3% | 63.0% |
| January | 74-17 | 81.3% | 8.7 | 84.2% | 66.7% |
| February | 18-15 | 54.5% | 6.6 | 52.4% | 58.3% |

**Context:** Feb decline is 33 picks on thin post-ASB market. Both external reviews confirmed this is market structure, not model failure.

## Commit

```
0d0b5060 feat: Session 318 signal cleanup, filter tightening, market regime early warning
```
