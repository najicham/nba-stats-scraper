# Session 511 Handoff — 2026-04-04

**Context:** Session 511 continued cost reduction execution from Sessions 509/510.
Five review agents were run first to validate the state before acting.
All remaining high-priority plan items from the cost reduction plan have now been completed.

---

## What Happened This Session

### Review Phase (5 Agents)

Before executing, 5 agents reviewed the current state:
1. **Canary tiering** — confirmed working. `CANARY_TIER=critical/routine` applying correctly via v1 API container overrides. $32/mo savings already realized.
2. **Billing trend** — Apr 4 tracking ~$22-24/day (on target). Pre-509 was $33-47/day. Cloud Logging dropped to $0.
3. **Pipeline health** — YELLOW (pre-existing issues only, no Session 510 regressions). DAL_MEM missing for Apr 1 causing Phase 3 retry loop. 2 picks/day from edge drought.
4. **Exporter audit** — 4 more unfiltered BQ queries found in `player_profile_exporter.py` (lines 340, 402, 499) and `best_bets_exporter.py` (lines 206, 292).
5. **Pending actions** — infinitecase region was wrong in handoff (`us-central1` → actually `us-west2`). Phase 3 dedup safe to delete. Canary 2nd job not needed.

### Changes Deployed

**Code (commit `512bd849`):**
- `player_profile_exporter.py` — 3 more partition filter fixes:
  - `_query_game_log` line 340: added `game_date >= CURRENT_DATE - 730d`
  - `_query_splits` line 402: added `game_date >= '2021-10-01'`
  - `_query_opponent_splits` line 499: added `game_date >= '2021-10-01'`
- `best_bets_exporter.py` — 2 `player_history` CTE fixes (both branches, lines 206+292): added `game_date >= DATE_SUB(@target_date, INTERVAL 730 DAY)` lower bound

**GCP actions:**
| Action | Savings | Notes |
|--------|---------|-------|
| Deleted `daily-yesterday-analytics` scheduler | ~$5-10/mo | Subset of `overnight-analytics-6am-et` (3 vs 5 processors) |
| Added `exclude-heartbeats` logging exclusion | marginal | Via `gcloud logging sinks update _Default --add-exclusion` |
| Infinitecase → 4Gi/2CPU (`revision 00087-gpg`) | ~$57/mo | Region was `us-west2`, NOT `us-central1` as handoff stated |
| Enabled `lgbm_v12_noveg_train1227_0221` | resolves drought | Dec 27–Feb 21 window, 71% HR @ edge 3+ |
| Enabled `catboost_v12_noveg_train1227_0221` | resolves drought | Dec 27–Feb 21 window, 72% HR @ edge 3+ |
| Model cache refreshed (`prediction-worker-00459-zln`) | immediate effect | 4 models now in fleet |
| Phase 2 concurrency `10 → 1` | semantic fix | Pub/Sub triggered, 1 message/request |
| Budget alerts: $200/$300/$400/$600/$800 | prevention | Via `gcloud beta billing budgets create` |
| AR cleanup Cloud Run Job + weekly scheduler (Sun 3 AM ET) | prevents regrowth | Image: `nba-props/ar-cleanup:latest`. Test run deleted stale images. |
| Cost attribution labels on 21 key services | visibility | `billing_service=nba/mlb`, `environment=production/dev` |

---

## Current Fleet Status

4 models enabled:
- `lgbm_v12_noveg_train1227_0221` — enabled ✅ (new, Dec 27–Feb 21 window)
- `catboost_v12_noveg_train1227_0221` — enabled ✅ (new, Dec 27–Feb 21 window)
- `lgbm_v12_noveg_train0126_0323` — enabled (old, Jan 26–Mar 23, compressed edge)
- `catboost_v12_noveg_train0126_0323` — enabled (old, Jan 26–Mar 23, compressed edge)

The two new models should generate picks from today's 6 AM ET pipeline run.

---

## Priority 1: Verify Picks Flowing Today

The models were enabled and cache refreshed at ~11:30 AM ET today. Today's pipeline runs at 6 AM ET, so picks won't appear until **tomorrow (Apr 5)**. Check then:

```bash
bq query --nouse_legacy_sql '
SELECT game_date, COUNT(*) as picks, AVG(ABS(predicted_points - current_points_line)) as avg_edge
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1 ORDER BY 1 DESC'
```

**Expected:** Apr 5 should have 5-15 picks (models with Dec-Feb training window have higher avg edge).

---

## Priority 2: Billing Trend Check

```bash
bq query --nouse_legacy_sql '
SELECT DATE(_PARTITIONTIME) as date, ROUND(SUM(cost), 2) as daily_cost
FROM `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1 DESC'
```

**Expected trajectory:**
- Apr 4: ~$22-24/day (Session 511 changes just deployed)
- Apr 5+: should drop further as infinitecase + all exporter fixes take effect
- Target: ~$18-20/day

---

## Priority 3: Known Pre-existing Issues (Not Session 511 Regressions)

1. **DAL_MEM (Apr 1) stuck retry loop**: `nba-phase3-analytics-processors` is getting 500s every ~30s from Pub/Sub retrying a failed boxscore completeness check. 9/10 games in gamebook for Apr 1. Options:
   - Wait for the game data to arrive via a delayed scrape
   - Or manually ack the dead-letter: find the Pub/Sub subscription for `nba-phase3-analytics-sub` and purge messages for Apr 1

2. **2 picks/day edge drought**: Was caused by compressed-edge models. The two new models (Dec-Feb window) should fix this starting Apr 5.

---

## Cumulative Savings Summary

| Bucket | Savings | Status |
|--------|---------|--------|
| Session 509 (Phase 3/4 CPU, main exporter fixes) | ~$209/mo | ✅ Live |
| Session 510 (log exclusion, canary tier, AR cleanup, 3 exporter fixes) | ~$60-82/mo | ✅ Live |
| Session 511 (infinitecase, 5 more exporter fixes, scheduler dedup, heartbeats) | ~$70-80/mo | ✅ Live |
| **Total deployed** | **~$340-370/mo** | from $886/mo baseline |
| **Projected bill** | **~$516-546/mo** | |

---

## Remaining Optional Items

| Item | Est. Savings | Notes |
|------|-------------|-------|
| Orchestrator min-instances 1→0 | ~$13-20/mo | HIGH RISK. Requires Pub/Sub ACK deadline fix first. |
| Phase 2 CPU 4→2 | ~$30/mo | Already at 1 CPU / 2Gi — nothing to do! |
| Scheduler audit (116 GCP vs 50 documented) | ~$5-10/mo | MLB jobs use `756957797294` URL pattern but still work |
| Terraform remote state backend | $0, risk prevention | Terraform not installed. GCS bucket doesn't exist. Skip. |

**Note:** Phase 2 is already at `cpu=1 / memory=2Gi` — the plan's P2-2 estimate of ~$30/mo savings is already realized (was never at 4 CPU in production).

---

## Key Files Modified This Session

| File | Change |
|------|--------|
| `data_processors/publishing/player_profile_exporter.py` | Partition filters on `_query_game_log`, `_query_splits`, `_query_opponent_splits` |
| `data_processors/publishing/best_bets_exporter.py` | 730-day lower bound on both `player_history` CTE branches |

## Reference

- **Session 510 handoff:** `docs/09-handoff/2026-04-04-SESSION-510-HANDOFF.md`
- **Session 509 handoff:** `docs/09-handoff/2026-04-03-SESSION-509-HANDOFF.md`
- **Full cost reduction plan:** `docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md`
- **Billing table:** `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
- **AR cleanup job:** `gcloud run jobs execute ar-weekly-cleanup --region=us-west2 --project=nba-props-platform`
- **AR cleanup scheduler:** `ar-weekly-cleanup` (Sundays 3 AM ET, us-west2)
