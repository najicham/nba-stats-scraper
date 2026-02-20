# Session 306 Handoff — Frontend Signal Architecture + Best Bets V2 Plan

**Date:** 2026-02-20
**Focus:** Frontend/backend signal architecture alignment, picks presentation redesign, Best Bets V2 multi-model architecture plan

---

## What Was Done

### 1. Frontend Signal Architecture Q&A

Answered 4 detailed questions from the frontend team (`props-web/docs/backend-requests/2026-02-19-picks-signal-architecture.md`):

1. **`model_group.signal` is date-level** — same value for all models (queries champion only). Frontend moved it to page-level badge.
2. **`signals/{date}.json` is live** — files exist Feb 4 through Feb 19. Gap = All-Star break. Frontend fixed 404 handling.
3. **Pick-level signals** — documented all 17 active tags with labels, descriptions, hit rates, direction filters. Frontend added signal chips with tooltips.
4. **Three signal concepts are independent** — daily signal (date metadata), pick signals (per-pick annotations), signal_condition (subset filter).

**Response doc:** `props-web/docs/backend-requests/2026-02-19-signal-architecture-response.md`

### 2. Subset-to-Model Binding Analysis

Investigated how subsets are tied to models across retrains:
- Champion (`catboost_v9`) uses fixed system_id — subsets persist across retrains
- Shadow models use timestamped system_ids — subsets break on retrain
- Cross-model subsets use family-based pattern matching — auto-survives retrains
- **Recommendation:** All models should use stable family-based system_ids (Option A, confirmed by frontend)

### 3. Picks Presentation Gaps Investigation

Frontend reported 7 issues in `props-web/docs/backend-requests/2026-02-19-picks-presentation-gaps.md`. Root-caused all:

| Issue | Root Cause | Status |
|-------|-----------|--------|
| "Other"/unknown subsets | `catboost_v9_low_vegas` missing from `subset_public_names.py` and `model_codenames.py` | Fix needed |
| Best Bets no record | Record computed in best-bets exporter but not wired into picks export | Fix needed |
| Cross-model player names | `cross_model_subset_materializer.py` line 235: `player_name = player_lookup` (bug) | Fix needed |
| Null records on most subsets | Expected for new/post-ASB models with limited grading history | Expected |
| No subset_type/layer field | `scenario_category` exists in schema but never populated | Enhancement needed |
| No signal_condition exposed | Column exists, not exported | Enhancement needed |
| Only season/month/week windows | Rolling 7d/14d/30d computed elsewhere but not in picks export | Enhancement needed |

**Response doc:** `props-web/docs/backend-requests/2026-02-19-picks-presentation-gaps-response.md`

### 4. Two-Page Architecture Decision

After deep audit of the actual data (88KB picks JSON, 63% duplication, 185 entries for 68 unique players), proposed splitting into:

- **Page 1: Public Picks** — Best Bets prominently at top, flat deduplicated all-predictions below. Simple, actionable.
- **Page 2: Analytics Dashboard** — Full model groups, subsets by layer (L1/L2/L3), selection funnel visualization, per-subset performance.

**Architecture doc:** `props-web/docs/backend-requests/2026-02-19-two-page-architecture.md`

### 5. Best Bets V2 Architecture Plan (MAIN OUTPUT)

Deep investigation revealed best bets are **champion-only** — only `catboost_v9` predictions feed the aggregator. Cross-model data is annotation-only, signals are gates-only, ranking is pure edge.

**Key data findings:**
- Edge 5-7 = 58% HR, 7+ = 65% HR (edge is king, confirmed)
- V9 OVER = 57.4% but UNDER = 47.2% (UNDER is liability without extra evidence)
- V9+V12 agreement = 45.5% HR (anti-correlated, confirmed)
- Combo signals: `combo_he_ms` 77.5%, `combo_3way` 67.0% (strong as filters)
- V9 currently cold: 14d HR 44.1% vs season 52.2%
- **Quantile models have almost no grading data** — critical blocker for multi-model
- Rich monitoring infrastructure (`model_performance_daily`, `signal_health_daily`, combo registry) exists but aggregator ignores it all

**Three-phase plan:**
- **Phase A:** Multi-source candidate generation (query all models, "best offer" dedup per player)
- **Phase B:** Trust-weighted scoring (Bayesian credibility × staleness factor → effective_edge)
- **Phase C:** Quality gates (60% expected HR floor, direction-specific rules, consensus adjustments)

**Plan doc:** `docs/08-projects/current/best-bets-v2/00-ARCHITECTURE-PLAN.md`

---

## Pending: Review from Another Chat

**The Best Bets V2 plan has been sent to another chat for review.** That chat will review the architecture plan and return feedback. When the user provides the response:

1. Read the feedback carefully
2. Identify what the reviewer agrees with, disagrees with, or wants changed
3. Revise the plan accordingly
4. If approved, begin implementation starting with Phase A

**The reviewer has access to:**
- `docs/08-projects/current/best-bets-v2/00-ARCHITECTURE-PLAN.md` (the full plan)
- All the context from CLAUDE.md about the system architecture

**Key questions the reviewer might address:**
- Is the "best offer" dedup strategy correct for multi-model candidates?
- Is the trust formula (Bayesian credibility weighting) the right approach vs alternatives?
- Is 60% expected HR the right quality gate threshold?
- Should UNDER picks have stricter requirements than OVER?
- Is the three-phase staging right, or should anything be reordered?
- Are there approaches or data sources we're missing?

---

## Files Created/Modified This Session

### Created
- `props-web/docs/backend-requests/2026-02-19-signal-architecture-response.md`
- `props-web/docs/backend-requests/2026-02-19-signal-architecture-followup-response.md`
- `props-web/docs/backend-requests/2026-02-19-picks-presentation-gaps-response.md`
- `props-web/docs/backend-requests/2026-02-19-two-page-architecture.md`
- `docs/08-projects/current/best-bets-v2/00-ARCHITECTURE-PLAN.md`

### Modified (Session 306 continuation — review chat)
- `ml/signals/aggregator.py` — UNDER line delta blocks 3.0→2.0, updated docstring
- `data_processors/publishing/signal_annotator.py` — DELETE + INSERT idempotency for `pick_signal_tags`
- `.claude/skills/validate-daily/SKILL.md` — Added Phase 0.59: per-signal firing rate monitor
- `CLAUDE.md` — Added negative filter entries 7-8 (UNDER + line delta 2.0)
- BQ: `pick_signal_tags` deduped (removed up to 9x duplicate rows)

### Session 306 Continuation — Key Findings
- **prop_line_drop_over signal now firing** (3 times on 2/19 after threshold change)
- **V9 OVER: 63.3% HR vs UNDER: 51.0%** (wider gap than plan stated)
- **UNDER at edge 5-7: 59.3% HR** — profitable, don't over-restrict
- **UNDER at edge 7+: 40.7% HR** — already blocked
- **Quantile grading volume**: V9 Q43=37, V9 Q45=25 graded edge 3+ — no longer a blocker
- **Best Bets V2 review**: Phase A recommended (simplified), Phase B deferred, Phase C simplified

---

## Known Issues Requiring Fixes (Not Done Yet)

| Issue | File | Fix |
|-------|------|-----|
| Low-vegas missing codename | `shared/config/model_codenames.py` | Add entry for `catboost_v9_low_vegas_train0106_0205` |
| Low-vegas missing subset names | `shared/config/subset_public_names.py` | Add 4 entries: `low_vegas_all_picks`, `low_vegas_all_predictions`, `low_vegas_high_edge`, `low_vegas_under_all` |
| Cross-model player names | `data_processors/publishing/cross_model_subset_materializer.py` | Add LEFT JOIN to `nba_players_registry` and `player_game_summary` |
| Quantile system_id mismatch | `dynamic_subset_definitions` in BQ | Subset defs reference `_train1102_0131` but active model is `_train1102_0125` |
| Best bets record not in picks export | `data_processors/publishing/all_subsets_picks_exporter.py` | Wire `_get_best_bets_record()` into picks export |
| Quantile grading volume | Grading pipeline | Verify quantile predictions flow into `prediction_accuracy` |

---

## Quick Reference

```bash
# Read the Best Bets V2 plan
cat docs/08-projects/current/best-bets-v2/00-ARCHITECTURE-PLAN.md

# Check current best bets output
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/2026-02-19.json | python3 -m json.tool

# Check model performance (trust data source)
bq query --use_legacy_sql=false "SELECT * FROM nba_predictions.model_performance_daily WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily) ORDER BY model_id"

# Check signal health (signal regime data source)
bq query --use_legacy_sql=false "SELECT * FROM nba_predictions.signal_health_daily WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily) ORDER BY signal_tag"

# Check quantile model grading coverage (critical blocker)
bq query --use_legacy_sql=false "SELECT system_id, COUNT(*) as graded FROM nba_predictions.prediction_accuracy WHERE game_date >= '2026-02-01' AND system_id LIKE '%q4%' GROUP BY 1"
```
