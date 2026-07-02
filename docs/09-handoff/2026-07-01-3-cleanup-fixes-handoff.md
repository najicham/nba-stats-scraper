# Session Handoff — 2026-07-01 (Session 3, Cleanup & Fixes)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commits:** `7d1a3f9b`, `df84bf0a`, `e2eeb527`, `e492b737`, `f6c18526`
**Picking up from:** `docs/09-handoff/2026-07-01-2-signal-research-session-handoff.md`

---

## What was accomplished

### Fix 1 — nba_tracking_stats scraper: PlayerOrTeam=Player (CRITICAL)

**Root cause found and fixed.**

`LeagueDashPtStats` in nba_api v1.11.4 defaults to `PlayerOrTeam.default = team` (confirmed from package source). The scraper called it without specifying player-level. Team stat rows have `TEAM_ID` not `PLAYER_ID`, so `_parse_result()` silently skipped all PT stat rows (`if pid is None: continue`). Result: drives, touches, paint_touches, catch_shoot_fga all 0.0 across all 307K rows.

**Fix (commit `7d1a3f9b`, v1.2):**
- `_fetch_all_via_nba_api`: added `player_or_team='Player'` to kwargs
- `_http_single`: added `'PlayerOrTeam': 'Player'` to HTTP params
- Both paths now return player-level PT stats

`drive_volume_under` will start accumulating correct `drives_avg_season` data from 2026-27 season open.

### Fix 2 — 4 removed signals still registered (CORRECTNESS BUG)

**Root cause:** The 2026-07-01 backtest session marked 4 signals `status: removed` in signals.yaml but did NOT remove their `registry.register()` calls from `ml/signals/registry.py`. A registered signal not in SHADOW_SIGNALS or BASE_SIGNALS counts toward `real_sc` (the pick qualification gate). If any of these fired, a pick could qualify on the strength of a known-bad signal.

**Removed from registry.py (commit `f6c18526`):**
- `steep_downtrend_under`: +0.2pp noise, dead end
- `low_var_mid_line_under`: -0.1pp, mid-line archetype refuted
- `season_breakout_over`: -0.2pp, 2/4 seasons, OVER scoring-env artifact
- `career_matchup_under`: +0.2pp, 1/5 seasons; inverse outperforms

Also removed the dead `matchup_3yr_query` from `supplemental_data.py` (no signal consumes `supp['career_matchup_3yr']` anymore). Saves one BQ query per day.

### Fix 3 — Documentation cleanup (commits `df84bf0a`, `e2eeb527`, `e492b737`)

- `signal_health.py`, `aggregator.py`: Updated `drive_volume_under` comment from "BROKEN" to "scraper bug fixed"
- `season_breakout_under.py`: Updated docstring from stale -3.0 threshold to -7.0
- `season-resume-2026-27.md`: Added 7 new shadow signals to fire rate monitor (13→20 total): `high_minutes_under`, `high_3pt_season_under`, `high_3pt_recent_under`, `star_out_rescue`, `drive_volume_under`, `season_breakout_under`, `fta_high_cv_under`

---

## System state after this session

### Shadow signal registry correctness
All 4 removed signals (`steep_downtrend_under`, `low_var_mid_line_under`, `season_breakout_over`, `career_matchup_under`) are now fully removed from the evaluation pipeline. Their files still exist in `ml/signals/` for reference but no signal evaluator imports them.

### nba_tracking_stats correctness (v1.2)
Deployed on nba-scrapers Cloud Run service. Will produce correct drives/touches/paint_touches data for 2026-27 season. First game day should show non-zero `drives_avg_season` in BQ once the scraper runs.

### Season-resume runbook state
Fire rate monitor now covers all 20 shadow signals. Added timing notes:
- `drive_volume_under` expected to fire from opening night
- `season_breakout_under` won't fire until game 20+ (late November)
- `high_3pt_season_under`, `high_3pt_recent_under`: check overlap with `hot_3pt_under` at game 30+

---

## Remaining open items (still from prior handoff)

### High priority (waits for Oct 2026 live data)
1. **star_out_rescue accumulation** — shadow fires from Oct 2026. Gate: N≥30 picks where signal fires, HR≥65%, incremental zone (edge 3-5.9) HR≥65%, explicit user sign-off.
2. **fta_high_cv_under accumulation** — same pattern as b2b_fatigue_under. Promote at N≥30 HR≥58% (excluding 2025-26 anomaly from gate data).

### Medium priority (off-season)
3. **VSiN scraper diagnostic** — data stopped 2026-03-28. Needs manual test at season open: run `python scrapers/external/vsin_betting_splits.py --date TODAY --debug` to verify HTML class `txt-color-vsinred` is still valid.

### Season-open (first week of 2026-27)
- Add 2026 to `FALLBACK_SEASON_START_DATES` once NBA announces schedule
- Verify nba_tracking_stats drives/touches are non-zero for first game day
- Run the 20-signal fire rate monitor query from the runbook
- Check `drive_volume_under` fires as expected (drives_avg_season >= 7 for high-usage players)
- Verify `season_breakout_under` starts firing at game 20+ in late November

### Do NOT re-investigate
- career_matchup_under: fully removed, inverse outperforms, model already encodes matchup
- steep_downtrend_under: +0.2pp noise
- low_var_mid_line_under: archetype hypothesis refuted
- drives/touches being 0.0 after the scraper fix: if you see this, check nba_tracking_stats scraper logs and verify `PlayerOrTeam=Player` param is being sent

---

## Key insight for future debugging

**The `real_sc` qualification gate relies on SHADOW_SIGNALS being complete.** Any signal NOT in BASE_SIGNALS and NOT in SHADOW_SIGNALS and NOT in UNDER/OVER_SIGNAL_WEIGHTS will:
1. Count toward `real_sc` (could gate picks in)
2. Get a default weight of 1.0 in UNDER quality scoring

The correct removal pattern for any signal is:
- Option A: Add to `SHADOW_SIGNALS` (still tracks for monitoring, but doesn't affect picks)
- Option B: Remove from `registry.py` entirely (no evaluation at all)

For signals that are "removed" (confirmed dead ends), Option B is correct. For signals that are "demoted for monitoring" (UNDER watch), Option A is correct.
