# Session Handoff — 2026-05-19 — MLB CF eligibility bar + 5/23 halt check

**Predecessor:** [`2026-05-18-3-post-review-hot-fixes-and-strategic-plan.md`](2026-05-18-3-post-review-hot-fixes-and-strategic-plan.md)

Short session. Path B from the predecessor's strategic plan shipped; the 5/23
calendar reminder is scheduled as a remote routine; an unrelated props-web bug
was handed off to a separate Claude Code session.

## TL;DR

- **Path B shipped**: MLB CF evaluator eligibility bar lowered to MLB volume.
  Replaced the unreachable 7-consecutive-days-with-N≥20-over-7d gate with two
  parallel OR paths. Auto-deploys on push to main.
- **5/23 halt_state check scheduled**: claude.ai routine
  `mlb-regressor-halt-check-2026-05-23` (`trig_01QiPjbGA3ztkgK56uq8dLD1`)
  fires once at 12:00 UTC (8 AM EDT) on 5/23, emits a self-contained markdown
  report with the three verification queries.
- **Props-web stale-tab bug** (Tonight page loader hangs after tab idle for
  hours) handed off via
  [`2026-05-19-props-web-stale-tab-prompt.md`](2026-05-19-props-web-stale-tab-prompt.md)
  to a new session in `~/code/props-web`.

## What changed

### `orchestration/cloud_functions/mlb_filter_counterfactual_evaluator/main.py`

New eligibility logic in `find_trending_bad_filters`. A filter is flagged
as trending-bad if EITHER:

- **Path A (`short_5d`)**: `N >= 10` graded over 5 days, CF HR ≥ 55%
- **Path B (`cumulative_30d`)**: `N >= 30` graded over 30 days, CF HR ≥ 55%

No consecutive-day streak gate. The NBA evaluator (`filter_counterfactual_evaluator/main.py`)
keeps its stricter 7-day-streak bar — only MLB changed.

Dropped dead constants: `MIN_PICKS_PER_DAY` (always 0), empty
`PER_FILTER_MIN_PICKS_7D` (never referenced). New constants:
`LOOKBACK_SHORT_DAYS=5`, `MIN_PICKS_SHORT=10`, `LOOKBACK_CUMULATIVE_DAYS=30`,
`MIN_PICKS_CUMULATIVE=30`. `CF_HR_THRESHOLD` and `NEVER_DEMOTE` unchanged.

Slack advisory output now shows `eligibility_path` per row and tags
`NEVER_DEMOTE` filters as `_(NEVER_DEMOTE — informational only)_` so we
don't confuse structural-block warnings with actionable ones.

Live-run as of 2026-05-19 fires on `direction_filter` (90.9% CF HR, N=11
via `short_5d`) — that's a `NEVER_DEMOTE` filter, so the advisory will tag
it as informational. Validates that the new bar is reachable; old bar
flagged nothing.

### Files NOT changed but worth knowing

- NBA evaluator (`orchestration/cloud_functions/filter_counterfactual_evaluator/main.py`)
  — intentionally untouched. Keep the stricter bar.
- `.claude/skills/mlb-best-bets-config/SKILL.md` — only reports CF HR from the
  daily table, doesn't reference the eligibility threshold. No update needed.
- `cloudbuild-functions.yaml` — no entry for the MLB CF (it has its own
  Cloud Build trigger `deploy-mlb-filter-counterfactual-evaluator` with
  `includedFiles: orchestration/cloud_functions/mlb_filter_counterfactual_evaluator/**`).
  Verified the trigger is correctly wired; auto-deploys on push.

## Deploys / schedules

| Resource | State |
|---|---|
| `mlb-filter-counterfactual-evaluator` CF | Auto-deploys on this commit (next push to main). Verify build: `gcloud builds list --region=us-west2 --project=nba-props-platform --filter='source.repoSource.repoName:github_najicham_nba-stats-scraper' --limit=5` |
| `mlb-filter-counterfactual-evaluator-daily` scheduler | No change. Still 11:30 AM ET Mar–Oct. Next fire 2026-05-19 (today) at 11:30 AM ET. |
| `mlb-regressor-halt-check-2026-05-23` routine | Created. One-shot. Fires 2026-05-23T12:00:00Z. Auto-disables after firing. View: https://claude.ai/code/routines/trig_01QiPjbGA3ztkgK56uq8dLD1 |

## Open threads

| Thread | Where it lives | When to revisit |
|---|---|---|
| Props-web Tonight-page loader hangs after idle tab | New session in `~/code/props-web`, prompt at [`2026-05-19-props-web-stale-tab-prompt.md`](2026-05-19-props-web-stale-tab-prompt.md). Suspected stale Next.js route chunk after Vercel redeploy. Firebase 400 is a secondary issue. | When that session reports back |
| 5/23 halt_state verification | Remote routine above | On 5/23 morning |
| Path A from predecessor — NBA grading audit | Not started. ~2h. Reported NBA BB HR is 63.8% on 654 graded picks; predecessor's critical reviewer flagged that NBA may have hidden grading quality gates like MLB did before the 5/18 fix. | Session 2+ priority |

## Verification queries for next session

Re-run from the predecessor's open list (now they should have CF rows for 5/18,
plus the new MLB rows from today's 11:30 AM ET firing under the lowered bar):

```bash
# What did the new bar flag for 5/18 + 5/19?
bq query --use_legacy_sql=false 'SELECT filter_name, game_date, blocked_count, wins, losses, counterfactual_hr FROM `nba-props-platform.mlb_predictions.filter_counterfactual_daily` WHERE game_date >= "2026-05-18" ORDER BY game_date DESC, blocked_count DESC'

# Spot-check what would have been flagged trending-bad under the new bar
# (Slack advisory should show direction_filter today)
# — already validated by running the query manually 2026-05-19; result: direction_filter at 90.9% via short_5d
```

## First message for the next session

```
Read docs/09-handoff/2026-05-19-cf-eligibility-and-halt-check.md.

State of open threads:
- 5/23 halt_state check fires as remote routine on 5/23 morning — no action needed before then.
- Props-web Tonight-page stale-tab bug is being investigated in a separate session in ~/code/props-web. If they reported back, integrate their findings; otherwise leave alone.
- Path A (NBA grading audit) from the 5/18-3 predecessor is still the recommended Session 2 thread. ~2h. Goal: search NBA grading for hidden quality gates that void picks book-grade outcomes would have paid (DNP voids, minutes thresholds, etc.). Compare reported BB HR (63.8% on 654 picks) against what bettors actually face.

Defers and revisit triggers in the 5/18-3 handoff.
```

## Session totals

1 commit. Tiny in line-count, but unblocks CF Phase 1 (which would have
otherwise collected dust per the predecessor's "DEFENSIBLE-BUT-FRAGILE"
verdict).
