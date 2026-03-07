# Session 431b Handoff — Signal Cleanup + CI Promotion

**Date:** 2026-03-07
**Status:** All changes uncommitted — commit and push first.

---

## What Was Done

### 1. Demoted `sharp_book_lean_under` to Observation-Only
- **Why:** Zero production fires in entire 2025-26 season. Market regime makes negative sharp lean (soft books higher than sharp) nonexistent.
- **Changes:**
  - `ml/signals/aggregator.py`: Removed from `UNDER_SIGNAL_WEIGHTS` dict (was weight 1.0) and from `rescue_tags` set
  - `ml/signals/signal_health.py`: Updated comment to reflect observation status
  - Signal still fires and tracks in `signal_health_daily` — just no longer weights UNDER picks or rescues sub-edge picks

### 2. Suppressed `blowout_recovery` During Toxic Window
- **Why:** Signal collapses from 75% to 33% HR (-41.7pp) during trade deadline + ASB window. Only signal with catastrophic toxic collapse.
- **Changes:**
  - `ml/signals/blowout_recovery.py`: Added `detect_regime(game_date)` check. Returns `_no_qualify()` when `regime.is_toxic`.
  - Uses existing `shared/config/calendar_regime.py` — toxic window = Jan 30 to Feb 25 for 2025-26 season.
  - Signal still fires normally outside the toxic window.

### 3. Promoted All 5 CI Checks to Blocking
- **Why:** All 3 warning-only checks now pass clean. Prior Session 431a had already fixed the actual violations (45 deploy scripts, 6 schema fields, hardcoded model ref). This session made the validator smarter.
- **Changes:**
  - `.github/workflows/pre-commit-checks.yml`: Removed `continue-on-error: true` from all 3 warning-only steps
  - `.pre-commit-hooks/validate_deploy_safety.py`: Rewrote to skip false positives — echo/printf lines, comment lines, `bin/archive/` dir, `verify-env-vars-preserved.sh`
- **All 5 blocking checks:** `validate_python_syntax`, `validate_dockerfile_imports`, `validate_deploy_safety`, `validate_schema_fields`, `validate_model_references`

### 4. Verified Infrastructure
- Phase 3→4 and 4→5 orchestrator concurrency: both maxInstances=3, concurrency=1 (correct)
- Confirmed `volatile_starter_under` + `downtrend_under` already promoted to weight 2.0 (Session 427, handoff was stale)

### 5. Updated Docs
- `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`: 27 active signals (was 28), sharp_book_lean_under→OBSERVATION, blowout_recovery notes

---

## Uncommitted Files

```
ml/signals/aggregator.py
ml/signals/blowout_recovery.py
ml/signals/signal_health.py
.github/workflows/pre-commit-checks.yml
.pre-commit-hooks/validate_deploy_safety.py
docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md
docs/09-handoff/START-NEXT-SESSION-HERE.md
docs/09-handoff/2026-03-07-SESSION-431b-HANDOFF.md
```

### Suggested Commit

```
feat: demote sharp_book_lean_under, suppress blowout_recovery toxic window, promote CI checks

- Remove sharp_book_lean_under from UNDER_SIGNAL_WEIGHTS and rescue_tags (zero 2026 fires)
- Add detect_regime() toxic window gate to blowout_recovery signal
- Promote all 5 pre-commit CI checks from warning-only to blocking
- Update validate_deploy_safety.py to filter false positives

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## What to Do Next

### Priority 1: Auto-Demote Filters (2 hr)
- Daily CF computes counterfactual HR for each active negative filter
- CF HR >= 55% at N >= 20 for 7 consecutive days → auto-demote to observation + Slack alert
- Needs BQ table for `filtered_picks` persistence
- Foundation: `aggregator.py:_record_filtered()` tracks filtered picks, `bin/post_filter_eval.py` grades counterfactuals
- Reference: Session 428 manually demoted 4 filters with CF HR 55-65%

### Priority 2: MLB Pre-Season (Mar 24-25)
- Resume 22 scheduler jobs
- Retrain CatBoost V1 on freshest data
- E2E smoke test with spring training data
- Complete batter backfill (108/550 dates)
- Checklist: `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md`

### Priority 3: SPOF Fallback Scrapers (strategic)
NumberFire (only projection), RotoWire (only minutes), VSiN (only betting %), Covers (only referee), Hashtag (only DvP)

---

## System State

| Item | Status |
|------|--------|
| Fleet | 8 enabled models, AUTO_DISABLE live |
| Signals | 27 active + 26 shadow |
| CI | All 5 pre-commit checks BLOCKING |
| Monitors | 3 scheduled CFs (data source 7AM, signal decay 12PM, weight report Mon 10AM) |
| MLB | 20 days to opening day, schedulers paused |
